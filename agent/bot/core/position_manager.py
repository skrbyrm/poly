# agent/bot/core/position_manager.py
"""
Position manager — Multi-position tracking, TP/SL, trailing stop, timeout exit.

Değişiklikler (Sprint 1):
  - _fetch_current_price() artık checks.py'deki doğru parse fonksiyonunu kullanıyor
  - avg_price = 0 durumu için None guard eklendi
  - check_exit_conditions() daha güvenli hata yönetimi ile
"""
import time
from typing import Dict, Any, Optional, List

from ..config import TP_PCT, SL_PCT, MAX_HOLD_S, EXIT_ON_TIMEOUT
from ..clob_read import get_orderbook
from ..risk.checks import _get_best_bid_ask
from ..monitoring.logger import get_logger

logger = get_logger("position_manager")


class PositionManager:
    """Pozisyon yönetimi — TP/SL, timeout, trailing stop."""

    def __init__(self):
        self.tp_pct = TP_PCT
        self.sl_pct = SL_PCT
        self.max_hold_seconds = MAX_HOLD_S
        self.exit_on_timeout = bool(EXIT_ON_TIMEOUT)

    # ─────────────────────────────────────────────
    # Ana kontrol döngüsü
    # ─────────────────────────────────────────────

    def check_exit_conditions(
        self,
        positions: Dict[str, Dict[str, Any]],
        current_prices: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Tüm açık pozisyonları tara, exit sinyali üret.

        Args:
            positions:      {token_id: position_data}
            current_prices: {token_id: price} — sağlanmazsa orderbook'tan çekilir

        Returns:
            Exit sinyalleri listesi
        """
        exit_signals: List[Dict[str, Any]] = []

        for token_id, pos in list(positions.items()):
            try:
                avg_price = float(pos.get("avg_price") or 0)
                qty = float(pos.get("qty") or 0)
                opened_at = float(pos.get("opened_at") or time.time())

                # Geçersiz pozisyon — atla
                if avg_price <= 0 or qty <= 0:
                    logger.warning(
                        "Skipping invalid position",
                        token_id=token_id, avg_price=avg_price, qty=qty
                    )
                    continue

                # Güncel fiyatı al
                if current_prices and token_id in current_prices:
                    current_price = current_prices[token_id]
                else:
                    current_price = self._fetch_current_price(token_id)

                if not current_price or current_price <= 0:
                    # Fiyat alınamadı — timeout kontrolünü yine de yap
                    if self.exit_on_timeout:
                        hold_duration = time.time() - opened_at
                        if hold_duration >= self.max_hold_seconds:
                            exit_signals.append({
                                "token_id": token_id,
                                "reason": "timeout_no_price",
                                "qty": qty,
                                "current_price": avg_price,   # fallback: avg price
                                "pnl_pct": 0.0,
                                "avg_price": avg_price,
                                "hold_duration": int(hold_duration),
                            })
                    continue

                pnl_pct = (current_price - avg_price) / avg_price

                # 1. Take Profit
                if pnl_pct >= self.tp_pct:
                    exit_signals.append(self._build_signal(
                        token_id, "take_profit", qty, current_price, pnl_pct, avg_price
                    ))
                    continue

                # 2. Stop Loss
                if pnl_pct <= -self.sl_pct:
                    exit_signals.append(self._build_signal(
                        token_id, "stop_loss", qty, current_price, pnl_pct, avg_price
                    ))
                    continue

                # 3. Timeout
                if self.exit_on_timeout:
                    hold_duration = time.time() - opened_at
                    if hold_duration >= self.max_hold_seconds:
                        exit_signals.append({
                            **self._build_signal(
                                token_id, "timeout", qty, current_price, pnl_pct, avg_price
                            ),
                            "hold_duration": int(hold_duration),
                        })

            except Exception as e:
                logger.error(
                    "Exit condition check failed",
                    token_id=token_id, error=str(e)
                )

        return exit_signals

    # ─────────────────────────────────────────────
    # Yardımcılar
    # ─────────────────────────────────────────────

    @staticmethod
    def _build_signal(
        token_id: str,
        reason: str,
        qty: float,
        current_price: float,
        pnl_pct: float,
        avg_price: float,
    ) -> Dict[str, Any]:
        return {
            "token_id": token_id,
            "reason": reason,
            "qty": qty,
            "current_price": current_price,
            "pnl_pct": round(pnl_pct * 100, 2),
            "avg_price": avg_price,
        }

    def _fetch_current_price(self, token_id: str) -> Optional[float]:
        """
        Token için güncel mid price çek.

        ⚠️  Polymarket orderbook ters sıralı — checks.py'deki
            _get_best_bid_ask() kullanılıyor.
        """
        try:
            ob_result = get_orderbook(token_id, timeout_s=2)

            if not ob_result.get("ok"):
                return None

            best_bid, best_ask = _get_best_bid_ask(ob_result)

            if best_bid is None or best_ask is None:
                return None

            return round((best_bid + best_ask) / 2, 6)

        except Exception as e:
            logger.error("Price fetch failed", token_id=token_id, error=str(e))
            return None

    def calculate_trailing_stop(
        self,
        token_id: str,
        entry_price: float,
        current_price: float,
        trailing_pct: float = 0.005,
    ) -> float:
        """
        Trailing stop price hesapla.

        Args:
            entry_price:  Giriş fiyatı
            current_price: Güncel fiyat
            trailing_pct:  Trailing yüzdesi (varsayılan %0.5)

        Returns:
            Stop price
        """
        peak_price = max(entry_price, current_price)
        return round(peak_price * (1 - trailing_pct), 6)

    def should_rebalance(self, positions: Dict[str, Dict[str, Any]]) -> bool:
        """Portföyde %40'tan fazla tek pozisyon var mı?"""
        if not positions:
            return False

        total_value = sum(
            float(p.get("qty", 0)) * float(p.get("avg_price", 0))
            for p in positions.values()
        )

        if total_value == 0:
            return False

        max_pct = max(
            (float(p.get("qty", 0)) * float(p.get("avg_price", 0))) / total_value
            for p in positions.values()
        )

        return max_pct > 0.40

    def get_position_summary(
        self, positions: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Tüm açık pozisyonların özetini döner."""
        if not positions:
            return {"total_positions": 0, "total_value": 0, "avg_hold_duration": 0}

        total_value = 0.0
        total_duration = 0.0
        current_time = time.time()

        for pos in positions.values():
            qty = float(pos.get("qty", 0))
            avg_price = float(pos.get("avg_price", 0))
            opened_at = float(pos.get("opened_at", current_time))

            total_value += qty * avg_price
            total_duration += current_time - opened_at

        return {
            "total_positions": len(positions),
            "total_value": round(total_value, 2),
            "avg_hold_duration": int(total_duration / len(positions)),
            "positions": positions,
        }


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

_position_manager: Optional[PositionManager] = None


def get_position_manager() -> PositionManager:
    global _position_manager
    if _position_manager is None:
        _position_manager = PositionManager()
    return _position_manager
