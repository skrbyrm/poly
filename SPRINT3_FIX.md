# Sprint 3 Fix — Deployment Talimatları

## Değiştirilen / Oluşturulan Dosyalar

| Dosya | Durum | Değişiklik |
|-------|-------|------------|
| `agent/bot/api.py` | **GÜNCELLENDİ** | `backtest_router` import + `app.include_router()` eklendi |
| `agent/bot/api/__init__.py` | **YENİ** | Eksik `__init__.py` oluşturuldu |
| `agent/bot/api/backtest_routes.py` | **GÜNCELLENDİ** | Yeni `/backtest/db/runs` endpoint + `asyncio.get_event_loop()` fix |
| `agent/bot/backtest/analytics.py` | **GÜNCELLENDİ** | `DATABASE_URL` construct fix, çift `compute_metrics()` kaldırıldı |
| `scripts/backtest.py` | **GÜNCELLENDİ** | Stub → gerçek CLI implementasyonu |
| `compose.yaml` | **GÜNCELLENDİ** | Agent servisine `DATABASE_URL` ve `POSTGRES_HOST` eklendi |
| `agent/requirements.txt` | **GÜNCELLENDİ** | `psycopg2-binary` eklendi |

---

## Deployment

```bash
# 1. Dosyaları yerine koy (repodan)
# 2. Rebuild
docker compose down agent runner
docker compose up -d --build agent runner

# 3. Kontrol
curl http://localhost:8080/health
curl http://localhost:8080/backtest/db/runs   # yeni endpoint
```

---

## Backtest Kullanımı

### API (Docker içinden)
```bash
# Backtest çalıştır
curl -X POST http://localhost:8080/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"days_back": 14, "max_markets": 30, "save_to_db": true}'

# Son raporu oku
curl http://localhost:8080/backtest/latest

# DB'deki tüm run'lar
curl http://localhost:8080/backtest/db/runs

# Grid search optimizasyonu
curl -X POST http://localhost:8080/backtest/optimize \
  -H "Content-Type: application/json" \
  -d '{"days_back": 7, "max_markets": 10}'
```

### CLI (host'tan)
```bash
# Basit çalıştır
python scripts/backtest.py

# Özel parametreler
python scripts/backtest.py --days 30 --markets 50 --tp 0.03 --sl 0.02

# Grid search
python scripts/backtest.py --optimize --days 7 --markets 10

# JSON çıktı (pipe için)
python scripts/backtest.py --json | jq '.win_rate'
```

---

## Root Cause Özeti

### 1. Router bağlantı eksikliği
`backtest_routes.py` var ama `api.py`'de `include_router()` yoktu.
→ Tüm `/backtest/*` endpoint'ler 404 döndürüyordu.

### 2. `agent/bot/api/__init__.py` eksikti
Python `agent/bot/api/backtest_routes.py`'yi paket olarak tanımıyordu.
→ Import sırasında `ModuleNotFoundError` atıyordu.

### 3. `DATABASE_URL` env yok
`analytics.py` → `os.environ["DATABASE_URL"]` ile KeyError atıyordu.
compose.yaml'da `DATABASE_URL` set edilmemişti.
→ Çözüm: `_get_database_url()` fonksiyonu `POSTGRES_*` parçalarından inşa ediyor,
  `compose.yaml`'da agent servisine de `DATABASE_URL` açıkça eklendi.

### 4. Çift `compute_metrics()`
`grid_search()` içinde `engine.run()` zaten çağırıyor,
`result.compute_metrics()` tekrar çağrılıyordu.
→ Kaldırıldı.

### 5. `scripts/backtest.py` stub
`"not_implemented"` döndürüyordu.
→ Gerçek CLI implementasyonu: argparse, BacktestConfig, ReplayEngine,
  generate_report, save_result_to_db akışı tam entegre.

### 6. `psycopg2` requirements'ta yoktu
`psycopg2-binary>=2.9.0` eklendi.
