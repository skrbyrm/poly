# agent/bot/api/backtest_routes.py
"""
Backtest API Routes

POST /backtest/run        — Backtest başlat
GET  /backtest/latest     — Son backtest raporu
POST /backtest/optimize   — Grid search ile parametre optimizasyonu
GET  /backtest/db/runs    — DB'deki tüm run özetleri
"""
import asyncio
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..backtest.replay_engine import BacktestConfig, ReplayEngine
from ..backtest.analytics import (
    generate_report,
    breakdown_by_category,
    breakdown_by_exit_reason,
    equity_curve,
    save_result_to_db,
    grid_search,
    _get_database_url,
)
from ..monitoring.logger import get_logger

logger = get_logger("api.backtest")
router = APIRouter(prefix="/backtest", tags=["backtest"])

# Son backtest sonucu (in-memory cache)
_last_result = None


# ─────────────────────────────────────────────
# Request modelleri
# ─────────────────────────────────────────────

class BacktestRequest(BaseModel):
    days_back:       int   = Field(default=14,  ge=1,  le=90)
    max_markets:     int   = Field(default=30,  ge=1,  le=200)
    initial_cash:    float = Field(default=100.0)
    order_usd:       float = Field(default=5.0,  ge=0.5)
    take_profit_pct: float = Field(default=0.03, ge=0.005)
    stop_loss_pct:   float = Field(default=0.02, ge=0.005)
    max_hold_steps:  int   = Field(default=12,   ge=1)
    min_imbalance:   float = Field(default=0.30, ge=0.0, le=1.0)
    categories:      List[str] = Field(default_factory=lambda: ["all"])
    save_to_db:      bool = Field(default=True)
    run_name:        str  = Field(default="")


class OptimizeRequest(BaseModel):
    days_back:   int = Field(default=14, ge=1, le=30)
    max_markets: int = Field(default=20, ge=1, le=100)


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.post("/run")
async def run_backtest(req: BacktestRequest):
    """
    Backtest çalıştır ve sonuçları döndür.
    Uyarı: max_markets büyükse birkaç dakika sürebilir.
    """
    global _last_result

    config = BacktestConfig(
        initial_cash=req.initial_cash,
        order_usd=req.order_usd,
        take_profit_pct=req.take_profit_pct,
        stop_loss_pct=req.stop_loss_pct,
        max_hold_steps=req.max_hold_steps,
        min_imbalance=req.min_imbalance,
        categories=req.categories,
    )

    try:
        engine = ReplayEngine(config)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: engine.run(
                days_back=req.days_back,
                max_markets=req.max_markets,
            )
        )

        _last_result = result

        db_saved = False
        if req.save_to_db:
            db_saved = save_result_to_db(
                result,
                run_name=req.run_name or f"api_{req.days_back}d"
            )

        return {
            "ok":              True,
            "markets_tested":  result.markets_tested,
            "total_trades":    result.total_trades,
            "win_rate":        result.win_rate,
            "total_pnl":       result.total_pnl,
            "sharpe_ratio":    result.sharpe_ratio,
            "max_drawdown":    result.max_drawdown,
            "avg_hold_hours":  result.avg_hold_hours,
            "db_saved":        db_saved,
            "by_category":     breakdown_by_category(result),
            "by_exit_reason":  breakdown_by_exit_reason(result),
            "equity_curve":    equity_curve(result)[-20:],
        }

    except Exception as e:
        logger.error("Backtest run failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/latest")
async def get_latest_report():
    """Son backtest'in text raporunu döndür."""
    if _last_result is None:
        raise HTTPException(
            status_code=404,
            detail="No backtest run yet. Call POST /backtest/run first."
        )

    report_text = generate_report(_last_result)
    return {
        "ok":     True,
        "report": report_text,
        "summary": {
            "trades":    _last_result.total_trades,
            "win_rate":  _last_result.win_rate,
            "total_pnl": _last_result.total_pnl,
            "sharpe":    _last_result.sharpe_ratio,
        },
    }


@router.post("/optimize")
async def optimize_parameters(req: OptimizeRequest):
    """
    Grid search ile TP/SL/imbalance optimizasyonu.
    27 kombinasyon × max_markets market.
    Küçük değerlerle başla: days_back=7, max_markets=10
    """
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, lambda: grid_search(
                days_back=req.days_back,
                max_markets=req.max_markets,
            )
        )

        top5 = results[:5]

        return {
            "ok":                  True,
            "best":                top5[0] if top5 else None,
            "top_5":               top5,
            "total_combinations":  len(results),
            "recommendation":      _make_recommendation(top5[0]) if top5 else "No results",
        }

    except Exception as e:
        logger.error("Optimize failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/db/runs")
async def list_db_runs(limit: int = 20):
    """
    PostgreSQL'deki backtest run özetlerini listele.
    """
    db_url = _get_database_url()
    if not db_url:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(db_url)
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("""
            SELECT id, run_name, run_at, markets, total_trades,
                   win_rate, total_pnl, sharpe, max_drawdown, avg_hold_h
            FROM backtest_runs
            ORDER BY run_at DESC
            LIMIT %s
        """, (limit,))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        return {
            "ok":   True,
            "runs": [dict(r) for r in rows],
            "count": len(rows),
        }

    except psycopg2.errors.UndefinedTable:
        return {"ok": True, "runs": [], "count": 0, "note": "No backtest runs yet"}
    except Exception as e:
        logger.error("DB list runs failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# Yardımcı
# ─────────────────────────────────────────────

def _make_recommendation(best: dict) -> str:
    if not best:
        return "Insufficient data"

    return (
        f"Set TAKE_PROFIT_PCT={best['take_profit']:.2f}, "
        f"STOP_LOSS_PCT={best['stop_loss']:.2f}, "
        f"MIN_IMBALANCE={best['min_imbalance']:.2f} "
        f"→ Sharpe={best['sharpe']:.2f}, WinRate={best['win_rate']:.1f}%, "
        f"PnL=${best['total_pnl']:+.4f}"
    )
