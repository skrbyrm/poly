# agent/bot/backtest/analytics.py
"""
Backtest Analytics — Sonuçları analiz et, kaydet, raporla.

Düzeltmeler:
  - DATABASE_URL artık POSTGRES_* env var'larından otomatik construct ediliyor
  - grid_search içinde çift compute_metrics() kaldırıldı
"""
import json
import statistics
from dataclasses import asdict
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from .replay_engine import BacktestResult, BacktestTrade, BacktestConfig
from ..monitoring.logger import get_logger

logger = get_logger("backtest.analytics")


# ─────────────────────────────────────────────
# DB URL helper
# ─────────────────────────────────────────────

def _get_database_url() -> Optional[str]:
    """
    DATABASE_URL'yi önce env'den, yoksa POSTGRES_* parçalarından üret.

    compose.yaml'da agent servisine DATABASE_URL set edilmişse onu kullan.
    Yoksa POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB / POSTGRES_HOST'tan
    postgresql://user:password@host:5432/db şeklinde inşa et.
    """
    import os

    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url

    user     = os.getenv("POSTGRES_USER", "polymarket")
    password = os.getenv("POSTGRES_PASSWORD", "polymarket")
    db       = os.getenv("POSTGRES_DB", "polymarket")
    # Docker Compose içinde servis adı "postgres" host olarak kullanılır
    host     = os.getenv("POSTGRES_HOST", "postgres")
    port     = os.getenv("POSTGRES_PORT", "5432")

    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


# ─────────────────────────────────────────────
# Breakdown analizleri
# ─────────────────────────────────────────────

def breakdown_by_category(result: BacktestResult) -> Dict[str, Dict[str, Any]]:
    """Kategori bazlı performans."""
    groups: Dict[str, List[BacktestTrade]] = {}
    for trade in result.trades:
        groups.setdefault(trade.category, []).append(trade)

    out = {}
    for cat, trades in groups.items():
        pnls = [t.pnl for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        out[cat] = {
            "trades":      len(trades),
            "win_rate":    round(wins / len(trades) * 100, 1),
            "total_pnl":   round(sum(pnls), 4),
            "avg_pnl":     round(statistics.mean(pnls), 4) if pnls else 0,
            "best_trade":  round(max(pnls), 4) if pnls else 0,
            "worst_trade": round(min(pnls), 4) if pnls else 0,
        }
    return out


def breakdown_by_exit_reason(result: BacktestResult) -> Dict[str, Dict[str, Any]]:
    """Çıkış nedeni bazlı istatistikler."""
    groups: Dict[str, List[BacktestTrade]] = {}
    for trade in result.trades:
        groups.setdefault(trade.exit_reason, []).append(trade)

    out = {}
    for reason, trades in groups.items():
        pnls = [t.pnl for t in trades]
        out[reason] = {
            "count":          len(trades),
            "total_pnl":      round(sum(pnls), 4),
            "avg_pnl":        round(statistics.mean(pnls), 4) if pnls else 0,
            "pct_of_trades":  round(len(trades) / len(result.trades) * 100, 1)
                              if result.trades else 0,
        }
    return out


def equity_curve(result: BacktestResult) -> List[Dict[str, Any]]:
    """Zaman bazlı equity eğrisi."""
    if not result.trades:
        return []

    equity = result.config.initial_cash
    curve  = []

    for trade in sorted(result.trades, key=lambda t: t.entry_ts):
        equity += trade.pnl
        curve.append({
            "ts":       trade.exit_ts,
            "equity":   round(equity, 4),
            "pnl":      trade.pnl,
            "category": trade.category,
        })

    return curve


# ─────────────────────────────────────────────
# Parametre optimizasyonu
# ─────────────────────────────────────────────

def grid_search(
    days_back: int = 14,
    max_markets: int = 30,
) -> List[Dict[str, Any]]:
    """
    TP/SL/imbalance parametrelerini grid search ile optimize et.

    Test kombinasyonları (3×3×3 = 27):
      take_profit:   [0.02, 0.03, 0.05]
      stop_loss:     [0.01, 0.02, 0.03]
      min_imbalance: [0.20, 0.30, 0.40]
    """
    from .replay_engine import ReplayEngine

    tp_values  = [0.02, 0.03, 0.05]
    sl_values  = [0.01, 0.02, 0.03]
    imb_values = [0.20, 0.30, 0.40]

    results = []

    for tp in tp_values:
        for sl in sl_values:
            for imb in imb_values:
                config = BacktestConfig(
                    take_profit_pct=tp,
                    stop_loss_pct=sl,
                    min_imbalance=imb,
                )
                engine = ReplayEngine(config)
                # run() içinde compute_metrics() zaten çağrılıyor
                result = engine.run(days_back=days_back, max_markets=max_markets)

                results.append({
                    "take_profit":   tp,
                    "stop_loss":     sl,
                    "min_imbalance": imb,
                    "trades":        result.total_trades,
                    "win_rate":      result.win_rate,
                    "total_pnl":     result.total_pnl,
                    "sharpe":        result.sharpe_ratio,
                    "max_drawdown":  result.max_drawdown,
                })

                logger.info(
                    "Grid search step",
                    tp=tp, sl=sl, imb=imb,
                    trades=result.total_trades,
                    win_rate=result.win_rate,
                    sharpe=result.sharpe_ratio,
                )

    results.sort(key=lambda x: x.get("sharpe", -99), reverse=True)
    return results


# ─────────────────────────────────────────────
# Rapor üretimi
# ─────────────────────────────────────────────

def generate_report(result: BacktestResult) -> str:
    """İnsan okunabilir backtest raporu."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cfg = result.config

    cat_breakdown  = breakdown_by_category(result)
    exit_breakdown = breakdown_by_exit_reason(result)

    lines = [
        "=" * 60,
        f"BACKTEST REPORT — {now}",
        "=" * 60,
        "",
        "── CONFIG ──────────────────────────────────",
        f"  Initial cash:    ${cfg.initial_cash:.2f}",
        f"  Order size:      ${cfg.order_usd:.2f}",
        f"  Take profit:     {cfg.take_profit_pct*100:.1f}%",
        f"  Stop loss:       {cfg.stop_loss_pct*100:.1f}%",
        f"  Max hold steps:  {cfg.max_hold_steps}",
        f"  Min imbalance:   {cfg.min_imbalance:.2f}",
        "",
        "── RESULTS ─────────────────────────────────",
        f"  Markets tested:  {result.markets_tested}",
        f"  Total trades:    {result.total_trades}",
        f"  Win rate:        {result.win_rate:.1f}%",
        f"  Total PnL:       ${result.total_pnl:+.4f}",
        f"  Sharpe ratio:    {result.sharpe_ratio:.2f}",
        f"  Max drawdown:    ${result.max_drawdown:.4f}",
        f"  Avg hold time:   {result.avg_hold_hours:.1f}h",
        "",
    ]

    if cat_breakdown:
        lines.append("── BY CATEGORY ─────────────────────────────")
        for cat, stats in sorted(cat_breakdown.items()):
            lines.append(
                f"  {cat:12s}  trades={stats['trades']:3d}  "
                f"win={stats['win_rate']:4.1f}%  "
                f"pnl={stats['total_pnl']:+.4f}"
            )
        lines.append("")

    if exit_breakdown:
        lines.append("── BY EXIT REASON ──────────────────────────")
        for reason, stats in sorted(exit_breakdown.items()):
            lines.append(
                f"  {reason:15s}  n={stats['count']:3d}  "
                f"avg_pnl={stats['avg_pnl']:+.4f}  "
                f"({stats['pct_of_trades']:.0f}%)"
            )
        lines.append("")

    if result.trades:
        sorted_by_pnl = sorted(result.trades, key=lambda t: t.pnl, reverse=True)
        lines.append("── TOP 3 TRADES ─────────────────────────────")
        for t in sorted_by_pnl[:3]:
            lines.append(
                f"  {t.pnl:+.4f}  {t.question[:40]}  [{t.exit_reason}]"
            )
        lines.append("")
        lines.append("── WORST 3 TRADES ───────────────────────────")
        for t in sorted_by_pnl[-3:]:
            lines.append(
                f"  {t.pnl:+.4f}  {t.question[:40]}  [{t.exit_reason}]"
            )

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


# ─────────────────────────────────────────────
# PostgreSQL kayıt
# ─────────────────────────────────────────────

def save_result_to_db(result: BacktestResult, run_name: str = "") -> bool:
    """
    Backtest sonuçlarını PostgreSQL'e kaydet.

    Tablo: backtest_runs   (özet)
    Tablo: backtest_trades (detay)

    DATABASE_URL yoksa POSTGRES_* env var'larından inşa edilir.
    """
    db_url = _get_database_url()
    if not db_url:
        logger.warning("No database URL available, skipping DB save")
        return False

    try:
        import psycopg2

        conn = psycopg2.connect(db_url)
        cur  = conn.cursor()

        # Tablo oluştur (yoksa)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id           SERIAL PRIMARY KEY,
                run_name     TEXT,
                run_at       TIMESTAMPTZ DEFAULT NOW(),
                config       JSONB,
                markets      INT,
                total_trades INT,
                win_rate     FLOAT,
                total_pnl    FLOAT,
                sharpe       FLOAT,
                max_drawdown FLOAT,
                avg_hold_h   FLOAT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id          SERIAL PRIMARY KEY,
                run_id      INT REFERENCES backtest_runs(id),
                token_id    TEXT,
                question    TEXT,
                category    TEXT,
                side        TEXT,
                entry_price FLOAT,
                exit_price  FLOAT,
                qty         FLOAT,
                entry_ts    FLOAT,
                exit_ts     FLOAT,
                exit_reason TEXT,
                pnl         FLOAT,
                pnl_pct     FLOAT
            )
        """)

        # Run kaydı
        cur.execute("""
            INSERT INTO backtest_runs
            (run_name, config, markets, total_trades, win_rate, total_pnl,
             sharpe, max_drawdown, avg_hold_h)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            run_name,
            json.dumps(asdict(result.config)),
            result.markets_tested,
            result.total_trades,
            result.win_rate,
            result.total_pnl,
            result.sharpe_ratio,
            result.max_drawdown,
            result.avg_hold_hours,
        ))

        run_id = cur.fetchone()[0]

        # Trade kayıtları
        for t in result.trades:
            cur.execute("""
                INSERT INTO backtest_trades
                (run_id, token_id, question, category, side,
                 entry_price, exit_price, qty, entry_ts, exit_ts,
                 exit_reason, pnl, pnl_pct)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                run_id, t.token_id, t.question, t.category, t.side,
                t.entry_price, t.exit_price, t.qty, t.entry_ts, t.exit_ts,
                t.exit_reason, t.pnl, t.pnl_pct,
            ))

        conn.commit()
        cur.close()
        conn.close()

        logger.info("Backtest saved to DB", run_id=run_id, trades=len(result.trades))
        return True

    except ImportError:
        logger.warning("psycopg2 not installed, skipping DB save")
        return False
    except Exception as e:
        logger.error("DB save failed", error=str(e))
        return False
