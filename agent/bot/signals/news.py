# agent/bot/signals/news.py
"""
News Signal — Tavily API ile gerçek zamanlı haber analizi.

Bir market sorusu için:
  1. Tavily'de ara
  2. Başlık + snippet'lerden sentiment çıkar
  3. -1.0 (çok bearish) → +1.0 (çok bullish) skoru döndür
  
Cache: Her soru için 10 dakika TTL (aşırı API çağrısını önler)
"""
import os
import re
import time
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from ..utils.cache import get_redis_client
from ..monitoring.logger import get_logger

logger = get_logger("signal.news")

_NEWS_CACHE_TTL = 600        # 10 dakika
_NEWS_CACHE_PREFIX = "news:v1"
_MAX_RESULTS = 5
_REQUEST_TIMEOUT = 6         # saniye


@dataclass
class NewsSignal:
    sentiment: float          # -1.0 → +1.0
    confidence: float         # 0.0 → 1.0
    headline_count: int
    summary: str              # LLM prompt'una eklenecek özet
    source: str               # "tavily" | "cache" | "unavailable"


# ─────────────────────────────────────────────
# Ana fonksiyon
# ─────────────────────────────────────────────

def get_news_signal(question: str, token_side: str = "YES") -> NewsSignal:
    """
    Market sorusu için haber sinyali üret.
    
    Args:
        question:   Market sorusu ("Will X happen by Y?")
        token_side: "YES" veya "NO" — hangi taraf için trading yapılıyor
    
    Returns:
        NewsSignal
    """
    if not question or len(question.strip()) < 5:
        return _unavailable("Empty question")
    
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not tavily_key:
        return _unavailable("TAVILY_API_KEY not set")
    
    # Cache kontrolü
    cache_key = f"{_NEWS_CACHE_PREFIX}:{_hash_question(question)}"
    cached = _load_from_cache(cache_key)
    if cached:
        logger.info("News signal from cache", question=question[:60])
        return cached
    
    # API'den çek
    results = _fetch_tavily(question, tavily_key)
    if not results:
        return _unavailable("No results from Tavily")
    
    signal = _analyze_results(results, question, token_side)
    _save_to_cache(cache_key, signal)
    
    logger.info(
        "News signal fetched",
        question=question[:60],
        sentiment=signal.sentiment,
        confidence=signal.confidence,
        headlines=signal.headline_count,
    )
    return signal


# ─────────────────────────────────────────────
# Tavily API
# ─────────────────────────────────────────────

def _fetch_tavily(question: str, api_key: str) -> List[Dict[str, Any]]:
    """Tavily'den haber çek."""
    try:
        import requests
        
        # Kısa, odaklı query — gereksiz kelimeler çıkar
        query = _clean_query(question)
        
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": _MAX_RESULTS,
                "search_depth": "basic",
                "include_answer": False,
            },
            timeout=_REQUEST_TIMEOUT,
        )
        
        if resp.status_code != 200:
            logger.warning("Tavily API error", status=resp.status_code)
            return []
        
        return resp.json().get("results", [])
    
    except Exception as e:
        logger.error("Tavily fetch failed", error=str(e))
        return []


def _clean_query(question: str) -> str:
    """
    Polymarket sorusundan arama sorgusu üret.
    
    "Will X happen by December 31?" → "X"
    "Will [team] win?" → "[team] win"
    """
    # "Will ... by DATE?" formatındaki soruları kısalt
    q = re.sub(r'\bby\s+\w+\s+\d+,?\s*\d{4}\b', '', question, flags=re.IGNORECASE)
    q = re.sub(r'\bby\s+end\s+of\s+\w+\b', '', q, flags=re.IGNORECASE)
    q = re.sub(r'\bwill\b', '', q, flags=re.IGNORECASE)
    q = re.sub(r'\?', '', q)
    q = re.sub(r'\s+', ' ', q).strip()
    
    return q[:120]  # Tavily max query uzunluğu


# ─────────────────────────────────────────────
# Sentiment analizi
# ─────────────────────────────────────────────

# Bullish / bearish sinyal kelimeleri
_BULLISH_WORDS = {
    "win", "wins", "victory", "lead", "leads", "ahead", "approved", "passes",
    "surge", "rally", "rises", "breaks", "confirms", "announces", "secures",
    "gains", "positive", "success", "achieves", "likely", "probable",
    "majority", "dominant", "strong", "record", "high", "up", "increase",
    "agreement", "deal", "signed", "passed", "elected", "confirmed",
}

_BEARISH_WORDS = {
    "lose", "loses", "loss", "defeat", "fails", "fail", "rejected", "denied",
    "falls", "drop", "declines", "uncertain", "doubt", "concern", "risk",
    "unlikely", "improbable", "weak", "negative", "down", "decrease",
    "blocked", "vetoed", "dismissed", "withdrawn", "cancelled", "postponed",
    "lawsuit", "investigation", "scandal", "crisis", "collapse",
}


def _analyze_results(
    results: List[Dict[str, Any]],
    question: str,
    token_side: str,
) -> NewsSignal:
    """
    Haber sonuçlarından sentiment skoru üret.
    """
    if not results:
        return _unavailable("No results to analyze")
    
    texts = []
    for r in results:
        title = r.get("title", "")
        content = r.get("content", "")[:300]
        texts.append(f"{title}. {content}")
    
    combined = " ".join(texts).lower()
    words = set(re.findall(r'\b[a-z]+\b', combined))
    
    bullish_hits = len(words & _BULLISH_WORDS)
    bearish_hits = len(words & _BEARISH_WORDS)
    total_hits = bullish_hits + bearish_hits
    
    if total_hits == 0:
        raw_sentiment = 0.0
        confidence = 0.2
    else:
        # -1.0 → +1.0
        raw_sentiment = (bullish_hits - bearish_hits) / total_hits
        # Confidence: ne kadar çok hit, o kadar güvenilir (max 0.8)
        confidence = min(0.8, total_hits / 10)
    
    # NO token için sentiment ters çevir
    if token_side.upper() == "NO":
        raw_sentiment = -raw_sentiment
    
    # Özet oluştur
    snippets = [r.get("title", "") for r in results[:3] if r.get("title")]
    summary = " | ".join(snippets)[:400]
    
    return NewsSignal(
        sentiment=round(raw_sentiment, 3),
        confidence=round(confidence, 3),
        headline_count=len(results),
        summary=summary,
        source="tavily",
    )


# ─────────────────────────────────────────────
# Cache
# ─────────────────────────────────────────────

def _load_from_cache(key: str) -> Optional[NewsSignal]:
    try:
        redis = get_redis_client()
        raw = redis.get(key)
        if raw:
            d = json.loads(raw)
            return NewsSignal(**d)
    except Exception:
        pass
    return None


def _save_to_cache(key: str, signal: NewsSignal) -> None:
    try:
        redis = get_redis_client()
        redis.setex(key, _NEWS_CACHE_TTL, json.dumps({
            "sentiment": signal.sentiment,
            "confidence": signal.confidence,
            "headline_count": signal.headline_count,
            "summary": signal.summary,
            "source": "cache",
        }))
    except Exception:
        pass


def _hash_question(question: str) -> str:
    import hashlib
    return hashlib.md5(question.lower().strip().encode()).hexdigest()[:16]


def _unavailable(reason: str) -> NewsSignal:
    return NewsSignal(
        sentiment=0.0,
        confidence=0.0,
        headline_count=0,
        summary="",
        source="unavailable",
    )
