# agent/bot/execution/live_exec.py
import time
from typing import Dict, Any, Optional
from ..clob import build_clob_client
from .live_ledger import LIVE_LEDGER
from ..monitoring.logger import log_trade
from ..monitoring.metrics import get_metrics_tracker
from ..monitoring.alerts import alert_trade


def _pick_params_class():
    """py-clob-client versiyonuna göre doğru params class'ı bul"""
    for name in ["BalanceAllowanceParams", "GetBalanceAllowanceParams", "BalanceAllowanceRequest"]:
        try:
            mod = __import__("py_clob_client.clob_types", fromlist=[name])
            cls = getattr(mod, name)
            return cls
        except Exception:
            pass
    return None


def place_order(token_id: str, side: str, price: float, qty: float) -> Dict[str, Any]:
    side = side.lower()

    if side not in ("buy", "sell"):
        return {"ok": False, "error": "Invalid side"}
    if qty <= 0:
        return {"ok": False, "error": "Invalid quantity"}
    if not (0.01 <= price <= 0.99):
        return {"ok": False, "error": "Invalid price"}

    try:
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL

        client = build_clob_client()
        clob_side = BUY if side == "buy" else SELL

        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=qty,
            side=clob_side,
        )

        signed_order = client.create_order(order_args)
        response = client.post_order(signed_order, OrderType.GTC)

        if response and (response.get("success") or response.get("orderID") or response.get("order_id")):
            order_id = response.get("orderID") or response.get("order_id") or ""

            if side == "buy":
                LIVE_LEDGER.add_position(token_id, qty, price, order_id)
            else:
                pnl = LIVE_LEDGER.reduce_position(token_id, qty, price, order_id)
                if pnl is not None:
                    get_metrics_tracker().record_trade({
                        "token_id": token_id,
                        "side": "sell",
                        "price": price,
                        "qty": qty,
                        "pnl": pnl,
                        "timestamp": time.time()
                    })
                    alert_trade(side, token_id, price, qty, pnl)

            log_trade(side.upper(), token_id, price, qty, mode="live", order_id=order_id)

            return {
                "ok": True,
                "side": side,
                "token_id": token_id,
                "price": price,
                "qty": qty,
                "order_id": order_id,
                "timestamp": time.time()
            }
        else:
            error_msg = str(response) if response else "No response"
            return {"ok": False, "error": f"Order rejected: {error_msg}"}

    except Exception as e:
        return {"ok": False, "error": f"Live execution error: {e}"}


def cancel_order(order_id: str) -> Dict[str, Any]:
    try:
        client = build_clob_client()
        response = client.cancel(order_id)
        return {"ok": True, "order_id": order_id, "response": str(response)}
    except Exception as e:
        return {"ok": False, "error": f"Cancel error: {e}"}


def get_open_orders(token_id: str = None) -> Dict[str, Any]:
    try:
        client = build_clob_client()
        orders = client.get_orders()
        if token_id and isinstance(orders, list):
            orders = [o for o in orders if o.get("asset_id") == token_id]
        return {
            "ok": True,
            "orders": orders if isinstance(orders, list) else [],
            "count": len(orders) if isinstance(orders, list) else 0
        }
    except Exception as e:
        return {"ok": False, "error": f"Get orders error: {e}"}


def get_balance() -> Dict[str, Any]:
    try:
        client = build_clob_client()

        ParamsCls = _pick_params_class()

        if ParamsCls:
            params = ParamsCls()
            # asset_type field'ı varsa set et
            for field, value in [("asset_type", "COLLATERAL"), ("signature_type", 0)]:
                if hasattr(params, field):
                    try:
                        setattr(params, field, value)
                    except Exception:
                        pass
            balance = client.get_balance_allowance(params=params)
        else:
            # Params class bulunamadı - direkt çağır
            balance = client.get_balance_allowance()

        # USDC balance'ı parse et (6 decimal)
        raw_balance = int(balance.get("balance", 0))
        usdc = raw_balance / 1e6

        return {
            "ok": True,
            "usdc": round(usdc, 6),
            "raw": balance
        }

    except Exception as e:
        return {"ok": False, "error": f"Balance error: {e}"}


def get_address() -> Optional[str]:
    try:
        client = build_clob_client()
        return client.get_address()
    except Exception:
        return None


def get_usdc_balance() -> float:
    """Funder adresinin USDC bakiyesini getir"""
    try:
        from py_clob_client.clob_types import AssetType, BalanceAllowanceParams
        client = build_clob_client()
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        result = client.get_balance_allowance(params=params)
        raw = int(result.get("balance", 0))
        return raw / 1e6
    except Exception as e:
        print(f"[BALANCE] Error: {e}")
        return 0.0
