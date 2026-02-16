# agent/bot/utils/validators.py
"""
Input validation ve data sanitization
"""
from typing import Optional, Dict, Any

def validate_token_id(token_id: str) -> bool:
    """Token ID formatını doğrula"""
    if not token_id or not isinstance(token_id, str):
        return False
    # Polymarket token ID'leri genelde numeric string
    return len(token_id) > 0 and len(token_id) < 100

def validate_price(price: float) -> bool:
    """Fiyat değerini doğrula (0.01 - 0.99 arası)"""
    return isinstance(price, (int, float)) and 0.01 <= price <= 0.99

def validate_quantity(qty: float) -> bool:
    """Miktar değerini doğrula"""
    return isinstance(qty, (int, float)) and qty > 0

def validate_side(side: str) -> bool:
    """Order side doğrula (buy/sell)"""
    return isinstance(side, str) and side.lower() in ("buy", "sell")

def sanitize_decision(decision: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    LLM'den gelen decision objesini doğrula ve temizle
    
    Beklenen format:
    {
        "decision": "buy" | "sell" | "hold",
        "token_id": "12345",
        "limit_price": 0.65,
        "confidence": 0.75,
        "reasoning": "..."
    }
    """
    if not isinstance(decision, dict):
        return None
    
    # Required fields
    if "decision" not in decision or "token_id" not in decision:
        return None
    
    action = str(decision["decision"]).lower()
    if action not in ("buy", "sell", "hold"):
        return None
    
    # Hold için sadece decision yeterli
    if action == "hold":
        return {
            "decision": "hold",
            "token_id": str(decision.get("token_id", "")),
            "confidence": float(decision.get("confidence", 0.5)),
            "reasoning": str(decision.get("reasoning", "Hold decision"))
        }
    
    # Buy/Sell için limit_price zorunlu
    if "limit_price" not in decision:
        return None
    
    try:
        token_id = str(decision["token_id"])
        limit_price = float(decision["limit_price"])
        confidence = float(decision.get("confidence", 0.5))
        
        if not validate_token_id(token_id):
            return None
        if not validate_price(limit_price):
            return None
        if not (0.0 <= confidence <= 1.0):
            confidence = 0.5
        
        return {
            "decision": action,
            "token_id": token_id,
            "limit_price": limit_price,
            "confidence": confidence,
            "reasoning": str(decision.get("reasoning", ""))
        }
    except (ValueError, TypeError):
        return None

def validate_orderbook(ob: Dict[str, Any]) -> bool:
    """Orderbook formatını doğrula"""
    if not isinstance(ob, dict):
        return False
    
    bids = ob.get("bids", [])
    asks = ob.get("asks", [])
    
    if not isinstance(bids, list) or not isinstance(asks, list):
        return False
    
    # En az bir bid ve ask olmalı
    return len(bids) > 0 and len(asks) > 0
