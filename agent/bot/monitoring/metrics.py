# agent/bot/monitoring/metrics.py
"""
Performance metrics tracking ve hesaplama
"""
import os
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from ..utils.cache import get_redis_client, get_cached, set_cached

class MetricsTracker:
    """Performance metrikleri izleyici"""
    
    def __init__(self):
        self.redis = get_redis_client()
    
    def record_trade(self, trade_data: Dict[str, Any]) -> None:
        """Trade kaydı"""
        try:
            timestamp = int(time.time())
            date_key = datetime.utcnow().strftime("%Y-%m-%d")
            
            # Trade history
            trade_key = f"metrics:trades:{date_key}"
            self.redis.lpush(trade_key, str(trade_data))
            self.redis.expire(trade_key, 86400 * 30)  # 30 gün sakla
            
            # Counters
            self.redis.incr(f"metrics:count:trades:{date_key}")
            self.redis.expire(f"metrics:count:trades:{date_key}", 86400 * 30)
            
            # PnL tracking
            pnl = float(trade_data.get("pnl", 0))
            if pnl != 0:
                current_pnl = float(self.redis.get(f"metrics:pnl:{date_key}") or 0)
                self.redis.set(f"metrics:pnl:{date_key}", current_pnl + pnl)
                self.redis.expire(f"metrics:pnl:{date_key}", 86400 * 30)
            
            # Win/Loss tracking
            if pnl > 0:
                self.redis.incr(f"metrics:wins:{date_key}")
            elif pnl < 0:
                self.redis.incr(f"metrics:losses:{date_key}")
            
        except Exception as e:
            print(f"[METRICS] Record trade error: {e}")
    
    def get_daily_metrics(self, date: Optional[str] = None) -> Dict[str, Any]:
        """Günlük metrikleri getir"""
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")
        
        try:
            trades = int(self.redis.get(f"metrics:count:trades:{date}") or 0)
            pnl = float(self.redis.get(f"metrics:pnl:{date}") or 0)
            wins = int(self.redis.get(f"metrics:wins:{date}") or 0)
            losses = int(self.redis.get(f"metrics:losses:{date}") or 0)
            
            win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0
            
            return {
                "date": date,
                "trades": trades,
                "pnl": round(pnl, 2),
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 2)
            }
        except Exception as e:
            print(f"[METRICS] Get daily metrics error: {e}")
            return {"date": date, "trades": 0, "pnl": 0, "wins": 0, "losses": 0, "win_rate": 0}
    
    def get_weekly_metrics(self) -> Dict[str, Any]:
        """Haftalık metrikleri getir"""
        total_trades = 0
        total_pnl = 0.0
        total_wins = 0
        total_losses = 0
        
        for i in range(7):
            date = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
            daily = self.get_daily_metrics(date)
            total_trades += daily["trades"]
            total_pnl += daily["pnl"]
            total_wins += daily["wins"]
            total_losses += daily["losses"]
        
        win_rate = (total_wins / (total_wins + total_losses) * 100) if (total_wins + total_losses) > 0 else 0.0
        
        return {
            "period": "7d",
            "trades": total_trades,
            "pnl": round(total_pnl, 2),
            "wins": total_wins,
            "losses": total_losses,
            "win_rate": round(win_rate, 2)
        }
    
    def calculate_sharpe_ratio(self, days: int = 30) -> float:
        """Sharpe ratio hesapla"""
        try:
            daily_returns = []
            
            for i in range(days):
                date = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
                pnl = float(self.redis.get(f"metrics:pnl:{date}") or 0)
                daily_returns.append(pnl)
            
            if not daily_returns or all(r == 0 for r in daily_returns):
                return 0.0
            
            import statistics
            mean_return = statistics.mean(daily_returns)
            std_return = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0
            
            if std_return == 0:
                return 0.0
            
            # Annualized Sharpe (252 trading days)
            sharpe = (mean_return / std_return) * (252 ** 0.5)
            return round(sharpe, 2)
        except Exception as e:
            print(f"[METRICS] Sharpe ratio error: {e}")
            return 0.0
    
    def calculate_max_drawdown(self, days: int = 30) -> float:
        """Maximum drawdown hesapla"""
        try:
            cumulative_pnl = 0.0
            peak = 0.0
            max_dd = 0.0
            
            for i in range(days - 1, -1, -1):  # Tersine, en eskiden yeniye
                date = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
                daily_pnl = float(self.redis.get(f"metrics:pnl:{date}") or 0)
                cumulative_pnl += daily_pnl
                
                if cumulative_pnl > peak:
                    peak = cumulative_pnl
                
                drawdown = peak - cumulative_pnl
                if drawdown > max_dd:
                    max_dd = drawdown
            
            return round(max_dd, 2)
        except Exception as e:
            print(f"[METRICS] Max drawdown error: {e}")
            return 0.0
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Kapsamlı performance özeti"""
        daily = self.get_daily_metrics()
        weekly = self.get_weekly_metrics()
        sharpe = self.calculate_sharpe_ratio(30)
        max_dd = self.calculate_max_drawdown(30)
        
        return {
            "daily": daily,
            "weekly": weekly,
            "sharpe_ratio_30d": sharpe,
            "max_drawdown_30d": max_dd,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def record_decision_accuracy(self, token_id: str, decision: str, actual_outcome: str) -> None:
        """AI decision accuracy tracking"""
        try:
            date_key = datetime.utcnow().strftime("%Y-%m-%d")
            
            # Total decisions
            self.redis.incr(f"metrics:decisions:{date_key}")
            
            # Correct decisions
            if decision == actual_outcome:
                self.redis.incr(f"metrics:decisions:correct:{date_key}")
            
            self.redis.expire(f"metrics:decisions:{date_key}", 86400 * 30)
            self.redis.expire(f"metrics:decisions:correct:{date_key}", 86400 * 30)
        except Exception as e:
            print(f"[METRICS] Decision accuracy error: {e}")
    
    def get_decision_accuracy(self, days: int = 7) -> float:
        """AI decision accuracy oranı"""
        try:
            total_decisions = 0
            correct_decisions = 0
            
            for i in range(days):
                date = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
                total_decisions += int(self.redis.get(f"metrics:decisions:{date}") or 0)
                correct_decisions += int(self.redis.get(f"metrics:decisions:correct:{date}") or 0)
            
            if total_decisions == 0:
                return 0.0
            
            return round((correct_decisions / total_decisions) * 100, 2)
        except Exception:
            return 0.0


# Global instance
_metrics_tracker = None

def get_metrics_tracker() -> MetricsTracker:
    """MetricsTracker singleton"""
    global _metrics_tracker
    if _metrics_tracker is None:
        _metrics_tracker = MetricsTracker()
    return _metrics_tracker
