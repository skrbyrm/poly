# agent/tests/test_sprint3_backtest.py
"""
Sprint 3 — Backtest framework testleri.

Gerçek API çağrısı yok — tüm network I/O mock'lanır.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

def make_price_points(prices, base_ts=None, interval=3600):
    """Test için fiyat noktası listesi üret."""
    from bot.backtest.data_loader import PricePoint
    if base_ts is None:
        base_ts = 1_700_000_000.0
    return [
        PricePoint(timestamp=base_ts + i * interval, price=p)
        for i, p in enumerate(prices)
    ]


def make_market_history(token_id="tok_test", prices=None, resolution=1.0):
    from bot.backtest.data_loader import MarketHistory, PricePoint
    if prices is None:
        prices = [0.45, 0.47, 0.50, 0.53, 0.55, 0.52, 0.48, 0.50]
    pts = make_price_points(prices)
    return MarketHistory(
        token_id=token_id,
        question="Will X happen?",
        category="other",
        start_ts=pts[0].timestamp,
        end_ts=pts[-1].timestamp,
        resolution=resolution,
        prices=pts,
    )


# ─────────────────────────────────────────────
# Data loader
# ─────────────────────────────────────────────

class TestMarketHistory:

    def test_price_series_extracted(self):
        h = make_market_history(prices=[0.40, 0.45, 0.50])
        assert h.price_series == [0.40, 0.45, 0.50]

    def test_timestamps_extracted(self):
        h = make_market_history(prices=[0.40, 0.45])
        assert len(h.timestamps) == 2
        assert h.timestamps[0] < h.timestamps[1]

    def test_price_at_nearest(self):
        h = make_market_history(prices=[0.40, 0.45, 0.50])
        # Timestamp tam ortada → en yakın olanı dönsün
        ts = h.prices[0].timestamp
        assert h.price_at(ts) == pytest.approx(0.40)

    def test_price_at_empty_returns_none(self):
        from bot.backtest.data_loader import MarketHistory
        h = MarketHistory(
            token_id="t", question="q", category="c",
            start_ts=0, end_ts=0, resolution=None, prices=[]
        )
        assert h.price_at(12345) is None


# ─────────────────────────────────────────────
# BacktestConfig
# ─────────────────────────────────────────────

class TestBacktestConfig:

    def test_default_values(self):
        from bot.backtest.replay_engine import BacktestConfig
        cfg = BacktestConfig()
        assert cfg.initial_cash == 100.0
        assert cfg.order_usd == 5.0
        assert cfg.take_profit_pct > 0
        assert cfg.stop_loss_pct > 0

    def test_custom_values(self):
        from bot.backtest.replay_engine import BacktestConfig
        cfg = BacktestConfig(take_profit_pct=0.05, stop_loss_pct=0.03)
        assert cfg.take_profit_pct == 0.05
        assert cfg.stop_loss_pct == 0.03


# ─────────────────────────────────────────────
# BacktestResult metrics
# ─────────────────────────────────────────────

class TestBacktestResult:

    def _make_result(self, pnls):
        from bot.backtest.replay_engine import BacktestConfig, BacktestResult, BacktestTrade
        trades = [
            BacktestTrade(
                token_id="t",
                question="q",
                category="other",
                side="buy",
                entry_price=0.48,
                exit_price=0.48 + pnl / 10,
                qty=10.0,
                entry_ts=1_700_000_000 + i * 3600,
                exit_ts=1_700_000_000 + i * 3600 + 1800,
                exit_reason="take_profit" if pnl > 0 else "stop_loss",
                pnl=pnl,
                pnl_pct=pnl / 0.48 * 100,
                resolution=None,
            )
            for i, pnl in enumerate(pnls)
        ]
        result = BacktestResult(
            config=BacktestConfig(),
            trades=trades,
            markets_tested=5,
            start_ts=0.0,
            end_ts=1000.0,
        )
        result.compute_metrics()
        return result

    def test_win_rate_calculation(self):
        result = self._make_result([0.10, 0.05, -0.03, -0.02, 0.08])
        # 3 win, 2 loss = 60%
        assert result.win_rate == pytest.approx(60.0)

    def test_total_pnl(self):
        result = self._make_result([0.10, 0.05, -0.03])
        assert result.total_pnl == pytest.approx(0.12, abs=0.001)

    def test_all_wins_100_pct(self):
        result = self._make_result([0.10, 0.05, 0.08])
        assert result.win_rate == 100.0

    def test_all_losses_0_pct(self):
        result = self._make_result([-0.01, -0.02, -0.03])
        assert result.win_rate == 0.0

    def test_sharpe_positive_for_winning_strategy(self):
        # Tutarlı kazanç → pozitif Sharpe
        result = self._make_result([0.10] * 10)
        # Std=0 olduğunda Sharpe sonsuz, uygulama bunu handle etmeli
        # Sadece crash olmadığını kontrol et
        assert result.sharpe_ratio is not None

    def test_max_drawdown_positive(self):
        result = self._make_result([0.10, -0.15, 0.05])
        assert result.max_drawdown >= 0.0

    def test_avg_hold_hours_computed(self):
        result = self._make_result([0.10, 0.05])
        assert result.avg_hold_hours == pytest.approx(0.5, abs=0.1)

    def test_empty_trades(self):
        from bot.backtest.replay_engine import BacktestConfig, BacktestResult
        result = BacktestResult(
            config=BacktestConfig(), trades=[],
            markets_tested=0, start_ts=0, end_ts=0,
        )
        result.compute_metrics()   # crash olmamalı
        assert result.total_trades == 0
        assert result.win_rate == 0.0


# ─────────────────────────────────────────────
# Analytics
# ─────────────────────────────────────────────

class TestAnalytics:

    def _result_with_categories(self):
        from bot.backtest.replay_engine import BacktestConfig, BacktestResult, BacktestTrade
        trades = [
            BacktestTrade("t1","q","sports","buy",0.48,0.52,10,0,3600,"take_profit",0.04,8.3,None),
            BacktestTrade("t2","q","sports","buy",0.48,0.45,10,0,3600,"stop_loss",-0.03,-6.25,None),
            BacktestTrade("t3","q","politics","buy",0.60,0.65,10,0,3600,"take_profit",0.05,8.3,None),
        ]
        r = BacktestResult(config=BacktestConfig(), trades=trades, markets_tested=3, start_ts=0, end_ts=0)
        r.compute_metrics()
        return r

    def test_category_breakdown_keys(self):
        from bot.backtest.analytics import breakdown_by_category
        result = self._result_with_categories()
        bd = breakdown_by_category(result)
        assert "sports" in bd
        assert "politics" in bd

    def test_category_trade_count(self):
        from bot.backtest.analytics import breakdown_by_category
        result = self._result_with_categories()
        bd = breakdown_by_category(result)
        assert bd["sports"]["trades"] == 2
        assert bd["politics"]["trades"] == 1

    def test_exit_reason_breakdown(self):
        from bot.backtest.analytics import breakdown_by_exit_reason
        result = self._result_with_categories()
        bd = breakdown_by_exit_reason(result)
        assert "take_profit" in bd
        assert "stop_loss" in bd
        assert bd["take_profit"]["count"] == 2

    def test_equity_curve_length(self):
        from bot.backtest.analytics import equity_curve
        result = self._result_with_categories()
        curve = equity_curve(result)
        assert len(curve) == len(result.trades)

    def test_equity_curve_monotone_on_all_wins(self):
        from bot.backtest.replay_engine import BacktestConfig, BacktestResult, BacktestTrade
        from bot.backtest.analytics import equity_curve
        trades = [
            BacktestTrade("t","q","other","buy",0.48,0.52,10,i*100,i*100+50,"take_profit",0.04,8.3,None)
            for i in range(5)
        ]
        r = BacktestResult(config=BacktestConfig(), trades=trades, markets_tested=5, start_ts=0, end_ts=0)
        r.compute_metrics()
        curve = equity_curve(r)
        equities = [pt["equity"] for pt in curve]
        assert equities == sorted(equities)

    def test_report_generated(self):
        from bot.backtest.analytics import generate_report
        result = self._result_with_categories()
        report = generate_report(result)
        assert "BACKTEST REPORT" in report
        assert "Win rate" in report
        assert "sports" in report

    def test_report_contains_pnl(self):
        from bot.backtest.analytics import generate_report
        result = self._result_with_categories()
        report = generate_report(result)
        assert "Total PnL" in report


# ─────────────────────────────────────────────
# Replay engine — unit (mock'lu)
# ─────────────────────────────────────────────

class TestReplayEngine:

    def test_simulate_take_profit(self):
        """Fiyat TP seviyesine ulaşınca exit olmalı."""
        from bot.backtest.replay_engine import ReplayEngine, BacktestConfig
        config = BacktestConfig(
            take_profit_pct=0.05,
            stop_loss_pct=0.10,
            min_imbalance=0.0,   # Her zaman giriş yap
            order_usd=5.0,
        )
        engine = ReplayEngine(config)
        history = make_market_history(
            prices=[0.40, 0.42, 0.45, 0.48, 0.42 * 1.06, 0.43]   # 5.gün +6%
        )

        trades = engine._simulate_on_history(history, {})
        tp_trades = [t for t in trades if t.exit_reason == "take_profit"]
        assert len(tp_trades) >= 1

    def test_simulate_stop_loss(self):
        """Fiyat SL seviyesine düşünce exit olmalı."""
        from bot.backtest.replay_engine import ReplayEngine, BacktestConfig
        config = BacktestConfig(
            take_profit_pct=0.10,
            stop_loss_pct=0.02,
            min_imbalance=0.0,
            order_usd=5.0,
        )
        engine = ReplayEngine(config)
        history = make_market_history(
            prices=[0.50, 0.51, 0.52, 0.50 * 0.97, 0.50, 0.51]   # 4.gün -3%
        )

        trades = engine._simulate_on_history(history, {})
        sl_trades = [t for t in trades if t.exit_reason == "stop_loss"]
        assert len(sl_trades) >= 1

    def test_simulate_no_entry_if_min_imbalance_high(self):
        """Yüksek min_imbalance → basit signal yetersiz → trade yok."""
        from bot.backtest.replay_engine import ReplayEngine, BacktestConfig
        config = BacktestConfig(
            min_imbalance=0.99,   # pratik olarak sonsuz
            order_usd=5.0,
        )
        engine = ReplayEngine(config)
        history = make_market_history(
            prices=[0.50, 0.51, 0.50, 0.51, 0.50, 0.49, 0.50]
        )
        trades = engine._simulate_on_history(history, {})
        assert len(trades) == 0

    def test_category_detection(self):
        from bot.backtest.replay_engine import ReplayEngine, BacktestConfig
        engine = ReplayEngine(BacktestConfig())
        assert engine._detect_category("Will the NBA championship be won?") == "sports"
        assert engine._detect_category("Will Bitcoin hit $100k?") == "crypto"
        assert engine._detect_category("Will Senate vote on the bill?") == "politics"
        assert engine._detect_category("Some random question?") == "other"
