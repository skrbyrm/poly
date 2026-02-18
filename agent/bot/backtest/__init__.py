# agent/bot/backtest/__init__.py
"""
Backtest modülü — Geçmiş veri üzerinde strateji testi.

Modüller:
  data_loader.py   — Polymarket geçmiş fiyat verisi
  replay_engine.py — Strateji simülasyonu
  analytics.py     — Metrikler, rapor, DB kayıt, grid search
"""
from .data_loader import get_data_loader, MarketHistory, PricePoint
from .replay_engine import ReplayEngine, BacktestConfig, BacktestResult, BacktestTrade, create_replay_engine
from .analytics import generate_report, breakdown_by_category, grid_search

__all__ = [
    "get_data_loader", "MarketHistory", "PricePoint",
    "ReplayEngine", "BacktestConfig", "BacktestResult", "BacktestTrade", "create_replay_engine",
    "generate_report", "breakdown_by_category", "grid_search",
]
