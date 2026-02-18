#!/usr/bin/env python3
# scripts/backtest.py
"""
Backtest CLI — Polymarket geçmiş veri üzerinde strateji testi.

Kullanım:
  # Basit çalıştır (son 14 gün, 30 market)
  python scripts/backtest.py

  # Özel parametreler
  python scripts/backtest.py --days 30 --markets 50 --tp 0.03 --sl 0.02

  # Grid search (parametre optimizasyonu)
  python scripts/backtest.py --optimize --days 7 --markets 10

  # Sonucu API üzerinden çalıştır
  curl -X POST http://localhost:8080/backtest/run \
       -H "Content-Type: application/json" \
       -d '{"days_back": 14, "max_markets": 30}'
"""
import sys
import os
import argparse
import json

# agent klasörünü Python path'e ekle
AGENT_DIR = os.path.join(os.path.dirname(__file__), '..', 'agent')
sys.path.insert(0, AGENT_DIR)

# .env yükle (varsa)
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"[ENV] Loaded: {env_path}")
except ImportError:
    pass


def run_backtest(
    days_back: int = 14,
    max_markets: int = 30,
    initial_cash: float = 100.0,
    order_usd: float = 5.0,
    take_profit: float = 0.03,
    stop_loss: float = 0.02,
    max_hold_steps: int = 12,
    min_imbalance: float = 0.30,
    save_db: bool = True,
    run_name: str = "",
    verbose: bool = True,
) -> dict:
    """
    Backtest çalıştır ve sonuç dict döndür.
    """
    from bot.backtest.replay_engine import BacktestConfig, ReplayEngine
    from bot.backtest.analytics import (
        generate_report,
        breakdown_by_category,
        breakdown_by_exit_reason,
        equity_curve,
        save_result_to_db,
    )

    if verbose:
        print(f"\n{'='*60}")
        print(f"BACKTEST PARAMETERS")
        print(f"{'='*60}")
        print(f"  Days back:       {days_back}")
        print(f"  Max markets:     {max_markets}")
        print(f"  Initial cash:    ${initial_cash:.2f}")
        print(f"  Order size:      ${order_usd:.2f}")
        print(f"  Take profit:     {take_profit*100:.1f}%")
        print(f"  Stop loss:       {stop_loss*100:.1f}%")
        print(f"  Max hold steps:  {max_hold_steps}")
        print(f"  Min imbalance:   {min_imbalance:.2f}")
        print(f"{'='*60}\n")

    config = BacktestConfig(
        initial_cash=initial_cash,
        order_usd=order_usd,
        take_profit_pct=take_profit,
        stop_loss_pct=stop_loss,
        max_hold_steps=max_hold_steps,
        min_imbalance=min_imbalance,
    )

    engine = ReplayEngine(config)

    print(f"[BACKTEST] Fetching resolved markets (last {days_back} days)...")
    result = engine.run(days_back=days_back, max_markets=max_markets)

    if verbose:
        print(generate_report(result))

    if save_db and result.total_trades > 0:
        name = run_name or f"cli_{days_back}d_{max_markets}m"
        saved = save_result_to_db(result, run_name=name)
        if verbose:
            status = "✓ Saved to PostgreSQL" if saved else "⚠ DB save skipped (check connection)"
            print(f"\n[DB] {status}")

    return {
        "markets_tested":  result.markets_tested,
        "total_trades":    result.total_trades,
        "win_rate":        result.win_rate,
        "total_pnl":       result.total_pnl,
        "sharpe_ratio":    result.sharpe_ratio,
        "max_drawdown":    result.max_drawdown,
        "avg_hold_hours":  result.avg_hold_hours,
        "by_category":     breakdown_by_category(result),
        "by_exit_reason":  breakdown_by_exit_reason(result),
    }


def run_optimize(
    days_back: int = 7,
    max_markets: int = 10,
    verbose: bool = True,
) -> list:
    """
    Grid search ile parametre optimizasyonu.
    """
    from bot.backtest.analytics import grid_search

    if verbose:
        print(f"\n{'='*60}")
        print(f"GRID SEARCH OPTIMIZATION")
        print(f"  Days back:    {days_back}")
        print(f"  Max markets:  {max_markets}")
        print(f"  Combinations: 27 (3×3×3)")
        print(f"{'='*60}\n")

    results = grid_search(days_back=days_back, max_markets=max_markets)

    if verbose and results:
        print(f"\n{'='*60}")
        print(f"TOP 5 PARAMETER COMBINATIONS")
        print(f"{'='*60}")
        for i, r in enumerate(results[:5], 1):
            print(
                f"  #{i}  TP={r['take_profit']:.2f}  SL={r['stop_loss']:.2f}  "
                f"Imb={r['min_imbalance']:.2f}  "
                f"→ Sharpe={r['sharpe']:.2f}  WR={r['win_rate']:.1f}%  "
                f"PnL=${r['total_pnl']:+.4f}"
            )

        best = results[0]
        print(f"\n{'='*60}")
        print(f"RECOMMENDED SETTINGS (.env)")
        print(f"{'='*60}")
        print(f"  TAKE_PROFIT={best['take_profit']:.2f}")
        print(f"  STOP_LOSS={best['stop_loss']:.2f}")
        print(f"  MIN_IMBALANCE={best['min_imbalance']:.2f}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Backtest CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument("--days",     type=int,   default=14,   help="Kaç gün geriye (default: 14)")
    parser.add_argument("--markets",  type=int,   default=30,   help="Kaç market (default: 30)")
    parser.add_argument("--cash",     type=float, default=100.0, help="Başlangıç bakiye USD (default: 100)")
    parser.add_argument("--order",    type=float, default=5.0,  help="Order büyüklüğü USD (default: 5)")
    parser.add_argument("--tp",       type=float, default=0.03, help="Take profit %% (default: 0.03)")
    parser.add_argument("--sl",       type=float, default=0.02, help="Stop loss %% (default: 0.02)")
    parser.add_argument("--hold",     type=int,   default=12,   help="Max hold adım sayısı (default: 12)")
    parser.add_argument("--imb",      type=float, default=0.30, help="Min imbalance (default: 0.30)")
    parser.add_argument("--name",     type=str,   default="",   help="Çalıştırma adı")
    parser.add_argument("--no-db",    action="store_true",      help="DB'ye kaydetme")
    parser.add_argument("--optimize", action="store_true",      help="Grid search modu")
    parser.add_argument("--json",     action="store_true",      help="Sonucu JSON olarak bas")

    args = parser.parse_args()

    if args.optimize:
        results = run_optimize(
            days_back=args.days,
            max_markets=args.markets,
            verbose=not args.json,
        )
        if args.json:
            print(json.dumps(results[:5], indent=2))
    else:
        result = run_backtest(
            days_back=args.days,
            max_markets=args.markets,
            initial_cash=args.cash,
            order_usd=args.order,
            take_profit=args.tp,
            stop_loss=args.sl,
            max_hold_steps=args.hold,
            min_imbalance=args.imb,
            save_db=not args.no_db,
            run_name=args.name,
            verbose=not args.json,
        )
        if args.json:
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
