# agent/bot/core/market_intelligence.py
"""
Market intelligence - Polymarket'e özel fırsat tarama
"""
import time
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..gamma import candidate_markets, extract_clob_token_ids
from ..clob_read import get_orderbook
from ..config import CAND_LIMIT, MIN_BAND_DEPTH

class MarketIntelligence:

    def __init__(self):
        self.max_workers = 10
        self.min_depth = 10
        self.min_bid = 0.05
        self.max_ask = 0.95
        self.max_spread = 0.25
        self.min_mid = 0.10
        self.max_mid = 0.90

    def get_candidate_tokens(self, limit: int = None) -> List[str]:
        if limit is None:
            limit = CAND_LIMIT
        markets = candidate_markets(limit=limit)
        all_tokens = []
        for market in markets:
            tokens = extract_clob_token_ids(market)
            all_tokens.extend(tokens)
        return list(set(all_tokens))

    def fetch_orderbooks_parallel(self, token_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_token = {
                executor.submit(get_orderbook, tid): tid
                for tid in token_ids
            }
            for future in as_completed(future_to_token):
                token_id = future_to_token[future]
                try:
                    result = future.result(timeout=5)
                    results[token_id] = result
                except Exception as e:
                    results[token_id] = {"ok": False, "error": str(e)}
        return results

    def score_opportunity(self, token_id: str, orderbook: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not orderbook.get("ok"):
            return None

        ob = orderbook.get("orderbook", {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])

        if not bids or not asks:
            return None

        try:
            # Polymarket orderbook ters sıralı gelir!
            # bids[0] = en düşük bid → max() ile gerçek best bid buluyoruz
            # asks[0] = en yüksek ask → min() ile gerçek best ask buluyoruz
            bid_prices = [float(b.get("price", 0)) for b in bids if float(b.get("price", 0)) > 0]
            ask_prices = [float(a.get("price", 0)) for a in asks if float(a.get("price", 0)) > 0]

            if not bid_prices or not ask_prices:
                return None

            best_bid = max(bid_prices)  # Gerçek best bid
            best_ask = min(ask_prices)  # Gerçek best ask

            if best_bid <= 0 or best_ask <= 0:
                return None

            if best_bid >= best_ask:
                return None  # Crossed book

            # Spread (cent cinsinden)
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2

            # === FİLTRELER ===
            if best_bid < self.min_bid:
                return None  # Market neredeyse kesin HAYIR
            if best_ask > self.max_ask:
                return None  # Market neredeyse kesin EVET
            if spread > self.max_spread:
                return None  # Spread çok geniş
            if not (self.min_mid <= mid_price <= self.max_mid):
                return None  # Fiyat belirsiz bölgede değil

            # Depth - sadece makul fiyatlı seviyeleri say
            bid_depth = sum(
                float(b.get("price", 0)) * float(b.get("size", 0))
                for b in bids
                if float(b.get("price", 0)) >= self.min_bid
            )
            ask_depth = sum(
                float(a.get("price", 0)) * float(a.get("size", 0))
                for a in asks
                if float(a.get("price", 0)) <= self.max_ask
            )
            total_depth = bid_depth + ask_depth

            if total_depth < self.min_depth:
                return None

            # === SCORING ===
            # 1. Spread skoru (dar spread = yüksek skor)
            spread_score = max(0, 100 * (1 - (spread / self.max_spread)))

            # 2. Depth skoru
            depth_score = min(100, (total_depth / max(self.min_depth, 1)) * 20)

            # 3. Mid price skoru (0.45-0.55 = max belirsizlik = max fırsat)
            dist_from_center = abs(mid_price - 0.50)
            price_score = max(0, 100 * (1 - (dist_from_center / 0.30)))

            # 4. Imbalance (bid/ask ağırlık farkı = yön sinyali)
            if bid_depth > 0 and ask_depth > 0:
                imbalance = abs(bid_depth - ask_depth) / (bid_depth + ask_depth)
                imbalance_score = imbalance * 100
            else:
                imbalance_score = 0

            total_score = (
                spread_score    * 0.40 +
                depth_score     * 0.25 +
                price_score     * 0.25 +
                imbalance_score * 0.10
            )

            return {
                "token_id": token_id,
                "score": round(total_score, 2),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": round(spread, 4),
                "mid_price": round(mid_price, 4),
                "bid_depth": round(bid_depth, 2),
                "ask_depth": round(ask_depth, 2),
                "total_depth": round(total_depth, 2),
                "imbalance": round(imbalance_score, 2)
            }

        except Exception as e:
            print(f"[MARKET_INTEL] Score error for {token_id}: {e}")
            return None

    def find_top_opportunities(self, topk: int = 5) -> Dict[str, Any]:
        start_time = time.time()

        token_ids = self.get_candidate_tokens()

        if not token_ids:
            return {"ok": False, "error": "No candidate tokens", "topk": [], "time_s": 0, "scanned": 0}

        orderbooks = self.fetch_orderbooks_parallel(token_ids)

        scored = []
        for token_id, ob in orderbooks.items():
            result = self.score_opportunity(token_id, ob)
            if result:
                scored.append(result)

        ok_count = sum(1 for ob in orderbooks.values() if ob.get("ok"))
        print(f"[MARKET_INTEL] Scanned: {len(token_ids)} | OK: {ok_count} | Passed: {len(scored)}")

        if not scored:
            return {
                "ok": False,
                "error": f"No opportunities passed filters ({ok_count}/{len(token_ids)} ok)",
                "topk": [],
                "time_s": round(time.time() - start_time, 2),
                "scanned": len(token_ids)
            }

        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        top = scored[:topk]

        if top:
            t = top[0]
            print(f"[MARKET_INTEL] Best: bid={t['best_bid']} ask={t['best_ask']} "
                  f"spread={t['spread']} mid={t['mid_price']} score={t['score']}")

        return {
            "ok": True,
            "topk": top,
            "count": len(top),
            "scanned": len(token_ids),
            "time_s": round(time.time() - start_time, 2)
        }


_market_intelligence = None

def get_market_intelligence() -> MarketIntelligence:
    global _market_intelligence
    if _market_intelligence is None:
        _market_intelligence = MarketIntelligence()
    return _market_intelligence
