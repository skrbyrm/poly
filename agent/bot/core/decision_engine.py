# agent/bot/core/decision_engine.py
"""
Decision Engine — AI karar koordinasyonu.

Sprint 2 değişiklikleri:
  - market_data snapshot'tan alınıp prompt_builder'a geçiyor
  - Fallback strategy güncellendi
"""
from typing import Dict, Any, Optional

from ..ai.prompt_builder import build_decision_prompt
from ..ai.model_ensemble import get_ai_decision
from ..ai.decision_validator import validate_llm_decision
from ..config import USE_LLM, MIN_LLM_CONF
from ..monitoring.logger import log_decision, get_logger

logger = get_logger("decision_engine")


class DecisionEngine:

    def __init__(self):
        self.use_llm = bool(USE_LLM)
        self.min_confidence = MIN_LLM_CONF

    def make_decision(
        self,
        snapshot: Dict[str, Any],
        ledger: Dict[str, Any],
        orderbook: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Karar ver.
        
        Args:
            snapshot: Market intelligence snapshot (topk + market_data)
            ledger:   Mevcut pozisyonlar
            orderbook: İlk candidate orderbook (opsiyonel, doğrulama için)
        
        Returns:
            Decision dict
        """
        if not self.use_llm:
            return self._fallback_decision(snapshot, ledger)

        try:
            # market_data artık snapshot içinde taşınıyor
            market_data_map = snapshot.get("market_data", {})
            market_data_list = list(market_data_map.values())

            messages = build_decision_prompt(
                snapshot,
                ledger,
                orderbook=orderbook,
                market_data=market_data_list,
            )

            decision = get_ai_decision(messages, snapshot, ledger)

            if not decision:
                logger.warning("AI returned no decision, using fallback")
                return self._fallback_decision(snapshot, ledger)

            valid, reason = validate_llm_decision(decision, snapshot, ledger, orderbook)
            if not valid:
                logger.warning("AI decision invalid", reason=reason)
                return self._fallback_decision(snapshot, ledger)

            confidence = float(decision.get("confidence", 0.5))
            if confidence < self.min_confidence:
                logger.info("Low confidence hold", confidence=confidence, threshold=self.min_confidence)
                return {"decision": "hold", "reason": "Low confidence", "confidence": confidence}

            log_decision(
                decision.get("decision", "hold"),
                decision.get("token_id", "N/A"),
                confidence,
                reasoning=decision.get("reasoning", ""),
            )
            return decision

        except Exception as e:
            logger.error("Decision engine error", error=str(e))
            return self._fallback_decision(snapshot, ledger)

    @staticmethod
    def _opp_get(opp: Dict[str, Any], *keys, default=0):
        for k in keys:
            if k in opp and opp.get(k) is not None:
                return opp[k]
        return default

    def _fallback_decision(
        self,
        snapshot: Dict[str, Any],
        ledger: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Rule-based fallback (LLM yoksa veya başarısız olursa)."""
        topk = snapshot.get("topk", [])
        if not topk:
            return {"decision": "hold", "reason": "No opportunities", "confidence": 0.5}

        best = topk[0]
        spread_pct = float(self._opp_get(best, "spread_pct", default=100))
        mid_price  = float(self._opp_get(best, "mid_price", "mid_band", default=0))
        bid_depth  = float(self._opp_get(best, "bid_depth", "bid_depth_band", default=0))
        ask_depth  = float(self._opp_get(best, "ask_depth", "ask_depth_band", default=0))
        total_depth = bid_depth + ask_depth

        if spread_pct > 2.0:
            return {"decision": "hold", "reason": "Spread too wide", "confidence": 0.5}
        if not (0.35 <= mid_price <= 0.65):
            return {"decision": "hold", "reason": "Price out of fallback band", "confidence": 0.5}
        if total_depth < 100:
            return {"decision": "hold", "reason": "Insufficient depth", "confidence": 0.5}

        token_id = str(best.get("token_id"))
        best_bid = float(self._opp_get(best, "best_bid", "band_best_bid", default=0))
        best_ask = float(self._opp_get(best, "best_ask", "band_best_ask", default=0))

        positions = ledger.get("positions", {})
        if token_id in positions:
            pos = positions[token_id]
            avg_price = float(pos.get("avg_price", 0))
            if avg_price > 0 and mid_price > avg_price * 1.02:
                return {
                    "decision": "sell",
                    "token_id": token_id,
                    "limit_price": best_bid if best_bid > 0 else mid_price,
                    "confidence": 0.60,
                    "reasoning": "Fallback: take profit at +2%",
                }
            return {"decision": "hold", "reason": "Position not profitable yet", "confidence": 0.5}

        if best_ask <= 0:
            return {"decision": "hold", "reason": "Invalid ask price", "confidence": 0.5}

        # Strong imbalance → buy
        if bid_depth > ask_depth * 2.0:
            return {
                "decision": "buy",
                "token_id": token_id,
                "limit_price": best_ask,
                "confidence": 0.62,
                "reasoning": f"Fallback: bid-heavy depth ({bid_depth:,.0f} vs {ask_depth:,.0f})",
            }

        return {"decision": "hold", "reason": "No clear edge in fallback", "confidence": 0.5}

    def evaluate_decision_quality(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        confidence = float(decision.get("confidence", 0.5))
        quality = confidence * 50
        if decision.get("decision") in ("buy", "sell"):
            quality += 30
        if decision.get("reasoning"):
            quality += 20
        return {
            "quality_score": round(quality, 2),
            "confidence": confidence,
            "is_high_quality": quality >= 70,
        }


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

_decision_engine: Optional[DecisionEngine] = None


def get_decision_engine() -> DecisionEngine:
    global _decision_engine
    if _decision_engine is None:
        _decision_engine = DecisionEngine()
    return _decision_engine
