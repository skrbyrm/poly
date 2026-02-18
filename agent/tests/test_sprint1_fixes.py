# agent/tests/test_sprint1_fixes.py
"""
Sprint 1 — Tüm critical fix'lerin test edilmesi.

Test senaryoları:
  1. Orderbook parse doğruluğu (BUG-02)
  2. Position manager fiyat fetch (BUG-05)
  3. Order tracker fill logic (BUG-01)
  4. Paper ledger initial cash (BUG-04)
  5. Reserved cash mekanizması
"""
import time
import pytest


# ─────────────────────────────────────────────
# BUG-02: Orderbook parse
# ─────────────────────────────────────────────

class TestOrderbookParse:
    """Polymarket orderbook ters sıralı — max/min kullanılmalı."""

    def _make_ob(self, bids, asks):
        """Test orderbook yardımcısı."""
        return {
            "ok": True,
            "orderbook": {
                "bids": [{"price": str(p), "size": "100"} for p in bids],
                "asks": [{"price": str(p), "size": "100"} for p in asks],
            },
        }

    def test_best_bid_is_max(self):
        from bot.risk.checks import _get_best_bid_ask
        # Polymarket: bids ters sıralı — en düşük önce
        ob = self._make_ob(bids=[0.40, 0.43, 0.45], asks=[0.55, 0.52, 0.50])
        best_bid, best_ask = _get_best_bid_ask(ob)
        assert best_bid == 0.45, f"Expected 0.45, got {best_bid}"

    def test_best_ask_is_min(self):
        from bot.risk.checks import _get_best_bid_ask
        ob = self._make_ob(bids=[0.40, 0.43, 0.45], asks=[0.55, 0.52, 0.50])
        best_bid, best_ask = _get_best_bid_ask(ob)
        assert best_ask == 0.50, f"Expected 0.50, got {best_ask}"

    def test_crossed_book_returns_none(self):
        from bot.risk.checks import _get_best_bid_ask
        # bid > ask → crossed, geçersiz
        ob = self._make_ob(bids=[0.60], asks=[0.50])
        best_bid, best_ask = _get_best_bid_ask(ob)
        assert best_bid is None
        assert best_ask is None

    def test_empty_orderbook(self):
        from bot.risk.checks import _get_best_bid_ask
        ob = {"ok": True, "orderbook": {"bids": [], "asks": []}}
        best_bid, best_ask = _get_best_bid_ask(ob)
        assert best_bid is None
        assert best_ask is None

    def test_mid_price(self):
        from bot.risk.checks import get_mid_price
        ob = self._make_ob(bids=[0.40, 0.43, 0.45], asks=[0.55, 0.52, 0.50])
        mid = get_mid_price(ob)
        assert mid == pytest.approx(0.475, abs=0.001)

    def test_spread_quality_pass(self):
        from bot.risk.checks import check_spread_quality
        ob = self._make_ob(bids=[0.48], asks=[0.52])
        ok, spread = check_spread_quality(ob)
        assert ok is True
        assert spread == pytest.approx(0.04, abs=0.001)

    def test_spread_quality_fail(self):
        from bot.risk.checks import check_spread_quality
        import os
        os.environ["MAX_SPREAD"] = "0.05"
        ob = self._make_ob(bids=[0.30], asks=[0.70])
        ok, spread = check_spread_quality(ob)
        assert ok is False

    def test_validate_buy_price_ok(self):
        from bot.risk.checks import validate_order_price
        ob = self._make_ob(bids=[0.48], asks=[0.52])
        ok, reason = validate_order_price(0.52, ob, "buy")
        assert ok is True, reason

    def test_validate_sell_price_too_low(self):
        from bot.risk.checks import validate_order_price
        ob = self._make_ob(bids=[0.48], asks=[0.52])
        # Satış fiyatı best_bid'den çok düşük
        ok, reason = validate_order_price(0.30, ob, "sell")
        assert ok is False
        assert "too low" in reason


# ─────────────────────────────────────────────
# BUG-04: Paper ledger initial cash
# ─────────────────────────────────────────────

class TestPaperLedgerInitialCash:

    def test_initial_cash_from_env(self, monkeypatch):
        import os
        monkeypatch.setenv("PAPER_INITIAL_CASH", "25.0")

        from bot.execution.paper_ledger import _default_initial_cash
        assert _default_initial_cash() == 25.0

    def test_fallback_cash(self, monkeypatch):
        monkeypatch.delenv("PAPER_INITIAL_CASH", raising=False)
        monkeypatch.delenv("PAPER_CAPITAL", raising=False)

        from bot.execution.paper_ledger import _default_initial_cash
        assert _default_initial_cash() == 100.0

    def test_reserve_and_release(self):
        """Reserved cash mekanizması."""
        from bot.execution.paper_ledger import PaperLedger
        import unittest.mock as mock

        with mock.patch.object(PaperLedger, 'load_from_redis', return_value=None), \
             mock.patch.object(PaperLedger, 'save_to_redis', return_value=None):

            ledger = PaperLedger.__new__(PaperLedger)
            ledger.cash = 100.0
            ledger.positions = {}
            ledger.closed_positions = []
            ledger.total_pnl = 0.0
            ledger._reserved = {}

            # Rezerve et
            ok = ledger.reserve_cash(30.0, "order_001")
            assert ok is True
            assert ledger.cash == pytest.approx(70.0)
            assert ledger._reserved["order_001"] == 30.0

            # İptal et (nakit iade)
            returned = ledger.cancel_reserved("order_001")
            assert returned == 30.0
            assert ledger.cash == pytest.approx(100.0)
            assert "order_001" not in ledger._reserved

    def test_reserve_insufficient_cash(self):
        from bot.execution.paper_ledger import PaperLedger
        import unittest.mock as mock

        with mock.patch.object(PaperLedger, 'load_from_redis', return_value=None), \
             mock.patch.object(PaperLedger, 'save_to_redis', return_value=None):

            ledger = PaperLedger.__new__(PaperLedger)
            ledger.cash = 10.0
            ledger._reserved = {}

            ok = ledger.reserve_cash(50.0, "order_002")
            assert ok is False
            assert ledger.cash == 10.0  # değişmemeli


# ─────────────────────────────────────────────
# BUG-01: Order tracker fill logic
# ─────────────────────────────────────────────

class TestOrderTrackerPaperFills:

    def _make_tracker(self):
        from bot.execution.order_tracker import OrderTracker
        import unittest.mock as mock

        tracker = OrderTracker.__new__(OrderTracker)
        tracker._orders = {}
        # Redis mock
        tracker.redis = mock.MagicMock()
        tracker.redis.get.return_value = None
        return tracker

    def test_buy_fills_when_price_drops_to_limit(self):
        from bot.execution.order_tracker import TrackedOrder, OrderStatus
        tracker = self._make_tracker()

        order = TrackedOrder(
            order_id="test_buy_001",
            token_id="token_A",
            side="buy",
            limit_price=0.50,
            qty=10.0,
            mode="paper",
            placed_at=time.time(),
        )
        tracker._orders[order.order_id] = order

        # Fiyat limit'e düştü → fill
        fills = tracker.check_fills_paper({"token_A": 0.49})
        assert len(fills) == 1
        assert fills[0].token_id == "token_A"
        assert fills[0].side == "buy"
        assert order.status == OrderStatus.FILLED

    def test_sell_fills_when_price_rises_to_limit(self):
        from bot.execution.order_tracker import TrackedOrder, OrderStatus
        tracker = self._make_tracker()

        order = TrackedOrder(
            order_id="test_sell_001",
            token_id="token_B",
            side="sell",
            limit_price=0.60,
            qty=5.0,
            mode="paper",
            placed_at=time.time(),
        )
        tracker._orders[order.order_id] = order

        # Fiyat hedef'e ulaştı → fill
        fills = tracker.check_fills_paper({"token_B": 0.61})
        assert len(fills) == 1
        assert fills[0].side == "sell"
        assert order.status == OrderStatus.FILLED

    def test_no_fill_when_price_not_reached(self):
        from bot.execution.order_tracker import TrackedOrder, OrderStatus
        tracker = self._make_tracker()

        order = TrackedOrder(
            order_id="test_no_fill",
            token_id="token_C",
            side="buy",
            limit_price=0.45,
            qty=10.0,
            mode="paper",
            placed_at=time.time(),
        )
        tracker._orders[order.order_id] = order

        # Fiyat henüz limit'e ulaşmadı
        fills = tracker.check_fills_paper({"token_C": 0.50})
        assert len(fills) == 0
        assert order.status == OrderStatus.OPEN

    def test_order_expires_after_timeout(self):
        from bot.execution.order_tracker import TrackedOrder, OrderStatus
        tracker = self._make_tracker()

        order = TrackedOrder(
            order_id="test_expire",
            token_id="token_D",
            side="buy",
            limit_price=0.45,
            qty=10.0,
            mode="paper",
            placed_at=time.time() - 400,  # 400 saniye önce
        )
        tracker._orders[order.order_id] = order

        fills = tracker.check_fills_paper({"token_D": 0.50}, max_order_age_s=300)
        assert len(fills) == 0
        assert order.status == OrderStatus.EXPIRED


# ─────────────────────────────────────────────
# Entegrasyon: checks + position_manager
# ─────────────────────────────────────────────

class TestPositionManagerPriceFetch:

    def test_exit_condition_take_profit(self):
        from bot.core.position_manager import PositionManager

        pm = PositionManager()
        pm.tp_pct = 0.05   # %5
        pm.sl_pct = 0.10
        pm.exit_on_timeout = False

        positions = {
            "token_X": {
                "qty": 10.0,
                "avg_price": 0.50,
                "opened_at": time.time(),
            }
        }
        # Fiyat %6 arttı → TP tetiklemeli
        signals = pm.check_exit_conditions(positions, current_prices={"token_X": 0.53})
        assert len(signals) == 1
        assert signals[0]["reason"] == "take_profit"

    def test_exit_condition_stop_loss(self):
        from bot.core.position_manager import PositionManager

        pm = PositionManager()
        pm.tp_pct = 0.05
        pm.sl_pct = 0.05   # %5
        pm.exit_on_timeout = False

        positions = {
            "token_Y": {
                "qty": 5.0,
                "avg_price": 0.50,
                "opened_at": time.time(),
            }
        }
        # Fiyat %6 düştü → SL tetiklemeli
        signals = pm.check_exit_conditions(positions, current_prices={"token_Y": 0.47})
        assert len(signals) == 1
        assert signals[0]["reason"] == "stop_loss"

    def test_no_exit_within_band(self):
        from bot.core.position_manager import PositionManager

        pm = PositionManager()
        pm.tp_pct = 0.05
        pm.sl_pct = 0.05
        pm.exit_on_timeout = False

        positions = {
            "token_Z": {
                "qty": 5.0,
                "avg_price": 0.50,
                "opened_at": time.time(),
            }
        }
        # Fiyat ±%2 aralığında → hiç exit yok
        signals = pm.check_exit_conditions(positions, current_prices={"token_Z": 0.51})
        assert len(signals) == 0

    def test_invalid_position_skipped(self):
        """avg_price=0 olan pozisyonlar skip edilmeli."""
        from bot.core.position_manager import PositionManager

        pm = PositionManager()
        pm.exit_on_timeout = False

        positions = {
            "bad_pos": {"qty": 10.0, "avg_price": 0, "opened_at": time.time()},
        }
        signals = pm.check_exit_conditions(positions, current_prices={"bad_pos": 0.50})
        assert len(signals) == 0
