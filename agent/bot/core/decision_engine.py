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
        """
        Trading decision al
        
        Args:
            snapshot: Market snapshot
            ledger: Pozisyonlar
            orderbook: Orderbook data (opsiyonel)
        
        Returns:
            Decision dict
        """
        if not self.use_llm:
            # LLM disabled - fallback to rule-based
            return self._fallback_decision(snapshot, ledger)
        
        try:
            # 1. Prompt oluştur
            messages = build_decision_prompt(snapshot, ledger, orderbook)
            
            # 2. AI'dan karar al
            decision = get_ai_decision(messages, snapshot, ledger)
            
            if not decision:
                # AI failed - fallback
                return self._fallback_decision(snapshot, ledger)
            
            # 3. Validate
            valid, reason = validate_llm_decision(decision, snapshot, ledger, orderbook)
            
            if not valid:
                print(f"[DECISION] Invalid AI decision: {reason}")
                return self._fallback_decision(snapshot, ledger)
            
            # 4. Confidence check
            confidence = float(decision.get("confidence", 0.5))
            if confidence < self.min_confidence:
                print(f"[DECISION] Low confidence: {confidence} < {self.min_confidence}")
                return {"decision": "hold", "reason": "Low confidence", "confidence": confidence}
            
            # 5. Log decision
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
    
    def _fallback_decision(
        self,
        snapshot: Dict[str, Any],
        ledger: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Rule-based fallback decision (AI fail durumunda)
        
        Basit strateji:
        - Spread < 2%
        - Mid price 0.40-0.60 arası
        - Depth > min
        
        Returns:
            Decision dict
        """
        topk = snapshot.get("topk", [])
        
        if not topk:
            return {"decision": "hold", "reason": "No opportunities", "confidence": 0.5}
        
        # En yüksek skorlu opportunity
        best = topk[0]
        
        spread_pct = best.get("spread_pct", 100)
        mid_price = best.get("mid_price", 0)
        total_depth = best.get("total_depth", 0)
        
        # Rule-based conditions
        if spread_pct > 2.0:
            return {"decision": "hold", "reason": "Spread too wide", "confidence": 0.5}
        
        if not (0.40 <= mid_price <= 0.60):
            return {"decision": "hold", "reason": "Price out of band", "confidence": 0.5}
        
        if total_depth < 100:
            return {"decision": "hold", "reason": "Insufficient depth", "confidence": 0.5}
        
        # Check if we already have position
        positions = ledger.get("positions", {})
        token_id = str(best.get("token_id"))
        
        if token_id in positions:
            # Already have position - consider selling
            pos = positions[token_id]
            avg_price = float(pos.get("avg_price", 0))
            current_price = best.get("mid_price", 0)
            
            # Simple TP: +2%
            if current_price > avg_price * 1.02:
                return {
                    "decision": "sell",
                    "token_id": token_id,
                    "limit_price": best.get("best_bid", current_price),
                    "confidence": 0.6,
                    "reasoning": "Fallback: Take profit at +2%"
                }
            
            return {"decision": "hold", "reason": "Position not profitable", "confidence": 0.5}
        
        # No position - consider buying
        best_ask = best.get("best_ask", 0)
        
        return {
            "decision": "buy",
            "token_id": token_id,
            "limit_price": best_ask,
            "confidence": 0.6,
            "reasoning": "Fallback: Good opportunity (narrow spread, good depth)"
        }
    
    def evaluate_decision_quality(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decision kalitesini değerlendir
        
        Returns:
            Quality metrics
        """
        action = decision.get("decision", "hold")
        confidence = float(decision.get("confidence", 0.5))
        
        quality_score = 0.0
        
        # Confidence contribution
        quality_score += confidence * 50
        
        # Action contribution (buy/sell > hold)
        if action in ("buy", "sell"):
            quality_score += 30
        
        # Reasoning contribution
        if decision.get("reasoning"):
            quality_score += 20
        
        return {
            "quality_score": round(quality_score, 2),
            "confidence": confidence,
            "is_high_quality": quality_score >= 70
        }


# Global instance
_decision_engine = None

def get_decision_engine() -> DecisionEngine:
    """DecisionEngine singleton"""
    global _decision_engine
    if _decision_engine is None:
        _decision_engine = DecisionEngine()
    return _decision_engine
