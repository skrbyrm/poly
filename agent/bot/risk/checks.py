# agent/bot/risk/checks.py
"""
Order validation ve risk checks

⚠️  POLYMARKET ORDERBOOK NOTU:
    Polymarket CLOB API'de bids[0] en DÜŞÜK fiyatı döner (ters sıra).
    Bu yüzden:
      best_bid = max(all bid prices)
      best_ask = min(all ask prices)
    Direkt bids[0] veya asks[0] kullanmak HATALIDIR.
"""
import os
from typing import Optional, Dict, Any, Tuple


# ─────────────────────────────────────────────
# Yardımcı: Doğru best bid/ask hesapla
# ─────────────────────────────────────────────

def _get_best_bid_ask(orderbook: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """
    Polymarket orderbook'undan gerçek best bid ve best ask'ı çıkar.

    Polymarket'te bids[0] en DÜŞÜK fiyat, asks[0] en YÜKSEK fiyattır.
    Doğru değerler için max(bids) ve min(asks) kullanılmalıdır.

    Args:
        orderbook: get_orderbook() dönüşü  {"ok": bool, "orderbook": {"bids": [...], "asks": [...]}}

    Returns:
        (best_bid, best_ask) — bulunamazsa (None, None)
    """
    ob = orderbook.get("orderbook", {}) if isinstance(orderbook, dict) else {}
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])

    if not bids or not asks:
        return None, None

    try:
        bid_prices = [float(b.get("price", 0)) for b in bids if float(b.get("price", 0)) > 0]
        ask_prices = [float(a.get("price", 0)) for a in asks if float(a.get("price", 0)) > 0]

        if not bid_prices or not ask_prices:
            return None, None

        best_bid = max(bid_prices)   # ← max, çünkü ters sıralı
        best_ask = min(ask_prices)   # ← min, çünkü ters sıralı

        # Geçersiz crossed book kontrolü
        if best_bid >= best_ask:
            return None, None

        return best_bid, best_ask

    except (ValueError, TypeError):
        return None, None


def get_mid_price(orderbook: Dict[str, Any]) -> Optional[float]:
    """Orderbook'tan mid price hesapla."""
    best_bid, best_ask = _get_best_bid_ask(orderbook)
    if best_bid is None or best_ask is None:
        return None
    return round((best_bid + best_ask) / 2, 6)


def get_spread(orderbook: Dict[str, Any]) -> Optional[float]:
    """Orderbook'tan spread hesapla."""
    best_bid, best_ask = _get_best_bid_ask(orderbook)
    if best_bid is None or best_ask is None:
        return None
    return round(best_ask - best_bid, 6)


# ─────────────────────────────────────────────
# Risk check fonksiyonları
# ─────────────────────────────────────────────

def clamp_order(qty: float, price: float) -> float:
    """
    Order miktarını konfigürasyon limitlerinde tut.
    
    Returns:
        Geçerli qty veya 0.0 (çok küçükse)
    """
    min_order_size = float(os.getenv("MIN_ORDER_SIZE", "1.0"))
    max_order_size = float(os.getenv("MAX_ORDER_SIZE", "1000.0"))

    if qty < min_order_size:
        return 0.0
    if qty > max_order_size:
        qty = max_order_size

    return round(qty, 2)


def validate_order_price(
    price: float,
    orderbook: Dict[str, Any],
    side: str
) -> Tuple[bool, str]:
    """
    Order fiyatının orderbook ile makul aralıkta olup olmadığını kontrol et.

    Args:
        price:     Limit fiyat
        orderbook: get_orderbook() dönüşü
        side:      "buy" veya "sell"

    Returns:
        (valid, reason)
    """
    if not orderbook or not orderbook.get("ok"):
        return False, "Invalid orderbook"

    best_bid, best_ask = _get_best_bid_ask(orderbook)

    if best_bid is None or best_ask is None:
        return False, "Cannot determine best bid/ask from orderbook"

    if best_bid <= 0 or best_ask <= 0:
        return False, "Invalid best bid/ask values"

    spread = best_ask - best_bid
    max_spread = float(os.getenv("MAX_SPREAD", "0.15"))

    if spread > max_spread:
        return False, f"Spread too wide: {spread:.4f} > {max_spread}"

    if side.lower() == "buy":
        # Alış fiyatı best_ask'tan %10 fazlasını geçmemeli
        if price > best_ask * 1.10:
            return False, (
                f"Buy price too high: {price:.4f} vs best_ask {best_ask:.4f} "
                f"(>{best_ask * 1.10:.4f})"
            )
    else:  # sell
        # Satış fiyatı best_bid'den %10 düşüğünü geçmemeli
        if price < best_bid * 0.90:
            return False, (
                f"Sell price too low: {price:.4f} vs best_bid {best_bid:.4f} "
                f"(<{best_bid * 0.90:.4f})"
            )

    return True, "OK"


def check_spread_quality(orderbook: Dict[str, Any]) -> Tuple[bool, float]:
    """
    Spread kalitesini kontrol et.

    Returns:
        (spread_ok, spread_value)
        spread_value = 999.0 ise orderbook okunamadı
    """
    if not orderbook or not orderbook.get("ok"):
        return False, 999.0

    best_bid, best_ask = _get_best_bid_ask(orderbook)

    if best_bid is None or best_ask is None:
        return False, 999.0

    spread = best_ask - best_bid
    max_spread = float(os.getenv("MAX_SPREAD", "0.15"))

    return spread <= max_spread, round(spread, 6)


def check_depth_quality(
    orderbook: Dict[str, Any],
    min_depth: float = None
) -> Tuple[bool, str]:
    """
    Orderbook derinliğinin yeterli olup olmadığını kontrol et.

    Args:
        orderbook:  get_orderbook() dönüşü
        min_depth:  Minimum USD derinlik (None → env'den okunur)

    Returns:
        (depth_ok, reason)
    """
    if not orderbook or not orderbook.get("ok"):
        return False, "Invalid orderbook"

    if min_depth is None:
        min_depth = float(os.getenv("MIN_BAND_DEPTH", "5.0"))

    ob = orderbook.get("orderbook", {})
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])

    if not bids or not asks:
        return False, "Empty orderbook"

    # Sadece makul fiyat aralığındaki seviyeleri hesaba kat
    bid_depth = sum(
        float(b.get("price", 0)) * float(b.get("size", 0))
        for b in bids
        if 0.05 <= float(b.get("price", 0)) <= 0.95
    )
    ask_depth = sum(
        float(a.get("price", 0)) * float(a.get("size", 0))
        for a in asks
        if 0.05 <= float(a.get("price", 0)) <= 0.95
    )
    total_depth = bid_depth + ask_depth

    if total_depth < min_depth:
        return False, f"Insufficient depth: ${total_depth:.2f} < ${min_depth:.2f}"

    return True, "OK"


def validate_trade_timing(
    last_trade_ts: float,
    cooldown_seconds: int = None
) -> Tuple[bool, str]:
    """
    Son trade'den bu yana yeterli süre geçti mi?

    Args:
        last_trade_ts:    Son trade timestamp (0 = hiç trade olmadı)
        cooldown_seconds: Bekleme süresi (None → env'den)

    Returns:
        (timing_ok, reason)
    """
    import time

    if cooldown_seconds is None:
        cooldown_seconds = int(os.getenv("TRADE_COOLDOWN_S", "5"))

    if last_trade_ts == 0:
        return True, "OK"

    elapsed = time.time() - last_trade_ts

    if elapsed < cooldown_seconds:
        remaining = cooldown_seconds - elapsed
        return False, f"Trade cooldown: {remaining:.1f}s remaining"

    return True, "OK"
