# agent/bot/signals/__init__.py
"""
Signals modülü — Çok katmanlı sinyal motoru.

Modüller:
  news.py        — Tavily haber sinyali
  momentum.py    — Orderbook imbalance + spread + derinlik
  resolution.py  — Deadline proximity + market kategorisi
"""
from .news import get_news_signal, NewsSignal
from .momentum import get_momentum_signal, MomentumSignal
from .resolution import get_resolution_signal, ResolutionSignal

__all__ = [
    "get_news_signal", "NewsSignal",
    "get_momentum_signal", "MomentumSignal",
    "get_resolution_signal", "ResolutionSignal",
]
