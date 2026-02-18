# agent/bot/snapshot.py
"""
Snapshot — Market intelligence sonuçlarını biçimlendir.

Sprint 2: market_data (ham Gamma objeleri) artık snapshot ile birlikte
taşınıyor, böylece prompt_builder resolution date ve volume'a erişebiliyor.
"""
from typing import Dict, Any

from .core.market_intelligence import get_market_intelligence
from .gamma import candidate_markets, extract_clob_token_ids
from .config import SNAPSHOT_TIME_BUDGET_S, TOPK

WATCH: Dict[str, Any] = {}
WATCH_TTL_S = 300


def _build_token_to_question_map(limit: int = 500) -> Dict[str, str]:
    """token_id → market sorusu eşlemesi."""
    mapping = {}
    try:
        markets = candidate_markets(limit=limit)
        for m in markets:
            question = m.get("question", "")
            for tid in extract_clob_token_ids(m):
                mapping[tid] = question
    except Exception as e:
        print(f"[SNAPSHOT] Question map error: {e}")
    return mapping


def snapshot_scored_scan_topk_internal(
    time_budget_s: int = None,
    topk: int = None,
) -> Dict[str, Any]:
    """
    Top-K fırsat snapshot'ı.
    
    Returns:
        {ok, topk, market_data, count, time_s, scanned}
        topk[i] her iki isim setini de içeriyor (canonical + backward compat.)
        market_data: {token_id: gamma_market_obj}  ← YENİ
    """
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
            "market_data": {},
            "count": 0,
            "time_s": result.get("time_s", 0),
        }

    # question mapping (market_intelligence'dan gelmiyor, ayrıca çek)
    token_questions = _build_token_to_question_map()
    market_data     = result.get("market_data", {})

    formatted_topk = []
    for opp in result.get("topk", []):
        tid = opp.get("token_id")
        formatted_topk.append({
            "token_id":   tid,
            "question":   token_questions.get(tid, "Unknown market"),
            "score":      opp.get("score"),
            # canonical names
            "best_bid":   opp.get("best_bid"),
            "best_ask":   opp.get("best_ask"),
            "spread":     opp.get("spread"),
            "spread_pct": opp.get("spread_pct"),
            "mid_price":  opp.get("mid_price"),
            "bid_depth":  opp.get("bid_depth"),
            "ask_depth":  opp.get("ask_depth"),
            "total_depth":opp.get("total_depth"),
            "imbalance":  opp.get("imbalance"),
            "volume_24h": opp.get("volume_24h", 0),
            "liquidity":  opp.get("liquidity", 0),
            # backward compatibility aliases
            "band_best_bid":  opp.get("best_bid"),
            "band_best_ask":  opp.get("best_ask"),
            "spread_band":    opp.get("spread"),
            "mid_band":       opp.get("mid_price"),
            "bid_depth_band": opp.get("bid_depth"),
            "ask_depth_band": opp.get("ask_depth"),
        })

    return {
        "ok":         True,
        "topk":       formatted_topk,
        "market_data": market_data,
        "count":      len(formatted_topk),
        "time_s":     result.get("time_s", 0),
        "scanned":    result.get("scanned", 0),
    }


def snapshot_scored_scan_internal(time_budget_s: int = None) -> Dict[str, Any]:
    """Tekil snapshot (eski API uyumluluğu için)."""
    result = snapshot_scored_scan_topk_internal(time_budget_s=time_budget_s, topk=1)
    if not result.get("ok") or not result.get("topk"):
        return {"ok": False, "error": "No opportunities", "time_s": result.get("time_s", 0)}
    opp = result["topk"][0]
    return {
        "ok":         True,
        "token_id":   opp.get("token_id"),
        "question":   opp.get("question"),
        "score":      opp.get("score"),
        "best_bid":   opp.get("best_bid"),
        "best_ask":   opp.get("best_ask"),
        "spread":     opp.get("spread"),
        "spread_pct": opp.get("spread_pct"),
        "mid_price":  opp.get("mid_price"),
        "bid_depth":  opp.get("bid_depth"),
        "ask_depth":  opp.get("ask_depth"),
        "total_depth":opp.get("total_depth"),
        "time_s":     result.get("time_s", 0),
    }
