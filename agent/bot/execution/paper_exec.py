# agent/bot/execution/paper_exec.py
"""
Paper trading execution — Gerçekçi GTC simülasyonu.

Sprint 1 değişiklikleri:
  - Order anında fill değil, order_tracker'a eklenir
  - Her tick'te check_fills() çağrılarak realistic fill simüle edilir
  - Ledger sadece fill geldiğinde güncellenir
"""
import time
import uuid
from typing import Dict, Any, Optional

from .paper_ledger import LEDGER
from .order_tracker import get_order_tracker, TrackedOrder, FillResult
from ..monitoring.logger import get_logger, log_trade
from ..monitoring.metrics import get_metrics_tracker

logger = get_logger("paper_exec")


def place_order(
    token_id: str,
    side: str,
    price: float,
    qty: float,
    immediate: bool = False,
) -> Dict[str, Any]:
    """
    Paper trading order aç.

    Args:
        token_id:  Token ID
        side:      "buy" | "sell"
        price:     Limit fiyat
        qty:       Miktar
        immediate: True → eski davranış (anında fill). False → GTC simülasyon.

    Returns:
        {"ok": bool, "order_id": str, "status": "pending"|"filled", ...}
    """
    side = side.lower()

    # ── Validasyon ──
    if side not in ("buy", "sell"):
        return {"ok": False, "error": "side must be buy or sell"}
    if qty <= 0:
        return {"ok": False, "error": "qty must be > 0"}
    if not (0.01 <= price <= 0.99):
        return {"ok": False, "error": f"price {price} out of range [0.01, 0.99]"}

    order_id = f"paper_{uuid.uuid4().hex[:12]}"

    # ── Sell için pozisyon kontrolü (hemen) ──
    if side == "sell":
        pos = LEDGER.get_position(token_id)
        if not pos:
            return {"ok": False, "error": f"No position to sell for token {token_id}"}

        available_qty = float(pos.get("qty", 0))
        if qty > available_qty:
            qty = available_qty   # Maksimum mevcut miktarı sat

    # ── Buy için nakit kontrolü ──
    if side == "buy":
        cost = qty * price
        if cost > LEDGER.cash:
            return {
                "ok": False,
                "error": "Insufficient cash",
                "required": round(cost, 2),
                "available": round(LEDGER.cash, 2),
            }

    # ── Anında fill (immediate=True veya sell) ──
    # Sell order'lar her zaman anında fill edilir (piyasa çıkışı)
    if immediate or side == "sell":
        return _execute_fill(token_id, side, price, qty, order_id)

    # ── GTC: Order tracker'a ekle ──
    order = TrackedOrder(
        order_id=order_id,
        token_id=token_id,
        side=side,
        limit_price=price,
        qty=qty,
        mode="paper",
    )

    # Buy için nakit rezerve et (çift harcamayı önle)
    if side == "buy":
        LEDGER.reserve_cash(qty * price, order_id)

    get_order_tracker().add_order(order)

    logger.info(
        "Paper order placed (GTC)",
        order_id=order_id,
        token_id=token_id,
        side=side,
        price=price,
        qty=qty,
    )

    return {
        "ok": True,
        "order_id": order_id,
        "status": "pending",
        "side": side,
        "token_id": token_id,
        "price": price,
        "qty": qty,
        "mode": "paper",
        "timestamp": time.time(),
    }


def process_fills(current_prices: Dict[str, float]) -> list:
    """
    Bekleyen paper order'larını kontrol et, fill olanları ledger'a yaz.

    Her agent tick'te agent_logic.py tarafından çağrılır.

    Args:
        current_prices: {token_id: mid_price}

    Returns:
        Fill sonuçları listesi
    """
    tracker = get_order_tracker()
    fills = tracker.check_fills_paper(current_prices)

    results = []
    for fill in fills:
        # Reserved cash'i serbest bırak, gerçek fill yap
        if fill.side == "buy":
            LEDGER.release_reserved_cash(fill.order_id if hasattr(fill, 'order_id') else None)

        result = _execute_fill(
            fill.token_id, fill.side, fill.filled_price, fill.qty,
            order_id=fill.order_id,
        )
        results.append(result)

    return results


def _execute_fill(
    token_id: str,
    side: str,
    price: float,
    qty: float,
    order_id: str = None,
) -> Dict[str, Any]:
    """
    Ledger'ı fill ile güncelle.
    """
    try:
        if side == "buy":
            LEDGER.add_position(token_id, qty, price)
            log_trade("BUY", token_id, price, qty, mode="paper", order_id=order_id)
            return {
                "ok": True,
                "order_id": order_id,
                "status": "filled",
                "side": "buy",
                "token_id": token_id,
                "price": price,
                "qty": qty,
                "cost": round(qty * price, 4),
                "timestamp": time.time(),
            }

        else:  # sell
            pos = LEDGER.get_position(token_id)
            if not pos:
                return {"ok": False, "error": "Position closed before sell fill"}

            current_qty = float(pos.get("qty", 0))
            sell_qty = min(qty, current_qty)

            pnl = LEDGER.reduce_position(token_id, sell_qty, price)

            if pnl is not None:
                get_metrics_tracker().record_trade({
                    "token_id": token_id,
                    "side": "sell",
                    "price": price,
                    "qty": sell_qty,
                    "pnl": pnl,
                    "timestamp": time.time(),
                })

            log_trade("SELL", token_id, price, sell_qty, mode="paper",
                      pnl=pnl, order_id=order_id)

            return {
                "ok": True,
                "order_id": order_id,
                "status": "filled",
                "side": "sell",
                "token_id": token_id,
                "price": price,
                "qty": sell_qty,
                "pnl": pnl,
                "timestamp": time.time(),
            }

    except Exception as e:
        logger.error("Fill execution failed", token_id=token_id, side=side, error=str(e))
        return {"ok": False, "error": f"Fill execution error: {e}"}


def cancel_order(order_id: str) -> Dict[str, Any]:
    """Paper order iptal (tracker'dan çıkar + reserved cash iade)."""
    tracker = get_order_tracker()
    order = tracker.get_order(order_id)

    if not order:
        return {"ok": False, "error": f"Order {order_id} not found"}

    from .order_tracker import OrderStatus
    order.status = OrderStatus.CANCELLED
    tracker._save_to_redis()

    # Reserved cash iade
    if order.side == "buy":
        LEDGER.release_reserved_cash(order_id)

    logger.info("Paper order cancelled", order_id=order_id, token_id=order.token_id)
    return {"ok": True, "order_id": order_id, "message": "Order cancelled"}


def get_open_orders(token_id: str = None) -> Dict[str, Any]:
    """Açık paper order'ları döner."""
    tracker = get_order_tracker()
    open_orders = tracker.get_open_orders()

    if token_id:
        open_orders = [o for o in open_orders if o.token_id == token_id]

    return {
        "ok": True,
        "orders": [o.to_dict() for o in open_orders],
        "count": len(open_orders),
        "stats": tracker.get_stats(),
    }
