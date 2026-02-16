# agent/bot/risk/checks.py
"""
Order validation ve risk checks
"""
import os
from typing import Optional, Dict, Any

def clamp_order(qty: float, price: float) -> float:
    """
    Order miktarını min/max limitlerle sınırla
    
    Args:
        qty: Order miktarı
        price: Order fiyatı
    
    Returns:
        Clamped quantity
    """
    min_order_size = float(os.getenv("MIN_ORDER_SIZE", "1.0"))
    max_order_size = float(os.getenv("MAX_ORDER_SIZE", "1000.0"))
    
    # Min check
    if qty < min_order_size:
        return 0.0
    
    # Max check
    if qty > max_order_size:
        qty = max_order_size
    
    return round(qty, 2)


def validate_order_price(price: float, orderbook: Dict[str, Any], side: str) -> tuple[bool, str]:
    """
    Order fiyatını orderbook'a göre doğrula
    
    Args:
        price: Limit price
        orderbook: Orderbook data
        side: "buy" veya "sell"
    
    Returns:
        (valid, reason)
    """
    if not orderbook or not orderbook.get("ok"):
        return False, "Invalid orderbook"
    
    ob = orderbook.get("orderbook", {})
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])
    
    if not bids or not asks:
        return False, "Empty orderbook"
    
    try:
        best_bid = float(bids[0].get("price", 0))
        best_ask = float(asks[0].get("price", 0))
        
        if best_bid <= 0 or best_ask <= 0:
            return False, "Invalid best bid/ask"
        
        # Spread check
        spread = best_ask - best_bid
        max_spread = float(os.getenv("MAX_SPREAD", "0.05"))
        
        if spread > max_spread:
            return False, f"Spread too wide: {spread:.4f} > {max_spread}"
        
        # Price sanity check
        if side == "buy":
            # Buy fiyatı best_ask'den çok yüksek olmamalı
            if price > best_ask * 1.1:
                return False, f"Buy price too high: {price:.4f} vs best_ask {best_ask:.4f}"
        else:  # sell
            # Sell fiyatı best_bid'den çok düşük olmamalı
            if price < best_bid * 0.9:
                return False, f"Sell price too low: {price:.4f} vs best_bid {best_bid:.4f}"
        
        return True, "OK"
        
    except Exception as e:
        return False, f"Price validation error: {e}"


def check_spread_quality(orderbook: Dict[str, Any]) -> tuple[bool, float]:
    """
    Orderbook spread kalitesini kontrol et
    
    Returns:
        (acceptable, spread_value)
    """
    if not orderbook or not orderbook.get("ok"):
        return False, 999.0
    
    ob = orderbook.get("orderbook", {})
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])
    
    if not bids or not asks:
        return False, 999.0
    
    try:
        best_bid = float(bids[0].get("price", 0))
        best_ask = float(asks[0].get("price", 0))
        
        spread = best_ask - best_bid
        max_spread = float(os.getenv("MAX_SPREAD", "0.05"))
        
        return spread <= max_spread, spread
        
    except Exception:
        return False, 999.0


def check_depth_quality(orderbook: Dict[str, Any], min_depth: float = 50.0) -> tuple[bool, str]:
    """
    Orderbook depth kalitesini kontrol et
    
    Args:
        orderbook: Orderbook data
        min_depth: Minimum total depth (USD)
    
    Returns:
        (acceptable, reason)
    """
    if not orderbook or not orderbook.get("ok"):
        return False, "Invalid orderbook"
    
    ob = orderbook.get("orderbook", {})
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])
    
    if not bids or not asks:
        return False, "Empty orderbook"
    
    try:
        # Top 5 level depth hesapla
        bid_depth = sum(float(b.get("price", 0)) * float(b.get("size", 0)) for b in bids[:5])
        ask_depth = sum(float(a.get("price", 0)) * float(a.get("size", 0)) for a in asks[:5])
        
        total_depth = bid_depth + ask_depth
        
        if total_depth < min_depth:
            return False, f"Insufficient depth: ${total_depth:.2f} < ${min_depth:.2f}"
        
        return True, "OK"
        
    except Exception as e:
        return False, f"Depth check error: {e}"


def validate_trade_timing(last_trade_ts: float, cooldown_seconds: int = 5) -> tuple[bool, str]:
    """
    Trade timing kontrolü (çok hızlı trade engelleme)
    
    Args:
        last_trade_ts: Son trade timestamp
        cooldown_seconds: Minimum bekleme süresi
    
    Returns:
        (allowed, reason)
    """
    import time
    
    if last_trade_ts == 0:
        return True, "OK"
    
    elapsed = time.time() - last_trade_ts
    
    if elapsed < cooldown_seconds:
        return False, f"Trade cooldown: {cooldown_seconds - elapsed:.1f}s remaining"
    
    return True, "OK"
