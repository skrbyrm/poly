# agent/bot/backtest/data_loader.py
"""
Historical Data Loader — Polymarket geçmiş fiyat verisi.

Kaynaklar:
  1. Gamma API — market listesi ve metadata
  2. CLOB API  — geçmiş orderbook/trade verileri (varsa)
  3. Polymarket Data API — time-series fiyat geçmişi

Cache: Her market için 1 saatlik Redis cache.
"""
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

import requests

from ..utils.cache import get_redis_client
from ..monitoring.logger import get_logger

logger = get_logger("backtest.loader")

GAMMA_BASE   = "https://gamma-api.polymarket.com"
CLOB_BASE    = "https://clob.polymarket.com"
DATA_CACHE_TTL = 3600   # 1 saat


# ─────────────────────────────────────────────
# Veri yapıları
# ─────────────────────────────────────────────

@dataclass
class PricePoint:
    """Tek bir fiyat noktası."""
    timestamp: float   # Unix
    price: float       # 0.0 – 1.0
    volume: float = 0.0


@dataclass
class MarketHistory:
    """Bir market'in geçmiş fiyat serisi."""
    token_id:   str
    question:   str
    category:   str
    start_ts:   float
    end_ts:     float
    resolution: Optional[float]          # 1.0 = YES, 0.0 = NO, None = unresolved
    prices:     List[PricePoint] = field(default_factory=list)

    @property
    def price_series(self) -> List[float]:
        return [p.price for p in self.prices]

    @property
    def timestamps(self) -> List[float]:
        return [p.timestamp for p in self.prices]

    def price_at(self, ts: float) -> Optional[float]:
        """Verilen timestamp'e en yakın fiyatı döndür."""
        if not self.prices:
            return None
        closest = min(self.prices, key=lambda p: abs(p.timestamp - ts))
        return closest.price


# ─────────────────────────────────────────────
# Ana loader
# ─────────────────────────────────────────────

class HistoricalDataLoader:

    def __init__(self):
        self.redis  = get_redis_client()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "polymarket-backtest/1.0"

    # ── Public API ──

    def load_resolved_markets(
        self,
        days_back: int = 30,
        limit: int = 100,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Son N günde kapanan market'leri çek.

        Args:
            days_back: Kaç gün geriye
            limit:     Maksimum market sayısı
            category:  Filtre (None = hepsi)

        Returns:
            Market objeleri listesi (Gamma API formatı)
        """
        cache_key = f"backtest:resolved:{days_back}:{limit}:{category or 'all'}"
        cached = self._get_cache(cache_key)
        if cached:
            logger.info("Resolved markets from cache", count=len(cached))
            return cached

        markets = self._fetch_resolved_markets(days_back, limit)

        if category:
            cat_lower = category.lower()
            markets = [
                m for m in markets
                if cat_lower in (m.get("category") or "").lower()
                or cat_lower in (m.get("question") or "").lower()
            ]

        self._set_cache(cache_key, markets)
        logger.info("Resolved markets loaded", count=len(markets), days_back=days_back)
        return markets

    def load_market_history(
        self,
        token_id: str,
        fidelity: int = 60,     # dakika başına
    ) -> Optional[MarketHistory]:
        """
        Tek bir token için fiyat geçmişini çek.

        Args:
            token_id:  CLOB token ID
            fidelity:  Veri noktası aralığı (dakika)

        Returns:
            MarketHistory veya None
        """
        cache_key = f"backtest:history:{token_id}:{fidelity}"
        cached = self._get_cache(cache_key)
        if cached:
            return MarketHistory(**{
                **cached,
                "prices": [PricePoint(**p) for p in cached.get("prices", [])],
            })

        history = self._fetch_market_history(token_id, fidelity)
        if history:
            self._set_cache(cache_key, {
                **history.__dict__,
                "prices": [p.__dict__ for p in history.prices],
            })

        return history

    def load_batch(
        self,
        token_ids: List[str],
        fidelity: int = 60,
    ) -> Dict[str, MarketHistory]:
        """
        Birden fazla token için paralel veri yükle.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: Dict[str, MarketHistory] = {}

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(self.load_market_history, tid, fidelity): tid
                for tid in token_ids
            }
            for future in as_completed(futures):
                tid = futures[future]
                try:
                    history = future.result(timeout=10)
                    if history:
                        results[tid] = history
                except Exception as e:
                    logger.error("History load failed", token_id=tid, error=str(e))

        logger.info("Batch history loaded", requested=len(token_ids), loaded=len(results))
        return results

    # ── Gamma API ──

    def _fetch_resolved_markets(
        self, days_back: int, limit: int
    ) -> List[Dict[str, Any]]:
        """Gamma API'den kapanan market'leri çek."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        cutoff_ts = int(cutoff.timestamp())

        try:
            resp = self.session.get(
                f"{GAMMA_BASE}/markets",
                params={
                    "limit": min(limit, 500),
                    "closed": True,
                    "active": False,
                    "order": "volume24hrClob",
                    "ascending": False,
                },
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()

            markets = raw if isinstance(raw, list) else raw.get("markets", raw.get("data", []))

            # Cutoff filtresi
            filtered = []
            for m in markets:
                end_val = m.get("endDate") or m.get("end_date")
                if end_val:
                    try:
                        end_dt = datetime.fromisoformat(str(end_val).replace("Z", "+00:00"))
                        if end_dt.timestamp() >= cutoff_ts:
                            filtered.append(m)
                    except Exception:
                        filtered.append(m)
                else:
                    filtered.append(m)

            return filtered[:limit]

        except Exception as e:
            logger.error("Resolved markets fetch failed", error=str(e))
            return []

    def load_active_markets(
        self,
        limit: int = 100,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Aktif (açık) market'leri çek — bunların CLOB history'si dolu."""
        cache_key = f"backtest:active:{limit}:{category or 'all'}"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        try:
            resp = self.session.get(
                f"{GAMMA_BASE}/markets",
                params={
                    "limit": min(limit, 500),
                    "closed": False,
                    "active": True,
                    "order": "volume24hrClob",
                    "ascending": False,
                },
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()
            markets = raw if isinstance(raw, list) else raw.get("markets", raw.get("data", []))
            if category:
                cat_lower = category.lower()
                markets = [
                    m for m in markets
                    if cat_lower in (m.get("category") or "").lower()
                    or cat_lower in (m.get("question") or "").lower()
                ]
            result = markets[:limit]
            self._set_cache(cache_key, result)
            logger.info("Active markets loaded", count=len(result))
            return result
        except Exception as e:
            logger.error("Active markets fetch failed", error=str(e))
            return []

    # ── CLOB time-series ──

    def _fetch_market_history(
        self, token_id: str, fidelity: int
    ) -> Optional[MarketHistory]:
        """CLOB API'den token price history çek."""
        try:
            resp = self.session.get(
                f"{CLOB_BASE}/prices-history",
                params={
                    "market": token_id,
                    "fidelity": fidelity,
                    "interval": "1w",
                },
                timeout=10,
            )

            if resp.status_code == 404:
                logger.warning("No price history", token_id=token_id)
                return None

            resp.raise_for_status()
            data = resp.json()

            # Response formatı: {"history": [{"t": unix, "p": price}, ...]}
            raw_points = data.get("history", [])
            if not raw_points:
                return None

            prices = [
                PricePoint(
                    timestamp=float(pt.get("t", 0)),
                    price=float(pt.get("p", 0)),
                    volume=float(pt.get("v", 0)),
                )
                for pt in raw_points
                if pt.get("t") and pt.get("p")
            ]

            if not prices:
                return None

            prices.sort(key=lambda p: p.timestamp)

            return MarketHistory(
                token_id=token_id,
                question="",         # caller'dan zenginleştirilebilir
                category="other",
                start_ts=prices[0].timestamp,
                end_ts=prices[-1].timestamp,
                resolution=None,     # resolved markets için ayrıca doldurulur
                prices=prices,
            )

        except Exception as e:
            logger.error("History fetch failed", token_id=token_id, error=str(e))
            return None

    # ── Redis cache ──

    def _get_cache(self, key: str) -> Optional[Any]:
        try:
            raw = self.redis.get(f"backtest:{key}")
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def _set_cache(self, key: str, data: Any) -> None:
        try:
            self.redis.setex(f"backtest:{key}", DATA_CACHE_TTL, json.dumps(data))
        except Exception:
            pass


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

_loader: Optional[HistoricalDataLoader] = None


def get_data_loader() -> HistoricalDataLoader:
    global _loader
    if _loader is None:
        _loader = HistoricalDataLoader()
    return _loader
