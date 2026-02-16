# agent/bot/clob_read.py
"""
CLOB orderbook okuma fonksiyonları
"""
import requests
from typing import Dict, Any
from .clob import build_clob_client
from .config import CLOB_HOST
from .utils.retry import retry_on_network_error

def _level_to_dict(level) -> Dict[str, str]:
    """OrderBook level'ını dict'e çevir"""
    if isinstance(level, dict):
        return {"price": str(level.get("price")), "size": str(level.get("size"))}
    # OrderSummary objesi: level.price, level.size
    return {"price": str(getattr(level, "price")), "size": str(getattr(level, "size"))}

def _normalize_orderbook(ob) -> Dict[str, Any]:
    """
    Dict veya OrderBookSummary/OrderBook benzeri objeyi
    {"bids":[{"price","size"}], "asks":[...], ...} formatına çevir.
    """
    # dict ise aynen ama bids/asks listelerini normalize edelim
    if isinstance(ob, dict):
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        if isinstance(bids, list):
            bids = [_level_to_dict(x) for x in bids]
        if isinstance(asks, list):
            asks = [_level_to_dict(x) for x in asks]
        ob2 = dict(ob)
        ob2["bids"] = bids
        ob2["asks"] = asks
        return ob2

    # object ise attributes
    bids = getattr(ob, "bids", None)
    asks = getattr(ob, "asks", None)
    market = getattr(ob, "market", None)
    asset_id = getattr(ob, "asset_id", None)
    timestamp = getattr(ob, "timestamp", None)

    bids = [_level_to_dict(x) for x in (bids or [])]
    asks = [_level_to_dict(x) for x in (asks or [])]

    return {
        "market": market,
        "asset_id": asset_id,
        "timestamp": timestamp,
        "bids": bids,
        "asks": asks,
    }

@retry_on_network_error
def get_orderbook(token_id: str, timeout_s: int = 3) -> Dict[str, Any]:
    """
    Token için orderbook getir
    
    Args:
        token_id: Token ID
        timeout_s: HTTP timeout
    
    Returns:
        {"ok": bool, "token_id": str, "orderbook": {...}}
    """
    # 1) py-clob-client yolu
    try:
        c = build_clob_client()
        if hasattr(c, "get_order_book"):
            ob = c.get_order_book(token_id)
        elif hasattr(c, "get_book"):
            ob = c.get_book(token_id=token_id)
        else:
            ob = None

        if ob is not None:
            norm = _normalize_orderbook(ob)
            return {"ok": True, "token_id": token_id, "orderbook": norm}
    except Exception:
        pass

    # 2) direct HTTP fallback
    try:
        r = requests.get(f"{CLOB_HOST}/book", params={"token_id": token_id}, timeout=timeout_s)
        if r.status_code != 200:
            return {"ok": False, "token_id": token_id, "error": f"HTTP {r.status_code}", "text": r.text[:200]}
        j = r.json()
        norm = _normalize_orderbook(j)
        return {"ok": True, "token_id": token_id, "orderbook": norm}
    except Exception as e:
        return {"ok": False, "token_id": token_id, "error": f"{type(e).__name__}: {e}"}
