# agent/bot/backtest/replay_engine.py
"""
Replay Engine — Geçmiş veriler üzerinde strateji simülasyonu.

Mantık:
  1. Resolved market'leri yükle
  2. Her market için fiyat serisini ilerlet
  3. Her adımda signal engine'i çalıştır (gerçek kod)
  4. Karar → simüle edilmiş fill → PnL hesapla
  5. Sonuçları kaydet

Bu sayede:
  - TP/SL parametrelerini optimize edebiliriz
  - Kategori bazlı performansı görebiliriz
  - Confidence threshold'u kalibre edebiliriz
"""
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from .data_loader import MarketHistory, PricePoint, get_data_loader
from ..signals.momentum import get_momentum_signal
from ..signals.resolution import get_resolution_signal, ResolutionSignal
from ..monitoring.logger import get_logger

logger = get_logger("backtest.replay")


# ─────────────────────────────────────────────
# Veri yapıları
# ─────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """Backtest konfigürasyonu."""
    initial_cash: float        = 100.0
    order_usd: float           = 5.0
    take_profit_pct: float     = 0.03
    stop_loss_pct: float       = 0.02
    max_hold_steps: int        = 12    # adım sayısı (fidelity × bu = max hold süre)
    min_imbalance: float       = 0.30  # minimum imbalance skoru
    min_confidence: float      = 0.55
    max_spread: float          = 0.05
    min_depth_usd: float       = 500.0
    categories: List[str]      = field(default_factory=lambda: ["all"])


@dataclass
class BacktestTrade:
    """Tek bir simüle edilmiş trade."""
    token_id:    str
    question:    str
    category:    str
    side:        str
    entry_price: float
    exit_price:  float
    qty:         float
    entry_ts:    float
    exit_ts:     float
    exit_reason: str           # "take_profit" | "stop_loss" | "timeout" | "resolved"
    pnl:         float
    pnl_pct:     float
    resolution:  Optional[float]   # 1.0 / 0.0 / None


@dataclass
class BacktestResult:
    """Backtest sonuçları."""
    config:          BacktestConfig
    trades:          List[BacktestTrade]
    start_ts:        float
    end_ts:          float
    markets_tested:  int

    # Hesaplanan metrikler
    total_pnl:       float = 0.0
    win_rate:        float = 0.0
    sharpe_ratio:    float = 0.0
    max_drawdown:    float = 0.0
    avg_hold_hours:  float = 0.0
    total_trades:    int   = 0

    def compute_metrics(self) -> None:
        """Tüm metrikleri hesapla."""
        if not self.trades:
            return

        self.total_trades = len(self.trades)
        pnls = [t.pnl for t in self.trades]
        self.total_pnl = round(sum(pnls), 4)

        wins = sum(1 for p in pnls if p > 0)
        self.win_rate = round(wins / self.total_trades * 100, 2)

        # Sharpe (basit günlük return bazlı)
        if len(pnls) > 1:
            import statistics
            mean_pnl = statistics.mean(pnls)
            std_pnl  = statistics.stdev(pnls)
            if std_pnl > 0:
                self.sharpe_ratio = round(mean_pnl / std_pnl * (252 ** 0.5), 2)

        # Max drawdown
        equity = self.config.initial_cash
        peak   = equity
        max_dd = 0.0
        for pnl in pnls:
            equity += pnl
            peak = max(peak, equity)
            dd = peak - equity
            max_dd = max(max_dd, dd)
        self.max_drawdown = round(max_dd, 4)

        # Ortalama hold süresi
        hold_hours = [(t.exit_ts - t.entry_ts) / 3600 for t in self.trades]
        self.avg_hold_hours = round(sum(hold_hours) / len(hold_hours), 2) if hold_hours else 0.0


# ─────────────────────────────────────────────
# Replay Engine
# ─────────────────────────────────────────────

class ReplayEngine:

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.loader = get_data_loader()

    def run(
        self,
        days_back: int = 30,
        max_markets: int = 50,
    ) -> BacktestResult:
        """
        Backtest çalıştır.

        Args:
            days_back:    Kaç günlük veri
            max_markets:  Kaç market test edilsin

        Returns:
            BacktestResult
        """
        start_time = time.time()

        # 1. AKTİF markets yükle (resolved'ların CLOB history'si boş)
        categories = self.config.categories
        cat_filter = None if "all" in categories else categories[0]
        markets = self.loader.load_active_markets(
            limit=max_markets,
            category=cat_filter,
        )

        if not markets:
            logger.warning("No resolved markets found")
            return BacktestResult(
                config=self.config, trades=[], markets_tested=0,
                start_ts=start_time, end_ts=time.time(),
            )

        # 2. Her market için fiyat geçmişini yükle ve replay et
        all_trades: List[BacktestTrade] = []

        for market in markets[:max_markets]:
            try:
                trades = self._replay_market(market)
                all_trades.extend(trades)
            except Exception as e:
                logger.error(
                    "Market replay failed",
                    question=market.get("question", "")[:40],
                    error=str(e),
                )

        # 3. Sonuçları hesapla
        result = BacktestResult(
            config=self.config,
            trades=all_trades,
            markets_tested=len(markets),
            start_ts=start_time,
            end_ts=time.time(),
        )
        result.compute_metrics()

        elapsed = round(time.time() - start_time, 1)
        logger.info(
            "Backtest complete",
            markets=result.markets_tested,
            trades=result.total_trades,
            pnl=result.total_pnl,
            win_rate=result.win_rate,
            sharpe=result.sharpe_ratio,
            elapsed_s=elapsed,
        )

        return result

    def _replay_market(self, market: Dict[str, Any]) -> List[BacktestTrade]:
        """Tek bir market üzerinde stratejiyi replay et."""
        from ..gamma import extract_clob_token_ids

        token_ids = extract_clob_token_ids(market)
        if not token_ids:
            return []

        token_id = token_ids[0]   # İlk token (YES)
        question = market.get("question", "")

        # Fiyat geçmişini yükle
        history = self.loader.load_market_history(token_id, fidelity=60)
        if not history or len(history.prices) < 5:
            return []

        history.question = question
        history.category = self._detect_category(question)

        # Çözüm sonucunu belirle
        resolution = self._get_resolution(market)
        history.resolution = resolution

        # Fiyat serisi üzerinde karar simüle et
        trades = self._simulate_on_history(history, market)
        return trades

    def _simulate_on_history(
        self,
        history: MarketHistory,
        market: Dict[str, Any],
    ) -> List[BacktestTrade]:
        """
        Fiyat serisi üzerinde sinyal-bazlı simülasyon.
        
        Her adımda:
          1. Anlık orderbook proxy oluştur (history'den)
          2. Momentum sinyali hesapla
          3. Giriş kriterleri sağlanıyorsa buy
          4. TP/SL/timeout/resolution kontrolü → exit
        """
        trades: List[BacktestTrade] = []
        prices = history.prices
        cfg    = self.config

        position: Optional[Dict[str, Any]] = None
        hold_steps = 0

        for i, point in enumerate(prices):
            current_price = point.price

            # ── Açık pozisyon exit kontrolü ──
            if position:
                hold_steps += 1
                entry_price = position["entry_price"]
                pnl_pct = (current_price - entry_price) / entry_price

                exit_reason = None

                if pnl_pct >= cfg.take_profit_pct:
                    exit_reason = "take_profit"
                elif pnl_pct <= -cfg.stop_loss_pct:
                    exit_reason = "stop_loss"
                elif hold_steps >= cfg.max_hold_steps:
                    exit_reason = "timeout"
                elif i == len(prices) - 1:
                    exit_reason = "resolved"

                if exit_reason:
                    qty  = position["qty"]
                    pnl  = (current_price - entry_price) * qty

                    trades.append(BacktestTrade(
                        token_id=history.token_id,
                        question=history.question[:80],
                        category=history.category,
                        side="buy",
                        entry_price=entry_price,
                        exit_price=current_price,
                        qty=qty,
                        entry_ts=position["entry_ts"],
                        exit_ts=point.timestamp,
                        exit_reason=exit_reason,
                        pnl=round(pnl, 4),
                        pnl_pct=round(pnl_pct * 100, 2),
                        resolution=history.resolution,
                    ))
                    position = None
                    hold_steps = 0
                continue

            # ── Entry signal kontrolü ──
            if cfg.min_imbalance <= 0.0:
                if position is None and i == 0:
                    entry_price = current_price
                    qty = cfg.order_usd / entry_price if entry_price > 0 else 0
                    if qty > 0:
                        position = {"entry_price": entry_price, "entry_ts": point.timestamp, "qty": qty}
                        hold_steps = 0
                continue

            if i < 3:
                continue   # Yeterli geçmiş yok

            signal = self._compute_signal(prices, i, market)
            if signal and signal >= cfg.min_imbalance:
                entry_price = current_price
                qty = cfg.order_usd / entry_price if entry_price > 0 else 0

                if qty > 0:
                    position = {
                        "entry_price": entry_price,
                        "entry_ts":    point.timestamp,
                        "qty":         qty,
                    }
                    hold_steps = 0

        return trades

    def _compute_signal(
        self,
        prices: List[PricePoint],
        idx: int,
        market: Dict[str, Any],
    ) -> Optional[float]:
        """
        Geçmiş fiyat noktalarından basit momentum sinyali türet.
        (Gerçek orderbook olmadan, fiyat hareketi proxy kullanılır)

        Returns:
            0.0–1.0 sinyal gücü veya None (sinyal yok)
        """
        if idx < 3:
            return None

        recent = prices[max(0, idx-3):idx+1]
        current = prices[idx].price
        prev    = prices[idx-1].price
        avg_recent = sum(p.price for p in recent) / len(recent)

        # Basit momentum: fiyat ortalamanın üstündeyse ve yükseliyorsa
        if current > avg_recent and current > prev:
            momentum = (current - avg_recent) / avg_recent
            return min(1.0, momentum * 10)  # 0-1 scale

        return None

    def _detect_category(self, question: str) -> str:
        """Basit keyword matching ile kategori tespiti."""
        q = question.lower()
        if any(kw in q for kw in ["election", "president", "vote", "bill", "congress"]):
            return "politics"
        if any(kw in q for kw in ["nfl", "nba", "mlb", "soccer", "championship", "match", "win"]):
            return "sports"
        if any(kw in q for kw in ["bitcoin", "btc", "ethereum", "crypto", "price"]):
            return "crypto"
        if any(kw in q for kw in ["fed", "rate", "inflation", "stock", "gdp"]):
            return "finance"
        return "other"

    def _get_resolution(self, market: Dict[str, Any]) -> Optional[float]:
        """Market'in çözüm sonucunu belirle (1.0=YES, 0.0=NO)."""
        outcome = market.get("outcomePrices") or market.get("outcome_prices")
        if outcome:
            try:
                if isinstance(outcome, str):
                    import json
                    outcome = json.loads(outcome)
                if isinstance(outcome, list) and len(outcome) >= 1:
                    return float(outcome[0])   # İlk token (YES) çözüm fiyatı
            except Exception:
                pass
        return None


# ─────────────────────────────────────────────
# Singleton factory
# ─────────────────────────────────────────────

def create_replay_engine(config: Optional[BacktestConfig] = None) -> ReplayEngine:
    if config is None:
        config = BacktestConfig()
    return ReplayEngine(config)
