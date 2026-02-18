# agent/bot/state.py
"""
Global agent state.

Sprint 4 değişiklikleri:
  - tick_error_count: art arda başarısız tick sayısı
  - last_error_ts: son hata timestamp'i
  - tick_count: toplam tick sayısı
  - record_tick_error() / record_tick_success() yardımcıları
"""
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentState:
    """Bot'un global runtime state'i."""

    trading_enabled:    bool  = False
    mode:               str   = "paper"   # "paper" | "live"
    markets:            List[str] = field(default_factory=list)
    last_error:         Optional[str]   = None
    metrics:            Dict[str, Any]  = field(default_factory=dict)
    address:            Optional[str]   = None

    # Trade streak
    consecutive_losses: int   = 0
    consecutive_wins:   int   = 0
    last_trade_timestamp: float = 0.0

    # Tick health (Sprint 4)
    tick_count:         int   = 0
    tick_error_count:   int   = 0          # art arda hatalı tick
    tick_total_errors:  int   = 0          # toplam hatalı tick
    last_error_ts:      float = 0.0        # son hata zamanı
    last_success_ts:    float = 0.0        # son başarılı tick zamanı

    def record_trade_result(self, pnl: float) -> None:
        """Trade sonucunu kaydet, streak'leri güncelle."""
        if pnl > 0:
            self.consecutive_wins  += 1
            self.consecutive_losses = 0
        elif pnl < 0:
            self.consecutive_losses += 1
            self.consecutive_wins   = 0

    def reset_streaks(self) -> None:
        self.consecutive_wins  = 0
        self.consecutive_losses = 0

    def record_tick_success(self) -> None:
        """Başarılı tick kaydet."""
        self.tick_count       += 1
        self.tick_error_count  = 0
        self.last_success_ts   = time.time()

    def record_tick_error(self, error: str) -> None:
        """Başarısız tick kaydet."""
        self.tick_count        += 1
        self.tick_error_count  += 1
        self.tick_total_errors += 1
        self.last_error         = error
        self.last_error_ts      = time.time()

    @property
    def is_healthy(self) -> bool:
        """Son 5 tick'in en az biri başarılıysa sağlıklı sayılır."""
        return self.tick_error_count < 5

    @property
    def seconds_since_last_success(self) -> Optional[float]:
        if self.last_success_ts == 0.0:
            return None
        return time.time() - self.last_success_ts


# Singleton
STATE = AgentState()
