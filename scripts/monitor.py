#!/usr/bin/env python3
# scripts/monitor.py
"""
Health monitoring script - Bot durumunu izle
"""
import sys
import os
import time
import requests

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

def check_health(control_url: str = "http://localhost:8080") -> dict:
    """Health check"""
    try:
        response = requests.get(f"{control_url}/health", timeout=5)
        return response.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_dashboard(control_url: str = "http://localhost:8080") -> dict:
    """Dashboard check"""
    try:
        response = requests.get(f"{control_url}/dashboard", timeout=5)
        return response.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def monitor_loop(control_url: str, interval: int = 60):
    """Continuous monitoring loop"""
    print(f"[MONITOR] Starting monitoring - interval: {interval}s")
    print(f"[MONITOR] Control URL: {control_url}\n")
    
    while True:
        try:
            # Health check
            health = check_health(control_url)
            
            if health.get("ok"):
                state = health.get("state", {})
                tick = health.get("tick", {})
                
                print(f"✓ Health OK - Mode: {state.get('mode')}, Trading: {state.get('trading_enabled')}")
                print(f"  Last tick: {tick.get('last_tick_ms', 0):.0f}ms ago")
            else:
                print(f"✗ Health check failed: {health.get('error')}")
            
            # Dashboard
            dashboard = check_dashboard(control_url)
            
            if dashboard.get("status") == "active":
                perf = dashboard.get("performance", {})
                daily = perf.get("daily", {})
                
                print(f"  Today: {daily.get('trades', 0)} trades, PnL: ${daily.get('pnl', 0):.2f}")
            
            print()
            
        except Exception as e:
            print(f"✗ Monitor error: {e}\n")
        
        time.sleep(interval)


def main():
    """Monitor script main"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor bot health")
    parser.add_argument("--url", default="http://localhost:8080", help="Control API URL")
    parser.add_argument("--interval", type=int, default=60, help="Check interval (seconds)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    
    args = parser.parse_args()
    
    if args.once:
        health = check_health(args.url)
        print(f"Health: {health}")
        
        dashboard = check_dashboard(args.url)
        print(f"Dashboard: {dashboard}")
    else:
        monitor_loop(args.url, args.interval)


if __name__ == "__main__":
    main()
