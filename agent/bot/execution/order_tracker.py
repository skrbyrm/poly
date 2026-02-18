# agent/bot/execution/order_tracker.py
"""
Order Tracker — GTC order fill takibi.

Polymarket'te limit order'lar anında dolmaz.
Bu modül açık order'ları izler, fill kontrolü yapar.

Paper mode:  Simüle edilmiş fill — fiyat limithe ulaştıysa doldur.
Live mode:   CLOB API'den order status çek, fill gelince ledger güncelle.

Kullanım:
    tracker = get_order_tracker()
    tracker.add_order(order)            # yeni order ekle
    fills = tracker.check_fills(...)    # her tick'te çağır
"""
import time
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
from enum import Enum

from ..utils.cache import get_redis_client
from ..monitoring.logger import get_logger

logger = get_logger("order_tracker")

TRACKER_REDIS_KEY = "order_tracker:open_orders"
ORDER_TTL_S = 86400  # 24 saat sonra stale order temizle


# ─────────────────────────────────────────────
# Veri yapıları
# ─────────────────────────────────────────────

class OrderStatus(str, Enum):
    OPEN      = "open"
    FILLED    = "filled"
    CANCELLED = "cancelled"
    EXPIRED   = "expired"


@dataclass
class TrackedOrder:
    """Takip edilen order."""
    order_id:    str
    token_id:    str
    side:        str          # "buy" | "sell"
    limit_price: float
    qty:         float
    mode:        str          # "paper" | "live"
    placed_at:   float = field(default_factory=time.time)
    status:      str   = OrderStatus.OPEN
    filled_at:   Optional[float] = None
    filled_price: Optional[float] = None
    clob_order_id: Optional[str]  = None   # live mode'da CLOB'dan gelen ID

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TrackedOrder":
        return TrackedOrder(**{k: v for k, v in d.items() if k in TrackedOrder.__dataclass_fields__})


@dataclass
class FillResult:
    """Bir fill'in sonucu."""
    order_id:    str
    token_id:    str
    side:        str
    filled_price: float
    qty:         float
    pnl:         Optional[float] = None     # sadece sell fill'lerde


# ─────────────────────────────────────────────
# OrderTracker
# ─────────────────────────────────────────────

class OrderTracker:
    """
    GTC order fill tracker.

    Redis'te açık order'ları saklar.
    Her tick'te check_fills() çağrılarak fill kontrolü yapılır.
    """

    def __init__(self):
        self.redis = get_redis_client()
        self._orders: Dict[str, TrackedOrder] = {}
        self._load_from_redis()

    # ──────────── CRUD ────────────

    def add_order(self, order: TrackedOrder) -> None:
        """Yeni order'ı takip listesine ekle."""
        self._orders[order.order_id] = order
        self._save_to_redis()
        logger.info(
            "Order tracked",
            order_id=order.order_id,
            token_id=order.token_id,
            side=order.side,
            price=order.limit_price,
            qty=order.qty,
            mode=order.mode,
        )

    def remove_order(self, order_id: str) -> None:
        """Order'ı takip listesinden çıkar."""
        if order_id in self._orders:
            del self._orders[order_id]
            self._save_to_redis()

    def get_open_orders(self) -> List[TrackedOrder]:
        """Tüm açık order'ları döner."""
        return [o for o in self._orders.values() if o.status == OrderStatus.OPEN]

    def get_order(self, order_id: str) -> Optional[TrackedOrder]:
        return self._orders.get(order_id)

    # ──────────── Fill kontrolü ────────────

    def check_fills_paper(
        self,
        current_prices: Dict[str, float],
        max_order_age_s: int = None,
    ) -> List[FillResult]:
        """
        Paper mode fill kontrolü.

        Kural: limit_price'a ulaşıldıysa → fill et.
          buy  order: current_price <= limit_price  → fill
          sell order: current_price >= limit_price  → fill

        Args:
            current_prices:  {token_id: mid_price}
            max_order_age_s: Bu süreden eskiler iptal edilir (None → env'den MAX_HOLD_S)

        Returns:
            Bu çağrıda gerçekleşen fill listesi
        """
        if max_order_age_s is None:
            import os
            max_order_age_s = int(os.getenv("MAX_HOLD_S", "180"))

        fills: List[FillResult] = []
        now = time.time()

        for order in list(self.get_open_orders()):
            if order.mode != "paper":
                continue

            token_id = order.token_id
            current_price = current_prices.get(token_id)

            # Fiyat bilgisi yoksa atla
            if current_price is None or current_price <= 0:
                continue

            # Timeout — order iptal
            age = now - order.placed_at
            if age > max_order_age_s:
                order.status = OrderStatus.EXPIRED
                self._save_to_redis()
                logger.info(
                    "Paper order expired",
                    order_id=order.order_id,
                    token_id=token_id,
                    age_s=int(age),
                )
                continue

            # Fill kontrolü
            filled = False
            if order.side == "buy" and current_price <= order.limit_price:
                filled = True
            elif order.side == "sell" and current_price >= order.limit_price:
                filled = True

            if filled:
                order.status = OrderStatus.FILLED
                order.filled_at = now
                order.filled_price = current_price
                self._save_to_redis()

                fills.append(FillResult(
                    order_id=order.order_id,
                    token_id=token_id,
                    side=order.side,
                    filled_price=current_price,
                    qty=order.qty,
                ))
                logger.info(
                    "Paper order filled",
                    order_id=order.order_id,
                    token_id=token_id,
                    side=order.side,
                    filled_price=current_price,
                    limit_price=order.limit_price,
                )

        return fills

    def check_fills_live(self) -> List[FillResult]:
        """
        Live mode fill kontrolü — CLOB API'den order status çek.

        Returns:
            Bu çağrıda fill olan order'lar
        """
        fills: List[FillResult] = []

        for order in list(self.get_open_orders()):
            if order.mode != "live":
                continue

            clob_id = order.clob_order_id
            if not clob_id:
                continue

            try:
                from ..clob import build_clob_client
                client = build_clob_client()

                # CLOB'dan order durumu çek
                clob_order = client.get_order(clob_id) if hasattr(client, "get_order") else None

                if not clob_order:
                    continue

                status = clob_order.get("status", "").lower()
                size_matched = float(clob_order.get("size_matched") or 0)

                # Tamamen veya kısmen dolu
                if status in ("matched", "filled") or size_matched >= order.qty * 0.99:
                    avg_price = float(clob_order.get("avg_price") or order.limit_price)

                    order.status = OrderStatus.FILLED
                    order.filled_at = time.time()
                    order.filled_price = avg_price
                    self._save_to_redis()

                    fills.append(FillResult(
                        order_id=order.order_id,
                        token_id=order.token_id,
                        side=order.side,
                        filled_price=avg_price,
                        qty=size_matched or order.qty,
                    ))
                    logger.info(
                        "Live order filled",
                        order_id=order.order_id,
                        clob_order_id=clob_id,
                        side=order.side,
                        avg_price=avg_price,
                    )

                # İptal edilmiş
                elif status in ("cancelled", "canceled"):
                    order.status = OrderStatus.CANCELLED
                    self._save_to_redis()
                    logger.info("Live order cancelled", order_id=order.order_id, clob_id=clob_id)

            except Exception as e:
                logger.error("Live fill check failed", order_id=order.order_id, error=str(e))

        return fills

    # ──────────── İstatistik ────────────

    def get_stats(self) -> Dict[str, Any]:
        """Tracker istatistikleri."""
        all_orders = list(self._orders.values())
        return {
            "total":     len(all_orders),
            "open":      sum(1 for o in all_orders if o.status == OrderStatus.OPEN),
            "filled":    sum(1 for o in all_orders if o.status == OrderStatus.FILLED),
            "cancelled": sum(1 for o in all_orders if o.status == OrderStatus.CANCELLED),
            "expired":   sum(1 for o in all_orders if o.status == OrderStatus.EXPIRED),
        }

    # ──────────── Redis persistence ────────────

    def _save_to_redis(self) -> None:
        try:
            data = {oid: o.to_dict() for oid, o in self._orders.items()}
            self.redis.setex(TRACKER_REDIS_KEY, ORDER_TTL_S, json.dumps(data))
        except Exception as e:
            logger.error("OrderTracker save failed", error=str(e))

    def _load_from_redis(self) -> None:
        try:
            raw = self.redis.get(TRACKER_REDIS_KEY)
            if raw:
                data = json.loads(raw)
                self._orders = {
                    oid: TrackedOrder.from_dict(d)
                    for oid, d in data.items()
                }
                logger.info("OrderTracker loaded", count=len(self._orders))
        except Exception as e:
            logger.error("OrderTracker load failed", error=str(e))
            self._orders = {}

    def clear_old_orders(self, max_age_s: int = 86400) -> int:
        """
        Eski tamamlanmış order'ları temizle (filled/cancelled/expired).

        Returns:
            Temizlenen order sayısı
        """
        now = time.time()
        to_remove = [
            oid for oid, o in self._orders.items()
            if o.status != OrderStatus.OPEN and (now - (o.filled_at or o.placed_at)) > max_age_s
        ]
        for oid in to_remove:
            del self._orders[oid]
        if to_remove:
            self._save_to_redis()
        return len(to_remove)


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

_order_tracker: Optional[OrderTracker] = None


def get_order_tracker() -> OrderTracker:
    global _order_tracker
    if _order_tracker is None:
        _order_tracker = OrderTracker()
    return _order_tracker
