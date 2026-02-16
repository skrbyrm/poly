# agent/bot/agent_logic.py
"""
Ana agent logic - Market analizi, AI decision, execution
"""
import time
from typing import Dict, Any
from .state import STATE
from .snapshot import snapshot_scored_scan_topk_internal
from .core.market_intelligence import get_market_intelligence
from .core.decision_engine import get_decision_engine
from .core.risk_engine import get_risk_engine
from .core.position_manager import get_position_manager
from .execution.paper_ledger import LEDGER
from .execution.paper_exec import place_order as paper_place_order
from .execution.live_ledger import LIVE_LEDGER
from .execution.live_exec import place_order as live_place_order
from .clob_read import get_orderbook
from .config import TOPK, ORDER_USD, MANAGE_MAX_POS
from .monitoring.logger import get_logger

logger = get_logger("agent")

def agent_tick_internal() -> Dict[str, Any]:
    """
    Ana agent tick - her çalıştırmada bir kez
    
    Workflow:
    1. Market intelligence - top opportunities bul
    2. Mevcut pozisyonları kontrol et (TP/SL/timeout)
    3. AI decision al
    4. Risk kontrolü
    5. Execute trade
    
    Returns:
        Tick result
    """
    start_time = time.time()
    
    try:
        # Mode kontrolü
        mode = STATE.mode
        ledger = LEDGER if mode == "paper" else LIVE_LEDGER
        
        # 1. Position management - exit kontrolü
        position_exits = _check_position_exits(ledger)
        
        # 2. Max positions kontrolü
        current_positions = len(ledger.positions)
        if current_positions >= MANAGE_MAX_POS:
            return {
                "ok": True,
                "action": "hold",
                "reason": f"Max positions reached: {current_positions}/{MANAGE_MAX_POS}",
                "time_ms": int((time.time() - start_time) * 1000),
                "position_exits": position_exits
            }
        
        # 3. Market intelligence - opportunities bul
        snapshot = snapshot_scored_scan_topk_internal(topk=TOPK)
        
        if not snapshot.get("ok") or not snapshot.get("topk"):
            return {
                "ok": False,
                "error": "No market opportunities found",
                "time_ms": int((time.time() - start_time) * 1000)
            }
        
        # 4. AI decision al
        decision_engine = get_decision_engine()
        ledger_snapshot = _ledger_snapshot()
        
        decision = decision_engine.make_decision(snapshot, ledger_snapshot)
        
        action = decision.get("decision", "hold")
        
        if action == "hold":
            return {
                "ok": True,
                "action": "hold",
                "reason": decision.get("reasoning", "No action"),
                "confidence": decision.get("confidence", 0.5),
                "time_ms": int((time.time() - start_time) * 1000),
                "position_exits": position_exits
            }
        
        # 5. Orderbook getir (validation için)
        token_id = decision.get("token_id")
        orderbook = get_orderbook(token_id) if token_id else None
        
        # 6. Risk kontrolü
        risk_engine = get_risk_engine()
        allowed, reason, adjusted_decision = risk_engine.pre_trade_checks(
            decision, ledger_snapshot, orderbook
        )
        
        if not allowed:
            return {
                "ok": True,
                "action": "hold",
                "reason": f"Risk check failed: {reason}",
                "time_ms": int((time.time() - start_time) * 1000)
            }
        
        # 7. Execute trade
        trade_result = _execute_trade(adjusted_decision, mode, ledger)
        
        # 8. Post-trade update
        if trade_result.get("ok"):
            portfolio_value = ledger.get_portfolio_value()
            risk_engine.post_trade_update(trade_result, portfolio_value)
        
        return {
            "ok": True,
            "action": action,
            "trade_result": trade_result,
            "decision": adjusted_decision,
            "time_ms": int((time.time() - start_time) * 1000),
            "position_exits": position_exits
        }
        
    except Exception as e:
        logger.error(f"Agent tick error: {e}", error=str(e))
        return {
            "ok": False,
            "error": f"Agent tick error: {e}",
            "time_ms": int((time.time() - start_time) * 1000)
        }


def _check_position_exits(ledger) -> list:
    """Pozisyon exit kontrolü ve execution"""
    position_manager = get_position_manager()
    
    # Exit sinyalleri bul
    exit_signals = position_manager.check_exit_conditions(ledger.positions)
    
    results = []
    
    for signal in exit_signals:
        token_id = signal["token_id"]
        qty = signal["qty"]
        current_price = signal.get("current_price")
        reason = signal.get("reason")
        
        # Sell order
        mode = STATE.mode
        
        if mode == "paper":
            result = paper_place_order(token_id, "sell", current_price, qty)
        else:
            result = live_place_order(token_id, "sell", current_price, qty)
        
        results.append({
            "token_id": token_id,
            "reason": reason,
            "result": result
        })
        
        logger.info(f"Position exit: {token_id} - {reason}", 
                   token_id=token_id, reason=reason, pnl_pct=signal.get("pnl_pct"))
    
    return results


def _execute_trade(decision: Dict[str, Any], mode: str, ledger) -> Dict[str, Any]:
    """Trade execution"""
    action = decision.get("decision")
    token_id = decision.get("token_id")
    limit_price = float(decision.get("limit_price", 0))
    
    if not token_id or limit_price <= 0:
        return {"ok": False, "error": "Invalid decision parameters"}
    
    # Quantity hesapla
    if action == "buy":
        # Suggested qty kullan (Kelly'den geliyorsa)
        suggested_qty = decision.get("suggested_qty")
        
        if suggested_qty:
            qty = suggested_qty
        else:
            # Fallback: ORDER_USD / price
            qty = ORDER_USD / limit_price
    else:  # sell
        # Mevcut pozisyonun tamamını sat
        pos = ledger.get_position(token_id)
        if not pos:
            return {"ok": False, "error": "No position to sell"}
        
        qty = float(pos.get("qty", 0))
    
    # Execute
    if mode == "paper":
        result = paper_place_order(token_id, action, limit_price, qty)
    else:
        result = live_place_order(token_id, action, limit_price, qty)
    
    return result


def _ledger_snapshot() -> Dict[str, Any]:
    """Ledger snapshot getir (mode'a göre)"""
    if STATE.mode == "paper":
        return LEDGER.snapshot()
    else:
        return LIVE_LEDGER.snapshot()
