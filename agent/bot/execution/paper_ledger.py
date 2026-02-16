# agent/bot/execution/paper_ledger.py
"""
Paper trading ledger - Simülasyon için pozisyon takibi
"""
import os
import json
import time
from typing import Dict, Any, Optional
from ..utils.cache import get_redis_client
from ..config import LEDGER_REDIS_KEY

class PaperLedger:
    """Paper trading için ledger (pozisyon takibi)"""
    
    def __init__(self):
        self.redis = get_redis_client()
        self.key = LEDGER_REDIS_KEY
        
        # In-memory state
        self.cash: float = 1000.0  # Başlangıç bakiyesi
        self.positions: Dict[str, Dict[str, Any]] = {}  # token_id -> {qty, avg_price, ...}
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
                self.cash = float(state.get("cash", 1000.0))
                self.positions = state.get("positions", {})
                self.closed_positions = state.get("closed_positions", [])
                self.total_pnl = float(state.get("total_pnl", 0.0))
        except Exception as e:
            print(f"[LEDGER] Load error: {e}")
    
    def save_to_redis(self) -> None:
        """Ledger state'ini Redis'e kaydet"""
        try:
            state = {
                "cash": self.cash,
                "positions": self.positions,
                "closed_positions": self.closed_positions[-100:],  # Son 100 pozisyon
                "total_pnl": self.total_pnl,
                "updated_at": time.time()
            }
            self.redis.set(self.key, json.dumps(state))
        except Exception as e:
            print(f"[LEDGER] Save error: {e}")
    
    def add_position(self, token_id: str, qty: float, price: float) -> None:
        """Pozisyon ekle (BUY)"""
        if token_id in self.positions:
            # Mevcut pozisyon var, average price güncelle
            pos = self.positions[token_id]
            old_qty = float(pos.get("qty", 0))
            old_avg = float(pos.get("avg_price", 0))
            
            new_qty = old_qty + qty
            new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty if new_qty > 0 else price
            
            self.positions[token_id]["qty"] = new_qty
            self.positions[token_id]["avg_price"] = new_avg
        else:
            # Yeni pozisyon
            self.positions[token_id] = {
                "qty": qty,
                "avg_price": price,
                "opened_at": time.time()
            }
        
        # Cash düş
        self.cash -= (qty * price)
        self.save_to_redis()
    
    def reduce_position(self, token_id: str, qty: float, price: float) -> Optional[float]:
        """
        Pozisyon azalt (SELL)
        
        Returns:
            PnL (profit/loss)
        """
        if token_id not in self.positions:
            return None
        
        pos = self.positions[token_id]
        current_qty = float(pos.get("qty", 0))
        avg_price = float(pos.get("avg_price", 0))
        
        if qty > current_qty:
            qty = current_qty  # Maksimum mevcut qty
        
        # PnL hesapla
        pnl = (price - avg_price) * qty
        
        # Pozisyonu güncelle
        new_qty = current_qty - qty
        
        if new_qty <= 0.001:  # Pozisyon kapandı
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
        
        # Cash artır
        self.cash += (qty * price)
        self.total_pnl += pnl
        
        self.save_to_redis()
        return pnl
    
    def get_position(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Token için pozisyon bilgisi getir"""
        return self.positions.get(token_id)
    
    def get_portfolio_value(self, current_prices: Optional[Dict[str, float]] = None) -> float:
        """
        Portföy değerini hesapla
        
        Args:
            current_prices: {token_id: current_price} dict (opsiyonel)
        
        Returns:
            Total portfolio value
        """
        total = self.cash
        
        for token_id, pos in self.positions.items():
            qty = float(pos.get("qty", 0))
            
            if current_prices and token_id in current_prices:
                price = current_prices[token_id]
            else:
                price = float(pos.get("avg_price", 0))
            
            total += (qty * price)
        
        return total
    
    def snapshot(self) -> Dict[str, Any]:
        """Ledger snapshot'ı getir"""
        return {
            "ok": True,
            "cash": round(self.cash, 2),
            "positions": self.positions,
            "open_positions_count": len(self.positions),
            "total_pnl": round(self.total_pnl, 2),
            "portfolio_value": round(self.get_portfolio_value(), 2),
            "recent_closed": self.closed_positions[-10:]
        }
    
    def reset(self, initial_cash: float = 1000.0) -> None:
        """Ledger'ı sıfırla"""
        self.cash = initial_cash
        self.positions = {}
        self.closed_positions = []
        self.total_pnl = 0.0
        self.save_to_redis()


# Global instance
LEDGER = PaperLedger()

def load_ledger_from_redis(ledger: PaperLedger) -> None:
    """Helper function to load ledger"""
    ledger.load_from_redis()
