# agent/bot/api.py
"""
FastAPI endpoints — Control API.

Sprint 4 değişiklikleri:
  - /health  → tick error count, seconds_since_last_success, is_healthy flag
  - Config router eklendi (GET/POST /config/*)
  - agent_tick_internal hataları STATE'e kaydediliyor
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

# Routers
from .routers.backtest_routes import router as backtest_router
from .routers.config_routes   import router as config_router

app = FastAPI(title="Polymarket AI Agent — Full Stack")

app.include_router(backtest_router)
app.include_router(config_router)

# Tick overlap guard
_TICK_LOCK    = threading.Lock()
_LAST_TICK_TS: float = 0.0
_LAST_TICK_MS: float = 0.0


def _set_address_once() -> None:
    try:
        c    = build_clob_client()
        addr = getattr(c, "address", None) or getattr(c, "wallet_address", None)
        if addr:
            STATE.address = addr
    except Exception:
        pass


def _refresh_state_from_env() -> None:
    mode = (os.getenv("MODE") or os.getenv("EXEC_MODE") or "paper").strip().lower()
    if mode not in ("paper", "live"):
        mode = "paper"
    trading_enabled = (os.getenv("TRADING_ENABLED") or "0").strip().lower() in ("1", "true", "yes", "y", "on")
    STATE.mode            = mode
    STATE.trading_enabled = trading_enabled


@app.on_event("startup")
def _startup() -> None:
    patch_pyclob_hmac()
    _refresh_state_from_env()
    _set_address_once()
    try:
        load_ledger_from_redis(LEDGER)
    except Exception:
        pass
    print("[API] Startup complete — Polymarket AI Trader v4 ready")


class PaperOrderReq(BaseModel):
    token_id: str
    side: str
    price: float
    qty: float


# ─────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────

@app.get("/health")
def health() -> Dict[str, Any]:
    """
    Enhanced health check (Sprint 4).

    Dönen alanlar:
      ok                         → bool
      state                      → mode, trading_enabled, address
      tick.in_progress           → şu an tick çalışıyor mu
      tick.last_tick_ts          → son tick başlangıcı (unix)
      tick.last_tick_ms          → son tick süresi (ms)
      tick.consecutive_errors    → art arda başarısız tick sayısı
      tick.total_errors          → toplam hata
      tick.seconds_since_success → son başarılı tick'ten bu yana geçen süre
      tick.is_healthy            → consecutive_errors < 5
    """
    _refresh_state_from_env()

    sss = STATE.seconds_since_last_success
    return {
        "ok": True,
        "state": {
            "trading_enabled": STATE.trading_enabled,
            "mode":            STATE.mode,
            "address":         STATE.address,
        },
        "tick": {
            "in_progress":           _TICK_LOCK.locked(),
            "last_tick_ts":          _LAST_TICK_TS,
            "last_tick_ms":          _LAST_TICK_MS,
            "consecutive_errors":    STATE.tick_error_count,
            "total_errors":          STATE.tick_total_errors,
            "total_ticks":           STATE.tick_count,
            "last_error":            STATE.last_error,
            "last_error_ts":         STATE.last_error_ts or None,
            "seconds_since_success": round(sss, 1) if sss is not None else None,
            "is_healthy":            STATE.is_healthy,
        },
    }


# ─────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────

@app.get("/dashboard")
def dashboard() -> Dict[str, Any]:
    return get_dashboard_data()


@app.get("/dashboard/text")
def dashboard_text() -> str:
    return format_dashboard_text()


# ─────────────────────────────────────────────
# Risk
# ─────────────────────────────────────────────

@app.get("/risk/status")
def risk_status() -> Dict[str, Any]:
    return get_risk_engine().get_risk_status()


# ─────────────────────────────────────────────
# CLOB
# ─────────────────────────────────────────────

@app.get("/clob/ping")
def clob_ping() -> Dict[str, Any]:
    try:
        c  = build_clob_client()
        fn = getattr(c, "get_server_time", None) or getattr(c, "server_time", None)
        if callable(fn):
            st = fn()
            if isinstance(st, dict) and "server_time" in st:
                return {"ok": True, "server_time": st["server_time"]}
            return {"ok": True, "server_time": st}
        return {"ok": True, "server_time": int(time.time())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────
# Market snapshot
# ─────────────────────────────────────────────

@app.get("/markets/snapshot_scored")
def snapshot_scored() -> Dict[str, Any]:
    budget = int(os.getenv("SNAPSHOT_TIME_BUDGET_S", "60"))
    topk   = int(os.getenv("SNAP_TOPK", "4"))
    return snapshot_scored_scan_topk_internal(time_budget_s=budget, topk=topk)


# ─────────────────────────────────────────────
# Paper trading
# ─────────────────────────────────────────────

@app.post("/paper/order")
def paper_order(req: PaperOrderReq) -> Dict[str, Any]:
    side = (req.side or "").strip().lower()
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy/sell"}

    qty = clamp_order(float(req.qty), float(req.price))
    if qty <= 0:
        return {"ok": False, "error": "qty_zero_after_clamp"}

    return paper_place_order(str(req.token_id), side, float(req.price), float(qty))


@app.get("/paper/positions")
def paper_positions() -> Dict[str, Any]:
    return _ledger_snapshot()


# ─────────────────────────────────────────────
# Live trading
# ─────────────────────────────────────────────

@app.get("/live/positions")
def live_positions() -> Dict[str, Any]:
    try:
        if hasattr(LIVE_LEDGER, "load_from_redis"):
            LIVE_LEDGER.load_from_redis()
        return LIVE_LEDGER.snapshot()
    except Exception as e:
        return {"ok": False, "error": repr(e)}


# ─────────────────────────────────────────────
# Agent tick — overlap korumalı
# ─────────────────────────────────────────────

@app.post("/agent/tick")
def agent_tick() -> Dict[str, Any]:
    """
    Ana agent tick.

    Sprint 4: başarı/hata STATE'e kaydedilir → /health'te görünür.
    """
    global _LAST_TICK_TS, _LAST_TICK_MS
    _refresh_state_from_env()

    if not _TICK_LOCK.acquire(blocking=False):
        return {
            "ok":    False,
            "error": "tick_in_progress",
            "detail": "previous tick still running",
            "last_tick": {"ts": _LAST_TICK_TS, "ms": _LAST_TICK_MS},
        }

    t0 = time.time()
    try:
        result = agent_tick_internal()

        if result.get("ok"):
            STATE.record_tick_success()
        else:
            STATE.record_tick_error(result.get("error", "unknown"))

        return result

    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        STATE.record_tick_error(err)
        return {"ok": False, "error": err}

    finally:
        elapsed_ms    = (time.time() - t0) * 1000
        _LAST_TICK_TS = time.time()
        _LAST_TICK_MS = elapsed_ms
        _TICK_LOCK.release()
