# agent/bot/config.py
"""
Global configuration - Environment variables
"""
import os

def getenv(name: str, default: str = "") -> str:
    """Get environment variable with default"""
    v = os.getenv(name)
    return v if v not in (None, "") else default

# ===== CHAIN & CLOB =====
CHAIN_ID = int(getenv("CHAIN_ID", "137"))
CLOB_HOST = getenv("CLOB_HOST", "https://clob.polymarket.com")

# ===== WALLET & AUTH =====
PRIVATE_KEY = getenv("PRIVATE_KEY")
PK = getenv("PK", PRIVATE_KEY)  # Fallback
SIGNATURE_TYPE = int(getenv("SIGNATURE_TYPE", "1"))
FUNDER_ADDRESS = getenv("FUNDER_ADDRESS", "")

# ===== API CREDENTIALS =====
API_KEY = getenv("API_KEY")
API_SECRET = getenv("API_SECRET")
API_PASSPHRASE = getenv("API_PASSPHRASE", "")

# ===== MODE & CONTROL =====
MODE = getenv("MODE", "paper").lower()  # paper or live
TRADING_ENABLED = getenv("TRADING_ENABLED", "1") in ("1", "true", "yes")
CONTROL_HOST = getenv("CONTROL_HOST", "0.0.0.0")
CONTROL_PORT = int(getenv("CONTROL_PORT", "8080"))
LOG_LEVEL = getenv("LOG_LEVEL", "info").upper()

# ===== RISK & TRADING =====
ORDER_USD = float(getenv("ORDER_USD", "5.0"))
ENTRY_BELOW = float(getenv("ENTRY_BELOW", "0.99"))
MAX_SPREAD = float(getenv("MAX_SPREAD", "0.05"))
MIN_BAND_DEPTH = float(getenv("MIN_BAND_DEPTH", "50.0"))
TRADE_COOLDOWN_S = int(getenv("TRADE_COOLDOWN_S", "5"))
TAKE_PROFIT = float(getenv("TAKE_PROFIT", "0.01"))
STOP_LOSS = float(getenv("STOP_LOSS", "0.01"))
MANAGE_MAX_POS = int(getenv("MANAGE_MAX_POS", "3"))
SELL_SIZE_FRACTION = float(getenv("SELL_SIZE_FRACTION", "1.0"))

# ===== NEW: ADVANCED RISK =====
MAX_DAILY_LOSS = float(getenv("MAX_DAILY_LOSS", "50.0"))
MAX_WEEKLY_LOSS = float(getenv("MAX_WEEKLY_LOSS", "200.0"))
MAX_POSITION_SIZE_USD = float(getenv("MAX_POSITION_SIZE_USD", "100.0"))
MAX_POSITION_PCT = float(getenv("MAX_POSITION_PCT", "0.20"))
MAX_DRAWDOWN_PCT = float(getenv("MAX_DRAWDOWN_PCT", "0.15"))
MIN_ORDER_SIZE = float(getenv("MIN_ORDER_SIZE", "1.0"))
MAX_ORDER_SIZE = float(getenv("MAX_ORDER_SIZE", "1000.0"))

# ===== CIRCUIT BREAKER =====
CB_MAX_CONSECUTIVE_LOSSES = int(getenv("CB_MAX_CONSECUTIVE_LOSSES", "5"))
CB_COOLDOWN_SECONDS = int(getenv("CB_COOLDOWN_SECONDS", "3600"))

# ===== KELLY CRITERION =====
KELLY_FRACTION = float(getenv("KELLY_FRACTION", "0.25"))
MIN_POSITION_SIZE_USD = float(getenv("MIN_POSITION_SIZE_USD", "5.0"))

# ===== SNAPSHOT & SCANNING =====
MULTI_MARKET = int(getenv("MULTI_MARKET", "1"))
SNAP_TOPK = int(getenv("SNAP_TOPK", "1"))
TOPK = int(getenv("TOPK", "4"))
SNAPSHOT_TIME_BUDGET_S = int(getenv("SNAPSHOT_TIME_BUDGET_S", "60"))
CAND_LIMIT = int(getenv("CAND_LIMIT", "120"))

# ===== LLM =====
USE_LLM = int(getenv("USE_LLM", "1"))
LLM_API_KEY = getenv("LLM_API_KEY")
OPENAI_BASE_URL = getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_S = int(getenv("LLM_TIMEOUT_S", "8"))
LLM_MAX_OUTPUT_TOKENS = int(getenv("LLM_MAX_OUTPUT_TOKENS", "300"))
MIN_LLM_CONF = float(getenv("MIN_LLM_CONF", "0.55"))
STRICT_SNAPSHOT = int(getenv("STRICT_SNAPSHOT", "0"))

# ===== NEW: MULTI-MODEL LLM =====
LLM_ENSEMBLE_ENABLED = int(getenv("LLM_ENSEMBLE_ENABLED", "0"))
LLM_MODELS = getenv("LLM_MODELS", "gpt-4o-mini").split(",")  # Comma-separated
ANTHROPIC_API_KEY = getenv("ANTHROPIC_API_KEY", "")

# ===== REDIS =====
REDIS_URL = getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_PASSWORD = getenv("REDIS_PASSWORD", "")
LEDGER_REDIS_KEY = getenv("LEDGER_REDIS_KEY", "paper:ledger:v1")
LIVE_LEDGER_REDIS_KEY = getenv("LIVE_LEDGER_REDIS_KEY", "live:ledger:v1")
LIVE_LEDGER_TTL_S = int(getenv("LIVE_LEDGER_TTL_S", "86400"))

# ===== TP/SL =====
TP_ABS = float(getenv("TP_ABS", "0.01"))
SL_ABS = float(getenv("SL_ABS", "0.02"))
TP_PCT = float(getenv("TP_PCT", "0.01"))
SL_PCT = float(getenv("SL_PCT", "0.01"))

# ===== VOLATILITY FILTER =====
VOL_WINDOW_S = int(getenv("VOL_WINDOW_S", "300"))
MIN_VOL_PCT = float(getenv("MIN_VOL_PCT", "0.006"))
MAX_HOLD_S = int(getenv("MAX_HOLD_S", "180"))
EXIT_ON_TIMEOUT = int(getenv("EXIT_ON_TIMEOUT", "1"))
EXIT_CROSS_SPREAD = int(getenv("EXIT_CROSS_SPREAD", "1"))
MIN_SPREAD_PCT = float(getenv("MIN_SPREAD_PCT", "0.000"))

# ===== MONITORING & ALERTS =====
ALERTS_ENABLED = int(getenv("ALERTS_ENABLED", "1"))
TELEGRAM_BOT_TOKEN = getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = getenv("TELEGRAM_CHAT_ID", "")
SLACK_WEBHOOK_URL = getenv("SLACK_WEBHOOK_URL", "")

# ===== POSTGRES (UNUSED, opsiyonel) =====
POSTGRES_DB = getenv("POSTGRES_DB", "polymarket")
POSTGRES_USER = getenv("POSTGRES_USER", "polymarket")
POSTGRES_PASSWORD = getenv("POSTGRES_PASSWORD", "polymarket")

# ===== WATCH =====
WATCH_TTL_S = int(getenv("WATCH_TTL_S", "300"))
SHOW_CLOSED_POSITIONS = int(getenv("SHOW_CLOSED_POSITIONS", "0"))

# ===== TAVILY (Research API, opsiyonel) =====
TAVILY_API_KEY = getenv("TAVILY_API_KEY", "")
