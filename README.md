# 🤖 Polymarket AI Trading Agent - Full Stack

Tam otomatik, AI-powered Polymarket trading botu. Market intelligence, risk management, multi-model LLM ensemble ve real-time monitoring ile donatılmış profesyonel trading sistemi.

## 🎯 Özellikler

### 🧠 AI & Decision Making
- **Multi-Model LLM Ensemble**: GPT-4o-mini + Claude Sonnet consensus
- **Dynamic Prompt Engineering**: Market koşullarına göre adaptive promptlar
- **Decision Validation**: AI kararlarını fiziksel kurallarla doğrulama
- **Fallback Strategy**: AI fail durumunda rule-based trading

### 📊 Market Intelligence
- **Parallel Orderbook Fetching**: 10x hızlı market tarama
- **Smart Opportunity Scoring**: Spread, depth, volatility analizi
- **Real-time Market Data**: Gamma API integration
- **Volatility Filtering**: Sadece yüksek volatiliteli marketlerde trade

### 🛡️ Risk Management
- **Position Sizing**: Kelly Criterion ile optimal sizing
- **Multi-level Limits**: Daily/weekly loss limits, drawdown monitoring
- **Circuit Breaker**: Otomatik emergency stop
- **TP/SL & Trailing Stop**: Dinamik pozisyon yönetimi
- **Trade Validation**: Pre-trade risk checks

### 📈 Performance Tracking
- **Real-time Metrics**: Sharpe ratio, max drawdown, win rate
- **Trade History**: 30 günlük detaylı analiz
- **Dashboard**: Web-based monitoring interface
- **Alerts**: Telegram/Slack bildirimleri

### 🔧 Execution
- **Paper Trading**: Risk-free simülasyon
- **Live Trading**: Gerçek CLOB execution
- **Smart Order Routing**: Best execution price
- **Slippage Control**: TWAP ve price impact analizi

## 🚀 Kurulum

### 1. Prerequisites
- Docker & Docker Compose
- Python 3.12+ (local development için)
- Polymarket API credentials
- OpenAI API key (veya Anthropic)

### 2. Clone Repository
```bash
git clone <repo-url>
cd polymarket-ai-agent
```

### 3. Environment Setup
```bash
cp .env.example .env
nano .env
```

**Gerekli değişkenler:**
```bash
# Wallet
PRIVATE_KEY=0xYOUR_KEY
FUNDER_ADDRESS=0xYOUR_ADDRESS

# Polymarket API
API_KEY=your_api_key
API_SECRET=your_api_secret

# LLM
LLM_API_KEY=sk-proj-YOUR_KEY
```

### 4. Start Services
```bash
docker-compose up -d
```

### 5. Verify
```bash
curl http://localhost:8080/health
curl http://localhost:8080/dashboard/text
```

## 📖 Kullanım

### Dashboard
```bash
# Web dashboard
open http://localhost:8080/dashboard

# CLI dashboard
python scripts/monitor.py --once

# Continuous monitoring
python scripts/monitor.py --interval 30
```

### Manual Trading (Paper)
```bash
curl -X POST http://localhost:8080/paper/order \
  -H "Content-Type: application/json" \
  -d '{
    "token_id": "123456",
    "side": "buy",
    "price": 0.55,
    "qty": 10
  }'
```

### Risk Status
```bash
curl http://localhost:8080/risk/status
```

### Reset State (Emergency)
```bash
python scripts/reset_state.py
```

## ⚙️ Configuration

### Risk Parameters
```bash
MAX_DAILY_LOSS=50.0          # Günlük max kayıp ($)
MAX_WEEKLY_LOSS=200.0        # Haftalık max kayıp ($)
MAX_POSITION_PCT=0.20        # Portföyün max %20'si
MAX_DRAWDOWN_PCT=0.15        # %15 max drawdown
CB_MAX_CONSECUTIVE_LOSSES=5  # 5 ardışık kayıp = stop
```

### Trading Parameters
```bash
ORDER_USD=5.0                # Order büyüklüğü
TP_PCT=0.01                  # %1 take profit
SL_PCT=0.01                  # %1 stop loss
MAX_HOLD_S=180               # 3 dakika max hold
MANAGE_MAX_POS=3             # Max 3 açık pozisyon
```

### LLM Parameters
```bash
LLM_MODEL=gpt-4o-mini
MIN_LLM_CONF=0.55           # Min confidence threshold
LLM_ENSEMBLE_ENABLED=0      # Multi-model ensemble
```

## 🏗️ Architecture
```
agent/
├── bot/
│   ├── core/              # Business logic
│   │   ├── market_intelligence.py
│   │   ├── decision_engine.py
│   │   ├── risk_engine.py
│   │   ├── position_manager.py
│   │   └── performance_tracker.py
│   ├── ai/                # LLM & validation
│   │   ├── llm_client.py
│   │   ├── decision_validator.py
│   │   ├── prompt_builder.py
│   │   └── model_ensemble.py
│   ├── execution/         # Order execution
│   │   ├── paper_exec.py
│   │   ├── live_exec.py
│   │   ├── order_router.py
│   │   └── slippage_control.py
│   ├── risk/              # Risk management
│   │   ├── limits.py
│   │   ├── circuit_breaker.py
│   │   ├── drawdown_monitor.py
│   │   └── kelly_criterion.py
│   ├── monitoring/        # Observability
│   │   ├── logger.py
│   │   ├── alerts.py
│   │   ├── metrics.py
│   │   └── dashboard.py
│   └── utils/             # Utilities
│       ├── hmac_patch.py
│       ├── validators.py
│       ├── retry.py
│       └── cache.py
└── scripts/               # Management scripts
    ├── monitor.py
    ├── backtest.py
    └── reset_state.py
```

## 📊 Metrics & Monitoring

### Daily Summary
```
Today's Performance:
- Trades: 12
- PnL: $8.50
- Win Rate: 66.7%
- Sharpe Ratio (30d): 1.85
- Max Drawdown: $3.20 (3.2%)
```

### Alerts
- ✅ Trade executed
- ⚠️ Loss limit warning (80% consumed)
- 🚨 Circuit breaker triggered
- ❌ API error

## 🔒 Security

- ✅ Private keys in environment variables
- ✅ API credentials encrypted
- ✅ Rate limiting
- ✅ Input validation
- ⚠️ Use secrets manager in production (Vault, AWS Secrets)

## 🧪 Testing

### Paper Trading (Recommended)
```bash
# .env
MODE=paper
TRADING_ENABLED=1
```

### Live Trading (Production)
```bash
# .env
MODE=live
TRADING_ENABLED=1

# Start with small position sizes!
ORDER_USD=3.0
MAX_POSITION_SIZE_USD=10.0
```

## 🐛 Troubleshooting

### HMAC Authentication Error
```bash
# Patch otomatik uygulanır, ancak manuel kontrol:
curl http://localhost:8080/health
# "address" field görünmeli
```

### Redis Connection Error
```bash
docker-compose logs redis
docker-compose restart redis
```

### Circuit Breaker Açık
```bash
# Status kontrol
curl http://localhost:8080/risk/status

# Manuel reset
python scripts/reset_state.py
```

## 📚 Documentation

- [Polymarket API](https://docs.polymarket.com)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
- [OpenAI API](https://platform.openai.com/docs)

## 🤝 Contributing

1. Fork repository
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open Pull Request

## ⚠️ Disclaimer

Bu yazılım eğitim amaçlıdır. Gerçek parayla trading yaparken:
- Küçük miktarlarla başlayın
- Risk yönetimine dikkat edin
- Stratejinizi backtest edin
- Yasal düzenlemelere uyun

**Finansal tavsiye değildir. Kendi riskinizle kullanın.**

## 📄 License

MIT License - see LICENSE file

## 🙏 Credits

Built with:
- FastAPI
- py-clob-client
- OpenAI API
- Redis
- Docker

---

**Happy Trading! 🚀📈**
