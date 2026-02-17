# agent/bot/core/decision_engine.py
"""
Decision engine - AI decision koordinasyonu ve fallback stratejisi
"""
import time
from typing import Dict, Any, Optional
from ..ai.prompt_builder import build_decision_prompt
from ..ai.model_ensemble import get_ai_decision
from ..ai.decision_validator import validate_llm_decision
from ..config import USE_LLM, MIN_LLM_CONF
from ..monitoring.logger import log_decision


class DecisionEngine:
    """AI decision engine"""

    def __init__(self):
        self.use_llm = bool(USE_LLM)
        self.min_confidence = MIN_LLM_CONF

    def make_decision(
        self,
        snapshot: Dict[str, Any],
        ledger: Dict[str, Any],
        orderbook: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not self.use_llm:
            return self._fallback_decision(snapshot, ledger)

        try:
            messages = build_decision_prompt(snapshot, ledger, orderbook)
            decision = get_ai_decision(messages, snapshot, ledger)

            if not decision:
                return self._fallback_decision(snapshot, ledger)

            valid, reason = validate_llm_decision(decision, snapshot, ledger, orderbook)
            if not valid:
                print(f"[DECISION] Invalid AI decision: {reason}")
                return self._fallback_decision(snapshot, ledger)

            confidence = float(decision.get("confidence", 0.5))
            if confidence < self.min_confidence:
                print(f"[DECISION] Low confidence: {confidence} < {self.min_confidence}")
                return {"decision": "hold", "reason": "Low confidence", "confidence": confidence}

            log_decision(
                decision.get("decision", "hold"),
                decision.get("token_id", "N/A"),
                confidence,
                reasoning=decision.get("reasoning", "")
            )
            return decision

        except Exception as e:
            print(f"[DECISION] AI decision error: {e}")
            return self._fallback_decision(snapshot, ledger)

    @staticmethod
    def _opp_get(opp: Dict[str, Any], *keys, default=0):
        for k in keys:
            if k in opp and opp.get(k) is not None:
                return opp.get(k)
        return default

    def _fallback_decision(
        self,
        snapshot: Dict[str, Any],
        ledger: Dict[str, Any]
    ) -> Dict[str, Any]:
        topk = snapshot.get("topk", [])
        if not topk:
            return {"decision": "hold", "reason": "No opportunities", "confidence": 0.5}

        best = topk[0]

        spread_pct = float(self._opp_get(best, "spread_pct", default=100))
        mid_price = float(self._opp_get(best, "mid_price", "mid_band", default=0))
        total_depth = float(
            self._opp_get(best, "total_depth", default=0)
        )
        if total_depth <= 0:
            bid_depth = float(self._opp_get(best, "bid_depth", "bid_depth_band", default=0))
            ask_depth = float(self._opp_get(best, "ask_depth", "ask_depth_band", default=0))
            total_depth = bid_depth + ask_depth

        if spread_pct > 2.0:
            return {"decision": "hold", "reason": "Spread too wide", "confidence": 0.5}

        if not (0.40 <= mid_price <= 0.60):
            return {"decision": "hold", "reason": "Price out of band", "confidence": 0.5}

        if total_depth < 100:
            return {"decision": "hold", "reason": "Insufficient depth", "confidence": 0.5}

        positions = ledger.get("positions", {})
        token_id = str(best.get("token_id"))

        best_bid = float(self._opp_get(best, "best_bid", "band_best_bid", default=0))
        best_ask = float(self._opp_get(best, "best_ask", "band_best_ask", default=0))

        if token_id in positions:
            pos = positions[token_id]
            avg_price = float(pos.get("avg_price", 0))
            current_price = mid_price if mid_price > 0 else best_bid

            if avg_price > 0 and current_price > avg_price * 1.02:
                return {
                    "decision": "sell",
                    "token_id": token_id,
                    "limit_price": best_bid if best_bid > 0 else current_price,
                    "confidence": 0.6,
                    "reasoning": "Fallback: Take profit at +2%"
                }

            return {"decision": "hold", "reason": "Position not profitable", "confidence": 0.5}

        if best_ask <= 0:
            return {"decision": "hold", "reason": "Invalid ask price", "confidence": 0.5}

        return {
            "decision": "buy",
            "token_id": token_id,
            "limit_price": best_ask,
            "confidence": 0.6,
            "reasoning": "Fallback: Good opportunity (narrow spread, good depth)"
        }

    def evaluate_decision_quality(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        action = decision.get("decision", "hold")
        confidence = float(decision.get("confidence", 0.5))

        quality_score = 0.0
        quality_score += confidence * 50

        if action in ("buy", "sell"):
            quality_score += 30

        if decision.get("reasoning"):
            quality_score += 20

        return {
            "quality_score": round(quality_score, 2),
            "confidence": confidence,
            "is_high_quality": quality_score >= 70
        }


_decision_engine = None


def get_decision_engine() -> DecisionEngine:
    global _decision_engine
    if _decision_engine is None:
        _decision_engine = DecisionEngine()
    return _decision_engine
