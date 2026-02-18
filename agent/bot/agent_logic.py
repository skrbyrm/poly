# agent/bot/agent_logic.py
"""
Ana agent logic — Market analizi, AI decision, execution.

Sprint 1 değişiklikleri:
  - Order tracker entegre edildi (GTC fill processing)
  - CLOB sync her N tick'te bir çalışıyor
  - Hata yönetimi güçlendirildi
  - current_prices tick'e taşındı (position check için)
"""
import time
from typing import Dict, Any, Optional

from .state import STATE
from .snapshot import snapshot_scored_scan_topk_internal
from .core.market_intelligence import get_market_intelligence
from .core.decision_engine import get_decision_engine
from .core.risk_engine import get_risk_engine
from .core.position_manager import get_position_manager
from .execution.paper_ledger import LEDGER
from .execution.paper_exec import place_order as paper_place_order, process_fills
from .execution.live_ledger import LIVE_LEDGER
from .execution.live_exec import place_order as live_place_order
from .execution.order_tracker import get_order_tracker
from .clob_read import get_orderbook
from .risk.checks import _get_best_bid_ask
from .config import TOPK, ORDER_USD, MANAGE_MAX_POS
from .monitoring.logger import get_logger

logger = get_logger("agent")

# CLOB sync her 10 tick'te bir (10 dakika) çalışır
_CLOB_SYNC_INTERVAL = 10
_tick_counter = 0


def agent_tick_internal() -> Dict[str, Any]:
    """
    Ana agent tick.

    Workflow:
      1. Paper fills / CLOB sync
      2. Pozisyon exit kontrolü (TP/SL/timeout)
      3. Max position limiti
      4. Market intelligence
      5. AI decision
      6. Risk kontrolü
      7. Order execution

    Returns:
        Tick sonucu
    """
    global _tick_counter
    _tick_counter += 1
    start_time = time.time()
    mode = STATE.mode

    try:
        ledger = LEDGER if mode == "paper" else LIVE_LEDGER

        # ── 1a. Paper: bekleyen GTC fill'leri işle ──
        fill_results = []
        if mode == "paper":
            current_prices = _fetch_current_prices(ledger.positions)
            fill_results = process_fills(current_prices)
            if fill_results:
                logger.info("Paper fills processed", count=len(fill_results))

        # ── 1b. Live: periyodik CLOB sync ──
        if mode == "live" and _tick_counter % _CLOB_SYNC_INTERVAL == 1:
            try:
                sync_result = LIVE_LEDGER.sync_with_clob()
                logger.info("CLOB sync", ok=sync_result.get("ok"), usdc=sync_result.get("usdc"))
            except Exception as e:
                logger.error("CLOB sync failed", error=str(e))

        # ── 2. Pozisyon exit kontrolü ──
        position_exits = _check_position_exits(ledger)

        # ── 3. Max pozisyon limiti ──
        current_positions = len(ledger.positions)
        if current_positions >= MANAGE_MAX_POS:
            return {
                "ok": True,
                "action": "hold",
                "reason": f"Max positions: {current_positions}/{MANAGE_MAX_POS}",
                "time_ms": _elapsed(start_time),
                "position_exits": position_exits,
                "fill_results": fill_results,
            }

        # ── 4. Market intelligence ──
        snapshot = snapshot_scored_scan_topk_internal(topk=TOPK)

        if not snapshot.get("ok") or not snapshot.get("topk"):
            return {
                "ok": False,
                "error": "No market opportunities found",
                "time_ms": _elapsed(start_time),
                "position_exits": position_exits,
            }

        # ── 5. AI decision ──
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
                "time_ms": _elapsed(start_time),
                "position_exits": position_exits,
                "fill_results": fill_results,
            }

        # ── 6. Risk kontrolü ──
        token_id = decision.get("token_id")
        orderbook = get_orderbook(token_id) if token_id else None

        risk_engine = get_risk_engine()
        allowed, reason, adjusted_decision = risk_engine.pre_trade_checks(
            decision, ledger_snapshot, orderbook
        )

        if not allowed:
            return {
                "ok": True,
                "action": "hold",
                "reason": f"Risk check failed: {reason}",
                "time_ms": _elapsed(start_time),
                "position_exits": position_exits,
                "fill_results": fill_results,
            }

        # ── 7. Order execution ──
        trade_result = _execute_trade(adjusted_decision, mode, ledger)

        if trade_result.get("ok"):
            portfolio_value = ledger.get_portfolio_value()
            risk_engine.post_trade_update(trade_result, portfolio_value)

        return {
            "ok": True,
            "action": action,
            "trade_result": trade_result,
            "decision": adjusted_decision,
            "time_ms": _elapsed(start_time),
            "position_exits": position_exits,
            "fill_results": fill_results,
        }

    except Exception as e:
        logger.error("Agent tick failed", error=str(e))
        return {
            "ok": False,
            "error": f"Agent tick error: {e}",
            "time_ms": _elapsed(start_time),
        }


# ─────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────

def _fetch_current_prices(positions: Dict[str, Any]) -> Dict[str, float]:
    """
    Açık pozisyonlar için güncel mid price'ları toplu çek.
    """
    prices: Dict[str, float] = {}
    for token_id in positions:
        try:
            ob = get_orderbook(token_id, timeout_s=2)
            if ob.get("ok"):
                best_bid, best_ask = _get_best_bid_ask(ob)
                if best_bid and best_ask:
                    prices[token_id] = round((best_bid + best_ask) / 2, 6)
        except Exception:
            pass
    return prices


def _check_position_exits(ledger) -> list:
    """Pozisyon exit sinyalleri üret ve execute et."""
    position_manager = get_position_manager()
    mode = STATE.mode

    # Güncel fiyatları çek
    current_prices = _fetch_current_prices(ledger.positions)

    exit_signals = position_manager.check_exit_conditions(
        ledger.positions, current_prices
    )

    results = []
    for signal in exit_signals:
        token_id = signal["token_id"]
        qty = signal["qty"]
        current_price = signal.get("current_price")
        reason = signal.get("reason")

        if mode == "paper":
            result = paper_place_order(token_id, "sell", current_price, qty, immediate=True)
        else:
            result = live_place_order(token_id, "sell", current_price, qty)

        results.append({
            "token_id": token_id,
            "reason": reason,
            "pnl_pct": signal.get("pnl_pct"),
            "result": result,
        })

        logger.info(
            "Position exit",
            token_id=token_id,
            reason=reason,
            pnl_pct=signal.get("pnl_pct"),
        )

    return results


def _execute_trade(
    decision: Dict[str, Any],
    mode: str,
    ledger,
) -> Dict[str, Any]:
    """Trade execution."""
    action = decision.get("decision")
    token_id = decision.get("token_id")
    limit_price = float(decision.get("limit_price", 0))

    if not token_id or limit_price <= 0:
        return {"ok": False, "error": "Invalid decision parameters"}

    if action == "buy":
        suggested_qty = decision.get("suggested_qty")
        qty = suggested_qty if suggested_qty else ORDER_USD / limit_price
    else:
        pos = ledger.get_position(token_id)
        if not pos:
            return {"ok": False, "error": "No position to sell"}
        qty = float(pos.get("qty", 0))

    if mode == "paper":
        return paper_place_order(token_id, action, limit_price, qty)
    else:
        return live_place_order(token_id, action, limit_price, qty)


def _ledger_snapshot() -> Dict[str, Any]:
    if STATE.mode == "paper":
        return LEDGER.snapshot()
    return LIVE_LEDGER.snapshot()


def _elapsed(start_time: float) -> int:
    return int((time.time() - start_time) * 1000)
