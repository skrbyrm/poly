import pytest
from bot.core.market_intelligence import MarketIntelligence
from bot.core.decision_engine import DecisionEngine


def _mock_orderbook():
    return {
        "ok": True,
        "orderbook": {
            "bids": [{"price": "0.48", "size": "500"}],
            "asks": [{"price": "0.52", "size": "500"}],
        }
    }


def test_market_intelligence_has_spread_pct():
    intel = MarketIntelligence()
    opp = intel.score_opportunity("123", _mock_orderbook())
    assert opp is not None
    assert "spread_pct" in opp
    assert opp["spread_pct"] > 0


def test_fallback_decision_uses_snapshot_schema():
    engine = DecisionEngine()
    snapshot = {
        "topk": [{
            "token_id": "123",
            "spread_pct": 1.5,
            "mid_price": 0.50,
            "total_depth": 500,
            "best_ask": 0.52,
            "best_bid": 0.48
        }]
    }
    ledger = {"positions": {}, "cash": 1000}
    decision = engine._fallback_decision(snapshot, ledger)
    assert decision["decision"] in ("buy", "hold")


def test_fallback_sell_if_profitable():
    engine = DecisionEngine()
    snapshot = {
        "topk": [{
            "token_id": "123",
            "spread_pct": 1.0,
            "mid_price": 0.55,
            "total_depth": 500,
            "best_ask": 0.56,
            "best_bid": 0.54
        }]
    }
    ledger = {"positions": {"123": {"qty": 10, "avg_price": 0.50}}, "cash": 1000}
    decision = engine._fallback_decision(snapshot, ledger)
    assert decision["decision"] == "sell"
