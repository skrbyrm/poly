from bot.core.market_intelligence import MarketIntelligence
from bot import snapshot as snapshot_mod


class _FakeIntel:
    def find_top_opportunities(self, topk=1):
        return {
            "ok": True,
            "topk": [
                {
                    "token_id": "123",
                    "score": 88.5,
                    "best_bid": 0.48,
                    "best_ask": 0.50,
                    "spread": 0.02,
                    "spread_pct": 4.0,
                    "mid_price": 0.49,
                    "bid_depth": 100.0,
                    "ask_depth": 120.0,
                    "total_depth": 220.0,
                    "imbalance": 9.0,
                }
            ][:topk],
            "time_s": 0.1,
            "scanned": 1,
        }


def test_market_intelligence_score_contains_core_fields():
    intel = MarketIntelligence()
    orderbook = {
        "ok": True,
        "orderbook": {
            "bids": [{"price": "0.48", "size": "500"}],
            "asks": [{"price": "0.50", "size": "500"}],
        },
    }

    opp = intel.score_opportunity("token-x", orderbook)
    assert opp is not None
    assert "best_bid" in opp and "best_ask" in opp and "mid_price" in opp


def test_snapshot_formats_topk(monkeypatch):
    monkeypatch.setattr(snapshot_mod, "get_market_intelligence", lambda: _FakeIntel())
    monkeypatch.setattr(snapshot_mod, "_build_token_to_question_map", lambda limit=500: {"123": "Will X happen?"})

    result = snapshot_mod.snapshot_scored_scan_topk_internal(topk=1)
    assert result["ok"] is True
    top = result["topk"][0]
    assert top["token_id"] == "123"
    assert top["question"] == "Will X happen?"
    assert "score" in top
