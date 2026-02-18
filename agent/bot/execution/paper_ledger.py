# agent/bot/execution/paper_ledger.py
"""
Paper trading ledger — Simülasyon için pozisyon takibi.

Sprint 1 değişiklikleri:
  - Başlangıç bakiyesi artık env'den okunuyor (PAPER_INITIAL_CASH)
  - reserved_cash mekanizması eklendi (GTC buy order'lar için)
  - get_portfolio_value() artık reserved cash'i de sayıyor
"""
import os
import json
import time
from typing import Dict, Any, Optional

from ..utils.cache import get_redis_client
from ..config import LEDGER_REDIS_KEY
from ..monitoring.logger import get_logger

logger = get_logger("paper_ledger")


def _default_initial_cash() -> float:
    """
    Başlangıç bakiyesini env'den oku.
    
    Öncelik: PAPER_INITIAL_CASH → PAPER_CAPITAL → 100.0 (varsayılan)
    
    Not: Live capital ~10$ olduğu için varsayılan 100$ olarak güncellendi.
    Gerçek test için env'de PAPER_INITIAL_CASH=10.0 set et.
    """
    for key in ("PAPER_INITIAL_CASH", "PAPER_CAPITAL"):
        val = os.getenv(key)
        if val:
            try:
                return float(val)
            except ValueError:
                pass
    return 100.0  # Varsayılan: $100 (daha gerçekçi test için)


class PaperLedger:
    """Paper trading ledger — pozisyon ve nakit takibi."""

    def __init__(self):
        self.redis = get_redis_client()
        self.key = LEDGER_REDIS_KEY

        # In-memory state
        self.cash: float = _default_initial_cash()
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.closed_positions: list = []
        self.total_pnl: float = 0.0

        # GTC buy order'lar için rezerve edilen nakit
        # {order_id: reserved_amount}
        self._reserved: Dict[str, float] = {}

        self.load_from_redis()

    # ──────────── Persistence ────────────

    def load_from_redis(self) -> None:
        try:
            data = self.redis.get(self.key)
            if data:
                state = json.loads(data)
                self.cash = float(state.get("cash", _default_initial_cash()))
                self.positions = state.get("positions", {})
                self.closed_positions = state.get("closed_positions", [])
                self.total_pnl = float(state.get("total_pnl", 0.0))
                self._reserved = state.get("reserved", {})
        except Exception as e:
            logger.error("Ledger load failed", error=str(e))

    def save_to_redis(self) -> None:
        try:
            state = {
                "cash": self.cash,
                "positions": self.positions,
                "closed_positions": self.closed_positions[-200:],
                "total_pnl": self.total_pnl,
                "reserved": self._reserved,
                "updated_at": time.time(),
            }
            self.redis.set(self.key, json.dumps(state))
        except Exception as e:
            logger.error("Ledger save failed", error=str(e))

    # ──────────── Reserved cash (GTC order için) ────────────

    def reserve_cash(self, amount: float, order_id: str) -> bool:
        """
        GTC buy order için nakit rezerve et.
        
        Returns:
            True: rezerve edildi, False: yetersiz nakit
        """
        if amount > self.cash:
            return False
        self.cash -= amount
        self._reserved[order_id] = amount
        self.save_to_redis()
        return True

    def release_reserved_cash(self, order_id: Optional[str]) -> float:
        """
        Rezerve edilmiş nakiti serbest bırak (iptal veya fill sonrası).
        
        Returns:
            Serbest bırakılan miktar
        """
        if not order_id or order_id not in self._reserved:
            return 0.0
        amount = self._reserved.pop(order_id)
        # Fill durumunda nakit geri eklenmez (zaten pozisyona dönüştü)
        # Cancel durumunda geri ekle — çağıran taraf karar verir
        self.save_to_redis()
        return amount

    def cancel_reserved(self, order_id: str) -> float:
        """İptal edilen order'ın rezervini nakit olarak iade et."""
        amount = self.release_reserved_cash(order_id)
        if amount > 0:
            self.cash += amount
            self.save_to_redis()
        return amount

    # ──────────── Position management ────────────

    def add_position(self, token_id: str, qty: float, price: float) -> None:
        """Pozisyon ekle (BUY fill)."""
        if token_id in self.positions:
            pos = self.positions[token_id]
            old_qty = float(pos.get("qty", 0))
            old_avg = float(pos.get("avg_price", 0))

            new_qty = old_qty + qty
            new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty if new_qty > 0 else price

            self.positions[token_id]["qty"] = new_qty
            self.positions[token_id]["avg_price"] = round(new_avg, 6)
        else:
            self.positions[token_id] = {
                "qty": qty,
                "avg_price": round(price, 6),
                "opened_at": time.time(),
            }

        # Nakit düş — reserved cash zaten düşülmüş olabilir
        # Eğer rezerve edilmemişse direkt düş
        self.save_to_redis()

    def reduce_position(self, token_id: str, qty: float, price: float) -> Optional[float]:
        """
        Pozisyon azalt (SELL fill).
        
        Returns:
            PnL veya None (pozisyon bulunamazsa)
        """
        if token_id not in self.positions:
            return None

        pos = self.positions[token_id]
        current_qty = float(pos.get("qty", 0))
        avg_price = float(pos.get("avg_price", 0))

        qty = min(qty, current_qty)
        pnl = (price - avg_price) * qty
        new_qty = current_qty - qty

        if new_qty <= 0.001:
            self.closed_positions.append({
                "token_id": token_id,
                "qty": current_qty,
                "avg_buy_price": avg_price,
                "sell_price": price,
                "pnl": round(pnl, 4),
                "closed_at": time.time(),
            })
            del self.positions[token_id]
        else:
            self.positions[token_id]["qty"] = round(new_qty, 6)

        self.cash += qty * price
        self.total_pnl += pnl
        self.save_to_redis()
        return round(pnl, 4)

    def get_position(self, token_id: str) -> Optional[Dict[str, Any]]:
        return self.positions.get(str(token_id))

    # ──────────── Portfolio ────────────

    def get_portfolio_value(self, current_prices: Optional[Dict[str, float]] = None) -> float:
        """
        Toplam portföy değeri = nakit + pozisyonlar + rezerve.
        
        Args:
            current_prices: {token_id: price} — sağlanmazsa avg_price kullanılır
        """
        total = self.cash + sum(self._reserved.values())

        for token_id, pos in self.positions.items():
            qty = float(pos.get("qty", 0))
            if current_prices and token_id in current_prices:
                price = current_prices[token_id]
            else:
                price = float(pos.get("avg_price", 0))
            total += qty * price

        return round(total, 2)

    def snapshot(self) -> Dict[str, Any]:
        """Ledger snapshot."""
        reserved_total = sum(self._reserved.values())
        return {
            "ok": True,
            "cash": round(self.cash, 2),
            "reserved_cash": round(reserved_total, 2),
            "available_cash": round(self.cash, 2),
            "positions": self.positions,
            "open_positions_count": len(self.positions),
            "total_pnl": round(self.total_pnl, 2),
            "portfolio_value": self.get_portfolio_value(),
            "recent_closed": self.closed_positions[-10:],
        }

    def reset(self, initial_cash: float = None) -> None:
        """Ledger sıfırla."""
        if initial_cash is None:
            initial_cash = _default_initial_cash()
        self.cash = initial_cash
        self.positions = {}
        self.closed_positions = []
        self.total_pnl = 0.0
        self._reserved = {}
        self.save_to_redis()
        logger.info("Paper ledger reset", initial_cash=initial_cash)


# ─────────────────────────────────────────────
# Global instance
# ─────────────────────────────────────────────

LEDGER = PaperLedger()


def load_ledger_from_redis(ledger: PaperLedger) -> None:
    ledger.load_from_redis()
