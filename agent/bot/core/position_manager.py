# agent/bot/core/position_manager.py
"""
Position manager - Multi-position tracking, TP/SL, trailing stop
"""
import time
from typing import Dict, Any, Optional, List, Tuple
from ..config import TP_PCT, SL_PCT, MAX_HOLD_S, EXIT_ON_TIMEOUT
from ..clob_read import get_orderbook

class PositionManager:
    """Pozisyon yönetimi - TP/SL, timeout, trailing stop"""
    
    def __init__(self):
        self.tp_pct = TP_PCT
        self.sl_pct = SL_PCT
        self.max_hold_seconds = MAX_HOLD_S
        self.exit_on_timeout = bool(EXIT_ON_TIMEOUT)
    
    def check_exit_conditions(
        self,
        positions: Dict[str, Dict[str, Any]],
        current_prices: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """
        Pozisyonları kontrol et ve çıkış gerekenleri bul
        
        Args:
            positions: {token_id: position_data}
            current_prices: {token_id: current_price} (opsiyonel)
        
        Returns:
            Exit edilmesi gereken pozisyonlar listesi
        """
        exit_signals = []
        
        for token_id, pos in positions.items():
            avg_price = float(pos.get("avg_price", 0))
            qty = float(pos.get("qty", 0))
            opened_at = float(pos.get("opened_at", time.time()))
            
            if avg_price <= 0 or qty <= 0:
                continue
            
            # Current price getir
            if current_prices and token_id in current_prices:
                current_price = current_prices[token_id]
            else:
                current_price = self._fetch_current_price(token_id)
            
            if not current_price or current_price <= 0:
                continue
            
            # PnL hesapla
            pnl_pct = (current_price - avg_price) / avg_price
            
            # 1. Take Profit kontrolü
            if pnl_pct >= self.tp_pct:
                exit_signals.append({
                    "token_id": token_id,
                    "reason": "take_profit",
                    "qty": qty,
                    "current_price": current_price,
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "avg_price": avg_price
                })
                continue
            
            # 2. Stop Loss kontrolü
            if pnl_pct <= -self.sl_pct:
                exit_signals.append({
                    "token_id": token_id,
                    "reason": "stop_loss",
                    "qty": qty,
                    "current_price": current_price,
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "avg_price": avg_price
                })
                continue
            
            # 3. Timeout kontrolü
            if self.exit_on_timeout:
                hold_duration = time.time() - opened_at
                
                if hold_duration >= self.max_hold_seconds:
                    exit_signals.append({
                        "token_id": token_id,
                        "reason": "timeout",
                        "qty": qty,
                        "current_price": current_price,
                        "pnl_pct": round(pnl_pct * 100, 2),
                        "avg_price": avg_price,
                        "hold_duration": int(hold_duration)
                    })
        
        return exit_signals
    
    def _fetch_current_price(self, token_id: str) -> Optional[float]:
        """Token için current mid price getir"""
        try:
            ob_result = get_orderbook(token_id, timeout_s=2)
            
            if not ob_result.get("ok"):
                return None
            
            ob = ob_result.get("orderbook", {})
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            
            if not bids or not asks:
                return None
            
            best_bid = float(bids[0].get("price", 0))
            best_ask = float(asks[0].get("price", 0))
            
            mid_price = (best_bid + best_ask) / 2
            return mid_price
            
        except Exception:
            return None
    
    def calculate_trailing_stop(
        self,
        token_id: str,
        entry_price: float,
        current_price: float,
        trailing_pct: float = 0.005
    ) -> float:
        """
        Trailing stop price hesapla
        
        Args:
            token_id: Token ID
            entry_price: Giriş fiyatı
            current_price: Mevcut fiyat
            trailing_pct: Trailing percentage (varsayılan %0.5)
        
        Returns:
            Trailing stop price
        """
        # En yüksek fiyatı track et (cache'de saklanabilir)
        peak_price = max(entry_price, current_price)
        
        # Trailing stop = peak_price - (peak_price * trailing_pct)
        stop_price = peak_price * (1 - trailing_pct)
        
        return stop_price
    
    def should_rebalance(self, positions: Dict[str, Dict[str, Any]]) -> bool:
        """
        Pozisyonlar rebalance edilmeli mi?
        
        Örnek: Bir pozisyon portföyün %50'sinden fazla oldu
        
        Returns:
            True if rebalancing needed
        """
        if not positions:
            return False
        
        # Total position value
        total_value = sum(
            float(pos.get("qty", 0)) * float(pos.get("avg_price", 0))
            for pos in positions.values()
        )
        
        if total_value == 0:
            return False
        
        # En büyük pozisyonun yüzdesi
        max_position_pct = max(
            (float(pos.get("qty", 0)) * float(pos.get("avg_price", 0))) / total_value
            for pos in positions.values()
        )
        
        # %40'tan fazla ise rebalance et
        return max_position_pct > 0.40
    
    def get_position_summary(self, positions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Pozisyonların özetini çıkar
        
        Returns:
            Summary dict
        """
        if not positions:
            return {
                "total_positions": 0,
                "total_value": 0,
                "avg_hold_duration": 0
            }
        
        total_value = 0.0
        total_duration = 0.0
        current_time = time.time()
        
        for pos in positions.values():
            qty = float(pos.get("qty", 0))
            avg_price = float(pos.get("avg_price", 0))
            opened_at = float(pos.get("opened_at", current_time))
            
            total_value += qty * avg_price
            total_duration += (current_time - opened_at)
        
        avg_duration = total_duration / len(positions) if positions else 0
        
        return {
            "total_positions": len(positions),
            "total_value": round(total_value, 2),
            "avg_hold_duration": int(avg_duration),
            "positions": positions
        }


# Global instance
_position_manager = None

def get_position_manager() -> PositionManager:
    """PositionManager singleton"""
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager