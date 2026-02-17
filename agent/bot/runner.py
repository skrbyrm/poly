# agent/bot/runner.py
import os
import sys
import time
import requests

CONTROL_URL = os.getenv("CONTROL_URL", "http://localhost:8080")
TICK_EVERY_S = int(os.getenv("TICK_EVERY_S", "60"))
TICK_HTTP_TIMEOUT_S = int(os.getenv("TICK_HTTP_TIMEOUT_S", "180"))

def log(msg):
    print(msg, flush=True)

def main():
    log(f"[RUNNER] Starting - tick every {TICK_EVERY_S}s")
    log(f"[RUNNER] Control URL: {CONTROL_URL}")

    while True:
        try:
            ts = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
            log(f"\n[RUNNER] Triggering tick at {ts}")

            response = requests.post(
                f"{CONTROL_URL}/agent/tick",
                timeout=TICK_HTTP_TIMEOUT_S
            )

            if response.status_code == 200:
                result = response.json()

                if result.get("ok"):
                    action = result.get("action", "unknown")
                    log(f"[RUNNER] ✓ action={action} | {result.get('time_ms', 0)}ms")

                    if action in ("buy", "sell") and result.get("trade_result"):
                        t = result["trade_result"]
                        log(f"[RUNNER]   → {action.upper()} {t.get('qty',0):.2f} tokens @ ${t.get('price',0):.4f} | ok={t.get('ok')}")

                    exits = result.get("position_exits", [])
                    for ex in exits:
                        r = ex.get("result", {})
                        log(f"[RUNNER]   ← EXIT {ex['reason']} | pnl=${r.get('pnl', 0):.4f}")

                elif result.get("error") == "tick_in_progress":
                    log(f"[RUNNER] ⚠ tick already in progress, skipping")
                else:
                    log(f"[RUNNER] ✗ {result.get('error', 'unknown error')}")
            else:
                log(f"[RUNNER] ✗ HTTP {response.status_code}: {response.text[:200]}")

        except requests.exceptions.Timeout:
            log(f"[RUNNER] ⚠ Timeout (>{TICK_HTTP_TIMEOUT_S}s)")
        except Exception as e:
            log(f"[RUNNER] ✗ Error: {e}")

        log(f"[RUNNER] Sleeping {TICK_EVERY_S}s...")
        time.sleep(TICK_EVERY_S)

if __name__ == "__main__":
    main()
