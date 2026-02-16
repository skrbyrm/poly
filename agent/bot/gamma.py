# agent/bot/gamma.py
"""
Gamma API - Polymarket market data
"""
import json
import requests
from typing import List, Dict, Any
from .utils.retry import retry_on_network_error
from .utils.cache import cache_with_ttl

GAMMA_BASE = "https://gamma-api.polymarket.com"

def _normalize_markets(payload) -> List[Dict]:
    """API response'dan market listesini çıkar"""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("markets", "data", "items", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
    return []

@retry_on_network_error
@cache_with_ttl(ttl_seconds=60, key_prefix="gamma:markets")
def get_markets(
    limit: int = 200,
    offset: int = 0,
    *,
    closed=False,
    active=True,
    archived=False,
    enableOrderBook=True,
    order="volume24hrClob",
    ascending=False
) -> List[Dict[str, Any]]:
    """
    Gamma API'den market listesi getir
    
    Args:
        limit: Kaç market
        offset: Offset
        closed: Kapalı marketler dahil mi
        active: Aktif marketler
        archived: Arşivlenmiş marketler
        enableOrderBook: OrderBook bilgisi
        order: Sıralama kriteri
        ascending: Artan sıralama
    
    Returns:
        Market listesi
    """
    params = {
        "limit": limit,
        "offset": offset,
        "closed": closed,
        "active": active,
        "archived": archived,
        "enableOrderBook": enableOrderBook,
        "order": order,
        "ascending": ascending,
    }
    r = requests.get(f"{GAMMA_BASE}/markets", params=params, timeout=10)
    r.raise_for_status()
    return _normalize_markets(r.json())

def extract_clob_token_ids(market: Dict) -> List[str]:
    """Market'ten CLOB token ID'lerini çıkar"""
    v = market.get("clobTokenIds") or market.get("clob_token_ids")
    if not v:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x]
    if isinstance(v, str):
        try:
            arr = json.loads(v)
            if isinstance(arr, list):
                return [str(x) for x in arr if x]
        except Exception:
            return []
    return []

def candidate_markets(limit: int = 300) -> List[Dict]:
    """
    Trade için uygun market listesi getir
    
    Filtreler:
    - Active & not closed
    - CLOB token ID'leri var
    - Likidite > 0
    
    Returns:
        Candidate market listesi
    """
    markets = get_markets(
        limit=limit,
        closed=False,
        active=True,
        archived=False,
        enableOrderBook=True,
        order="volume24hrClob",
        ascending=False,
    )

    candidates = []
    for m in markets:
        tids = extract_clob_token_ids(m)
        if not tids:
            continue

        # Likidite kontrolü
        liq = float(m.get("liquidityClob") or 0)
        v24 = float(m.get("volume24hrClob") or 0)
        vclob = float(m.get("volumeClob") or 0)

        if (liq <= 0) and (v24 <= 0) and (vclob <= 0):
            continue

        candidates.append(m)

    return candidates
