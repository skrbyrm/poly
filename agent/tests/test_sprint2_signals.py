# agent/tests/test_sprint2_signals.py
"""
Sprint 2 — Signal engine testleri.
"""
import pytest


# ─────────────────────────────────────────────
# Momentum signal
# ─────────────────────────────────────────────

class TestMomentumSignal:

    def _ob(self, bids, asks):
        return {
            "ok": True,
            "orderbook": {
                "bids": [{"price": str(p), "size": str(s)} for p, s in bids],
                "asks": [{"price": str(p), "size": str(s)} for p, s in asks],
            },
        }

    def test_bid_heavy_positive_imbalance(self):
        from bot.signals.momentum import get_momentum_signal
        # Bid depth >> Ask depth
        ob = self._ob(
            bids=[(0.48, 10000), (0.45, 5000)],
            asks=[(0.52, 500),  (0.55, 300)],
        )
        sig = get_momentum_signal(ob)
        assert sig is not None
        assert sig.imbalance > 0.5, f"Expected strong positive imbalance, got {sig.imbalance}"
        assert sig.composite > 0

    def test_ask_heavy_negative_imbalance(self):
        from bot.signals.momentum import get_momentum_signal
        ob = self._ob(
            bids=[(0.48, 200), (0.45, 100)],
            asks=[(0.52, 8000), (0.55, 4000)],
        )
        sig = get_momentum_signal(ob)
        assert sig is not None
        assert sig.imbalance < -0.5, f"Expected negative imbalance, got {sig.imbalance}"

    def test_balanced_near_zero(self):
        from bot.signals.momentum import get_momentum_signal
        ob = self._ob(
            bids=[(0.48, 1000)],
            asks=[(0.52, 1000)],
        )
        sig = get_momentum_signal(ob)
        assert sig is not None
        assert abs(sig.imbalance) < 0.1

    def test_invalid_orderbook_returns_none(self):
        from bot.signals.momentum import get_momentum_signal
        sig = get_momentum_signal({"ok": False})
        assert sig is None

    def test_empty_orderbook_returns_none(self):
        from bot.signals.momentum import get_momentum_signal
        sig = get_momentum_signal({"ok": True, "orderbook": {"bids": [], "asks": []}})
        assert sig is None

    def test_signal_text_generated(self):
        from bot.signals.momentum import get_momentum_signal
        ob = self._ob(
            bids=[(0.48, 5000)],
            asks=[(0.52, 1000)],
        )
        sig = get_momentum_signal(ob)
        assert sig is not None
        assert len(sig.signal_text) > 10


# ─────────────────────────────────────────────
# Resolution signal
# ─────────────────────────────────────────────

class TestResolutionSignal:

    def test_politics_category_detected(self):
        from bot.signals.resolution import get_resolution_signal
        market = {"question": "Will the Senate pass the new election bill?"}
        sig = get_resolution_signal(market)
        assert sig.category == "politics"

    def test_sports_category_detected(self):
        from bot.signals.resolution import get_resolution_signal
        market = {"question": "Will the NBA championship be won by Lakers?"}
        sig = get_resolution_signal(market)
        assert sig.category == "sports"

    def test_crypto_category_detected(self):
        from bot.signals.resolution import get_resolution_signal
        market = {"question": "Will Bitcoin reach $100k by end of year?"}
        sig = get_resolution_signal(market)
        assert sig.category == "crypto"

    def test_future_date_proximity_score(self):
        from bot.signals.resolution import get_resolution_signal
        from datetime import datetime, timezone, timedelta

        future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        market = {"question": "Will X happen?", "endDate": future}
        sig = get_resolution_signal(market)

        assert sig.days_to_resolution is not None
        assert 5 < sig.days_to_resolution < 9
        assert sig.proximity_score == 1.0  # sweetspot

    def test_expired_market(self):
        from bot.signals.resolution import get_resolution_signal
        from datetime import datetime, timezone, timedelta

        past = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        market = {"question": "Will X happen?", "endDate": past}
        sig = get_resolution_signal(market)

        assert sig.is_expired is True
        assert sig.proximity_score == 0.0

    def test_imminent_market(self):
        from bot.signals.resolution import get_resolution_signal
        from datetime import datetime, timezone, timedelta

        soon = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        market = {"question": "Will X happen?", "endDate": soon}
        sig = get_resolution_signal(market)

        assert sig.is_imminent is True
        assert sig.proximity_score < 0.5

    def test_category_weights_sum_to_one(self):
        from bot.signals.resolution import get_resolution_signal
        for cat in ("politics", "sports", "crypto", "finance", "other"):
            market = {"question": f"Test {cat} question"}
            sig = get_resolution_signal(market)
            total = sum(sig.category_weight.values())
            assert abs(total - 1.0) < 0.01, f"Weights don't sum to 1 for {cat}: {total}"


# ─────────────────────────────────────────────
# News signal (Tavily mock)
# ─────────────────────────────────────────────

class TestNewsSignal:

    def test_no_tavily_key_returns_unavailable(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        from bot.signals.news import get_news_signal
        sig = get_news_signal("Will X happen?")
        assert sig.source == "unavailable"
        assert sig.sentiment == 0.0

    def test_empty_question_returns_unavailable(self):
        from bot.signals.news import get_news_signal
        sig = get_news_signal("")
        assert sig.source == "unavailable"

    def test_sentiment_bullish_words(self):
        from bot.signals.news import _analyze_results
        results = [
            {"title": "Team wins championship, confirms victory"},
            {"title": "Strong surge leads to record high"},
        ]
        sig = _analyze_results(results, "Will team win?", "YES")
        assert sig.sentiment > 0, f"Expected positive sentiment, got {sig.sentiment}"

    def test_sentiment_bearish_words(self):
        from bot.signals.news import _analyze_results
        results = [
            {"title": "Team loses, fails to qualify"},
            {"title": "Collapse and defeat confirmed"},
        ]
        sig = _analyze_results(results, "Will team win?", "YES")
        assert sig.sentiment < 0, f"Expected negative sentiment, got {sig.sentiment}"

    def test_no_sentiment_neutral(self):
        from bot.signals.news import _analyze_results
        results = [{"title": "Something happened today somewhere"}]
        sig = _analyze_results(results, "Will something happen?", "YES")
        # Neutral when no bullish/bearish words
        assert sig.confidence < 0.5

    def test_no_sentiment_flips_for_no_token(self):
        from bot.signals.news import _analyze_results
        results = [{"title": "Wins and confirms victory strongly"}]
        yes_sig = _analyze_results(results, "Will X?", "YES")
        no_sig  = _analyze_results(results, "Will X?", "NO")
        assert yes_sig.sentiment > 0
        assert no_sig.sentiment < 0  # ters çevrilmeli


# ─────────────────────────────────────────────
# Prompt builder — integration
# ─────────────────────────────────────────────

class TestPromptBuilder:

    def _snapshot(self):
        return {
            "topk": [{
                "token_id": "tok_123",
                "question": "Will Bitcoin reach $100k?",
                "best_bid": 0.48,
                "best_ask": 0.52,
                "mid_price": 0.50,
                "spread": 0.04,
                "spread_pct": 8.0,
                "bid_depth": 50000,
                "ask_depth": 10000,
                "total_depth": 60000,
                "imbalance": 66.7,
            }],
            "market_data": {},
        }

    def test_prompt_has_system_and_user(self):
        from bot.ai.prompt_builder import build_decision_prompt
        msgs = build_decision_prompt(self._snapshot(), {"cash": 50, "positions": {}})
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_user_prompt_contains_token_id(self):
        from bot.ai.prompt_builder import build_decision_prompt
        msgs = build_decision_prompt(self._snapshot(), {"cash": 50, "positions": {}})
        assert "tok_123" in msgs[1]["content"]

    def test_user_prompt_contains_question(self):
        from bot.ai.prompt_builder import build_decision_prompt
        msgs = build_decision_prompt(self._snapshot(), {"cash": 50, "positions": {}})
        assert "Bitcoin" in msgs[1]["content"]

    def test_user_prompt_contains_depth(self):
        from bot.ai.prompt_builder import build_decision_prompt
        msgs = build_decision_prompt(self._snapshot(), {"cash": 50, "positions": {}})
        content = msgs[1]["content"]
        # Depth bilgisi olmalı
        assert "50,000" in content or "50000" in content or "Bid" in content

    def test_existing_position_shown(self):
        from bot.ai.prompt_builder import build_decision_prompt
        ledger = {
            "cash": 50,
            "positions": {"tok_123": {"qty": 10, "avg_price": 0.45}},
        }
        msgs = build_decision_prompt(self._snapshot(), ledger)
        assert "YOU OWN" in msgs[1]["content"]
