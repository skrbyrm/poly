# agent/bot/risk/checks.py
"""
Order validation ve risk checks - Polymarket orderbook ters sıralıdır!
"""
import os
from typing import Optional, Dict, Any

def _get_best_bid_ask(orderbook: Dict[str, Any]):
    """
    Polymarket'te bids[0] en düşük, asks[0] en yüksektir.
    Gerçek best bid = max(bids), best ask = min(asks)
    """
    ob = orderbook.get("orderbook", {})
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])

    if not bids or not asks:
        return None, None

    bid_prices = [float(b.get("price", 0)) for b in bids if float(b.get("price", 0)) > 0]
    ask_prices = [float(a.get("price", 0)) for a in asks if float(a.get("price", 0)) > 0]

    if not bid_prices or not ask_prices:
        return None, None

    return max(bid_prices), min(ask_prices)


def clamp_order(qty: float, price: float) -> float:
    min_order_size = float(os.getenv("MIN_ORDER_SIZE", "1.0"))
    max_order_size = float(os.getenv("MAX_ORDER_SIZE", "1000.0"))

    if qty < min_order_size:
        return 0.0
    if qty > max_order_size:
        qty = max_order_size

    return round(qty, 2)


def validate_order_price(price: float, orderbook: Dict[str, Any], side: str) -> tuple[bool, str]:
    if not orderbook or not orderbook.get("ok"):
        return False, "Invalid orderbook"

    best_bid, best_ask = _get_best_bid_ask(orderbook)

    if best_bid is None or best_ask is None:
        return False, "Empty orderbook"

    if best_bid <= 0 or best_ask <= 0:
        return False, "Invalid best bid/ask"

    spread = best_ask - best_bid
    max_spread = float(os.getenv("MAX_SPREAD", "0.15"))

    if spread > max_spread:
        return False, f"Spread too wide: {spread:.4f} > {max_spread}"

    if side == "buy":
        if price > best_ask * 1.1:
            return False, f"Buy price too high: {price:.4f} vs best_ask {best_ask:.4f}"
    else:
        if price < best_bid * 0.9:
            return False, f"Sell price too low: {price:.4f} vs best_bid {best_bid:.4f}"

    return True, "OK"


def check_spread_quality(orderbook: Dict[str, Any]) -> tuple[bool, float]:
    if not orderbook or not orderbook.get("ok"):
        return False, 999.0

    best_bid, best_ask = _get_best_bid_ask(orderbook)

    if best_bid is None or best_ask is None:
        return False, 999.0

    spread = best_ask - best_bid
    max_spread = float(os.getenv("MAX_SPREAD", "0.15"))

    return spread <= max_spread, spread


def check_depth_quality(orderbook: Dict[str, Any], min_depth: float = None) -> tuple[bool, str]:
    if not orderbook or not orderbook.get("ok"):
        return False, "Invalid orderbook"

    if min_depth is None:
        min_depth = float(os.getenv("MIN_BAND_DEPTH", "5.0"))

    ob = orderbook.get("orderbook", {})
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])

    if not bids or not asks:
        return False, "Empty orderbook"

    # Sadece makul fiyatlı seviyeleri say
    bid_depth = sum(
        float(b.get("price", 0)) * float(b.get("size", 0))
        for b in bids if float(b.get("price", 0)) >= 0.10
    )
    ask_depth = sum(
        float(a.get("price", 0)) * float(a.get("size", 0))
        for a in asks if float(a.get("price", 0)) <= 0.90
    )
    total_depth = bid_depth + ask_depth

    if total_depth < min_depth:
        return False, f"Insufficient depth: ${total_depth:.2f} < ${min_depth:.2f}"

    return True, "OK"


def validate_trade_timing(last_trade_ts: float, cooldown_seconds: int = None) -> tuple[bool, str]:
    import time

    if cooldown_seconds is None:
        cooldown_seconds = int(os.getenv("TRADE_COOLDOWN_S", "5"))

    if last_trade_ts == 0:
        return True, "OK"

    elapsed = time.time() - last_trade_ts

    if elapsed < cooldown_seconds:
        return False, f"Trade cooldown: {cooldown_seconds - elapsed:.1f}s remaining"

    return True, "OK"
