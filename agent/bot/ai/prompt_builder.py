# agent/bot/ai/prompt_builder.py
import os
import json
from typing import Dict, Any, List, Optional

def _web_research(question: str) -> str:
    """Tavily ile market hakkında haber ara"""
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    if not tavily_key:
        return "No web research available."
    
    try:
        import requests
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": tavily_key,
                "query": question,
                "max_results": 3,
                "search_depth": "basic"
            },
            timeout=5
        )
        if r.status_code == 200:
            results = r.json().get("results", [])
            if not results:
                return "No recent news found."
            lines = []
            for res in results[:3]:
                lines.append(f"- {res.get('title', '')}: {res.get('content', '')[:200]}")
            return "\n".join(lines)
    except Exception as e:
        return f"Research error: {e}"
    
    return "No web research available."


def build_decision_prompt(
    snapshot: Dict[str, Any],
    ledger: Dict[str, Any],
    orderbook: Optional[Dict[str, Any]] = None,
    market_context: Optional[Dict[str, Any]] = None
) -> List[Dict[str, str]]:

    system_prompt = """You are an aggressive, profit-focused prediction market trader on Polymarket.

Your ONLY goal: maximize USDC profits by buying underpriced YES/NO tokens.

POLYMARKET MECHANICS:
- Tokens resolve to $1.00 (YES wins) or $0.00 (NO wins)
- Price = market's implied probability (0.50 = 50/50, 0.30 = 30% chance)
- BID DEPTH >> ASK DEPTH → heavy buying pressure → price likely going UP → BUY
- ASK DEPTH >> BID DEPTH → heavy selling pressure → price likely going DOWN → buy the OTHER side or SELL

EDGE SIGNALS (trade when you see these):
1. Strong imbalance: one side has 3x+ more depth → follow the money
2. Mispricing: market price conflicts with recent news
3. Momentum: price at 0.50 but news strongly favors one outcome

TRADING RULES:
- confidence >= 0.60 → TRADE aggressively
- confidence 0.55-0.60 → TRADE conservatively  
- confidence < 0.55 → HOLD
- Never buy above 0.85 or below 0.15 (too risky)
- Prefer markets with depth > $1000 on at least one side

OUTPUT: Valid JSON only.
{
  "decision": "buy" | "sell" | "hold",
  "token_id": "token_id_here",
  "limit_price": 0.51,
  "confidence": 0.75,
  "reasoning": "Brief explanation of edge"
}"""

    topk = snapshot.get("topk", [])
    positions = ledger.get("positions", {})
    cash = ledger.get("cash", 0)

    user_content = "**MARKET OPPORTUNITIES:**\n\n"

    for i, candidate in enumerate(topk, 1):
        tid = candidate.get("token_id")
        question = candidate.get("question", "Unknown")
        best_bid = candidate.get("band_best_bid", 0)
        best_ask = candidate.get("band_best_ask", 0)
        spread = candidate.get("spread_band", 0)
        bid_depth = candidate.get("bid_depth_band", 0)
        ask_depth = candidate.get("ask_depth_band", 0)
        imbalance = candidate.get("imbalance", 0)

        # Imbalance yorumu
        if bid_depth > 0 and ask_depth > 0:
            ratio = bid_depth / ask_depth
            if ratio > 2:
                imbalance_signal = f"⬆️ BID-HEAVY ({ratio:.1f}x) → buyers dominating → price may rise"
            elif ratio < 0.5:
                imbalance_signal = f"⬇️ ASK-HEAVY ({1/ratio:.1f}x) → sellers dominating → price may fall"
            else:
                imbalance_signal = "↔️ BALANCED"
        else:
            imbalance_signal = "↔️ BALANCED"

        user_content += f"**Option {i}: {question}**\n"
        user_content += f"- Token ID: {tid}\n"
        user_content += f"- Price: Bid={best_bid:.3f} | Ask={best_ask:.3f} | Mid={((best_bid+best_ask)/2):.3f}\n"
        user_content += f"- Spread: {spread:.4f}\n"
        user_content += f"- Depth: Bid=${bid_depth:,.0f} | Ask=${ask_depth:,.0f}\n"
        user_content += f"- Signal: {imbalance_signal}\n"

        # Mevcut pozisyon var mı?
        if tid in positions:
            pos = positions[tid]
            avg_price = float(pos.get("avg_price", 0))
            qty = float(pos.get("qty", 0))
            mid = (best_bid + best_ask) / 2
            pnl_pct = ((mid - avg_price) / avg_price * 100) if avg_price > 0 else 0
            user_content += f"- ⚠️ YOU OWN THIS: {qty:.1f} tokens @ ${avg_price:.3f} | Current PnL: {pnl_pct:+.1f}%\n"

        # Web araştırması (sadece ilk 2 market için, hızlı tutmak için)
        if i <= 2 and os.getenv("TAVILY_API_KEY"):
            research = _web_research(question[:100])
            if research and research != "No web research available.":
                user_content += f"- 📰 Recent news:\n{research}\n"

        user_content += "\n"

    user_content += f"**YOUR PORTFOLIO:**\n"
    user_content += f"- Cash: ${cash:.2f} USDC\n"
    user_content += f"- Open Positions: {len(positions)}\n"

    if positions:
        user_content += "\n**OPEN POSITIONS:**\n"
        for token_id, pos in list(positions.items())[:5]:
            user_content += f"- Token ...{token_id[-12:]}: {pos.get('qty', 0):.1f} qty @ ${pos.get('avg_price', 0):.3f}\n"

    user_content += """
**YOUR TASK:**
1. Identify the BEST opportunity based on imbalance signal + news
2. Make a decisive buy/sell/hold decision
3. If imbalance is strong (3x+), that's your edge - USE IT

Respond with ONLY valid JSON, no markdown."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
