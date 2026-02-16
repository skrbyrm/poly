# agent/bot/utils/cache.py
"""
Redis-based caching utilities
"""
import os
import json
import time
import functools
from typing import Optional, Any, Callable
import redis

def get_redis_client() -> redis.Redis:
    """Redis client singleton"""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(redis_url, decode_responses=True)


def cache_with_ttl(ttl_seconds: int, key_prefix: str = "cache"):
    """
    Redis cache decorator with TTL
    
    Args:
        ttl_seconds: Cache süresi (saniye)
        key_prefix: Redis key prefix
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Cache key oluştur
            cache_key = f"{key_prefix}:{func.__name__}"
            
            # Args varsa key'e ekle
            if args:
                args_str = str(args)[:100]  # Çok uzun olmasın
                cache_key += f":{hash(args_str)}"
            
            try:
                r = get_redis_client()
                
                # Cache'den oku
                cached = r.get(cache_key)
                if cached:
                    return json.loads(cached)
                
                # Cache miss - fonksiyonu çalıştır
                result = func(*args, **kwargs)
                
                # Cache'e yaz
                r.setex(cache_key, ttl_seconds, json.dumps(result))
                
                return result
                
            except Exception as e:
                # Redis hatası - cache bypass
                print(f"[CACHE] Error: {e}, bypassing cache")
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def invalidate_cache(key_pattern: str) -> int:
    """
    Pattern'e uyan cache key'leri sil
    
    Args:
        key_pattern: Redis key pattern (örn: "cache:get_orderbook:*")
    
    Returns:
        Silinen key sayısı
    """
    try:
        r = get_redis_client()
        keys = r.keys(key_pattern)
        if keys:
            return r.delete(*keys)
        return 0
    except Exception as e:
        print(f"[CACHE] Invalidate error: {e}")
        return 0


def get_cached(key: str, default: Any = None) -> Any:
    """Redis'ten değer oku"""
    try:
        r = get_redis_client()
        val = r.get(key)
        return json.loads(val) if val else default
    except Exception:
        return default


def set_cached(key: str, value: Any, ttl: Optional[int] = None) -> bool:
    """Redis'e değer yaz"""
    try:
        r = get_redis_client()
        serialized = json.dumps(value)
        if ttl:
            r.setex(key, ttl, serialized)
        else:
            r.set(key, serialized)
        return True
    except Exception as e:
        print(f"[CACHE] Set error: {e}")
        return False


def increment_counter(key: str, ttl: Optional[int] = None) -> int:
    """Counter artır ve değeri döndür"""
    try:
        r = get_redis_client()
        val = r.incr(key)
        if ttl and val == 1:  # İlk set
            r.expire(key, ttl)
        return val
    except Exception:
        return 0


def get_counter(key: str) -> int:
    """Counter değerini oku"""
    try:
        r = get_redis_client()
        val = r.get(key)
        return int(val) if val else 0
    except Exception:
        return 0
