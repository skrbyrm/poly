# agent/bot/utils/retry.py
"""
Exponential backoff retry mekanizması
"""
import time
import functools
from typing import Callable, Any, Optional, Type, Tuple

def exponential_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Exponential backoff decorator
    
    Args:
        max_retries: Maksimum deneme sayısı
        base_delay: İlk bekleme süresi (saniye)
        max_delay: Maksimum bekleme süresi (saniye)
        exceptions: Yakalanacak exception'lar
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        # Son deneme, exception'ı fırlat
                        raise
                    
                    # Exponential delay hesapla
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    
                    print(f"[RETRY] {func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}), "
                          f"retrying in {delay:.1f}s: {e}")
                    
                    time.sleep(delay)
            
            # Buraya normalde gelmemeli ama yine de
            if last_exception:
                raise last_exception
            
        return wrapper
    return decorator


def retry_on_network_error(func: Callable) -> Callable:
    """Network hatalarında retry yapan decorator"""
    import requests
    
    @exponential_backoff(
        max_retries=3,
        base_delay=2.0,
        max_delay=10.0,
        exceptions=(
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.HTTPError,
        )
    )
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    
    return wrapper


def retry_on_api_error(func: Callable) -> Callable:
    """API hatalarında retry yapan decorator (rate limit vb.)"""
    @exponential_backoff(
        max_retries=5,
        base_delay=1.0,
        max_delay=30.0,
        exceptions=(Exception,)
    )
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        
        # API response kontrolü
        if isinstance(result, dict):
            # Rate limit check
            if result.get("error") == "rate_limit_exceeded":
                raise Exception("Rate limit exceeded")
            
            # Generic API error
            if not result.get("ok") and "error" in result:
                error_msg = result.get("error")
                # Bazı hatalar için retry yapma
                if error_msg in ("invalid_token_id", "market_closed", "insufficient_balance"):
                    return result
                raise Exception(f"API error: {error_msg}")
        
        return result
    
    return wrapper
