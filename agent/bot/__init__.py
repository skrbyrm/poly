# agent/bot/__init__.py
"""
Polymarket AI Trading Agent - Full Stack
"""
from .utils import patch_pyclob_hmac

# HMAC patch'i otomatik uygula
patch_pyclob_hmac()

__version__ = "2.0.0"
__all__ = []
