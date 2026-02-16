# agent/bot/monitoring/dashboard.py
"""
Real-time dashboard data provider
"""
from typing import Dict, Any, List
from datetime import datetime
from .metrics import get_metrics_tracker

def get_dashboard_data() -> Dict[str, Any]:
    """
    Dashboard için tüm verileri topla
    
    Returns:
        Dashboard data dictionary
    """
    metrics = get_metrics_tracker()
    
    try:
        performance = metrics.get_performance_summary()
        decision_accuracy = metrics.get_decision_accuracy(7)
        
        return {
            "status": "active",
            "timestamp": datetime.utcnow().isoformat(),
            "performance": performance,
            "ai_accuracy": {
                "decision_accuracy_7d": decision_accuracy,
            },
            "health": {
                "uptime": "running",
                "last_update": datetime.utcnow().isoformat()
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


def format_dashboard_text() -> str:
    """Dashboard verisini text formatında döndür (CLI için)"""
    data = get_dashboard_data()
    
    if data.get("status") == "error":
        return f"❌ Error: {data.get('error')}"
    
    perf = data.get("performance", {})
    daily = perf.get("daily", {})
    weekly = perf.get("weekly", {})
    
    text = f"""
╔══════════════════════════════════════════╗
║      POLYMARKET AI TRADER DASHBOARD      ║
╚══════════════════════════════════════════╝

📊 TODAY'S PERFORMANCE
  Trades:    {daily.get('trades', 0)}
  PnL:       ${daily.get('pnl', 0):.2f}
  Win Rate:  {daily.get('win_rate', 0):.1f}%
  Wins:      {daily.get('wins', 0)} | Losses: {daily.get('losses', 0)}

📈 WEEKLY PERFORMANCE (7d)
  Trades:    {weekly.get('trades', 0)}
  PnL:       ${weekly.get('pnl', 0):.2f}
  Win Rate:  {weekly.get('win_rate', 0):.1f}%

📉 RISK METRICS (30d)
  Sharpe Ratio:    {perf.get('sharpe_ratio_30d', 0):.2f}
  Max Drawdown:    ${perf.get('max_drawdown_30d', 0):.2f}

🤖 AI PERFORMANCE
  Decision Accuracy (7d): {data.get('ai_accuracy', {}).get('decision_accuracy_7d', 0):.1f}%

⏰ Last Update: {data.get('timestamp', 'N/A')}
"""
    return text
