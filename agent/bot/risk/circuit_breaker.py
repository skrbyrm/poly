# agent/bot/risk/circuit_breaker.py
"""
Circuit breaker - Acil durum otomatik stop mekanizması
"""
import os
import time
from typing import Dict, Any, Optional
from datetime import datetime
from ..utils.cache import get_redis_client
from ..monitoring.alerts import alert_circuit_breaker

class CircuitBreaker:
    """
    Circuit breaker pattern - Trading'i otomatik durdurma
    
    Durma sebepleri:
    - Günlük loss limit aşımı
    - Drawdown limit aşımı
    - Ardışık kayıplar (örn: 5 trade üst üste kayıp)
    - API hatası (rate limit vb.)
    - Manuel stop
    """
    
    STATE_CLOSED = "closed"  # Normal çalışma
    STATE_OPEN = "open"      # Trading durduruldu
    STATE_HALF_OPEN = "half_open"  # Test modunda
    
    def __init__(self):
        self.redis = get_redis_client()
        self.max_consecutive_losses = int(os.getenv("CB_MAX_CONSECUTIVE_LOSSES", "5"))
        self.cooldown_seconds = int(os.getenv("CB_COOLDOWN_SECONDS", "3600"))  # 1 saat
    
    def get_state(self) -> str:
        """Circuit breaker durumunu getir"""
        state = self.redis.get("circuit_breaker:state")
        return state if state in (self.STATE_CLOSED, self.STATE_OPEN, self.STATE_HALF_OPEN) else self.STATE_CLOSED
    
    def is_open(self) -> bool:
        """Circuit breaker açık mı? (Trading durdurulmuş mu?)"""
        return self.get_state() == self.STATE_OPEN
    
    def trip(self, reason: str) -> None:
        """
        Circuit breaker'ı aç (Trading'i durdur)
        
        Args:
            reason: Durma sebebi
        """
        if self.is_open():
            return  # Zaten açık
        
        self.redis.set("circuit_breaker:state", self.STATE_OPEN)
        self.redis.set("circuit_breaker:reason", reason)
        self.redis.set("circuit_breaker:tripped_at", datetime.utcnow().isoformat())
        
        # Alert gönder
        alert_circuit_breaker(reason)
        
        print(f"[CIRCUIT BREAKER] TRIPPED: {reason}")
    
    def reset(self) -> None:
        """Circuit breaker'ı sıfırla (Trading'i yeniden başlat)"""
        self.redis.set("circuit_breaker:state", self.STATE_CLOSED)
        self.redis.delete("circuit_breaker:reason")
        self.redis.delete("circuit_breaker:tripped_at")
        print("[CIRCUIT BREAKER] RESET - Trading resumed")
    
    def check_consecutive_losses(self, consecutive_losses: int) -> None:
        """Ardışık kayıp kontrolü"""
        if consecutive_losses >= self.max_consecutive_losses:
            self.trip(f"Consecutive losses limit reached: {consecutive_losses}")
    
    def check_daily_loss(self, daily_loss: float, limit: float) -> None:
        """Günlük kayıp limiti kontrolü"""
        if abs(daily_loss) >= limit:
            self.trip(f"Daily loss limit exceeded: ${daily_loss:.2f} >= ${limit:.2f}")
    
    def check_drawdown(self, drawdown_pct: float, limit_pct: float) -> None:
        """Drawdown limiti kontrolü"""
        if drawdown_pct >= limit_pct:
            self.trip(f"Max drawdown exceeded: {drawdown_pct*100:.1f}% >= {limit_pct*100:.1f}%")
    
    def check_api_errors(self, error_count: int, threshold: int = 10) -> None:
        """API hata sayısı kontrolü"""
        if error_count >= threshold:
            self.trip(f"API error threshold exceeded: {error_count} errors")
    
    def auto_reset_check(self) -> bool:
        """
        Cooldown süresi geçtiyse otomatik reset
        
        Returns:
            Reset yapıldı mı?
        """
        if not self.is_open():
            return False
        
        tripped_at_str = self.redis.get("circuit_breaker:tripped_at")
        if not tripped_at_str:
            return False
        
        try:
            tripped_at = datetime.fromisoformat(tripped_at_str)
            elapsed = (datetime.utcnow() - tripped_at).total_seconds()
            
            if elapsed >= self.cooldown_seconds:
                self.reset()
                return True
        except Exception as e:
            print(f"[CIRCUIT BREAKER] Auto reset check error: {e}")
        
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Circuit breaker durumunu getir"""
        state = self.get_state()
        reason = self.redis.get("circuit_breaker:reason") or "N/A"
        tripped_at = self.redis.get("circuit_breaker:tripped_at") or "N/A"
        
        status = {
            "state": state,
            "is_open": state == self.STATE_OPEN,
            "trading_enabled": state == self.STATE_CLOSED,
        }
        
        if state == self.STATE_OPEN:
            status["reason"] = reason
            status["tripped_at"] = tripped_at
            
            # Cooldown hesapla
            try:
                tripped_dt = datetime.fromisoformat(tripped_at)
                elapsed = (datetime.utcnow() - tripped_dt).total_seconds()
                remaining = max(0, self.cooldown_seconds - elapsed)
                status["cooldown_remaining_seconds"] = int(remaining)
            except Exception:
                status["cooldown_remaining_seconds"] = self.cooldown_seconds
        
        return status


# Global instance
_circuit_breaker = None

def get_circuit_breaker() -> CircuitBreaker:
    """CircuitBreaker singleton"""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker
