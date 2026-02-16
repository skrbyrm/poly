# agent/bot/execution/order_router.py
"""
Smart order routing - Best execution price, order splitting
"""
from typing import Dict, Any, Optional, List, Tuple
from ..clob_read import get_orderbook
from ..config import MAX_SPREAD

class OrderRouter:
    """Smart order routing ve execution optimization"""
    
    def __init__(self):
        self.max_spread = MAX_SPREAD
    
    def find_best_execution_price(
        self,
        token_id: str,
        side: str,
        target_qty: float
    ) -> Optional[Tuple[float, float]]:
        """
        Best execution price bul
        
        Args:
            token_id: Token ID
            side: "buy" or "sell"
            target_qty: Hedef miktar
        
        Returns:
            (best_price, available_qty) veya None
        """
        ob_result = get_orderbook(token_id)
        
        if not ob_result.get("ok"):
            return None
        
        ob = ob_result.get("orderbook", {})
        
        if side.lower() == "buy":
            # Asks'ten en iyi fiyatı bul
            asks = ob.get("asks", [])
            if not asks:
                return None
            
            best_ask = float(asks[0].get("price", 0))
            best_size = float(asks[0].get("size", 0))
            
            return (best_ask, min(best_size, target_qty))
        
        else:  # sell
            # Bids'den en iyi fiyatı bul
            bids = ob.get("bids", [])
            if not bids:
                return None
            
            best_bid = float(bids[0].get("price", 0))
            best_size = float(bids[0].get("size", 0))
            
            return (best_bid, min(best_size, target_qty))
    
    def calculate_slippage(
        self,
        token_id: str,
        side: str,
        qty: float,
        limit_price: float
    ) -> Optional[float]:
        """
        Tahmini slippage hesapla
        
        Args:
            token_id: Token ID
            side: "buy" or "sell"
            qty: Order miktarı
            limit_price: Limit fiyat
        
        Returns:
            Slippage percentage (0.0 - 1.0) veya None
        """
        result = self.find_best_execution_price(token_id, side, qty)
        
        if not result:
            return None
        
        best_price, _ = result
        
        if best_price <= 0:
            return None
        
        # Slippage hesapla
        if side.lower() == "buy":
            slippage = (limit_price - best_price) / best_price
        else:
            slippage = (best_price - limit_price) / best_price
        
        return abs(slippage)
    
    def split_large_order(
        self,
        token_id: str,
        side: str,
        total_qty: float,
        max_order_size: float = 100.0
    ) -> List[float]:
        """
        Büyük order'ı küçük parçalara böl
        
        Args:
            token_id: Token ID
            side: "buy" or "sell"
            total_qty: Toplam miktar
            max_order_size: Maksimum tek order büyüklüğü
        
        Returns:
            Order büyüklükleri listesi
        """
        if total_qty <= max_order_size:
            return [total_qty]
        
        # Order'ı eşit parçalara böl
        num_orders = int(total_qty / max_order_size) + 1
        chunk_size = total_qty / num_orders
        
        chunks = [chunk_size] * (num_orders - 1)
        chunks.append(total_qty - sum(chunks))  # Kalan
        
        return [c for c in chunks if c > 0]
    
    def optimize_limit_price(
        self,
        token_id: str,
        side: str,
        desired_price: float,
        aggressive: bool = False
    ) -> Optional[float]:
        """
        Limit price'ı orderbook'a göre optimize et
        
        Args:
            token_id: Token ID
            side: "buy" or "sell"
            desired_price: İstenilen fiyat
            aggressive: Agresif pricing (hızlı execution)
        
        Returns:
            Optimize edilmiş fiyat
        """
        ob_result = get_orderbook(token_id)
        
        if not ob_result.get("ok"):
            return desired_price
        
        ob = ob_result.get("orderbook", {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        
        if not bids or not asks:
            return desired_price
        
        best_bid = float(bids[0].get("price", 0))
        best_ask = float(asks[0].get("price", 0))
        
        if side.lower() == "buy":
            if aggressive:
                # Market taker - best ask'e vur
                return best_ask
            else:
                # Maker - best bid üstüne koy (queue'ya gir)
                return min(desired_price, best_ask - 0.0001)
        
        else:  # sell
            if aggressive:
                # Market taker - best bid'e vur
                return best_bid
            else:
                # Maker - best ask altına koy
                return max(desired_price, best_bid + 0.0001)


# Global instance
_order_router = None

def get_order_router() -> OrderRouter:
    """OrderRouter singleton"""
    global _order_router
    if _order_router is None:
        _order_router = OrderRouter()
    return _order_router
