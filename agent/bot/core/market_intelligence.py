# agent/bot/core/market_intelligence.py
"""
Market intelligence - Paralel orderbook fetching, scoring, opportunity ranking
"""
import time
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..gamma import candidate_markets, extract_clob_token_ids
from ..clob_read import get_orderbook
from ..utils.cache import cache_with_ttl
from ..config import CAND_LIMIT, MAX_SPREAD, MIN_BAND_DEPTH

class MarketIntelligence:
    """Market analizi ve opportunity scoring"""
    
    def __init__(self):
        self.max_workers = 10  # Paralel orderbook fetch
        self.max_spread = MAX_SPREAD
        self.min_depth = MIN_BAND_DEPTH
    
    @cache_with_ttl(ttl_seconds=30, key_prefix="market_intel:candidates")
    def get_candidate_tokens(self, limit: int = None) -> List[str]:
        """
        Candidate token ID listesi getir
        
        Args:
            limit: Maksimum market sayısı
        
        Returns:
            Token ID listesi
        """
        if limit is None:
            limit = CAND_LIMIT
        
        markets = candidate_markets(limit=limit)
        
        all_tokens = []
        for market in markets:
            tokens = extract_clob_token_ids(market)
            all_tokens.extend(tokens)
        
        # Unique
        return list(set(all_tokens))
    
    def fetch_orderbooks_parallel(self, token_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Paralel orderbook fetching (10x hızlı)
        
        Args:
            token_ids: Token ID listesi
        
        Returns:
            {token_id: orderbook_result}
        """
        results = {}
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_token = {
                executor.submit(get_orderbook, tid): tid
                for tid in token_ids
            }
            
            # Collect results
            for future in as_completed(future_to_token):
                token_id = future_to_token[future]
                try:
                    result = future.result(timeout=5)
                    results[token_id] = result
                except Exception as e:
                    results[token_id] = {"ok": False, "error": str(e)}
        
        return results
    
    def score_opportunity(self, token_id: str, orderbook: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Market opportunity scoring
        
        Scoring kriterleri:
        - Spread (dar spread = yüksek skor)
        - Liquidity depth
        - Volatility (future: historical data)
        
        Returns:
            Score dict veya None
        """
        if not orderbook.get("ok"):
            return None
        
        ob = orderbook.get("orderbook", {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        
        if not bids or not asks:
            return None
        
        try:
            best_bid = float(bids[0].get("price", 0))
            best_ask = float(asks[0].get("price", 0))
            
            if best_bid <= 0 or best_ask <= 0:
                return None
            
            # Spread hesapla
            spread = best_ask - best_bid
            spread_pct = spread / best_bid
            
            # Spread filtresi
            if spread_pct > self.max_spread:
                return None
            
            # Depth hesapla (top 5 level)
            bid_depth = sum(float(b.get("price", 0)) * float(b.get("size", 0)) for b in bids[:5])
            ask_depth = sum(float(a.get("price", 0)) * float(a.get("size", 0)) for a in asks[:5])
            total_depth = bid_depth + ask_depth
            
            # Depth filtresi
            if total_depth < self.min_depth:
                return None
            
            # Mid price
            mid_price = (best_bid + best_ask) / 2
            
            # Scoring (0-100)
            # 1. Spread component (dar spread = yüksek skor)
            spread_score = max(0, 100 * (1 - (spread_pct / self.max_spread)))
            
            # 2. Depth component
            depth_score = min(100, (total_depth / self.min_depth) * 50)
            
            # 3. Price band (0.35-0.70 arası tercih)
            if 0.35 <= mid_price <= 0.70:
                band_score = 100
            else:
                band_score = 50
            
            # Weighted score
            total_score = (spread_score * 0.4) + (depth_score * 0.4) + (band_score * 0.2)
            
            return {
                "token_id": token_id,
                "score": round(total_score, 2),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": spread,
                "spread_pct": round(spread_pct * 100, 2),
                "mid_price": mid_price,
                "bid_depth": round(bid_depth, 2),
                "ask_depth": round(ask_depth, 2),
                "total_depth": round(total_depth, 2)
            }
        
        except Exception as e:
            print(f"[MARKET_INTEL] Score error for {token_id}: {e}")
            return None
    
    def find_top_opportunities(self, topk: int = 5) -> Dict[str, Any]:
        """
        En iyi trading fırsatlarını bul
        
        Args:
            topk: Kaç tane opportunity
        
        Returns:
            Top opportunities dict
        """
        start_time = time.time()
        
        # 1. Candidate tokens getir
        token_ids = self.get_candidate_tokens()
        
        if not token_ids:
            return {
                "ok": False,
                "error": "No candidate tokens found",
                "topk": [],
                "time_s": time.time() - start_time
            }
        
        # 2. Paralel orderbook fetch
        orderbooks = self.fetch_orderbooks_parallel(token_ids)
        
        # 3. Score her token
        scored = []
        for token_id, ob in orderbooks.items():
            score_result = self.score_opportunity(token_id, ob)
            if score_result:
                scored.append(score_result)
        
        # 4. Sort by score (descending)
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        # 5. Top K
        top_opportunities = scored[:topk]
        
        return {
            "ok": True,
            "topk": top_opportunities,
            "count": len(top_opportunities),
            "scanned": len(token_ids),
            "time_s": round(time.time() - start_time, 2)
        }


# Global instance
_market_intelligence = None

def get_market_intelligence() -> MarketIntelligence:
    """MarketIntelligence singleton"""
    global _market_intelligence
    if _market_intelligence is None:
        _market_intelligence = MarketIntelligence()
    return _market_intelligence
