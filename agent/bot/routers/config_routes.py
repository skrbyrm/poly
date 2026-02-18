# agent/bot/routers/config_routes.py
"""
Config API Routes — Sprint 4 Block C

GET  /config/current              → Mevcut parametreler
POST /config/update               → Parametreleri güncelle
POST /config/reset                → Env değerlerine döndür
POST /config/apply-backtest       → En iyi backtest'i otomatik uygula
GET  /config/backtest-suggestion  → Öneri göster (uygulamadan)
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.config_manager import get_config_manager
from ..monitoring.logger import get_logger

logger = get_logger("api.config")
router = APIRouter(prefix="/config", tags=["config"])


# ─────────────────────────────────────────────
# Request modelleri
# ─────────────────────────────────────────────

class UpdateRequest(BaseModel):
    params: Dict[str, Any]
    reason: Optional[str] = None    # neyin değiştirildiğine dair not


class ResetRequest(BaseModel):
    params: Optional[List[str]] = None   # None = hepsini sıfırla


class ApplyBacktestRequest(BaseModel):
    take_profit:   Optional[float] = None
    stop_loss:     Optional[float] = None
    min_imbalance: Optional[float] = None
    sharpe:        Optional[float] = None
    win_rate:      Optional[float] = None


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.get("/current")
def get_current_config() -> Dict[str, Any]:
    """
    Mevcut tüm runtime parametrelerini döndür.

    Her parametre için: değer, kaynak (runtime vs env), min/max, açıklama.
    """
    mgr = get_config_manager()
    return {
        "ok": True,
        "config": mgr.get_all(),
        "info": "source='runtime' → değiştirilmiş, source='env_or_default' → orijinal",
    }


@router.post("/update")
def update_config(req: UpdateRequest) -> Dict[str, Any]:
    """
    Bir veya birden fazla parametreyi runtime'da güncelle.

    Örnek body:
    {
      "params": {
        "take_profit_pct": 0.04,
        "stop_loss_pct": 0.025,
        "min_confidence": 0.60
      },
      "reason": "Backtest sonuçlarına göre ayar"
    }

    Değişiklikler Redis'e kaydedilir — restart'a dayanıklıdır.
    """
    if not req.params:
        raise HTTPException(status_code=422, detail="params cannot be empty")

    mgr = get_config_manager()
    ok, result = mgr.update(req.params)

    if req.reason:
        logger.info("Config update with reason", reason=req.reason, params=list(req.params.keys()))

    return {
        "ok": True,
        "applied": result["applied"],
        "rejected": result["rejected"],
        "all_applied": ok,
        "reason": req.reason,
    }


@router.post("/reset")
def reset_config(req: ResetRequest) -> Dict[str, Any]:
    """
    Parametreleri env değerlerine döndür.

    Body boş bırakılırsa TÜMÜ sıfırlanır.
    Belirli parametre listesi de verilebilir:
    {"params": ["take_profit_pct", "stop_loss_pct"]}
    """
    mgr = get_config_manager()
    result = mgr.reset(req.params)
    return {"ok": True, **result}


@router.get("/backtest-suggestion")
def get_backtest_suggestion() -> Dict[str, Any]:
    """
    PostgreSQL'deki en iyi backtest sonucuna göre öneri göster.
    Parametreleri değiştirmez — sadece ne uygulanacağını gösterir.
    """
    mgr = get_config_manager()
    best = mgr._load_best_from_db()

    if not best:
        return {
            "ok": False,
            "message": "No backtest data in DB. Run POST /backtest/run first.",
        }

    current = {
        "take_profit_pct": mgr.get("take_profit_pct"),
        "stop_loss_pct":   mgr.get("stop_loss_pct"),
        "min_imbalance":   mgr.get("min_imbalance"),
    }

    suggested = {
        "take_profit_pct": best.get("take_profit"),
        "stop_loss_pct":   best.get("stop_loss"),
        "min_imbalance":   best.get("min_imbalance"),
    }

    # Değişecek parametreleri belirt
    diff = {
        k: {"current": current.get(k), "suggested": v}
        for k, v in suggested.items()
        if v is not None and v != current.get(k)
    }

    return {
        "ok":          True,
        "current":     current,
        "suggested":   suggested,
        "diff":        diff,
        "backtest_stats": {
            "sharpe":   best.get("sharpe"),
            "win_rate": best.get("win_rate"),
        },
        "apply_cmd": "POST /config/apply-backtest  (body boş bırakılabilir)",
    }


@router.post("/apply-backtest")
def apply_backtest_config(req: Optional[ApplyBacktestRequest] = None) -> Dict[str, Any]:
    """
    En iyi backtest parametrelerini otomatik uygula.

    Body boş bırakılırsa PostgreSQL'den en yüksek Sharpe'lı sonuç alınır.
    Manuel override da yapılabilir:
    {
      "take_profit": 0.04,
      "stop_loss": 0.025,
      "min_imbalance": 0.30,
      "sharpe": 1.5,
      "win_rate": 58.3
    }
    """
    mgr = get_config_manager()

    top_result = None
    if req:
        top_result = {
            "take_profit":   req.take_profit,
            "stop_loss":     req.stop_loss,
            "min_imbalance": req.min_imbalance,
            "sharpe":        req.sharpe,
            "win_rate":      req.win_rate,
        }
        # Hepsi None ise DB'den al
        if all(v is None for v in top_result.values()):
            top_result = None

    result = mgr.apply_best_backtest(top_result)

    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))

    return result
