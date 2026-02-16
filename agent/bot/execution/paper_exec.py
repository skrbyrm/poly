# agent/bot/execution/paper_exec.py
"""
Paper trading execution - Simülasyon order execution
"""
import time
from typing import Dict, Any
from .paper_ledger import LEDGER
from ..monitoring.logger import log_trade
from ..monitoring.metrics import get_metrics_tracker

def place_order(token_id: str, side: str, price: float, qty: float) -> Dict[str, Any]:
    """
    Paper trading order yerleştir
    
    Args:
        token_id: Token ID
        side: "buy" or "sell"
        price: Limit price
        qty: Quantity
    
    Returns:
        Order result dict
    """
    side = side.lower()
    
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "Invalid side"}
    
    if qty <= 0:
        return {"ok": False, "error": "Invalid quantity"}
    
    if not (0.01 <= price <= 0.99):
        return {"ok": False, "error": "Invalid price"}
    
    # Simulate order execution
    try:
        if side == "buy":
            cost = qty * price
            
            # Cash kontrolü
            if cost > LEDGER.cash:
                return {
                    "ok": False,
                    "error": "Insufficient cash",
                    "required": cost,
                    "available": LEDGER.cash
                }
            
            # Pozisyon ekle
            LEDGER.add_position(token_id, qty, price)
            
            # Log
            log_trade("BUY", token_id, price, qty, mode="paper")
            
            return {
                "ok": True,
                "side": "buy",
                "token_id": token_id,
                "price": price,
                "qty": qty,
                "cost": cost,
                "timestamp": time.time()
            }
        
        else:  # sell
            # Pozisyon var mı kontrol
            pos = LEDGER.get_position(token_id)
            if not pos:
                return {"ok": False, "error": "No position to sell"}
            
            current_qty = float(pos.get("qty", 0))
            if qty > current_qty:
                qty = current_qty  # Maksimum mevcut qty
            
            # Pozisyon azalt
            pnl = LEDGER.reduce_position(token_id, qty, price)
            
            # Metrics kaydet
            if pnl is not None:
                metrics = get_metrics_tracker()
                metrics.record_trade({
                    "token_id": token_id,
                    "side": "sell",
                    "price": price,
                    "qty": qty,
                    "pnl": pnl,
                    "timestamp": time.time()
                })
            
            # Log
            log_trade("SELL", token_id, price, qty, mode="paper", pnl=pnl)
            
            return {
                "ok": True,
                "side": "sell",
                "token_id": token_id,
                "price": price,
                "qty": qty,
                "pnl": pnl,
                "timestamp": time.time()
            }
    
    except Exception as e:
        return {
            "ok": False,
            "error": f"Execution error: {e}"
        }


def cancel_order(order_id: str) -> Dict[str, Any]:
    """Paper trading'de cancel fonksiyonu (simülasyon)"""
    return {"ok": True, "message": "Paper trading - no real orders to cancel"}


def get_open_orders(token_id: str = None) -> Dict[str, Any]:
    """Paper trading'de open orders (simülasyon - her zaman boş)"""
    return {
        "ok": True,
        "orders": [],
        "message": "Paper trading - orders execute instantly"
    }
