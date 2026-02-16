# agent/bot/state.py
"""
Global agent state
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class AgentState:
    """Bot'un global state'i"""
    trading_enabled: bool = False
    mode: str = "paper"  # "paper" or "live"
    markets: List[str] = field(default_factory=list)
    last_error: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    address: Optional[str] = None
    
    # Runtime state
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    last_trade_timestamp: float = 0.0
    
    def record_trade_result(self, pnl: float) -> None:
        """Trade sonucunu kaydet ve streak'leri güncelle"""
        if pnl > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl < 0:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
    
    def reset_streaks(self) -> None:
        """Win/loss streak'lerini sıfırla"""
        self.consecutive_wins = 0
        self.consecutive_losses = 0

# Global state instance
STATE = AgentState()
