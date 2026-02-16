# agent/bot/monitoring/alerts.py
"""
Alert sistemi - Telegram/Slack bildirimleri
"""
import os
import requests
from typing import Optional, Dict, Any
from datetime import datetime

class AlertManager:
    """Alert gönderme sistemi"""
    
    def __init__(self):
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
        self.enabled = os.getenv("ALERTS_ENABLED", "1") in ("1", "true", "yes")
    
    def send_alert(self, message: str, level: str = "INFO", **kwargs) -> bool:
        """
        Alert gönder
        
        Args:
            message: Alert mesajı
            level: INFO, WARNING, ERROR, CRITICAL
            **kwargs: Ek bilgiler
        """
        if not self.enabled:
            return False
        
        # Emoji mapping
        emoji_map = {
            "INFO": "ℹ️",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "CRITICAL": "🚨",
            "SUCCESS": "✅",
            "TRADE": "💰",
        }
        
        emoji = emoji_map.get(level.upper(), "📢")
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        formatted_message = f"{emoji} *{level}*\n\n{message}\n\n_{timestamp}_"
        
        # Ek bilgiler varsa ekle
        if kwargs:
            formatted_message += "\n\n*Details:*\n"
            for key, value in kwargs.items():
                formatted_message += f"• {key}: `{value}`\n"
        
        success = False
        
        # Telegram gönder
        if self.telegram_token and self.telegram_chat_id:
            success |= self._send_telegram(formatted_message)
        
        # Slack gönder
        if self.slack_webhook:
            success |= self._send_slack(formatted_message, level)
        
        return success
    
    def _send_telegram(self, message: str) -> bool:
        """Telegram'a mesaj gönder"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            response = requests.post(url, json=payload, timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"[ALERT] Telegram error: {e}")
            return False
    
    def _send_slack(self, message: str, level: str) -> bool:
        """Slack'e mesaj gönder"""
        try:
            # Slack için renk kodu
            color_map = {
                "INFO": "#36a64f",
                "WARNING": "#ff9900",
                "ERROR": "#ff0000",
                "CRITICAL": "#990000",
                "SUCCESS": "#00ff00",
                "TRADE": "#0099ff",
            }
            
            payload = {
                "attachments": [{
                    "color": color_map.get(level.upper(), "#808080"),
                    "text": message,
                    "mrkdwn_in": ["text"]
                }]
            }
            
            response = requests.post(self.slack_webhook, json=payload, timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"[ALERT] Slack error: {e}")
            return False
    
    # Convenience methods
    def alert_trade(self, action: str, token_id: str, price: float, qty: float, pnl: Optional[float] = None):
        """Trade alert"""
        msg = f"🔔 *Trade Executed*\n\n"
        msg += f"Action: {action.upper()}\n"
        msg += f"Token: `{token_id}`\n"
        msg += f"Price: `{price:.4f}`\n"
        msg += f"Quantity: `{qty:.2f}`"
        
        if pnl is not None:
            pnl_emoji = "📈" if pnl > 0 else "📉"
            msg += f"\n{pnl_emoji} PnL: `${pnl:.2f}`"
        
        self.send_alert(msg, level="TRADE")
    
    def alert_loss_limit(self, current_loss: float, limit: float):
        """Kayıp limiti uyarısı"""
        msg = f"⚠️ *Loss Limit Warning*\n\n"
        msg += f"Current Loss: `${current_loss:.2f}`\n"
        msg += f"Limit: `${limit:.2f}`\n"
        msg += f"Percentage: `{(current_loss/limit)*100:.1f}%`"
        
        self.send_alert(msg, level="WARNING")
    
    def alert_circuit_breaker(self, reason: str):
        """Circuit breaker aktif oldu"""
        msg = f"🚨 *CIRCUIT BREAKER ACTIVATED*\n\n"
        msg += f"Reason: {reason}\n"
        msg += f"All trading STOPPED!"
        
        self.send_alert(msg, level="CRITICAL")
    
    def alert_error(self, error: str, context: Optional[Dict[str, Any]] = None):
        """Hata bildirimi"""
        msg = f"❌ *Error Occurred*\n\n{error}"
        self.send_alert(msg, level="ERROR", **(context or {}))
    
    def alert_daily_summary(self, trades: int, pnl: float, win_rate: float):
        """Günlük özet"""
        pnl_emoji = "📈" if pnl > 0 else "📉"
        msg = f"📊 *Daily Summary*\n\n"
        msg += f"Trades: `{trades}`\n"
        msg += f"{pnl_emoji} PnL: `${pnl:.2f}`\n"
        msg += f"Win Rate: `{win_rate:.1f}%`"
        
        self.send_alert(msg, level="INFO")


# Global instance
_alert_manager = None

def get_alert_manager() -> AlertManager:
    """AlertManager singleton"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager


# Convenience functions
def alert_trade(action: str, token_id: str, price: float, qty: float, pnl: Optional[float] = None):
    get_alert_manager().alert_trade(action, token_id, price, qty, pnl)

def alert_loss_limit(current_loss: float, limit: float):
    get_alert_manager().alert_loss_limit(current_loss, limit)

def alert_circuit_breaker(reason: str):
    get_alert_manager().alert_circuit_breaker(reason)

def alert_error(error: str, context: Optional[Dict[str, Any]] = None):
    get_alert_manager().alert_error(error, context)

def alert_daily_summary(trades: int, pnl: float, win_rate: float):
    get_alert_manager().alert_daily_summary(trades, pnl, win_rate)
