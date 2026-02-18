# agent/bot/core/config_manager.py
"""
Runtime Config Manager — Parametreleri çalışırken güncelle.

Sprint 4 — Block C:
  - Temel trading parametrelerini (TP/SL/imbalance/confidence) runtime'da değiştir
  - Backtest sonuçlarını okuyup en iyi parametreleri otomatik uygula
  - Değişiklikler Redis'te saklanır → restart'ta da korunur
  - GET /config/current  → mevcut parametreler
  - POST /config/update  → parametreleri güncelle
  - POST /config/apply-backtest → son backtest'ten otomatik al
"""
import json
import os
import time
from typing import Any, Dict, Optional, Tuple

from ..utils.cache import get_redis_client
from ..monitoring.logger import get_logger

logger = get_logger("config_manager")

CONFIG_REDIS_KEY = "runtime:config:v1"
CONFIG_TTL_S     = 86400 * 30   # 30 gün

# Güncellenebilir parametreler ve sınırları
_PARAM_SCHEMA: Dict[str, Dict[str, Any]] = {
    "take_profit_pct": {"min": 0.005, "max": 0.20,  "env": "TP_PCT",         "desc": "Take profit %"},
    "stop_loss_pct":   {"min": 0.005, "max": 0.20,  "env": "SL_PCT",         "desc": "Stop loss %"},
    "min_imbalance":   {"min": 0.05,  "max": 0.90,  "env": None,             "desc": "Min orderbook imbalance"},
    "min_confidence":  {"min": 0.40,  "max": 0.95,  "env": "MIN_LLM_CONF",   "desc": "Min LLM confidence"},
    "order_usd":       {"min": 1.0,   "max": 100.0, "env": "ORDER_USD",       "desc": "Order size USD"},
    "max_hold_s":      {"min": 60,    "max": 3600,  "env": "MAX_HOLD_S",      "desc": "Max hold seconds"},
    "max_spread":      {"min": 0.01,  "max": 0.30,  "env": "MAX_SPREAD",      "desc": "Max spread"},
}


class ConfigManager:
    """Runtime konfigürasyon yöneticisi."""

    def __init__(self):
        self.redis = get_redis_client()
        self._cache: Dict[str, Any] = {}
        self._loaded_at: float = 0.0
        self._load()

    # ──────────────────────────────────────────
    # Yükleme / kaydetme
    # ──────────────────────────────────────────

    def _load(self) -> None:
        """Redis'ten config'i yükle."""
        try:
            raw = self.redis.get(CONFIG_REDIS_KEY)
            if raw:
                self._cache = json.loads(raw)
                self._loaded_at = time.time()
                logger.info("Config loaded from Redis", params=list(self._cache.keys()))
        except Exception as e:
            logger.error("Config load failed", error=str(e))
            self._cache = {}

    def _save(self) -> bool:
        try:
            self._cache["_updated_at"] = time.time()
            self.redis.setex(CONFIG_REDIS_KEY, CONFIG_TTL_S, json.dumps(self._cache))
            return True
        except Exception as e:
            logger.error("Config save failed", error=str(e))
            return False

    # ──────────────────────────────────────────
    # Parametre okuma
    # ──────────────────────────────────────────

    def get(self, param: str, default: Any = None) -> Any:
        """
        Parametre değerini al.
        Önce runtime config, yoksa env, yoksa default.
        """
        if param in self._cache:
            return self._cache[param]

        schema = _PARAM_SCHEMA.get(param, {})
        env_key = schema.get("env")
        if env_key:
            val = os.getenv(env_key)
            if val is not None:
                try:
                    return float(val) if "." in val else int(val)
                except ValueError:
                    return val

        return default

    def get_all(self) -> Dict[str, Any]:
        """Tüm geçerli parametreleri döndür (env + runtime overrides)."""
        result: Dict[str, Any] = {}
        for param, schema in _PARAM_SCHEMA.items():
            result[param] = {
                "value":   self.get(param),
                "source":  "runtime" if param in self._cache else "env_or_default",
                "desc":    schema["desc"],
                "min":     schema["min"],
                "max":     schema["max"],
            }
        result["_updated_at"] = self._cache.get("_updated_at")
        return result

    # ──────────────────────────────────────────
    # Parametre güncelleme
    # ──────────────────────────────────────────

    def update(self, updates: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Parametreleri güncelle.

        Args:
            updates: {param: value, ...}

        Returns:
            (success, result_dict)
        """
        applied:  Dict[str, Any] = {}
        rejected: Dict[str, Any] = {}

        for param, value in updates.items():
            if param.startswith("_"):
                continue   # iç alanlar

            schema = _PARAM_SCHEMA.get(param)
            if not schema:
                rejected[param] = f"Unknown parameter. Valid: {list(_PARAM_SCHEMA)}"
                continue

            try:
                value = float(value)
            except (TypeError, ValueError):
                rejected[param] = f"Must be numeric"
                continue

            low, high = schema["min"], schema["max"]
            if not (low <= value <= high):
                rejected[param] = f"Out of range [{low}, {high}]"
                continue

            old = self.get(param)
            self._cache[param] = value
            applied[param] = {"old": old, "new": value}
            logger.info("Config param updated", param=param, old=old, new=value)

        if applied:
            self._save()

        return len(rejected) == 0, {"applied": applied, "rejected": rejected}

    def reset(self, params: Optional[list] = None) -> Dict[str, Any]:
        """
        Parametreleri env değerlerine geri döndür.

        Args:
            params: None → hepsini sıfırla, liste → sadece belirtilenleri
        """
        if params is None:
            reset_keys = [k for k in list(self._cache.keys()) if not k.startswith("_")]
        else:
            reset_keys = params

        for k in reset_keys:
            self._cache.pop(k, None)

        self._save()
        logger.info("Config reset", params=reset_keys)
        return {"reset": reset_keys}

    # ──────────────────────────────────────────
    # Backtest'ten otomatik uygulama
    # ──────────────────────────────────────────

    def apply_best_backtest(self, top_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        En iyi backtest parametrelerini otomatik uygula.

        Args:
            top_result: grid_search() döngüsünden gelen en iyi sonuç dict'i.
                        None ise PostgreSQL'den son optimize sonucunu okur.

        Returns:
            Uygulama sonucu
        """
        best = top_result or self._load_best_from_db()

        if not best:
            return {"ok": False, "error": "No backtest results available"}

        updates = {}

        tp = best.get("take_profit")
        sl = best.get("stop_loss")
        imb = best.get("min_imbalance")

        if tp is not None:
            updates["take_profit_pct"] = tp
        if sl is not None:
            updates["stop_loss_pct"] = sl
        if imb is not None:
            updates["min_imbalance"] = imb

        if not updates:
            return {"ok": False, "error": "No applicable parameters in backtest result"}

        ok, result = self.update(updates)
        result["source"] = "backtest"
        result["backtest_sharpe"] = best.get("sharpe", 0)
        result["backtest_win_rate"] = best.get("win_rate", 0)
        result["ok"] = True

        logger.info(
            "Config auto-applied from backtest",
            sharpe=best.get("sharpe"),
            win_rate=best.get("win_rate"),
            updates=list(updates.keys()),
        )
        return result

    def _load_best_from_db(self) -> Optional[Dict[str, Any]]:
        """PostgreSQL'den en yüksek Sharpe'lı backtest run'ını çek."""
        try:
            import psycopg2
            import psycopg2.extras

            from ..backtest.analytics import _get_database_url
            db_url = _get_database_url()
            if not db_url:
                return None

            conn = psycopg2.connect(db_url)
            cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT config, sharpe, win_rate, total_pnl
                FROM backtest_runs
                WHERE total_trades >= 5
                ORDER BY sharpe DESC
                LIMIT 1
            """)
            row = cur.fetchone()
            cur.close()
            conn.close()

            if not row:
                return None

            cfg = json.loads(row["config"]) if isinstance(row["config"], str) else row["config"]
            return {
                "take_profit": cfg.get("take_profit_pct"),
                "stop_loss":   cfg.get("stop_loss_pct"),
                "min_imbalance": cfg.get("min_imbalance"),
                "sharpe":      row["sharpe"],
                "win_rate":    row["win_rate"],
            }
        except Exception as e:
            logger.error("DB best backtest load failed", error=str(e))
            return None


# ──────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────

_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
