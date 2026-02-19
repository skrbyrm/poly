# agent/bot/runner.py
"""
Runner — Agent tick scheduler.

Sprint 4 değişiklikleri:
  - Exponential backoff: tick başarısız → giderek artan bekleme
  - Cool-down: art arda MAX hata → 10 dk dinlenme
  - Periyodik özet istatistikleri (her 10 tick)
  - Graceful shutdown: SIGTERM/SIGINT yakalanır
"""
import os
import sys
import time
import signal
import requests

CONTROL_URL         = os.getenv("CONTROL_URL", "http://localhost:8080")
TICK_EVERY_S        = int(os.getenv("TICK_EVERY_S", "60"))
TICK_HTTP_TIMEOUT_S = int(os.getenv("TICK_HTTP_TIMEOUT_S", "180"))

# Backoff
BACKOFF_BASE_S         = float(os.getenv("RUNNER_BACKOFF_BASE_S", "5"))
BACKOFF_MAX_S          = float(os.getenv("RUNNER_BACKOFF_MAX_S", "300"))
BACKOFF_FACTOR         = float(os.getenv("RUNNER_BACKOFF_FACTOR", "2.0"))
MAX_CONSECUTIVE_ERRORS = int(os.getenv("RUNNER_MAX_ERRORS", "10"))
COOLDOWN_S             = float(os.getenv("RUNNER_COOLDOWN_S", "600"))

_running = True


def _handle_signal(signum, frame):
    global _running
    log(f"[RUNNER] Signal {signum} received — graceful shutdown")
    _running = False


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)


def log(msg: str) -> None:
    print(msg, flush=True)


def _backoff_sleep(consecutive_errors: int) -> float:
    if consecutive_errors == 0:
        return TICK_EVERY_S
    return min(BACKOFF_BASE_S * (BACKOFF_FACTOR ** (consecutive_errors - 1)), BACKOFF_MAX_S)


def _do_tick(session: requests.Session) -> bool:
    """
    Tek tick çalıştır. True = başarılı, False = hata.
    """
    try:
        ts = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        log(f"\n[RUNNER] Tick at {ts}")

        t0 = time.time()
        resp = session.post(
            f"{CONTROL_URL}/agent/tick",
            timeout=TICK_HTTP_TIMEOUT_S,
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        if resp.status_code != 200:
            log(f"[RUNNER] ✗ HTTP {resp.status_code}: {resp.text[:200]}")
            return False

        result = resp.json()

        if result.get("ok"):
            action = result.get("action", "unknown")
            reason = result.get("reason") or result.get("detail") or result.get("error") or ""
            conf = result.get("confidence")
            log(f"[RUNNER] ✓ action={action} | conf={conf} | {result.get('time_ms', elapsed_ms)}ms | {reason}")

            if action in ("buy", "sell") and result.get("trade_result"):
                t = result["trade_result"]
                log(f"[RUNNER]   → {action.upper()} {t.get('qty',0):.2f} @ ${t.get('price',0):.4f}  ok={t.get('ok')}")

            for ex in result.get("position_exits", []):
                r = ex.get("result", {})
                log(f"[RUNNER]   ← EXIT {ex['reason']} | pnl=${r.get('pnl', 0):.4f}")

            fills = result.get("fill_results", [])
            if fills:
                log(f"[RUNNER]   ~ {len(fills)} GTC fill(s)")

            return True

        elif result.get("error") == "tick_in_progress":
            log("[RUNNER] ⚠ tick_in_progress — skip (not an error)")
            return True

        else:
            log(f"[RUNNER] ✗ agent error: {result.get('error', 'unknown')}")
            return False

    except requests.exceptions.Timeout:
        log(f"[RUNNER] ✗ Timeout (>{TICK_HTTP_TIMEOUT_S}s)")
        return False
    except requests.exceptions.ConnectionError as e:
        log(f"[RUNNER] ✗ Connection error: {e}")
        return False
    except Exception as e:
        log(f"[RUNNER] ✗ {type(e).__name__}: {e}")
        return False


def _sleep_interruptible(seconds: float) -> None:
    deadline = time.time() + seconds
    while _running and time.time() < deadline:
        time.sleep(min(1.0, deadline - time.time()))


def main() -> None:
    log(f"[RUNNER] Starting — tick every {TICK_EVERY_S}s | {CONTROL_URL}")
    log(f"[RUNNER] Backoff base={BACKOFF_BASE_S}s max={BACKOFF_MAX_S}s factor={BACKOFF_FACTOR}x")

    session = requests.Session()
    session.headers["User-Agent"] = "polymarket-runner/4.0"

    consecutive_errors = 0
    total_ticks  = 0
    total_errors = 0
    start_ts     = time.time()

    while _running:
        # Cool-down: çok fazla art arda hata
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            log(f"[RUNNER] 🚨 {consecutive_errors} consecutive errors → cool-down {COOLDOWN_S:.0f}s")
            _sleep_interruptible(COOLDOWN_S)
            consecutive_errors = 0
            continue

        # Tick
        total_ticks += 1
        ok = _do_tick(session)

        if ok:
            consecutive_errors = 0
            sleep_s = TICK_EVERY_S
        else:
            consecutive_errors += 1
            total_errors += 1
            sleep_s = _backoff_sleep(consecutive_errors)
            log(f"[RUNNER] ↺ backoff {sleep_s:.0f}s (consecutive={consecutive_errors})")

        # Periyodik özet
        if total_ticks % 10 == 0:
            uptime_h  = (time.time() - start_ts) / 3600
            err_rate  = total_errors / total_ticks * 100
            log(f"[RUNNER] 📊 uptime={uptime_h:.1f}h ticks={total_ticks} errors={total_errors} ({err_rate:.1f}%)")

        log(f"[RUNNER] Sleeping {sleep_s:.0f}s...")
        _sleep_interruptible(sleep_s)

    log("[RUNNER] Shutdown complete.")
    session.close()


if __name__ == "__main__":
    main()
