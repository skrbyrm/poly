# agent/bot/ai/model_ensemble.py
"""
Multi-model ensemble - Birden fazla LLM'den consensus al
"""
from typing import Dict, Any, List, Optional
from collections import Counter
from ..config import LLM_ENSEMBLE_ENABLED, LLM_MODELS
from .llm_client import get_llm_client
from .decision_validator import validate_llm_decision, validate_ensemble_decisions

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
        """
        Birden fazla modelden karar al ve consensus bul
        
        Args:
            messages: Prompt messages
            snapshot: Market snapshot
            ledger: Pozisyonlar
        
        Returns:
            Consensus decision veya None
        """
        if not self.enabled or len(self.models) < 2:
            # Ensemble disabled, tek model kullan
            return self._single_model_decision(messages, snapshot, ledger)
        
        decisions = []
        
        # Her modelden karar al
        for model in self.models[:3]:  # Max 3 model
            provider = "anthropic" if "claude" in model.lower() else "openai"
            
            decision = self.llm_client.call(messages, model=model, provider=provider)
            
            if decision:
                # Validate
                valid, _ = validate_llm_decision(decision, snapshot, ledger)
                if valid:
                    decisions.append(decision)
        
        if not decisions:
            return None
        
        # Tek karar varsa direkt döndür
        if len(decisions) == 1:
            return decisions[0]
        
        # Consensus kontrolü
        valid, reason = validate_ensemble_decisions(decisions)
        if not valid:
            print(f"[ENSEMBLE] No consensus: {reason}")
            return None
        
        # Majority vote - en çok görülen action
        return self._majority_vote(decisions)
    
    def _majority_vote(self, decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Majority voting - en çok tekrar eden kararı seç
        
        Args:
            decisions: Tüm model kararları
        
        Returns:
            Winning decision
        """
        # Action bazında say
        action_counts = Counter([d.get("decision", "hold").lower() for d in decisions])
        winning_action, _ = action_counts.most_common(1)[0]
        
        # Winning action'a sahip kararları filtrele
        winning_decisions = [d for d in decisions if d.get("decision", "").lower() == winning_action]
        
        if not winning_decisions:
            return {"decision": "hold", "confidence": 0.5, "reasoning": "No consensus"}
        
        # Hold ise ilk hold decision'ı döndür
        if winning_action == "hold":
            return winning_decisions[0]
        
        # Buy/Sell için ortalama fiyat ve confidence al
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
        """Tek model ile karar al"""
        model = self.models[0] if self.models else None
        provider = "anthropic" if model and "claude" in model.lower() else "openai"
        
        decision = self.llm_client.call(messages, model=model, provider=provider)
        
        if not decision:
            return None
        
        # Validate
        valid, reason = validate_llm_decision(decision, snapshot, ledger)
        if not valid:
            print(f"[LLM] Invalid decision: {reason}")
            return None
        
        return decision


# Global instance
_model_ensemble = None

def get_model_ensemble() -> ModelEnsemble:
    """ModelEnsemble singleton"""
    global _model_ensemble
    if _model_ensemble is None:
        _model_ensemble = ModelEnsemble()
    return _model_ensemble


def get_ai_decision(
    messages: List[Dict[str, str]],
    snapshot: Dict[str, Any],
    ledger: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    AI decision al (convenience function)
    
    Args:
        messages: LLM prompt
        snapshot: Market snapshot
        ledger: Pozisyonlar
    
    Returns:
        Decision dict veya None
    """
    ensemble = get_model_ensemble()
    return ensemble.get_ensemble_decision(messages, snapshot, ledger)
