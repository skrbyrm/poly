# agent/bot/execution/__init__.py
"""
Execution modülü - Paper ve Live trading execution
"""
from .paper_ledger import LEDGER, load_ledger_from_redis
from .paper_exec import place_order as paper_place_order
from .live_ledger import LIVE_LEDGER
from .live_exec import (
    place_order as live_place_order,
    cancel_order as live_cancel_order,
    get_open_orders as live_get_open_orders,
    get_balance as live_get_balance
)
from .order_router import get_order_router
from .slippage_control import get_slippage_controller

__all__ = [
    # Paper
    "LEDGER",
    "load_ledger_from_redis",
    "paper_place_order",
    # Live
    "LIVE_LEDGER",
    "live_place_order",
    "live_cancel_order",
    "live_get_open_orders",
    "live_get_balance",
    # Routing & Slippage
    "get_order_router",
    "get_slippage_controller",
]
