# agent/bot/core/performance_tracker.py
"""
Performance tracker - Trade history analizi, auto-parameter tuning
"""
import time
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from ..monitoring.metrics import get_metrics_tracker
from ..utils.cache import get_redis_client

class PerformanceTracker:
    """Performance tracking ve analiz"""
    
    def __init__(self):
        self.metrics = get_metrics_tracker()
        self.redis = get_redis_client()
    
    def analyze_strategy_performance(self, days: int = 7) -> Dict[str, Any]:
        """
        Strateji performansını analiz et
        
        Args:
            days: Kaç günlük data
        
        Returns:
            Performance analysis
        """
        daily_metrics = []
        total_pnl = 0.0
        total_trades = 0
        
        for i in range(days):
            date = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
            daily = self.metrics.get_daily_metrics(date)
            
            daily_metrics.append(daily)
            total_pnl += daily.get("pnl", 0)
            total_trades += daily.get("trades", 0)
        
        # Sharpe ratio
        sharpe = self.metrics.calculate_sharpe_ratio(days)
        
        # Max drawdown
        max_dd = self.metrics.calculate_max_drawdown(days)
        
        # Win rate
        total_wins = sum(d.get("wins", 0) for d in daily_metrics)
        total_losses = sum(d.get("losses", 0) for d in daily_metrics)
        win_rate = (total_wins / (total_wins + total_losses) * 100) if (total_wins + total_losses) > 0 else 0
        
        # Average daily PnL
        avg_daily_pnl = total_pnl / days if days > 0 else 0
        
        return {
            "period_days": days,
            "total_pnl": round(total_pnl, 2),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "avg_daily_pnl": round(avg_daily_pnl, 2),
            "daily_breakdown": daily_metrics[:7]  # Son 7 gün
        }
    
    def get_best_trading_hours(self, days: int = 30) -> Dict[str, Any]:
        """
        En karlı trading saatleri (future implementation)
        
        Returns:
            Hourly performance breakdown
        """
        # TODO: Trade timestamp'lerini hour'a göre grupla
        # Şimdilik placeholder
        return {
            "analysis": "Not implemented yet",
            "best_hours": []
        }
    
    def get_market_type_performance(self) -> Dict[str, Any]:
        """
        Market tipine göre performans (future implementation)
        
        Örnek: Politics, Sports, Crypto marketlerde ayrı performans
        
        Returns:
            Performance by market category
        """
        # TODO: Market kategorilerine göre trade history analizi
        return {
            "analysis": "Not implemented yet",
            "by_category": {}
        }
    
    def suggest_parameter_adjustments(self) -> Dict[str, Any]:
        """
        Performansa göre parametre önerileri
        
        Returns:
            Suggested parameter adjustments
        """
        weekly = self.metrics.get_weekly_metrics()
        win_rate = weekly.get("win_rate", 0)
        pnl = weekly.get("pnl", 0)
        
        suggestions = []
        
        # Win rate çok düşükse
        if win_rate < 40 and weekly.get("trades", 0) >= 10:
            suggestions.append({
                "parameter": "MIN_LLM_CONF",
                "current": 0.55,
                "suggested": 0.65,
                "reason": "Low win rate - increase confidence threshold"
            })
        
        # Çok az trade
        if weekly.get("trades", 0) < 5:
            suggestions.append({
                "parameter": "MIN_LLM_CONF",
                "current": 0.55,
                "suggested": 0.50,
                "reason": "Too few trades - lower confidence threshold"
            })
        
        # Negative PnL
        if pnl < -20:
            suggestions.append({
                "parameter": "ORDER_USD",
                "current": 5.0,
                "suggested": 3.0,
                "reason": "Negative PnL - reduce position size"
            })
        
        return {
            "suggestions": suggestions,
            "analysis": {
                "win_rate": win_rate,
                "weekly_pnl": pnl,
                "weekly_trades": weekly.get("trades", 0)
            }
        }
    
    def export_trade_history(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Trade history export (CSV için)
        
        Returns:
            Trade history list
        """
        history = []
        
        for i in range(days):
            date = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
            
            try:
                trade_key = f"metrics:trades:{date}"
                trades = self.redis.lrange(trade_key, 0, -1)
                
                for trade_str in trades:
                    import json
                    trade = json.loads(trade_str)
                    history.append(trade)
            except Exception:
                pass
        
        return history
    
    def calculate_risk_adjusted_return(self) -> float:
        """
        Risk-adjusted return (Sortino ratio benzeri)
        
        Returns:
            Risk-adjusted return score
        """
        sharpe = self.metrics.calculate_sharpe_ratio(30)
        max_dd = self.metrics.calculate_max_drawdown(30)
        
        if max_dd == 0:
            return sharpe
        
        # Simple risk-adjusted score
        risk_adjusted = sharpe / (1 + (max_dd / 100))
        
        return round(risk_adjusted, 2)


# Global instance
_performance_tracker = None

def get_performance_tracker() -> PerformanceTracker:
    """PerformanceTracker singleton"""
    global _performance_tracker
    if _performance_tracker is None:
        _performance_tracker = PerformanceTracker()
    return _performance_tracker
