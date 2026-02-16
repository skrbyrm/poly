# agent/bot/utils/__init__.py
"""
Utility modülleri - HMAC patch otomatik uygulanır
"""
from .hmac_patch import patch_pyclob_hmac, is_patched
from .validators import (
    validate_token_id,
    validate_price,
    validate_quantity,
    validate_side,
    sanitize_decision,
    validate_orderbook
)
from .retry import (
    exponential_backoff,
    retry_on_network_error,
    retry_on_api_error
)
from .cache import (
    get_redis_client,
    cache_with_ttl,
    invalidate_cache,
    get_cached,
    set_cached,
    increment_counter,
    get_counter
)

__all__ = [
    # HMAC
    "patch_pyclob_hmac",
    "is_patched",
    # Validators
    "validate_token_id",
    "validate_price",
    "validate_quantity",
    "validate_side",
    "sanitize_decision",
    "validate_orderbook",
    # Retry
    "exponential_backoff",
    "retry_on_network_error",
    "retry_on_api_error",
    # Cache
    "get_redis_client",
    "cache_with_ttl",
    "invalidate_cache",
    "get_cached",
    "set_cached",
    "increment_counter",
    "get_counter",
]

# HMAC patch'i otomatik uygula
patch_pyclob_hmac()
