# agent/bot/signals/momentum.py
"""
Momentum Signal — Orderbook + fiyat hareketi analizi.

Kaynaklar:
  1. Bid/Ask imbalance (mevcut logiği buraya taşıdık)
  2. Spread genişliği (daralıyorsa momentum var)
  3. Orderbook derinlik dağılımı

Çıktı: -1.0 (güçlü bearish) → +1.0 (güçlü bullish)
"""
from dataclasses import dataclass
from typing import Dict, Any, Optional, List

from ..risk.checks import _get_best_bid_ask
from ..monitoring.logger import get_logger

logger = get_logger("signal.momentum")


@dataclass
class MomentumSignal:
    imbalance: float        # -1.0 → +1.0  (bid > ask = bullish)
    spread_score: float     # 0.0 → 1.0    (dar spread = daha iyi)
    depth_score: float      # 0.0 → 1.0    (derin = daha güvenilir)
    composite: float        # -1.0 → +1.0  (ağırlıklı ortalama)
    confidence: float       # 0.0 → 1.0
    best_bid: float
    best_ask: float
    bid_depth_usd: float
    ask_depth_usd: float
    spread: float
    mid_price: float
    signal_text: str        # İnsan okunabilir açıklama


def get_momentum_signal(orderbook: Dict[str, Any]) -> Optional[MomentumSignal]:
    """
    Orderbook'tan momentum sinyali üret.
    
    Args:
        orderbook: get_orderbook() dönüşü
    
    Returns:
        MomentumSignal veya None (orderbook geçersizse)
    """
    if not orderbook or not orderbook.get("ok"):
        return None
    
    ob = orderbook.get("orderbook", {})
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])
    
    if not bids or not asks:
        return None
    
    # Best bid/ask (düzeltilmiş parse)
    best_bid, best_ask = _get_best_bid_ask(orderbook)
    if best_bid is None or best_ask is None:
        return None
    
    spread = best_ask - best_bid
    mid_price = (best_bid + best_ask) / 2
    
    # ── Derinlik hesapla ──
    bid_depth = _calc_depth(bids, side="bid")
    ask_depth = _calc_depth(asks, side="ask")
    total_depth = bid_depth + ask_depth
    
    if total_depth <= 0:
        return None
    
    # ── 1. Imbalance skoru ──
    # +1.0 = tamamen bid-heavy (alıcı baskısı), -1.0 = tamamen ask-heavy
    imbalance = (bid_depth - ask_depth) / total_depth
    
    # ── 2. Spread skoru ──
    # Spread ne kadar dar, o kadar iyi (0.0 = %50 spread, 1.0 = 0 spread)
    max_useful_spread = 0.10
    spread_score = max(0.0, 1.0 - (spread / max_useful_spread))
    
    # ── 3. Depth skoru ──
    # Toplam derinlik ne kadar büyük, o kadar güvenilir
    depth_score = min(1.0, total_depth / 50_000)  # $50k = tam skor
    
    # ── Composite ──
    composite = (
        imbalance   * 0.60 +
        (spread_score - 0.5) * 2 * 0.20 +   # spread_score → [-1, +1]
        (depth_score - 0.5) * 2 * 0.20       # depth_score  → [-1, +1]
    )
    composite = max(-1.0, min(1.0, composite))
    
    # ── Confidence ──
    # Derin ve imbalance güçlüyse güven artar
    confidence = min(1.0, depth_score * 0.5 + abs(imbalance) * 0.5)
    
    # ── Açıklama ──
    signal_text = _describe(imbalance, bid_depth, ask_depth, spread)
    
    return MomentumSignal(
        imbalance=round(imbalance, 4),
        spread_score=round(spread_score, 4),
        depth_score=round(depth_score, 4),
        composite=round(composite, 4),
        confidence=round(confidence, 4),
        best_bid=round(best_bid, 4),
        best_ask=round(best_ask, 4),
        bid_depth_usd=round(bid_depth, 2),
        ask_depth_usd=round(ask_depth, 2),
        spread=round(spread, 4),
        mid_price=round(mid_price, 4),
        signal_text=signal_text,
    )


# ─────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────

def _calc_depth(levels: list, side: str) -> float:
    """
    Orderbook seviyelerinden USD derinliği hesapla.
    Sadece makul fiyat aralığını (0.05–0.95) dahil et.
    """
    total = 0.0
    for level in levels:
        try:
            price = float(level.get("price", 0))
            size = float(level.get("size", 0))
            if 0.05 <= price <= 0.95:
                total += price * size
        except (ValueError, TypeError):
            continue
    return total


def _describe(
    imbalance: float,
    bid_depth: float,
    ask_depth: float,
    spread: float,
) -> str:
    """İnsan okunabilir sinyal açıklaması."""
    if bid_depth > 0 and ask_depth > 0:
        ratio = bid_depth / ask_depth
    else:
        return "⚠️ Insufficient depth"
    
    if ratio >= 3.0:
        direction = f"⬆️ BID-HEAVY ({ratio:.1f}x) — strong buying pressure"
    elif ratio >= 1.5:
        direction = f"↑ Mild BID pressure ({ratio:.1f}x)"
    elif ratio <= 0.33:
        inv = ask_depth / bid_depth
        direction = f"⬇️ ASK-HEAVY ({inv:.1f}x) — strong selling pressure"
    elif ratio <= 0.67:
        inv = ask_depth / bid_depth
        direction = f"↓ Mild ASK pressure ({inv:.1f}x)"
    else:
        direction = "↔️ Balanced order book"
    
    spread_note = "tight spread ✓" if spread < 0.03 else f"spread={spread:.3f}"
    return f"{direction} | {spread_note} | bid=${bid_depth:,.0f} ask=${ask_depth:,.0f}"
