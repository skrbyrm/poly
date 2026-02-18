# agent/bot/ai/prompt_builder.py
"""
Prompt Builder — Multi-signal context ile zenginleştirilmiş LLM prompt.

Sprint 2 değişiklikleri:
  - Tüm sinyal katmanları prompt'a eklendi (news, momentum, resolution)
  - Kategori bazlı trading talimatları
  - Orderbook yorumu daha ayrıntılı
  - Market context (volume, resolution date) eklendi
"""
import json
from typing import Dict, Any, List, Optional

from ..signals.news import get_news_signal
from ..signals.momentum import get_momentum_signal
from ..signals.resolution import get_resolution_signal
from ..monitoring.logger import get_logger

logger = get_logger("prompt_builder")


SYSTEM_PROMPT = """You are an expert prediction market trader on Polymarket.

POLYMARKET MECHANICS:
- Tokens resolve to $1.00 (YES wins) or $0.00 (NO wins)
- Price = market's implied probability (e.g., 0.50 = 50/50)
- You are buying YES tokens unless told otherwise

YOUR EDGE SOURCES (ranked by reliability):
1. NEWS: Recent events strongly favoring one outcome
2. ORDER FLOW: Strong bid/ask imbalance (3x+ = significant signal)
3. MISPRICING: Market price vs actual probability based on evidence
4. RESOLUTION PROXIMITY: 1–14 days remaining = highest volatility window

DECISION RULES:
- confidence >= 0.65 → TRADE (recommended size from Kelly)
- confidence 0.55–0.65 → TRADE (minimum size)
- confidence < 0.55 → HOLD (no clear edge)
- NEVER buy above 0.88 or below 0.12 (resolution risk too high)
- Avoid expired or imminent (< 2h) markets

CATEGORY STRATEGIES:
- politics: Weight news 50%, be cautious with imbalance alone
- sports: Balance stats + imbalance, news matters near game time
- crypto: Momentum is key, follow order flow
- finance: Imbalance + macro context
- other: Be conservative, require multiple confirming signals

OUTPUT FORMAT: Valid JSON only, no markdown, no explanation outside JSON.
{
  "decision": "buy" | "sell" | "hold",
  "token_id": "...",
  "limit_price": 0.XX,
  "confidence": 0.XX,
  "reasoning": "1-2 sentence explanation of your edge"
}"""


def build_decision_prompt(
    snapshot: Dict[str, Any],
    ledger: Dict[str, Any],
    orderbook: Optional[Dict[str, Any]] = None,
    market_data: Optional[List[Dict[str, Any]]] = None,  # Gamma API market objeleri
) -> List[Dict[str, str]]:
    """
    Tam context ile LLM karar prompt'u oluştur.
    
    Args:
        snapshot:    Market intelligence snapshot (topk)
        ledger:      Mevcut pozisyonlar ve nakit
        orderbook:   İlk candidate'ın orderbook'u (opsiyonel)
        market_data: Gamma API'den ham market objeleri (sinyal için)
    
    Returns:
        [system_message, user_message]
    """
    topk = snapshot.get("topk", [])
    positions = ledger.get("positions", {})
    cash = ledger.get("cash", 0)
    
    # market_data index: token_id → market objesi
    market_index = _build_market_index(market_data or [])
    
    user_parts = ["## MARKET OPPORTUNITIES\n"]
    
    for i, candidate in enumerate(topk, 1):
        tid = candidate.get("token_id", "")
        question = candidate.get("question", "Unknown market")
        market_obj = market_index.get(tid, {})
        
        # ── Momentum sinyali ──
        ob_for_signal = orderbook if (i == 1 and orderbook) else None
        if not ob_for_signal and candidate:
            # Candidate'dan fake orderbook construct et (sinyal için yeterli)
            ob_for_signal = _candidate_to_ob(candidate)
        
        momentum = get_momentum_signal(ob_for_signal) if ob_for_signal else None
        
        # ── Resolution sinyali ──
        resolution = get_resolution_signal({**market_obj, "question": question})
        
        # ── News sinyali (sadece ilk 2 için, API limiti) ──
        news = None
        if i <= 2:
            try:
                news = get_news_signal(question)
            except Exception as e:
                logger.warning("News signal failed", question=question[:40], error=str(e))
        
        # ── Bölüm yaz ──
        user_parts.append(f"### Option {i}: {question}\n")
        user_parts.append(f"**Token ID:** `{tid}`\n")
        
        # Fiyat
        best_bid = candidate.get("best_bid", 0)
        best_ask = candidate.get("best_ask", 0)
        mid = candidate.get("mid_price", (best_bid + best_ask) / 2 if best_bid and best_ask else 0)
        user_parts.append(f"**Price:** Bid={best_bid:.3f} | Ask={best_ask:.3f} | Mid={mid:.3f}\n")
        
        # Volume & liquidity
        volume_24h = market_obj.get("volume24hrClob") or market_obj.get("volume24hr") or 0
        liquidity = market_obj.get("liquidityClob") or market_obj.get("liquidity") or 0
        if volume_24h or liquidity:
            user_parts.append(f"**Market:** 24h Vol=${float(volume_24h):,.0f} | Liq=${float(liquidity):,.0f}\n")
        
        # Momentum
        if momentum:
            user_parts.append(f"**Order Flow:** {momentum.signal_text}\n")
            user_parts.append(
                f"**Depth:** Bid=${momentum.bid_depth_usd:,.0f} | Ask=${momentum.ask_depth_usd:,.0f} "
                f"| Imbalance={momentum.imbalance:+.2f}\n"
            )
        else:
            bid_d = candidate.get("bid_depth", 0)
            ask_d = candidate.get("ask_depth", 0)
            user_parts.append(f"**Depth:** Bid=${bid_d:,.0f} | Ask=${ask_d:,.0f}\n")
        
        # Resolution
        user_parts.append(f"**Resolution:** {resolution.summary}\n")
        
        # Category weights (trade stratejisi için)
        w = resolution.category_weight
        user_parts.append(
            f"**Strategy:** Category={resolution.category} | "
            f"Weight momentum={w['momentum']:.0%} news={w['news']:.0%}\n"
        )
        
        # Uyarılar
        if resolution.is_expired:
            user_parts.append("⛔ **SKIP: Market already expired**\n")
        elif resolution.is_imminent:
            user_parts.append("⚠️ **CAUTION: Resolution < 2 hours (high risk)**\n")
        
        # News
        if news and news.source != "unavailable" and news.headline_count > 0:
            sentiment_label = "🟢 Bullish" if news.sentiment > 0.1 else ("🔴 Bearish" if news.sentiment < -0.1 else "⚪ Neutral")
            user_parts.append(
                f"**News ({news.headline_count} headlines):** {sentiment_label} "
                f"(sentiment={news.sentiment:+.2f}, conf={news.confidence:.2f})\n"
            )
            if news.summary:
                # İlk 200 karakter özet
                user_parts.append(f"> {news.summary[:200]}\n")
        
        # Mevcut pozisyon
        if tid in positions:
            pos = positions[tid]
            avg_p = float(pos.get("avg_price", 0))
            qty = float(pos.get("qty", 0))
            pnl_pct = ((mid - avg_p) / avg_p * 100) if avg_p > 0 and mid > 0 else 0
            user_parts.append(
                f"**⚠️ YOU OWN THIS:** {qty:.2f} tokens @ ${avg_p:.4f} | "
                f"PnL: {pnl_pct:+.1f}%\n"
            )
        
        user_parts.append("\n")
    
    # ── Portfolio ──
    user_parts.append("## YOUR PORTFOLIO\n")
    user_parts.append(f"- Available cash: **${cash:.2f} USDC**\n")
    user_parts.append(f"- Open positions: **{len(positions)}**\n")
    
    if positions:
        user_parts.append("\nOpen positions:\n")
        for tid, pos in list(positions.items())[:5]:
            user_parts.append(
                f"  - `...{tid[-8:]}`: {float(pos.get('qty',0)):.2f} @ ${float(pos.get('avg_price',0)):.4f}\n"
            )
    
    # ── Görev ──
    user_parts.append(
        "\n## YOUR TASK\n"
        "1. Identify the option with the **strongest edge** (news + order flow + category)\n"
        "2. Make a decisive buy/sell/hold decision\n"
        "3. Required confidence >= 0.55 to trade\n"
        "4. Respond with ONLY valid JSON — no markdown fences, no extra text\n"
    )
    
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": "".join(user_parts)},
    ]


# ─────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────

def _build_market_index(market_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """token_id → market objesi eşlemesi."""
    index: Dict[str, Dict[str, Any]] = {}
    for m in market_data:
        tids_raw = m.get("clobTokenIds") or m.get("clob_token_ids") or []
        if isinstance(tids_raw, str):
            try:
                tids_raw = json.loads(tids_raw)
            except Exception:
                tids_raw = []
        for tid in tids_raw:
            index[str(tid)] = m
    return index


def _candidate_to_ob(candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Snapshot candidate'ından minimal orderbook construct et.
    (Gerçek orderbook olmadığında momentum signal için)
    """
    best_bid = candidate.get("best_bid") or candidate.get("band_best_bid")
    best_ask = candidate.get("best_ask") or candidate.get("band_best_ask")
    bid_depth = candidate.get("bid_depth") or candidate.get("bid_depth_band") or 0
    ask_depth = candidate.get("ask_depth") or candidate.get("ask_depth_band") or 0
    
    if not best_bid or not best_ask:
        return None
    
    # Basit tek seviye orderbook (sinyal için yeterli)
    bid_size = (bid_depth / best_bid) if best_bid > 0 else 0
    ask_size = (ask_depth / best_ask) if best_ask > 0 else 0
    
    return {
        "ok": True,
        "orderbook": {
            "bids": [{"price": str(best_bid), "size": str(bid_size)}],
            "asks": [{"price": str(best_ask), "size": str(ask_size)}],
        },
    }
