# agent/bot/execution/slippage_control.py
"""
Slippage kontrolü ve TWAP (Time-Weighted Average Price)
"""
import time
from typing import Dict, Any, Optional, List
from ..clob_read import get_orderbook

class SlippageController:
    """Slippage minimize etme ve TWAP execution"""
    
    def __init__(self):
        self.max_slippage_pct = 0.02  # %2 max slippage
    
    def estimate_slippage(
        self,
        token_id: str,
        side: str,
        qty: float,
        limit_price: float
    ) -> Dict[str, Any]:
        """
        Slippage tahmini yap
        
        Args:
            token_id: Token ID
            side: "buy" or "sell"
            qty: Order miktarı
            limit_price: Limit fiyat
        
        Returns:
            Slippage bilgileri
        """
        ob_result = get_orderbook(token_id)
        
        if not ob_result.get("ok"):
            return {
                "ok": False,
                "error": "Failed to get orderbook"
            }
        
        ob = ob_result.get("orderbook", {})
        
        if side.lower() == "buy":
            levels = ob.get("asks", [])
        else:
            levels = ob.get("bids", [])
        
        if not levels:
            return {
                "ok": False,
                "error": "Empty orderbook"
            }
        
        # VWAP (Volume-Weighted Average Price) hesapla
        total_filled = 0.0
        total_cost = 0.0
        remaining_qty = qty
        
        for level in levels:
            if remaining_qty <= 0:
                break
            
            level_price = float(level.get("price", 0))
            level_size = float(level.get("size", 0))
            
            fill_qty = min(remaining_qty, level_size)
            total_filled += fill_qty
            total_cost += fill_qty * level_price
            remaining_qty -= fill_qty
        
        if total_filled == 0:
            return {
                "ok": False,
                "error": "Insufficient liquidity"
            }
        
        vwap = total_cost / total_filled
        slippage = abs((vwap - limit_price) / limit_price) if limit_price > 0 else 0
        
        return {
            "ok": True,
            "vwap": round(vwap, 6),
            "limit_price": limit_price,
            "slippage_pct": round(slippage * 100, 2),
            "filled_qty": total_filled,
            "requested_qty": qty,
            "is_acceptable": slippage <= self.max_slippage_pct
        }
    
    def is_slippage_acceptable(
        self,
        token_id: str,
        side: str,
        qty: float,
        limit_price: float
    ) -> tuple[bool, str]:
        """
        Slippage kabul edilebilir mi?
        
        Returns:
            (acceptable, reason)
        """
        result = self.estimate_slippage(token_id, side, qty, limit_price)
        
        if not result.get("ok"):
            return False, result.get("error", "Unknown error")
        
        if not result.get("is_acceptable"):
            return False, f"Slippage too high: {result.get('slippage_pct', 0)}%"
        
        filled = result.get("filled_qty", 0)
        requested = result.get("requested_qty", qty)
        
        if filled < requested * 0.5:
            return False, f"Insufficient liquidity: can only fill {filled}/{requested}"
        
        return True, "OK"
    
    def twap_split(
        self,
        total_qty: float,
        duration_seconds: int = 60,
        num_orders: int = 5
    ) -> List[Dict[str, Any]]:
        """
        TWAP için order'ı zaman dilimlerine böl
        
        Args:
            total_qty: Toplam miktar
            duration_seconds: Süre (saniye)
            num_orders: Order sayısı
        
        Returns:
            TWAP execution plan
        """
        interval = duration_seconds / num_orders
        qty_per_order = total_qty / num_orders
        
        plan = []
        current_time = time.time()
        
        for i in range(num_orders):
            plan.append({
                "order_num": i + 1,
                "qty": qty_per_order,
                "execute_at": current_time + (interval * i),
                "delay_seconds": interval * i
            })
        
        return plan
    
    def calculate_price_impact(
        self,
        token_id: str,
        side: str,
        qty: float
    ) -> Optional[float]:
        """
        Fiyat etkisini (price impact) hesapla
        
        Returns:
            Price impact percentage
        """
        ob_result = get_orderbook(token_id)
        
        if not ob_result.get("ok"):
            return None
        
        ob = ob_result.get("orderbook", {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        
        if not bids or not asks:
            return None
        
        # Mid price
        best_bid = float(bids[0].get("price", 0))
        best_ask = float(asks[0].get("price", 0))
        mid_price = (best_bid + best_ask) / 2
        
        # Execution price tahmin
        if side.lower() == "buy":
            levels = asks
        else:
            levels = bids
        
        total_qty = 0.0
        weighted_price = 0.0
        
        for level in levels:
            level_price = float(level.get("price", 0))
            level_size = float(level.get("size", 0))
            
            fill_qty = min(qty - total_qty, level_size)
            weighted_price += fill_qty * level_price
            total_qty += fill_qty
            
            if total_qty >= qty:
                break
        
        if total_qty == 0:
            return None
        
        avg_execution_price = weighted_price / total_qty
        price_impact = abs((avg_execution_price - mid_price) / mid_price)
        
        return price_impact


# Global instance
_slippage_controller = None

def get_slippage_controller() -> SlippageController:
    """SlippageController singleton"""
    global _slippage_controller
    if _slippage_controller is None:
        _slippage_controller = SlippageController()
    return _slippage_controller
