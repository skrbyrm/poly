# agent/bot/execution/live_ledger.py
"""
Live trading ledger - Gerçek pozisyon takibi
"""
import os
import json
import time
from typing import Dict, Any, Optional
from ..utils.cache import get_redis_client
from ..config import LIVE_LEDGER_REDIS_KEY, LIVE_LEDGER_TTL_S

class LiveLedger:
    """Live trading için ledger"""
    
    def __init__(self):
        self.redis = get_redis_client()
        self.key = LIVE_LEDGER_REDIS_KEY
        self.ttl = LIVE_LEDGER_TTL_S
        
        # In-memory state
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.closed_positions: list = []
        self.total_pnl: float = 0.0
        
        # Load from Redis
        self.load_from_redis()
    
    def load_from_redis(self) -> None:
        """Redis'ten ledger state'ini yükle"""
        try:
            data = self.redis.get(self.key)
            if data:
                state = json.loads(data)
                self.positions = state.get("positions", {})
                self.closed_positions = state.get("closed_positions", [])
                self.total_pnl = float(state.get("total_pnl", 0.0))
        except Exception as e:
            print(f"[LIVE_LEDGER] Load error: {e}")
    
    def save_to_redis(self) -> None:
        """Ledger state'ini Redis'e kaydet"""
        try:
            state = {
                "positions": self.positions,
                "closed_positions": self.closed_positions[-100:],
                "total_pnl": self.total_pnl,
                "updated_at": time.time()
            }
            self.redis.setex(self.key, self.ttl, json.dumps(state))
        except Exception as e:
            print(f"[LIVE_LEDGER] Save error: {e}")
    
    def sync_with_clob(self, clob_positions: Dict[str, Any]) -> None:
        """
        CLOB API'den pozisyonları senkronize et
        
        Args:
            clob_positions: CLOB'dan gelen pozisyon data
        """
        # TODO: CLOB API'den pozisyonları çek ve senkronize et
        # Bu implementation CLOB API response formatına göre customize edilmeli
        pass
    
    def add_position(self, token_id: str, qty: float, price: float, order_id: str = None) -> None:
        """Pozisyon ekle (BUY)"""
        if token_id in self.positions:
            pos = self.positions[token_id]
            old_qty = float(pos.get("qty", 0))
            old_avg = float(pos.get("avg_price", 0))
            
            new_qty = old_qty + qty
            new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty if new_qty > 0 else price
            
            self.positions[token_id]["qty"] = new_qty
            self.positions[token_id]["avg_price"] = new_avg
            
            if order_id:
                self.positions[token_id].setdefault("order_ids", []).append(order_id)
        else:
            self.positions[token_id] = {
                "qty": qty,
                "avg_price": price,
                "opened_at": time.time(),
                "order_ids": [order_id] if order_id else []
            }
        
        self.save_to_redis()
    
    def reduce_position(self, token_id: str, qty: float, price: float, order_id: str = None) -> Optional[float]:
        """Pozisyon azalt (SELL)"""
        if token_id not in self.positions:
            return None
        
        pos = self.positions[token_id]
        current_qty = float(pos.get("qty", 0))
        avg_price = float(pos.get("avg_price", 0))
        
        if qty > current_qty:
            qty = current_qty
        
        pnl = (price - avg_price) * qty
        new_qty = current_qty - qty
        
        if new_qty <= 0.001:
            closed_pos = {
                "token_id": token_id,
                "qty": current_qty,
                "avg_buy_price": avg_price,
                "sell_price": price,
                "pnl": pnl,
                "closed_at": time.time()
            }
            self.closed_positions.append(closed_pos)
            del self.positions[token_id]
        else:
            self.positions[token_id]["qty"] = new_qty
            if order_id:
                self.positions[token_id].setdefault("order_ids", []).append(order_id)
        
        self.total_pnl += pnl
        self.save_to_redis()
        return pnl
    
    def get_position(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Token için pozisyon bilgisi getir"""
        return self.positions.get(token_id)
    
    def snapshot(self) -> Dict[str, Any]:
        """Ledger snapshot'ı getir"""
        return {
            "ok": True,
            "positions": self.positions,
            "open_positions_count": len(self.positions),
            "total_pnl": round(self.total_pnl, 2),
            "recent_closed": self.closed_positions[-10:]
        }


# Global instance
LIVE_LEDGER = LiveLedger()
