# agent/bot/runner.py
"""
Agent runner - Periyodik olarak agent_tick'i çalıştırır
"""
import os
import sys
import time
import requests

CONTROL_URL = os.getenv("CONTROL_URL", "http://localhost:8080")
TICK_EVERY_S = int(os.getenv("TICK_EVERY_S", "60"))
TICK_HTTP_TIMEOUT_S = int(os.getenv("TICK_HTTP_TIMEOUT_S", "180"))

def main():
    """Runner main loop"""
    print(f"[RUNNER] Starting - tick every {TICK_EVERY_S}s")
    print(f"[RUNNER] Control URL: {CONTROL_URL}")
    
    while True:
        try:
            print(f"\n[RUNNER] Triggering tick at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
            
            response = requests.post(
                f"{CONTROL_URL}/agent/tick",
                timeout=TICK_HTTP_TIMEOUT_S
            )
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get("ok"):
                    action = result.get("action", "unknown")
                    print(f"[RUNNER] ✓ Tick successful - action: {action}")
                    
                    if "trade_result" in result:
                        trade = result["trade_result"]
                        if trade.get("ok"):
                            print(f"[RUNNER]   → Trade executed: {trade}")
                else:
                    error = result.get("error", "Unknown error")
                    print(f"[RUNNER] ✗ Tick failed: {error}")
            else:
                print(f"[RUNNER] ✗ HTTP error: {response.status_code}")
                print(f"[RUNNER]   Response: {response.text[:200]}")
        
        except requests.exceptions.Timeout:
            print(f"[RUNNER] ⚠ Tick timeout (>{TICK_HTTP_TIMEOUT_S}s)")
        
        except Exception as e:
            print(f"[RUNNER] ✗ Error: {e}")
        
        # Wait
        print(f"[RUNNER] Sleeping {TICK_EVERY_S}s...")
        time.sleep(TICK_EVERY_S)

if __name__ == "__main__":
    main()
