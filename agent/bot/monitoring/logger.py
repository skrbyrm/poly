# agent/bot/monitoring/logger.py
"""
Structured logging sistemi
"""
import os
import sys
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

class StructuredLogger:
    """JSON formatında structured logging"""
    
    def __init__(self, name: str, level: str = "INFO"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        
        # Handler zaten varsa ekleme
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JsonFormatter())
            self.logger.addHandler(handler)
    
    def _log(self, level: str, message: str, **kwargs):
        """Log mesajını JSON formatında yaz"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "message": message,
            **kwargs
        }
        
        getattr(self.logger, level.lower())(json.dumps(log_data))
    
    def info(self, message: str, **kwargs):
        self._log("INFO", message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self._log("WARNING", message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self._log("ERROR", message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        self._log("DEBUG", message, **kwargs)
    
    def trade(self, action: str, token_id: str, price: float, qty: float, **kwargs):
        """Trade-specific log"""
        self._log("INFO", f"TRADE: {action}", 
                  action=action,
                  token_id=token_id,
                  price=price,
                  qty=qty,
                  **kwargs)
    
    def decision(self, decision: str, token_id: str, confidence: float, **kwargs):
        """AI decision log"""
        self._log("INFO", f"DECISION: {decision}",
                  decision=decision,
                  token_id=token_id,
                  confidence=confidence,
                  **kwargs)
    
    def metric(self, metric_name: str, value: float, **kwargs):
        """Metric log"""
        self._log("INFO", f"METRIC: {metric_name}",
                  metric=metric_name,
                  value=value,
                  **kwargs)


class JsonFormatter(logging.Formatter):
    """JSON log formatter"""
    
    def format(self, record: logging.LogRecord) -> str:
        # Zaten JSON formatında ise direkt döndür
        try:
            json.loads(record.getMessage())
            return record.getMessage()
        except (json.JSONDecodeError, ValueError):
            # Düz mesaj ise JSON'a çevir
            log_data = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
            }
            if record.exc_info:
                log_data["exception"] = self.formatException(record.exc_info)
            
            return json.dumps(log_data)


# Global logger instance
_LOGGER_CACHE: Dict[str, StructuredLogger] = {}

def get_logger(name: str = "bot") -> StructuredLogger:
    """Logger singleton"""
    if name not in _LOGGER_CACHE:
        level = os.getenv("LOG_LEVEL", "INFO")
        _LOGGER_CACHE[name] = StructuredLogger(name, level)
    return _LOGGER_CACHE[name]


# Convenience functions
def log_info(message: str, **kwargs):
    get_logger().info(message, **kwargs)

def log_error(message: str, **kwargs):
    get_logger().error(message, **kwargs)

def log_warning(message: str, **kwargs):
    get_logger().warning(message, **kwargs)

def log_trade(action: str, token_id: str, price: float, qty: float, **kwargs):
    get_logger().trade(action, token_id, price, qty, **kwargs)

def log_decision(decision: str, token_id: str, confidence: float, **kwargs):
    get_logger().decision(decision, token_id, confidence, **kwargs)

def log_metric(metric_name: str, value: float, **kwargs):
    get_logger().metric(metric_name, value, **kwargs)
