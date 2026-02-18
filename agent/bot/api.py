# agent/bot/api.py
"""
FastAPI endpoints - Control API (revize edilmiş)
"""
import os
import time
import threading
from typing import Any, Dict
from fastapi import FastAPI
from pydantic import BaseModel

from .clob import build_clob_client
from .execution.paper_exec import place_order as paper_place_order
from .execution.paper_ledger import LEDGER, load_ledger_from_redis
from .risk.checks import clamp_order
from .state import STATE
from .snapshot import snapshot_scored_scan_topk_internal
from .agent_logic import agent_tick_internal, _ledger_snapshot
from .execution.live_ledger import LIVE_LEDGER
from .monitoring.dashboard import get_dashboard_data, format_dashboard_text
from .core.risk_engine import get_risk_engine
from .utils import patch_pyclob_hmac

# Backtest router
from .api.backtest_routes import router as backtest_router

app = FastAPI(title="Polymarket AI Agent - Full Stack")

# Backtest route'larını dahil et
app.include_router(backtest_router)

# Tick overlap guard
_TICK_LOCK = threading.Lock()
_LAST_TICK_TS: float = 0.0
_LAST_TICK_MS: float = 0.0


def _set_address_once() -> None:
    """CLOB client adresini state'e kaydet"""
    try:
        c = build_clob_client()
        addr = getattr(c, "address", None) or getattr(c, "wallet_address", None)
        if addr:
            STATE.address = addr
    except Exception:
        pass


def _refresh_state_from_env() -> None:
    """Environment'tan state'i yenile"""
    mode = (os.getenv("MODE") or os.getenv("EXEC_MODE") or os.getenv("BOT_MODE") or "paper").strip().lower()
    if mode not in ("paper", "live"):
        mode = "paper"
    trading_enabled = (os.getenv("TRADING_ENABLED") or "0").strip().lower() in ("1", "true", "yes", "y", "on")
    STATE.mode = mode
    STATE.trading_enabled = trading_enabled


@app.on_event("startup")
def _startup() -> None:
    """Startup tasks"""
    patch_pyclob_hmac()
    _refresh_state_from_env()
    _set_address_once()

    try:
        load_ledger_from_redis(LEDGER)
    except Exception:
        pass

    print("[API] Startup complete - Full stack AI trader ready")


class PaperOrderReq(BaseModel):
    token_id: str
    side: str
    price: float
    qty: float


@app.get("/health")
def health() -> Dict[str, Any]:
    """Health check endpoint"""
    _refresh_state_from_env()
    return {
        "ok": True,
        "state": {
            "trading_enabled": STATE.trading_enabled,
            "mode": STATE.mode,
            "address": STATE.address,
        },
        "tick": {
            "in_progress": _TICK_LOCK.locked(),
            "last_tick_ts": _LAST_TICK_TS,
            "last_tick_ms": _LAST_TICK_MS,
        }
    }


@app.get("/dashboard")
def dashboard() -> Dict[str, Any]:
    """Dashboard data"""
    return get_dashboard_data()


@app.get("/dashboard/text")
def dashboard_text() -> str:
    """Dashboard text format"""
    return format_dashboard_text()


@app.get("/risk/status")
def risk_status() -> Dict[str, Any]:
    """Risk status endpoint"""
    risk_engine = get_risk_engine()
    return risk_engine.get_risk_status()


@app.get("/clob/ping")
def clob_ping() -> Dict[str, Any]:
    """CLOB API ping"""
    try:
        c = build_clob_client()
        fn = getattr(c, "get_server_time", None) or getattr(c, "server_time", None)
        if callable(fn):
            st = fn()
            if isinstance(st, dict) and "server_time" in st:
                return {"ok": True, "server_time": st["server_time"]}
            return {"ok": True, "server_time": st}
        return {"ok": True, "server_time": int(time.time())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/markets/snapshot_scored")
def snapshot_scored() -> Dict[str, Any]:
    """Market snapshot - top opportunities"""
    budget = int(os.getenv("SNAPSHOT_TIME_BUDGET_S", "60"))
    topk = int(os.getenv("SNAP_TOPK", "4"))
    return snapshot_scored_scan_topk_internal(time_budget_s=budget, topk=topk)


@app.post("/paper/order")
def paper_order(req: PaperOrderReq) -> Dict[str, Any]:
    """Paper trading order"""
    side = (req.side or "").strip().lower()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy/sell"}

    qty = clamp_order(float(req.qty), float(req.price))
    if qty <= 0:
        return {"ok": False, "error": "qty_zero_after_clamp"}

    return paper_place_order(str(req.token_id), side, float(req.price), float(qty))


@app.get("/paper/positions")
def paper_positions() -> Dict[str, Any]:
    """Paper positions"""
    return _ledger_snapshot()


@app.get("/live/positions")
def live_positions() -> Dict[str, Any]:
    """Live positions"""
    try:
        if hasattr(LIVE_LEDGER, "load_from_redis"):
            LIVE_LEDGER.load_from_redis()
        return LIVE_LEDGER.snapshot()
    except Exception as e:
        return {"ok": False, "error": "live_ledger_snapshot_failed", "detail": repr(e)}


@app.post("/agent/tick")
def agent_tick() -> Dict[str, Any]:
    """
    Ana agent tick - overlap korumalı
    """
    global _LAST_TICK_TS, _LAST_TICK_MS
    _refresh_state_from_env()

    if not _TICK_LOCK.acquire(blocking=False):
        return {
            "ok": False,
            "error": "tick_in_progress",
            "detail": "previous tick still running",
            "last_tick": {"ts": _LAST_TICK_TS, "ms": _LAST_TICK_MS},
        }

    t0 = time.time()
    try:
        result = agent_tick_internal()
        return result
    finally:
        elapsed_ms = (time.time() - t0) * 1000
        _LAST_TICK_TS = time.time()
        _LAST_TICK_MS = elapsed_ms
        _TICK_LOCK.release()
