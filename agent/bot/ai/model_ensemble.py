"""
Multi-model ensemble - Birden fazla LLM'den consensus al
"""
from typing import Dict, Any, List, Optional
from collections import Counter
from ..config import LLM_ENSEMBLE_ENABLED, LLM_MODELS
from .llm_client import get_llm_client
from .decision_validator import validate_llm_decision, validate_ensemble_decisions
from ..monitoring.logger import get_logger


logger = get_logger("ensemble")


class ModelEnsemble:
    """Multi-model ensemble decision maker"""

    def __init__(self):
        self.enabled = bool(LLM_ENSEMBLE_ENABLED)
        self.models = [m.strip() for m in LLM_MODELS if m.strip()]
        self.llm_client = get_llm_client()

    def get_ensemble_decision(
        self,
        messages: List[Dict[str, str]],
        snapshot: Dict[str, Any],
        ledger: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled or len(self.models) < 2:
            logger.info("Ensemble disabled or single model", enabled=self.enabled, models=self.models)
            return self._single_model_decision(messages, snapshot, ledger)

        decisions = []

        for model in self.models[:3]:
            provider = "anthropic" if "claude" in model.lower() else "openai"
            logger.info("Query model", model=model, provider=provider)

            decision = self.llm_client.call(messages, model=model, provider=provider)

            if decision:
                valid, reason = validate_llm_decision(decision, snapshot, ledger)
                if valid:
                    decisions.append(decision)
                    logger.info("Decision accepted", model=model, provider=provider, action=decision.get("decision"))
                else:
                    logger.warning("Decision rejected", model=model, provider=provider, reason=reason)
            else:
                logger.warning("No decision from model", model=model, provider=provider)

        if not decisions:
            logger.warning("No valid decisions in ensemble")
            return None

        if len(decisions) == 1:
            logger.info("Single valid decision; skipping voting")
            return decisions[0]

        valid, reason = validate_ensemble_decisions(decisions)
        if not valid:
            logger.warning("No consensus", reason=reason)
            return None

        result = self._majority_vote(decisions)
        logger.info("Consensus selected", action=result.get("decision"), confidence=result.get("confidence"))
        return result

    def _majority_vote(self, decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        action_counts = Counter([d.get("decision", "hold").lower() for d in decisions])
        winning_action, _ = action_counts.most_common(1)[0]
        winning_decisions = [d for d in decisions if d.get("decision", "").lower() == winning_action]

        if not winning_decisions:
            return {"decision": "hold", "confidence": 0.5, "reasoning": "No consensus"}

        if winning_action == "hold":
            return winning_decisions[0]

        avg_price = sum(float(d.get("limit_price", 0)) for d in winning_decisions) / len(winning_decisions)
        avg_conf = sum(float(d.get("confidence", 0.5)) for d in winning_decisions) / len(winning_decisions)

        return {
            "decision": winning_action,
            "token_id": winning_decisions[0].get("token_id"),
            "limit_price": round(avg_price, 4),
            "confidence": round(avg_conf, 2),
            "reasoning": f"Ensemble consensus ({len(winning_decisions)}/{len(decisions)} models)",
            "ensemble_votes": len(winning_decisions)
        }

    def _single_model_decision(
        self,
        messages: List[Dict[str, str]],
        snapshot: Dict[str, Any],
        ledger: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        model = self.models[0] if self.models else None
        provider = "anthropic" if model and "claude" in model.lower() else "openai"

        decision = self.llm_client.call(messages, model=model, provider=provider)

        if not decision:
            logger.warning("Single-model decision empty", model=model, provider=provider)
            return None

        valid, reason = validate_llm_decision(decision, snapshot, ledger)
        if not valid:
            logger.warning("Single-model decision invalid", model=model, provider=provider, reason=reason)
            return None

        logger.info("Single-model decision valid", model=model, provider=provider, action=decision.get("decision"))
        return decision


_model_ensemble = None


def get_model_ensemble() -> ModelEnsemble:
    global _model_ensemble
    if _model_ensemble is None:
        _model_ensemble = ModelEnsemble()
    return _model_ensemble


def get_ai_decision(
    messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    ledger: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    ensemble = get_model_ensemble()
    return ensemble.get_ensemble_decision(messages, snapshot, ledger)
