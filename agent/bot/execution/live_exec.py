# agent/bot/execution/live_exec.py
"""
Live trading execution - Gerçek CLOB order execution
"""
import time
from typing import Dict, Any, Optional
from ..clob import build_clob_client
from .live_ledger import LIVE_LEDGER
from ..monitoring.logger import log_trade
from ..monitoring.metrics import get_metrics_tracker
from ..monitoring.alerts import alert_trade

def place_order(token_id: str, side: str, price: float, qty: float) -> Dict[str, Any]:
    """
    Live trading order yerleştir
    
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
    
    try:
        client = build_clob_client()
        
        # Create order
        if hasattr(client, "create_order"):
            response = client.create_order(
                token_id=token_id,
                side=side.upper(),
                price=price,
                size=qty
            )
        elif hasattr(client, "post_order"):
            response = client.post_order(
                token_id=token_id,
                side=side.upper(),
                price=price,
                size=qty
            )
        else:
            return {"ok": False, "error": "CLOB client missing order method"}
        
        # Parse response
        if isinstance(response, dict):
            if response.get("success") or response.get("ok"):
                order_id = response.get("order_id") or response.get("id")
                
                # Update ledger
                if side == "buy":
                    LIVE_LEDGER.add_position(token_id, qty, price, order_id)
                else:  # sell
                    pnl = LIVE_LEDGER.reduce_position(token_id, qty, price, order_id)
                    
                    # Metrics & alerts
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
                        alert_trade(side, token_id, price, qty, pnl)
                
                # Log
                log_trade(side.upper(), token_id, price, qty, mode="live", order_id=order_id)
                
                return {
                    "ok": True,
                    "side": side,
                    "token_id": token_id,
                    "price": price,
                    "qty": qty,
                    "order_id": order_id,
                    "timestamp": time.time()
                }
            else:
                error_msg = response.get("error") or response.get("message") or "Unknown error"
                return {"ok": False, "error": error_msg}
        
        return {"ok": False, "error": "Invalid response format"}
    
    except Exception as e:
        return {"ok": False, "error": f"Live execution error: {e}"}


def cancel_order(order_id: str) -> Dict[str, Any]:
    """
    Order iptal et
    
    Args:
        order_id: Order ID
    
    Returns:
        Cancel result
    """
    try:
        client = build_clob_client()
        
        if hasattr(client, "cancel_order"):
            response = client.cancel_order(order_id)
        elif hasattr(client, "delete_order"):
            response = client.delete_order(order_id)
        else:
            return {"ok": False, "error": "CLOB client missing cancel method"}
        
        if isinstance(response, dict):
            if response.get("success") or response.get("ok"):
                return {"ok": True, "order_id": order_id}
            else:
                return {"ok": False, "error": response.get("error") or "Cancel failed"}
        
        return {"ok": True, "order_id": order_id}
    
    except Exception as e:
        return {"ok": False, "error": f"Cancel error: {e}"}


def get_open_orders(token_id: str = None) -> Dict[str, Any]:
    """
    Açık order'ları getir
    
    Args:
        token_id: Opsiyonel token filter
    
    Returns:
        Open orders list
    """
    try:
        client = build_clob_client()
        
        if hasattr(client, "get_orders"):
            orders = client.get_orders()
        elif hasattr(client, "get_open_orders"):
            orders = client.get_open_orders()
        else:
            return {"ok": False, "error": "CLOB client missing get_orders method"}
        
        # Filter by token_id if provided
        if token_id and isinstance(orders, list):
            orders = [o for o in orders if o.get("token_id") == token_id]
        
        return {
            "ok": True,
            "orders": orders if isinstance(orders, list) else [],
            "count": len(orders) if isinstance(orders, list) else 0
        }
    
    except Exception as e:
        return {"ok": False, "error": f"Get orders error: {e}"}


def get_balance() -> Dict[str, Any]:
    """
    Wallet balance getir
    
    Returns:
        Balance info
    """
    try:
        client = build_clob_client()
        
        if hasattr(client, "get_balance"):
            balance = client.get_balance()
        elif hasattr(client, "get_balances"):
            balance = client.get_balances()
        else:
            return {"ok": False, "error": "CLOB client missing balance method"}
        
        return {
            "ok": True,
            "balance": balance
        }
    
    except Exception as e:
        return {"ok": False, "error": f"Balance error: {e}"}
