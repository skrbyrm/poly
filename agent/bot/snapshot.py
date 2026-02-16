# agent/bot/snapshot.py
"""
Market snapshot - En iyi trading fırsatlarını bul (revize edilmiş, paralel)
"""
import time
from typing import Dict, Any
from .core.market_intelligence import get_market_intelligence
from .config import SNAPSHOT_TIME_BUDGET_S, TOPK

# Watch mekanizması (backward compatibility)
WATCH: Dict[str, Any] = {}
WATCH_TTL_S = 300

def snapshot_scored_scan_internal(time_budget_s: int = None) -> Dict[str, Any]:
    """
    Market tarama ve scoring (backward compatibility wrapper)
    
    Args:
        time_budget_s: Maksimum süre (saniye)
    
    Returns:
        Snapshot result
    """
    if time_budget_s is None:
        time_budget_s = SNAPSHOT_TIME_BUDGET_S
    
    # Yeni market intelligence kullan
    intel = get_market_intelligence()
    result = intel.find_top_opportunities(topk=1)  # Tek opportunity
    
    if not result.get("ok") or not result.get("topk"):
        return {
            "ok": False,
            "error": "No opportunities found",
            "time_s": result.get("time_s", 0)
        }
    
    # İlk opportunity'yi al (backward compatibility)
    opp = result["topk"][0]
    
    return {
        "ok": True,
        "token_id": opp.get("token_id"),
        "score": opp.get("score"),
        "band_best_bid": opp.get("best_bid"),
        "band_best_ask": opp.get("best_ask"),
        "spread_band": opp.get("spread"),
        "mid_band": opp.get("mid_price"),
        "bid_depth_band": opp.get("bid_depth"),
        "ask_depth_band": opp.get("ask_depth"),
        "time_s": result.get("time_s", 0),
        "tried": result.get("scanned", 0)
    }


def snapshot_scored_scan_topk_internal(time_budget_s: int = None, topk: int = None) -> Dict[str, Any]:
    """
    Market tarama - Top K opportunities
    
    Args:
        time_budget_s: Maksimum süre (saniye)
        topk: Kaç tane opportunity
    
    Returns:
        Top K snapshot result
    """
    if time_budget_s is None:
        time_budget_s = SNAPSHOT_TIME_BUDGET_S
    
    if topk is None:
        topk = TOPK
    
    # Market intelligence kullan
    intel = get_market_intelligence()
    result = intel.find_top_opportunities(topk=topk)
    
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", "Unknown error"),
            "topk": [],
            "count": 0,
            "time_s": result.get("time_s", 0)
        }
    
    opportunities = result.get("topk", [])
    
    # Format conversion (score data -> snapshot format)
    formatted_topk = []
    for opp in opportunities:
        formatted_topk.append({
            "token_id": opp.get("token_id"),
            "score": opp.get("score"),
            "band_best_bid": opp.get("best_bid"),
            "band_best_ask": opp.get("best_ask"),
            "spread_band": opp.get("spread"),
            "spread_pct": opp.get("spread_pct"),
            "mid_band": opp.get("mid_price"),
            "bid_depth_band": opp.get("bid_depth"),
            "ask_depth_band": opp.get("ask_depth"),
        })
    
    return {
        "ok": True,
        "topk": formatted_topk,
        "count": len(formatted_topk),
        "time_s": result.get("time_s", 0),
        "scanned": result.get("scanned", 0)
    }
