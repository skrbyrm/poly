# agent/bot/core/risk_engine.py
"""
Risk engine - Tüm risk kontrollerini koordine eden merkezi motor
"""
from typing import Dict, Any, Optional, Tuple
from ..risk.limits import get_risk_limits
from ..risk.circuit_breaker import get_circuit_breaker
from ..risk.drawdown_monitor import get_drawdown_monitor
from ..risk.kelly_criterion import calculate_optimal_size
from ..risk.checks import (
    validate_order_price,
    check_spread_quality,
    check_depth_quality,
    validate_trade_timing
)
from ..monitoring.metrics import get_metrics_tracker
from ..state import STATE

class RiskEngine:
    """Merkezi risk yönetimi motoru"""
    
    def __init__(self):
        self.risk_limits = get_risk_limits()
        self.circuit_breaker = get_circuit_breaker()
        self.drawdown_monitor = get_drawdown_monitor()
        self.metrics = get_metrics_tracker()
    
    def pre_trade_checks(
        self,
        decision: Dict[str, Any],
        ledger: Dict[str, Any],
        orderbook: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Trade öncesi tüm risk kontrollerini yap
        
        Args:
            decision: AI decision
            ledger: Mevcut pozisyonlar
            orderbook: Orderbook data
        
        Returns:
            (allowed, reason, adjusted_decision)
        """
        action = decision.get("decision", "hold")
        
        # 1. Hold ise kontrol gereksiz
        if action == "hold":
            return True, "OK", decision
        
        # 2. Circuit breaker kontrolü
        if self.circuit_breaker.is_open():
            return False, "Circuit breaker is open - trading suspended", None
        
        # Auto-reset kontrolü
        self.circuit_breaker.auto_reset_check()
        
        # 3. Consecutive losses kontrolü
        self.circuit_breaker.check_consecutive_losses(STATE.consecutive_losses)
        
        if self.circuit_breaker.is_open():
            return False, "Circuit breaker triggered during checks", None
        
        # 4. Daily/Weekly PnL kontrolü
        daily_metrics = self.metrics.get_daily_metrics()
        daily_pnl = daily_metrics.get("pnl", 0)
        
        weekly_metrics = self.metrics.get_weekly_metrics()
        weekly_pnl = weekly_metrics.get("pnl", 0)
        
        # Drawdown kontrolü
        current_drawdown_pct = self.drawdown_monitor.get_current_drawdown_pct()
        
        # 5. Position limits kontrolü (sadece buy için)
        if action == "buy":
            positions = ledger.get("positions", {})
            current_positions = len(positions)
            
            # Portfolio value hesapla
            cash = ledger.get("cash", 0)
            portfolio_value = cash
            
            for pos in positions.values():
                portfolio_value += float(pos.get("qty", 0)) * float(pos.get("avg_price", 0))
            
            # Order size hesapla
            order_size_usd = self._calculate_order_size(decision, ledger)
            
            # Tüm limitleri kontrol et
            allowed, reason = self.risk_limits.can_open_position(
                order_size_usd=order_size_usd,
                portfolio_value=portfolio_value,
                current_positions=current_positions,
                daily_pnl=daily_pnl,
                weekly_pnl=weekly_pnl,
                current_drawdown_pct=current_drawdown_pct
            )
            
            if not allowed:
                return False, reason, None
        
        # 6. Orderbook quality checks
        if orderbook:
            # Spread check
            spread_ok, spread_val = check_spread_quality(orderbook)
            if not spread_ok:
                return False, f"Spread too wide: {spread_val:.4f}", None
            
            # Depth check
            depth_ok, depth_reason = check_depth_quality(orderbook)
            if not depth_ok:
                return False, depth_reason, None
            
            # Price validation
            token_id = decision.get("token_id")
            limit_price = decision.get("limit_price")
            
            if token_id and limit_price:
                price_ok, price_reason = validate_order_price(
                    limit_price, orderbook, action
                )
                if not price_ok:
                    return False, price_reason, None
        
        # 7. Trade timing check
        timing_ok, timing_reason = validate_trade_timing(
            STATE.last_trade_timestamp
        )
        if not timing_ok:
            return False, timing_reason, None
        
        # 8. Position sizing adjustment (Kelly Criterion)
        adjusted_decision = self._adjust_position_size(decision, ledger)
        
        return True, "All risk checks passed", adjusted_decision
    
    def _calculate_order_size(
        self,
        decision: Dict[str, Any],
        ledger: Dict[str, Any]
    ) -> float:
        """Order size'ı hesapla (USD)"""
        from ..config import ORDER_USD
        
        # Basit implementation - ORDER_USD kullan
        # Future: Kelly Criterion ile dinamik sizing
        return float(ORDER_USD)
    
    def _adjust_position_size(
        self,
        decision: Dict[str, Any],
        ledger: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Position size'ı Kelly Criterion ile ayarla
        
        Returns:
            Adjusted decision
        """
        action = decision.get("decision", "hold")
        
        if action != "buy":
            return decision
        
        # Portfolio value hesapla
        cash = ledger.get("cash", 0)
        positions = ledger.get("positions", {})
        portfolio_value = cash
        
        for pos in positions.values():
            portfolio_value += float(pos.get("qty", 0)) * float(pos.get("avg_price", 0))
        
        # Historical metrics
        weekly = self.metrics.get_weekly_metrics()
        wins = weekly.get("wins", 0)
        losses = weekly.get("losses", 0)
        total_trades = wins + losses
        
        if total_trades >= 10:
            # Yeterli data var - Kelly kullan
            win_rate = wins / total_trades
            # TODO: avg_win, avg_loss hesapla (şimdilik basit method)
            confidence = float(decision.get("confidence", 0.7))
            optimal_size = calculate_optimal_size(
                portfolio_value=portfolio_value,
                confidence=confidence
            )
        else:
            # Yeterli data yok - conservative sizing
            from ..config import ORDER_USD
            optimal_size = float(ORDER_USD)
        
        # Decision'a qty ekle
        limit_price = float(decision.get("limit_price", 0.5))
        if limit_price > 0:
            optimal_qty = optimal_size / limit_price
            decision["suggested_qty"] = round(optimal_qty, 2)
            decision["suggested_size_usd"] = round(optimal_size, 2)
        
        return decision
    
    def post_trade_update(
        self,
        trade_result: Dict[str, Any],
        current_portfolio_value: float
    ) -> None:
        """
        Trade sonrası güncelleme
        
        Args:
            trade_result: Trade sonucu
            current_portfolio_value: Güncel portföy değeri
        """
        # Drawdown güncelle
        self.drawdown_monitor.update_equity(current_portfolio_value)
        
        # PnL tracking
        pnl = trade_result.get("pnl")
        if pnl is not None:
            STATE.record_trade_result(pnl)
            
            # Daily loss check
            daily_metrics = self.metrics.get_daily_metrics()
            daily_pnl = daily_metrics.get("pnl", 0)
            
            self.circuit_breaker.check_daily_loss(
                daily_pnl,
                self.risk_limits.max_daily_loss
            )
            
            # Drawdown check
            current_dd_pct = self.drawdown_monitor.get_current_drawdown_pct()
            self.circuit_breaker.check_drawdown(
                current_dd_pct,
                self.risk_limits.max_drawdown_pct
            )
        
        # Update last trade timestamp
        import time
        STATE.last_trade_timestamp = time.time()
    
    def get_risk_status(self) -> Dict[str, Any]:
        """Mevcut risk durumunu getir"""
        daily = self.metrics.get_daily_metrics()
        weekly = self.metrics.get_weekly_metrics()
        dd_status = self.drawdown_monitor.get_drawdown_status()
        cb_status = self.circuit_breaker.get_status()
        limits = self.risk_limits.get_current_limits_status()
        
        return {
            "circuit_breaker": cb_status,
            "drawdown": dd_status,
            "limits": limits,
            "daily_metrics": daily,
            "weekly_metrics": weekly,
            "consecutive_losses": STATE.consecutive_losses,
            "consecutive_wins": STATE.consecutive_wins
        }


# Global instance
_risk_engine = None

def get_risk_engine() -> RiskEngine:
    """RiskEngine singleton"""
    global _risk_engine
    if _risk_engine is None:
        _risk_engine = RiskEngine()
    return _risk_engine
