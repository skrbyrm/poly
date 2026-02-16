# agent/bot/risk/kelly_criterion.py
"""
Kelly Criterion - Optimal position sizing
"""
import os
from typing import Dict, Any, Optional

class KellyCriterion:
    """
    Kelly Criterion ile position sizing hesaplama
    
    Formula: f = (bp - q) / b
    
    f = optimal position size (portföyün yüzdesi)
    b = odds (kazanç/kayıp oranı)
    p = win probability
    q = loss probability (1 - p)
    """
    
    def __init__(self):
        self.kelly_fraction = float(os.getenv("KELLY_FRACTION", "0.25"))  # Fractional Kelly (daha konservatif)
        self.min_position_size = float(os.getenv("MIN_POSITION_SIZE_USD", "5.0"))
        self.max_position_size = float(os.getenv("MAX_POSITION_SIZE_USD", "100.0"))
    
    def calculate_position_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        portfolio_value: float
    ) -> float:
        """
        Kelly Criterion ile optimal position size hesapla
        
        Args:
            win_rate: Win rate (0.0 - 1.0)
            avg_win: Ortalama kazanç (USD)
            avg_loss: Ortalama kayıp (USD, pozitif değer)
            portfolio_value: Toplam portföy değeri (USD)
        
        Returns:
            Önerilen position size (USD)
        """
        if win_rate <= 0 or win_rate >= 1:
            return self.min_position_size
        
        if avg_loss <= 0 or avg_win <= 0:
            return self.min_position_size
        
        # Kelly formula
        p = win_rate
        q = 1 - p
        b = avg_win / avg_loss  # Odds ratio
        
        kelly_pct = (b * p - q) / b
        
        # Negatif Kelly = edge yok, trade yapma
        if kelly_pct <= 0:
            return 0.0
        
        # Fractional Kelly (risk azaltma)
        adjusted_kelly = kelly_pct * self.kelly_fraction
        
        # Cap at maximum
        adjusted_kelly = min(adjusted_kelly, 0.5)  # Portföyün max %50'si
        
        # Position size hesapla
        position_size = portfolio_value * adjusted_kelly
        
        # Min/Max clamp
        position_size = max(self.min_position_size, position_size)
        position_size = min(self.max_position_size, position_size)
        
        return round(position_size, 2)
    
    def calculate_with_confidence(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        portfolio_value: float,
        confidence: float
    ) -> float:
        """
        Confidence score ile ayarlanmış position sizing
        
        Args:
            confidence: AI confidence score (0.0 - 1.0)
        
        Returns:
            Adjusted position size (USD)
        """
        base_size = self.calculate_position_size(win_rate, avg_win, avg_loss, portfolio_value)
        
        if base_size == 0:
            return 0.0
        
        # Confidence multiplier (0.5 = min confidence için %50, 1.0 = max için %100)
        confidence_adj = 0.5 + (confidence * 0.5)
        
        adjusted_size = base_size * confidence_adj
        
        # Min/Max clamp
        adjusted_size = max(self.min_position_size, adjusted_size)
        adjusted_size = min(self.max_position_size, adjusted_size)
        
        return round(adjusted_size, 2)
    
    def simple_position_size(
        self,
        portfolio_value: float,
        risk_pct: float = 0.02,
        confidence: float = 0.7
    ) -> float:
        """
        Basitleştirilmiş position sizing (historical data yoksa)
        
        Args:
            portfolio_value: Portföy değeri
            risk_pct: Risk yüzdesi (varsayılan %2)
            confidence: AI confidence
        
        Returns:
            Position size (USD)
        """
        base_size = portfolio_value * risk_pct
        
        # Confidence adjustment
        confidence_adj = 0.5 + (confidence * 0.5)
        adjusted_size = base_size * confidence_adj
        
        # Min/Max clamp
        adjusted_size = max(self.min_position_size, adjusted_size)
        adjusted_size = min(self.max_position_size, adjusted_size)
        
        return round(adjusted_size, 2)


# Global instance
_kelly_criterion = None

def get_kelly_criterion() -> KellyCriterion:
    """KellyCriterion singleton"""
    global _kelly_criterion
    if _kelly_criterion is None:
        _kelly_criterion = KellyCriterion()
    return _kelly_criterion


def calculate_optimal_size(
    portfolio_value: float,
    win_rate: Optional[float] = None,
    avg_win: Optional[float] = None,
    avg_loss: Optional[float] = None,
    confidence: float = 0.7
) -> float:
    """
    Optimal position size hesapla (convenience function)
    
    Historical data varsa Kelly, yoksa simple method kullan
    """
    kelly = get_kelly_criterion()
    
    # Historical data varsa Kelly kullan
    if all(x is not None for x in [win_rate, avg_win, avg_loss]):
        return kelly.calculate_with_confidence(
            win_rate, avg_win, avg_loss, portfolio_value, confidence
        )
    
    # Yoksa basit method
    return kelly.simple_position_size(portfolio_value, confidence=confidence)
