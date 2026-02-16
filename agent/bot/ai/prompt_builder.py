# agent/bot/ai/prompt_builder.py
"""
Dynamic prompt engineering - LLM için optimize edilmiş promptlar
"""
from typing import Dict, Any, List, Optional
import json

def build_decision_prompt(
    snapshot: Dict[str, Any],
    ledger: Dict[str, Any],
    orderbook: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None
) -> List[Dict[str, str]]:
    """
    LLM decision prompt'u oluştur
    
    Args:
        snapshot: Market snapshot (topk candidates)
        ledger: Mevcut pozisyonlar
        orderbook: Orderbook data (opsiyonel)
        market_context: Ek market bilgileri (volatility, trend vb.)
    
    Returns:
        Messages listesi [{"role": "system", "content": "..."}, ...]
    """
    
    # System prompt
    system_prompt = """You are an expert cryptocurrency prediction market trader on Polymarket.

Your goal is to maximize USDC profits through smart, data-driven trading decisions.

TRADING RULES:
1. Only trade when you have HIGH confidence (>0.6)
2. Consider spread, liquidity, volatility
3. Avoid markets with wide spreads (>5%)
4. Prefer liquid markets with good depth
5. Use limit orders near best bid/ask
6. Risk management is critical

OUTPUT FORMAT (JSON only):
{
  "decision": "buy" | "sell" | "hold",
  "token_id": "token_id_here",
  "limit_price": 0.65,
  "confidence": 0.75,
  "reasoning": "Brief explanation"
}

If "hold", only decision and reasoning needed."""

    # User prompt - Market data
    topk = snapshot.get("topk", [])
    
    user_content = "**CURRENT MARKET OPPORTUNITIES:**\n\n"
    
    for i, candidate in enumerate(topk, 1):
        user_content += f"**Option {i}:**\n"
        user_content += f"- Token ID: {candidate.get('token_id')}\n"
        user_content += f"- Market: {candidate.get('question', 'N/A')[:100]}\n"
        user_content += f"- Best Bid: {candidate.get('band_best_bid', 0):.4f}\n"
        user_content += f"- Best Ask: {candidate.get('band_best_ask', 0):.4f}\n"
        user_content += f"- Spread: {candidate.get('spread_band', 0):.4f}\n"
        user_content += f"- Bid Depth: ${candidate.get('bid_depth_band', 0):.2f}\n"
        user_content += f"- Ask Depth: ${candidate.get('ask_depth_band', 0):.2f}\n"
        
        if market_context:
            vol = market_context.get(f"volatility_{candidate.get('token_id')}")
            if vol:
                user_content += f"- Volatility (5m): {vol:.2%}\n"
        
        user_content += "\n"
    
    # Ledger bilgileri
    positions = ledger.get("positions", {})
    cash = ledger.get("cash", 0)
    
    user_content += f"**YOUR PORTFOLIO:**\n"
    user_content += f"- Cash: ${cash:.2f}\n"
    user_content += f"- Open Positions: {len(positions)}\n"
    
    if positions:
        user_content += "\n**OPEN POSITIONS:**\n"
        for token_id, pos in list(positions.items())[:5]:  # Max 5 göster
            user_content += f"- Token {token_id}: {pos.get('qty', 0):.2f} @ ${pos.get('avg_price', 0):.4f}\n"
    
    user_content += "\n**DECISION REQUIRED:**\n"
    user_content += "Analyze the opportunities above and make ONE trading decision (buy/sell/hold).\n"
    user_content += "Respond with ONLY valid JSON, no markdown, no explanations outside JSON."
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]


def build_market_analysis_prompt(market_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Market analizi için prompt (future use)
    
    Args:
        market_data: Market bilgileri
    
    Returns:
        Messages listesi
    """
    system_prompt = """You are a market analyst specializing in prediction markets.
Analyze the given market and provide insights on:
1. Market sentiment
2. Price trends
3. Risk factors
4. Trading opportunity score (0-100)

Return JSON format:
{
  "sentiment": "bullish" | "bearish" | "neutral",
  "trend": "up" | "down" | "sideways",
  "risk_score": 50,
  "opportunity_score": 75,
  "analysis": "Brief analysis"
}"""
    
    user_content = f"**MARKET DATA:**\n{json.dumps(market_data, indent=2)}\n\nProvide analysis."
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]


def build_simple_prompt(question: str, context: str = "") -> List[Dict[str, str]]:
    """
    Basit prompt builder (generic use)
    
    Args:
        question: Soru
        context: Context bilgisi
    
    Returns:
        Messages listesi
    """
    content = question
    if context:
        content = f"{context}\n\n{question}"
    
    return [
        {"role": "user", "content": content}
    ]
