# agent/bot/signals/resolution.py
"""
Resolution Signal — Market deadline yakınlığı ve kategori analizi.

Mantık:
  - Yaklaşan deadline olan market'ler daha oynak ve opportunity zengin
  - Çok yakın (< 2 saat) veya çok uzak (> 90 gün) marketler ideal değil
  - Sweetspot: 1–14 gün

Kategori stratejisi:
  - politics  → haber sinyali ağırlıklı
  - sports    → istatistik + imbalance
  - crypto    → momentum ağırlıklı  
  - finance   → imbalance + volume
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from ..monitoring.logger import get_logger

logger = get_logger("signal.resolution")


@dataclass
class ResolutionSignal:
    days_to_resolution: Optional[float]   # None = bilinmiyor
    proximity_score: float                 # 0.0 → 1.0 (1.0 = ideal mesafe)
    category: str                          # "politics", "sports", "crypto", ...
    category_weight: Dict[str, float]      # sinyal ağırlık önerileri
    is_imminent: bool                      # < 2 saat → riskli
    is_expired: bool                       # geçmiş tarih
    summary: str


# Kategori → sinyal ağırlıkları
_CATEGORY_WEIGHTS = {
    "politics": {
        "momentum": 0.20,
        "news":     0.50,
        "resolution": 0.30,
    },
    "sports": {
        "momentum": 0.40,
        "news":     0.30,
        "resolution": 0.30,
    },
    "crypto": {
        "momentum": 0.60,
        "news":     0.25,
        "resolution": 0.15,
    },
    "finance": {
        "momentum": 0.50,
        "news":     0.30,
        "resolution": 0.20,
    },
    "other": {
        "momentum": 0.40,
        "news":     0.35,
        "resolution": 0.25,
    },
}

_DEFAULT_WEIGHTS = _CATEGORY_WEIGHTS["other"]

# Kategori tespiti için anahtar kelimeler
_CATEGORY_KEYWORDS = {
    "politics": [
        "election", "president", "congress", "senate", "vote", "bill", "policy",
        "democrat", "republican", "minister", "parliament", "referendum",
        "inauguration", "candidat", "political",
    ],
    "sports": [
        "nfl", "nba", "mlb", "nhl", "soccer", "football", "basketball", "baseball",
        "hockey", "tennis", "golf", "ufc", "mma", "super bowl", "world cup",
        "championship", "playoff", "tournament", "match", "game",
        "team", "player", "coach", "season",
    ],
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain", "token",
        "defi", "nft", "altcoin", "solana", "binance", "coinbase",
        "price", "all-time high", "market cap",
    ],
    "finance": [
        "fed", "interest rate", "inflation", "gdp", "recession", "earnings",
        "stock", "ipo", "merger", "acquisition", "s&p", "nasdaq", "dow",
        "treasury", "bond", "yield", "dollar", "euro", "currency",
    ],
}


def get_resolution_signal(market: Dict[str, Any]) -> ResolutionSignal:
    """
    Market datasından resolution sinyali üret.
    
    Args:
        market: Gamma API market objesi (question, end_date_iso, category vs.)
    
    Returns:
        ResolutionSignal
    """
    question = market.get("question", "")
    
    # Kategori tespiti
    category = _detect_category(question, market)
    weights = _CATEGORY_WEIGHTS.get(category, _DEFAULT_WEIGHTS)
    
    # Deadline hesaplama
    end_date = _parse_end_date(market)
    
    if end_date is None:
        return ResolutionSignal(
            days_to_resolution=None,
            proximity_score=0.5,
            category=category,
            category_weight=weights,
            is_imminent=False,
            is_expired=False,
            summary=f"Category: {category} | Resolution date unknown",
        )
    
    now = datetime.now(timezone.utc)
    delta = end_date - now
    days = delta.total_seconds() / 86400
    
    is_expired  = days < 0
    is_imminent = 0 <= days < 0.083  # < 2 saat
    
    if is_expired:
        proximity_score = 0.0
        summary_suffix = "EXPIRED"
    elif is_imminent:
        proximity_score = 0.1   # Çok yakın = riskli
        summary_suffix = f"IMMINENT ({days*24:.1f}h)"
    else:
        proximity_score = _proximity_score(days)
        summary_suffix = f"{days:.1f} days remaining"
    
    return ResolutionSignal(
        days_to_resolution=round(days, 2) if not is_expired else None,
        proximity_score=round(proximity_score, 3),
        category=category,
        category_weight=weights,
        is_imminent=is_imminent,
        is_expired=is_expired,
        summary=f"Category: {category} | {summary_suffix}",
    )


# ─────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────

def _proximity_score(days: float) -> float:
    """
    Gün mesafesinden proximity score hesapla.
    
    Sweetspot: 1–14 gün → 1.0
    0–1 gün  → 0.3 (çok yakın, oynak)
    14–90 gün → doğrusal azalış
    90+ gün  → 0.1
    """
    if days <= 0:
        return 0.0
    if days < 1:
        return 0.3
    if days <= 14:
        return 1.0
    if days <= 90:
        return max(0.2, 1.0 - (days - 14) / 76 * 0.8)
    return 0.1


def _detect_category(question: str, market: Dict[str, Any]) -> str:
    """Market sorusundan kategori tespit et."""
    # Önce market'in kendi kategori bilgisine bak
    cat = market.get("category") or market.get("marketType") or ""
    if cat:
        cat_lower = cat.lower()
        for key in _CATEGORY_KEYWORDS:
            if key in cat_lower:
                return key
    
    # Soru metninden keyword matching
    q_lower = question.lower()
    scores: Dict[str, int] = {}
    
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in q_lower)
        if score > 0:
            scores[category] = score
    
    if scores:
        return max(scores, key=scores.get)
    
    return "other"


def _parse_end_date(market: Dict[str, Any]) -> Optional[datetime]:
    """Market datasından bitiş tarihini parse et."""
    for field in ("endDate", "end_date", "endDateIso", "resolution_date", "resolutionDate"):
        val = market.get(field)
        if not val:
            continue
        try:
            if isinstance(val, (int, float)):
                return datetime.fromtimestamp(val, tz=timezone.utc)
            
            # ISO string
            val_str = str(val).replace("Z", "+00:00")
            return datetime.fromisoformat(val_str)
        except (ValueError, TypeError):
            continue
    
    return None
