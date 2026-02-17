# agent/bot/snapshot.py
from typing import Dict, Any
from .core.market_intelligence import get_market_intelligence
from .gamma import candidate_markets, extract_clob_token_ids
from .config import SNAPSHOT_TIME_BUDGET_S, TOPK

WATCH: Dict[str, Any] = {}
WATCH_TTL_S = 300


def _build_token_to_question_map(limit: int = 500) -> Dict[str, str]:
    mapping = {}
    try:
        markets = candidate_markets(limit=limit)
        for m in markets:
            question = m.get("question", "")
            tokens = extract_clob_token_ids(m)
            for tid in tokens:
                mapping[tid] = question
    except Exception as e:
        print(f"[SNAPSHOT] Question map error: {e}")
    return mapping


def snapshot_scored_scan_topk_internal(time_budget_s: int = None, topk: int = None) -> Dict[str, Any]:
    if time_budget_s is None:
        time_budget_s = SNAPSHOT_TIME_BUDGET_S
    if topk is None:
        topk = TOPK

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

    token_questions = _build_token_to_question_map()
    opportunities = result.get("topk", [])

    formatted_topk = []
    for opp in opportunities:
        tid = opp.get("token_id")
        formatted_topk.append({
            "token_id": tid,
            "question": token_questions.get(tid, "Unknown market"),
            "score": opp.get("score"),
            "band_best_bid": opp.get("best_bid"),
            "band_best_ask": opp.get("best_ask"),
            "spread_band": opp.get("spread"),
            "spread_pct": opp.get("spread_pct"),
            "mid_band": opp.get("mid_price"),
            "bid_depth_band": opp.get("bid_depth"),
            "ask_depth_band": opp.get("ask_depth"),
            "imbalance": opp.get("imbalance"),
        })

    return {
        "ok": True,
        "topk": formatted_topk,
        "count": len(formatted_topk),
        "time_s": result.get("time_s", 0),
        "scanned": result.get("scanned", 0)
    }


def snapshot_scored_scan_internal(time_budget_s: int = None) -> Dict[str, Any]:
    result = snapshot_scored_scan_topk_internal(time_budget_s=time_budget_s, topk=1)
    if not result.get("ok") or not result.get("topk"):
        return {"ok": False, "error": "No opportunities", "time_s": result.get("time_s", 0)}
    opp = result["topk"][0]
    return {
        "ok": True,
        "token_id": opp.get("token_id"),
        "question": opp.get("question"),
        "score": opp.get("score"),
        "band_best_bid": opp.get("band_best_bid"),
        "band_best_ask": opp.get("band_best_ask"),
        "spread_band": opp.get("spread_band"),
        "mid_band": opp.get("mid_band"),
        "bid_depth_band": opp.get("bid_depth_band"),
        "ask_depth_band": opp.get("ask_depth_band"),
        "time_s": result.get("time_s", 0),
    }
