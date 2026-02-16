# agent/bot/risk/drawdown_monitor.py
"""
Drawdown monitoring ve tracking
"""
import os
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from ..utils.cache import get_redis_client

class DrawdownMonitor:
    """Drawdown izleme ve hesaplama"""
    
    def __init__(self):
        self.redis = get_redis_client()
        self.max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PCT", "0.15"))
    
    def update_equity(self, current_equity: float) -> None:
        """
        Mevcut equity'yi güncelle ve drawdown hesapla
        
        Args:
            current_equity: Mevcut portföy değeri (USD)
        """
        try:
            timestamp = datetime.utcnow().isoformat()
            
            # Equity history'e ekle
            self.redis.zadd("drawdown:equity_history", {
                f"{timestamp}:{current_equity}": int(datetime.utcnow().timestamp())
            })
            
            # Son 30 gün tut
            cutoff = int((datetime.utcnow() - timedelta(days=30)).timestamp())
            self.redis.zremrangebyscore("drawdown:equity_history", 0, cutoff)
            
            # Peak equity'yi güncelle
            peak = float(self.redis.get("drawdown:peak_equity") or current_equity)
            if current_equity > peak:
                self.redis.set("drawdown:peak_equity", current_equity)
                self.redis.set("drawdown:peak_date", timestamp)
            
            # Current drawdown hesapla
            current_dd = self._calculate_current_drawdown(current_equity, peak)
            self.redis.set("drawdown:current", current_dd)
            
            # Max drawdown güncelle
            max_dd = float(self.redis.get("drawdown:max") or 0)
            if current_dd > max_dd:
                self.redis.set("drawdown:max", current_dd)
                self.redis.set("drawdown:max_date", timestamp)
            
        except Exception as e:
            print(f"[DRAWDOWN] Update equity error: {e}")
    
    def _calculate_current_drawdown(self, current_equity: float, peak_equity: float) -> float:
        """
        Mevcut drawdown'ı hesapla (USD)
        
        Returns:
            Drawdown miktarı (pozitif değer)
        """
        if peak_equity <= 0:
            return 0.0
        
        drawdown = peak_equity - current_equity
        return max(0.0, drawdown)
    
    def get_current_drawdown_pct(self) -> float:
        """
        Mevcut drawdown yüzdesini getir
        
        Returns:
            Drawdown percentage (0.0 - 1.0)
        """
        try:
            current_dd = float(self.redis.get("drawdown:current") or 0)
            peak = float(self.redis.get("drawdown:peak_equity") or 0)
            
            if peak <= 0:
                return 0.0
            
            return current_dd / peak
        except Exception:
            return 0.0
    
    def get_max_drawdown(self) -> Dict[str, Any]:
        """Maximum drawdown bilgilerini getir"""
        try:
            max_dd = float(self.redis.get("drawdown:max") or 0)
            max_dd_date = self.redis.get("drawdown:max_date") or "N/A"
            peak = float(self.redis.get("drawdown:peak_equity") or 0)
            
            max_dd_pct = (max_dd / peak) if peak > 0 else 0.0
            
            return {
                "max_drawdown_usd": round(max_dd, 2),
                "max_drawdown_pct": round(max_dd_pct * 100, 2),
                "max_drawdown_date": max_dd_date,
                "peak_equity": round(peak, 2)
            }
        except Exception as e:
            print(f"[DRAWDOWN] Get max drawdown error: {e}")
            return {
                "max_drawdown_usd": 0,
                "max_drawdown_pct": 0,
                "max_drawdown_date": "N/A",
                "peak_equity": 0
            }
    
    def get_drawdown_status(self) -> Dict[str, Any]:
        """Drawdown durumunu getir"""
        try:
            current_dd = float(self.redis.get("drawdown:current") or 0)
            peak = float(self.redis.get("drawdown:peak_equity") or 0)
            current_dd_pct = (current_dd / peak) if peak > 0 else 0.0
            
            max_dd_info = self.get_max_drawdown()
            
            # Limit kontrolü
            is_within_limit = current_dd_pct < self.max_drawdown_pct
            
            return {
                "current_drawdown_usd": round(current_dd, 2),
                "current_drawdown_pct": round(current_dd_pct * 100, 2),
                "peak_equity": round(peak, 2),
                "max_drawdown": max_dd_info,
                "limit_pct": round(self.max_drawdown_pct * 100, 2),
                "is_within_limit": is_within_limit,
                "usage_pct": round((current_dd_pct / self.max_drawdown_pct) * 100, 2) if self.max_drawdown_pct > 0 else 0
            }
        except Exception as e:
            print(f"[DRAWDOWN] Get status error: {e}")
            return {
                "current_drawdown_usd": 0,
                "current_drawdown_pct": 0,
                "peak_equity": 0,
                "is_within_limit": True,
                "usage_pct": 0
            }
    
    def reset_drawdown(self) -> None:
        """Drawdown tracking'i sıfırla (yeni başlangıç için)"""
        try:
            self.redis.delete("drawdown:peak_equity")
            self.redis.delete("drawdown:peak_date")
            self.redis.delete("drawdown:current")
            self.redis.delete("drawdown:max")
            self.redis.delete("drawdown:max_date")
            self.redis.delete("drawdown:equity_history")
        except Exception as e:
            print(f"[DRAWDOWN] Reset error: {e}")


# Global instance
_drawdown_monitor = None

def get_drawdown_monitor() -> DrawdownMonitor:
    """DrawdownMonitor singleton"""
    global _drawdown_monitor
    if _drawdown_monitor is None:
        _drawdown_monitor = DrawdownMonitor()
    return _drawdown_monitor
