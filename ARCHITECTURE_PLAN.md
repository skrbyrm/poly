# 🏗️ Polymarket AI Trading Agent — Mimari Plan & Geliştirme Yol Haritası

> **Hedef:** Paper trading'de tutarlı kâr üreten, sonra live'a geçecek tam otonom bir ajan.  
> **Strateji:** Önce güvenilir, sonra kârlı.

---

## 📐 Bölüm 1: Mevcut Sistemin Gerçek Durumu

### ✅ Sağlam Olanlar (Değiştirme)
- Docker Compose altyapısı (4 servis)
- FastAPI + Uvicorn yapısı
- Redis state management
- Risk engine çerçevesi (limits, circuit breaker, Kelly)
- Paper/Live mod ayrımı
- Structured logging

### 🚨 Kritik Hatalar (P0 — Hemen Düzeltilmeli)

#### BUG-01: Order Fill Tracking Yok
**Dosya:** `execution/live_exec.py` + `execution/paper_exec.py`
```
Mevcut: Order gönderilir → anında position açılır
Gerçek: GTC order saatlerce dolu olmayabilir
Sonuç: Gerçekte olmayan pozisyonlar takip ediliyor
```
**Çözüm:** `order_tracker.py` modülü — açık order'ları poll et, fill gelince ledger güncelle.

#### BUG-02: Orderbook Ters Parse
**Dosya:** `risk/checks.py`, `core/position_manager.py`
```python
# YANLIŞ — bids[0] Polymarket'te en DÜŞÜK fiyat
best_bid = float(bids[0].get("price", 0))

# DOĞRU
best_bid = max(float(b["price"]) for b in bids)
best_ask = min(float(a["price"]) for a in asks)
```
**Etki:** Tüm fiyat validasyonları yanlış çalışıyor.

#### BUG-03: LiveLedger CLOB Sync Boş
**Dosya:** `execution/live_ledger.py`
```python
def sync_with_clob(self, clob_positions): 
    pass  # TODO yazan boş fonksiyon
```
**Sonuç:** Live mode'da gerçek pozisyonlar ile local state uyuşmuyor.

#### BUG-04: Paper Ledger Başlangıç Bakiyesi Yanlış
```python
self.cash: float = 1000.0  # paper_ledger.py
# Ama gerçek live capital: ~10 USDC
```
**Sonuç:** Paper test sonuçları live'a hiç transfer olmuyor.

#### BUG-05: Position Manager'da Fiyat Fetch Hatası
**Dosya:** `core/position_manager.py`
```python
# _fetch_current_price() orderbook'u yanlış parse ediyor
best_bid = float(bids[0].get("price", 0))  # ters sıra!
```

### ⚠️ Profitability Engelleri (P1)

| # | Sorun | Etki | Çözüm |
|---|-------|------|-------|
| P1-01 | LLM sadece imbalance sinyali alıyor | Kör karar | Resolution date, volume trend, price history ekle |
| P1-02 | Tavily API bağlı değil | Haber yok | prompt_builder.py'de aktif et |
| P1-03 | Market question mapping yavaş | Her tick'te 500 market çekiyor | Cache + TTL artır |
| P1-04 | TP/SL çok dar (0.01) | Noise'dan stop yiyor | Volatilite bazlı dinamik TP/SL |
| P1-05 | Tek strateji (imbalance) | Edge yok | En az 2-3 strateji ekle |
| P1-06 | Hiç backtesting yok | Kör uçuş | Historical data + replay |

---

## 🗺️ Bölüm 2: Hedef Mimari

```
┌─────────────────────────────────────────────────────────────┐
│                        RUNNER (60s tick)                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ POST /agent/tick
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      FASTAPI AGENT                          │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  1. ORDER TRACKER (yeni)                            │   │
│  │     - Açık order'ları kontrol et                   │   │
│  │     - Fill gelince ledger güncelle                  │   │
│  │     - Timeout olan order'ları iptal et              │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  2. MARKET INTELLIGENCE (geliştirilmiş)             │   │
│  │     - Parallel orderbook scan (mevcut ✓)           │   │
│  │     - Volume trend analizi (yeni)                   │   │
│  │     - Resolution date filter (yeni)                 │   │
│  │     - Category scoring (yeni)                       │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  3. SIGNAL ENGINE (yeni modül)                      │   │
│  │     - Imbalance signal (mevcut, düzeltilecek)       │   │
│  │     - Momentum signal (yeni)                        │   │
│  │     - News signal via Tavily (yeni)                 │   │
│  │     - Resolution proximity signal (yeni)            │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  4. AI DECISION ENGINE (geliştirilmiş)              │   │
│  │     - Zengin context prompt (yeni)                  │   │
│  │     - Multi-signal ensemble (yeni)                  │   │
│  │     - Claude + GPT consensus (mevcut, düzeltilmiş)  │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  5. RISK ENGINE (düzeltilmiş)                       │   │
│  │     - Orderbook parse fix                           │   │
│  │     - Volatility-based TP/SL                        │   │
│  │     - Position correlation check                    │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  6. EXECUTION (düzeltilmiş)                         │   │
│  │     - Order fill tracking                           │   │
│  │     - CLOB sync                                     │   │
│  │     - Accurate paper simulation                     │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  7. PERFORMANCE ANALYTICS (geliştirilmiş)           │   │
│  │     - Trade journal                                 │   │
│  │     - Strategy attribution                          │   │
│  │     - Auto parameter tuning                         │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
   ┌─────────┐    ┌─────────┐    ┌──────────┐
   │  Redis  │    │Postgres │    │Polymarket│
   └─────────┘    └─────────┘    └──────────┘
```

---

## 📦 Bölüm 3: Yeni & Değiştirilecek Modüller

### Yeni Modüller

```
agent/bot/
├── execution/
│   └── order_tracker.py          # YENİ — fill tracking
├── signals/                       # YENİ KLASÖR
│   ├── __init__.py
│   ├── imbalance.py              # mevcut logiği buraya taşı
│   ├── momentum.py               # fiyat momentum
│   ├── news.py                   # Tavily entegrasyonu
│   └── resolution.py             # deadline proximity
└── backtest/                      # YENİ KLASÖR
    ├── __init__.py
    ├── data_loader.py             # historical data
    ├── replay_engine.py           # strateji replay
    └── metrics_report.py          # sonuç raporu
```

### Değiştirilecek Modüller

```
agent/bot/
├── risk/checks.py                 # orderbook parse fix
├── core/position_manager.py       # price fetch fix
├── core/market_intelligence.py    # resolution date + volume
├── ai/prompt_builder.py           # zengin context
├── execution/live_exec.py         # order tracking entegre
├── execution/paper_exec.py        # realistic simulation
└── execution/live_ledger.py       # sync_with_clob implement
```

---

## 📅 Bölüm 4: Sprint Planı

### Sprint 1 — Güvenilirlik (P0 Buglar)
**Süre:** 1-2 gün  
**Hedef:** Sistem güvenilir ve doğru çalışsın

| Görev | Dosya | Öncelik |
|-------|-------|---------|
| Orderbook parse fix | `risk/checks.py`, `position_manager.py` | 🔴 Kritik |
| Paper ledger başlangıç sync | `paper_ledger.py` | 🔴 Kritik |
| Order fill tracking (paper) | `order_tracker.py` (yeni) | 🔴 Kritik |
| Position manager price fix | `position_manager.py` | 🔴 Kritik |
| Live ledger CLOB sync | `live_ledger.py` | 🟡 Önemli |

**Başarı Kriteri:** Paper trading 24 saat crash olmadan çalışsın, pozisyonlar doğru takip edilsin.

---

### Sprint 2 — Signal Kalitesi (P1)
**Süre:** 2-3 gün  
**Hedef:** AI daha iyi kararlar alsın

| Görev | Dosya | Açıklama |
|-------|-------|----------|
| Tavily news entegrasyonu | `signals/news.py` | Real-time haber |
| Momentum signal | `signals/momentum.py` | Fiyat hareketi |
| Resolution proximity | `signals/resolution.py` | Yaklaşan deadline |
| Zengin LLM prompt | `prompt_builder.py` | Tüm sinyaller prompt'a |
| Market category filter | `market_intelligence.py` | Sports/Politics/Crypto ayrı |
| Dinamik TP/SL | `risk_engine.py` | Volatilite bazlı |

**Başarı Kriteri:** Paper win rate > %50 (en az 20 trade).

---

### Sprint 3 — Backtesting & Optimizasyon
**Süre:** 2-3 gün  
**Hedef:** Strateji kanıtlansın

| Görev | Açıklama |
|-------|----------|
| Historical data loader | Gamma API'den geçmiş fiyat |
| Replay engine | Paper trades'i geçmişte test et |
| Parameter sweep | Optimal TP/SL, confidence threshold bul |
| Performance report | Sharpe, max DD, win rate per category |

**Başarı Kriteri:** 30 günlük backtest'te Sharpe Ratio > 1.0

---

### Sprint 4 — Production Ready
**Süre:** 1 gün  
**Hedef:** Live trading başlasın

| Görev | Açıklama |
|-------|----------|
| Paper → Live parameter mapping | 10$ capital için parametre ayarı |
| CLOB sync implement | Gerçek pozisyonları takip et |
| Telegram alerts aktif | Kritik olayları bildir |
| Health monitoring dashboard | `scripts/monitor.py` geliştirilmiş |

---

## 🏆 Bölüm 5: Başarı Metrikleri

### Paper Trading Hedefleri

```
Sprint 1 sonrası:
  ✓ 0 crash / 24 saat
  ✓ Pozisyon tracking doğruluğu: %100
  ✓ Orderbook parse doğruluğu: %100

Sprint 2 sonrası:
  ✓ Win Rate: > %50 (min 20 trade)
  ✓ Günlük trade sayısı: 3-8
  ✓ Ortalama holding time: 30-120dk

Sprint 3 sonrası:
  ✓ 30d Sharpe Ratio: > 1.0
  ✓ Max Drawdown: < %10
  ✓ Backtest PnL: pozitif

Sprint 4 sonrası (Live):
  ✓ 1. hafta: sermaye korunuyor (< -%5)
  ✓ 1. ay: %5+ büyüme
  ✓ 3. ay: %15+ büyüme
```

---

## ⚙️ Bölüm 6: Kritik Mimari Kararlar

### Karar 1: Paper Trading Simülasyon Modeli
**Soru:** Paper trade'lerde anlık execution mu, yoksa realistic fill simulation mi?

**Karar:** Realistic fill simulation — GTC order modeli
- Order yerleştir → watch listesine ekle
- Her tick'te: fiyat limit'e ulaştı mı kontrol et
- Ulaştıysa fill et, ulaşmadıysa beklet
- MAX_HOLD_S geçtiyse iptal et

**Sebep:** Live'a geçince gerçek davranışı yansıtmak için.

---

### Karar 2: Signal Ağırlıklandırma
**Soru:** Birden fazla sinyal nasıl kombine edilecek?

**Karar:** Weighted score sistemi
```python
final_score = (
    imbalance_signal * 0.30 +
    momentum_signal  * 0.25 +
    news_signal      * 0.25 +
    resolution_signal* 0.20
)
# final_score > 0.60 → BUY
# final_score < 0.40 → SELL (if position)
# else → HOLD
```

**LLM rolü:** Ham sinyalleri alan, context'i anlayan nihai karar verici.

---

### Karar 3: Market Kategorisi Stratejisi

| Kategori | Strateji | Neden |
|----------|----------|-------|
| **Politics** | Haber odaklı, düşük imbalance | Sürpriz event'lar dominanttır |
| **Sports** | İstatistik + imbalance | Tahmin edilebilir, likit |
| **Crypto** | Momentum ağırlıklı | Trend takipçisi |
| **Finance** | Imbalance + volume | Manipüle edilmesi zor |
| **Diğer** | Conservative, küçük pozisyon | Belirsiz edge |

---

### Karar 4: Hangi LLM Modeli?
**Mevcut:** GPT-4o-mini (ucuz, hızlı)
**Önerilen:**
- **Default:** GPT-4o-mini (hız + maliyet)
- **High confidence gerekince:** GPT-4o veya Claude Sonnet
- **Ensemble:** İkisi aynı anda, consensus varsa trade

**Maliyet tahmini:** ~100 trade/gün × $0.001/trade = $0.10/gün

---

### Karar 5: Database Kullanımı
**Mevcut:** Sadece Redis (volatile)

**Karar:** PostgreSQL'i aktif kullan:
- `trades` tablosu — tüm trade history
- `signals` tablosu — her sinyal ve sonucu
- `market_snapshots` tablosu — fiyat geçmişi (backtest için)

**Redis:** Sadece real-time state (ledger, cache, circuit breaker)

---

## 📝 Bölüm 7: Kod Standartları

### Her modül için:
```python
# 1. Type hints zorunlu
def get_signals(token_id: str, orderbook: Dict[str, Any]) -> SignalResult:

# 2. Dataclass kullan (dict yerine)
@dataclass
class SignalResult:
    imbalance: float
    momentum: float
    news: float
    composite: float
    confidence: float

# 3. Her kritik fonksiyon için test
# tests/test_signals.py

# 4. Tüm exception'lar logla
try:
    ...
except Exception as e:
    logger.error("Signal calculation failed", error=str(e), token_id=token_id)
    return SignalResult.empty()
```

---

## 🔄 Bölüm 8: Güncelliği Koruma (Sana Not)

Repo güncellediğinde söylemen yeterli. Ben:
1. Yeni dosyaları analiz ederim
2. Değişen kısımları not alırım
3. Planı güncelleririm
4. Bir sonraki sprint için hazır olurum

**Şu an hafızamda olan son versiyon:**
- Tüm dosyalar yukarıdaki gibi
- Son commit: Tam stack entegrasyon
- Son durum: Live order var (SELL 9.8 @ $0.50), paper ledger $1000 başlangıç

---