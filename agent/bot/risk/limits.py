# agent/bot/risk/limits.py
"""
Risk limitleri - Günlük/haftalık loss limits, pozisyon limitleri
"""
import os
from typing import Dict, Any, Optional
from datetime import datetime
from ..utils.cache import get_redis_client

class RiskLimits:
    """Risk limit kontrolü"""
    
    def __init__(self):
        self.redis = get_redis_client()
        
        # Config'den limitleri oku
        self.max_daily_loss = float(os.getenv("MAX_DAILY_LOSS", "50.0"))
        self.max_weekly_loss = float(os.getenv("MAX_WEEKLY_LOSS", "200.0"))
        self.max_position_size_usd = float(os.getenv("MAX_POSITION_SIZE_USD", "100.0"))
        self.max_position_pct = float(os.getenv("MAX_POSITION_PCT", "0.20"))  # Portföyün %20'si
        self.max_open_positions = int(os.getenv("MANAGE_MAX_POS", "3"))
        self.max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PCT", "0.15"))  # %15
    
    def check_daily_loss_limit(self, current_loss: float) -> tuple[bool, str]:
        """
        Günlük kayıp limitini kontrol et
        
        Returns:
            (allowed, reason)
        """
        if abs(current_loss) >= self.max_daily_loss:
            return False, f"Daily loss limit reached: ${current_loss:.2f} >= ${self.max_daily_loss:.2f}"
        
        return True, "OK"
    
    def check_weekly_loss_limit(self, current_loss: float) -> tuple[bool, str]:
        """Haftalık kayıp limitini kontrol et"""
        if abs(current_loss) >= self.max_weekly_loss:
            return False, f"Weekly loss limit reached: ${current_loss:.2f} >= ${self.max_weekly_loss:.2f}"
        
        return True, "OK"
    
    def check_position_size(self, order_size_usd: float, portfolio_value: float) -> tuple[bool, str]:
        """
        Pozisyon büyüklüğü kontrolü
        
        Args:
            order_size_usd: Order büyüklüğü (USD)
            portfolio_value: Toplam portföy değeri (USD)
        
        Returns:
            (allowed, reason)
        """
        # Absolute limit
        if order_size_usd > self.max_position_size_usd:
            return False, f"Position size exceeds limit: ${order_size_usd:.2f} > ${self.max_position_size_usd:.2f}"
        
        # Percentage limit
        if portfolio_value > 0:
            position_pct = order_size_usd / portfolio_value
            if position_pct > self.max_position_pct:
                return False, f"Position exceeds {self.max_position_pct*100:.0f}% of portfolio: {position_pct*100:.1f}%"
        
        return True, "OK"
    
    def check_max_positions(self, current_positions: int) -> tuple[bool, str]:
        """Maksimum açık pozisyon sayısını kontrol et"""
        if current_positions >= self.max_open_positions:
            return False, f"Max open positions reached: {current_positions} >= {self.max_open_positions}"
        
        return True, "OK"
    
    def check_drawdown_limit(self, current_drawdown_pct: float) -> tuple[bool, str]:
        """Drawdown limitini kontrol et"""
        if current_drawdown_pct >= self.max_drawdown_pct:
            return False, f"Max drawdown exceeded: {current_drawdown_pct*100:.1f}% >= {self.max_drawdown_pct*100:.1f}%"
        
        return True, "OK"
    
    def can_open_position(
        self,
        order_size_usd: float,
        portfolio_value: float,
        current_positions: int,
        daily_pnl: float,
        weekly_pnl: float,
        current_drawdown_pct: float
    ) -> tuple[bool, str]:
        """
        Tüm limitleri kontrol et ve pozisyon açılabilir mi?
        
        Returns:
            (allowed, reason)
        """
        # Daily loss limit
        allowed, reason = self.check_daily_loss_limit(daily_pnl)
        if not allowed:
            return False, reason
        
        # Weekly loss limit
        allowed, reason = self.check_weekly_loss_limit(weekly_pnl)
        if not allowed:
            return False, reason
        
        # Position size
        allowed, reason = self.check_position_size(order_size_usd, portfolio_value)
        if not allowed:
            return False, reason
        
        # Max positions
        allowed, reason = self.check_max_positions(current_positions)
        if not allowed:
            return False, reason
        
        # Drawdown
        allowed, reason = self.check_drawdown_limit(current_drawdown_pct)
        if not allowed:
            return False, reason
        
        return True, "All risk checks passed"
    
    def get_current_limits_status(self) -> Dict[str, Any]:
        """Mevcut limit durumlarını getir"""
        return {
            "limits": {
                "max_daily_loss": self.max_daily_loss,
                "max_weekly_loss": self.max_weekly_loss,
                "max_position_size_usd": self.max_position_size_usd,
                "max_position_pct": self.max_position_pct,
                "max_open_positions": self.max_open_positions,
                "max_drawdown_pct": self.max_drawdown_pct
            }
        }


# Global instance
_risk_limits = None

def get_risk_limits() -> RiskLimits:
    """RiskLimits singleton"""
    global _risk_limits
    if _risk_limits is None:
        _risk_limits = RiskLimits()
    return _risk_limits
