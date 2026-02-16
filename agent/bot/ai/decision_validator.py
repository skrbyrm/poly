# agent/bot/ai/decision_validator.py
"""
LLM decision validation - AI kararlarını fiziksel kurallarla doğrula
"""
from typing import Dict, Any, Optional, Tuple

def validate_llm_decision(
    decision: Dict[str, Any],
    snapshot: Dict[str, Any],
    ledger: Dict[str, Any],
    orderbook: Optional[Dict[str, Any]] = None
) -> Tuple[bool, str]:
    """
    LLM kararını doğrula
    
    Args:
        decision: LLM'den gelen decision
        snapshot: Market snapshot
        ledger: Mevcut pozisyonlar
        orderbook: Orderbook data (opsiyonel)
    
    Returns:
        (valid, reason)
    """
    
    # 1. Decision format kontrolü
    if not isinstance(decision, dict):
        return False, "Decision is not a dict"
    
    if "decision" not in decision:
        return False, "Missing 'decision' field"
    
    action = str(decision["decision"]).lower()
    if action not in ("buy", "sell", "hold"):
        return False, f"Invalid decision: {action}"
    
    # Hold için diğer kontroller gereksiz
    if action == "hold":
        return True, "OK"
    
    # 2. Token ID kontrolü
    if "token_id" not in decision:
        return False, "Missing 'token_id' field"
    
    token_id = str(decision["token_id"])
    
    # Token ID snapshot'ta var mı?
    topk = snapshot.get("topk", [])
    valid_tokens = [str(c.get("token_id")) for c in topk if c.get("token_id")]
    
    if token_id not in valid_tokens:
        return False, f"Token {token_id} not in snapshot candidates"
    
    # 3. Limit price kontrolü
    if "limit_price" not in decision:
        return False, "Missing 'limit_price' field"
    
    try:
        limit_price = float(decision["limit_price"])
    except (ValueError, TypeError):
        return False, "Invalid limit_price format"
    
    if not (0.01 <= limit_price <= 0.99):
        return False, f"Limit price out of range: {limit_price}"
    
    # 4. Orderbook ile karşılaştırma (varsa)
    if orderbook and orderbook.get("ok"):
        ob = orderbook.get("orderbook", {})
        bids = ob.get("bids", [])
        asks = ob.get("asks", [])
        
        if bids and asks:
            try:
                best_bid = float(bids[0].get("price", 0))
                best_ask = float(asks[0].get("price", 0))
                
                if action == "buy":
                    # Buy fiyatı çok yüksek olmamalı
                    if limit_price > best_ask * 1.2:
                        return False, f"Buy price too high: {limit_price} vs best_ask {best_ask}"
                else:  # sell
                    # Sell fiyatı çok düşük olmamalı
                    if limit_price < best_bid * 0.8:
                        return False, f"Sell price too low: {limit_price} vs best_bid {best_bid}"
            except Exception:
                pass
    
    # 5. Pozisyon kontrolü (sell için)
    if action == "sell":
        positions = ledger.get("positions", {})
        pos = positions.get(token_id, {})
        qty = float(pos.get("qty", 0))
        
        if qty <= 0:
            return False, f"Cannot sell - no position for token {token_id}"
    
    # 6. Confidence kontrolü
    confidence = float(decision.get("confidence", 0.5))
    if not (0.0 <= confidence <= 1.0):
        return False, f"Invalid confidence: {confidence}"
    
    min_conf = 0.55  # Config'den alınabilir
    if confidence < min_conf:
        return False, f"Confidence too low: {confidence} < {min_conf}"
    
    return True, "OK"


def validate_ensemble_decisions(decisions: list[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    Ensemble kararlarının tutarlılığını kontrol et
    
    Args:
        decisions: Birden fazla model'den gelen kararlar
    
    Returns:
        (valid, reason)
    """
    if not decisions:
        return False, "No decisions provided"
    
    if len(decisions) < 2:
        return True, "Single decision, no consensus needed"
    
    # Action'lar aynı mı?
    actions = [d.get("decision", "").lower() for d in decisions]
    unique_actions = set(actions)
    
    # Çoğunluk kontrolü
    from collections import Counter
    action_counts = Counter(actions)
    most_common = action_counts.most_common(1)[0]
    
    # En az %50 konsensus olmalı
    consensus_pct = most_common[1] / len(decisions)
    
    if consensus_pct < 0.5:
        return False, f"No consensus - actions split: {dict(action_counts)}"
    
    return True, f"Consensus: {most_common[0]} ({consensus_pct*100:.0f}%)"
