# agent/bot/core/market_intelligence.py
"""
Market Intelligence — Polymarket fırsat tarama.

Sprint 2 değişiklikleri:
  - find_top_opportunities() artık ham market objelerini de döndürüyor
    (prompt_builder için resolution date, volume vs.)
  - Resolution date filter eklendi (süresi dolan market'leri at)
  - Volume scoring eklendi
  - Category bilgisi score'a dahil edildi
"""
import time
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..gamma import candidate_markets, extract_clob_token_ids
from ..clob_read import get_orderbook
from ..config import CAND_LIMIT
from ..monitoring.logger import get_logger

logger = get_logger("market_intelligence")


class MarketIntelligence:

    def __init__(self):
        self.max_workers    = 10
        self.min_depth      = 10       # USD
        self.min_bid        = 0.05
        self.max_ask        = 0.95
        self.max_spread     = 0.25
        self.min_mid        = 0.10
        self.max_mid        = 0.90

    # ─────────────────────────────────────────────
    # Candidate tokens
    # ─────────────────────────────────────────────

    def get_candidate_tokens(
        self, limit: int = None
    ) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
        """
        Aktif marketlerden CLOB token ID'lerini çek.
        
        Returns:
            (token_ids, token_to_market_map)
        """
        if limit is None:
            limit = CAND_LIMIT

        markets = candidate_markets(limit=limit)
        token_ids: List[str] = []
        token_map: Dict[str, Dict[str, Any]] = {}

        for market in markets:
            # Süresi dolmuş market'leri atla
            if self._is_expired(market):
                continue

            tokens = extract_clob_token_ids(market)
            for tid in tokens:
                if tid not in token_map:
                    token_ids.append(tid)
                    token_map[tid] = market

        return list(dict.fromkeys(token_ids)), token_map  # deduplicate + preserve order

    def _is_expired(self, market: Dict[str, Any]) -> bool:
        """Market'in çözüm tarihi geçmiş mi?"""
        from datetime import datetime, timezone
        for field in ("endDate", "end_date", "resolutionDate"):
            val = market.get(field)
            if not val:
                continue
            try:
                if isinstance(val, (int, float)):
                    end = datetime.fromtimestamp(val, tz=timezone.utc)
                else:
                    end = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                if end < datetime.now(timezone.utc):
                    return True
            except (ValueError, TypeError):
                continue
        return False

    # ─────────────────────────────────────────────
    # Parallel orderbook fetch
    # ─────────────────────────────────────────────

    def fetch_orderbooks_parallel(
        self, token_ids: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(get_orderbook, tid): tid for tid in token_ids}
            for future in as_completed(futures):
                tid = futures[future]
                try:
                    results[tid] = future.result(timeout=5)
                except Exception as e:
                    results[tid] = {"ok": False, "error": str(e)}
        return results

    # ─────────────────────────────────────────────
    # Opportunity scoring
    # ─────────────────────────────────────────────

    def score_opportunity(
        self,
        token_id: str,
        orderbook: Dict[str, Any],
        market: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Tek bir token için fırsat skoru hesapla.
        
        Args:
            token_id:  Token ID
            orderbook: get_orderbook() dönüşü
            market:    Gamma API market objesi (varsa volume/liquidity bilgisi)
        
        Returns:
            Scored opportunity dict veya None (filtrelenirse)
        """
        if not orderbook.get("ok"):
            return None

        ob = orderbook.get("orderbook", {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])

        if not bids or not asks:
            return None

        try:
            from ..risk.checks import _get_best_bid_ask

            best_bid, best_ask = _get_best_bid_ask(orderbook)
            if best_bid is None or best_ask is None:
                return None

            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2
            spread_pct = (spread / mid_price * 100) if mid_price > 0 else 999.0

            # ── Filtreler ──
            if best_bid < self.min_bid:   return None
            if best_ask > self.max_ask:   return None
            if spread > self.max_spread:  return None
            if not (self.min_mid <= mid_price <= self.max_mid): return None

            # Derinlik
            bid_depth = sum(
                float(b.get("price", 0)) * float(b.get("size", 0))
                for b in bids if 0.05 <= float(b.get("price", 0)) <= 0.95
            )
            ask_depth = sum(
                float(a.get("price", 0)) * float(a.get("size", 0))
                for a in asks if 0.05 <= float(a.get("price", 0)) <= 0.95
            )
            total_depth = bid_depth + ask_depth

            if total_depth < self.min_depth:
                return None

            # ── Scoring ──
            spread_score    = max(0, 100 * (1 - spread / self.max_spread))
            depth_score     = min(100, (total_depth / max(self.min_depth, 1)) * 20)
            dist_center     = abs(mid_price - 0.50)
            price_score     = max(0, 100 * (1 - dist_center / 0.30))

            if bid_depth > 0 and ask_depth > 0:
                imbalance_raw   = abs(bid_depth - ask_depth) / (bid_depth + ask_depth)
                imbalance_score = imbalance_raw * 100
            else:
                imbalance_score = 0
                imbalance_raw   = 0

            # Volume bonus (varsa)
            volume_score = 0.0
            if market:
                v24 = float(market.get("volume24hrClob") or market.get("volume24hr") or 0)
                if v24 > 0:
                    volume_score = min(20, v24 / 5000)  # $100k = 20 puan

            total_score = (
                spread_score    * 0.35 +
                depth_score     * 0.25 +
                price_score     * 0.20 +
                imbalance_score * 0.10 +
                volume_score    * 0.10
            )

            return {
                "token_id":    token_id,
                "score":       round(total_score, 2),
                "best_bid":    round(best_bid, 4),
                "best_ask":    round(best_ask, 4),
                "spread":      round(spread, 4),
                "spread_pct":  round(spread_pct, 2),
                "mid_price":   round(mid_price, 4),
                "bid_depth":   round(bid_depth, 2),
                "ask_depth":   round(ask_depth, 2),
                "total_depth": round(total_depth, 2),
                "imbalance":   round(imbalance_score, 2),
                # volume
                "volume_24h":  float(market.get("volume24hrClob") or 0) if market else 0,
                "liquidity":   float(market.get("liquidityClob") or 0) if market else 0,
            }

        except Exception as e:
            logger.error("Score error", token_id=token_id, error=str(e))
            return None

    # ─────────────────────────────────────────────
    # Top opportunities
    # ─────────────────────────────────────────────

    def find_top_opportunities(self, topk: int = 5) -> Dict[str, Any]:
        """
        En iyi fırsatları bul.
        
        Returns:
            {ok, topk, market_data, count, scanned, time_s}
            market_data: {token_id: market_obj}  ← YENİ (prompt için)
        """
        start_time = time.time()

        token_ids, token_map = self.get_candidate_tokens()

        if not token_ids:
            return {"ok": False, "error": "No candidate tokens", "topk": [], "time_s": 0, "scanned": 0}

        orderbooks = self.fetch_orderbooks_parallel(token_ids)

        scored = []
        for tid, ob in orderbooks.items():
            market = token_map.get(tid)
            result = self.score_opportunity(tid, ob, market=market)
            if result:
                scored.append(result)

        ok_count = sum(1 for ob in orderbooks.values() if ob.get("ok"))
        logger.info(
            "Market scan complete",
            scanned=len(token_ids), ok=ok_count, passed=len(scored)
        )

        if not scored:
            return {
                "ok": False,
                "error": f"No opportunities passed filters ({ok_count}/{len(token_ids)} ok)",
                "topk": [],
                "market_data": {},
                "time_s": round(time.time() - start_time, 2),
                "scanned": len(token_ids),
            }

        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        top = scored[:topk]

        # Top token'lar için market objelerini döndür
        top_market_data = {
            t["token_id"]: token_map.get(t["token_id"], {})
            for t in top
        }

        if top:
            t = top[0]
            logger.info(
                "Best opportunity",
                bid=t["best_bid"], ask=t["best_ask"],
                spread_pct=t["spread_pct"], mid=t["mid_price"], score=t["score"]
            )

        return {
            "ok":          True,
            "topk":        top,
            "market_data": top_market_data,
            "count":       len(top),
            "scanned":     len(token_ids),
            "time_s":      round(time.time() - start_time, 2),
        }


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

_market_intelligence: Optional[MarketIntelligence] = None


def get_market_intelligence() -> MarketIntelligence:
    global _market_intelligence
    if _market_intelligence is None:
        _market_intelligence = MarketIntelligence()
    return _market_intelligence
