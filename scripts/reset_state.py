#!/usr/bin/env python3
# scripts/reset_state.py
"""
Emergency state reset - Redis state'ini temizle
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

def reset_state(confirm: bool = False):
    """
    Redis state'ini sıfırla
    
    Args:
        confirm: Onay gerekliliği
    """
    if not confirm:
        print("⚠️  WARNING: This will reset all bot state!")
        print("   - Paper ledger (positions, cash)")
        print("   - Live ledger (positions)")
        print("   - Circuit breaker state")
        print("   - Drawdown tracking")
        print("   - Metrics history (optional)")
        print()
        response = input("Are you sure? (type 'yes' to confirm): ")
        
        if response.lower() != "yes":
            print("❌ Reset cancelled")
            return
    
    try:
        from bot.utils.cache import get_redis_client
        from bot.execution.paper_ledger import LEDGER
        from bot.risk.circuit_breaker import get_circuit_breaker
        from bot.risk.drawdown_monitor import get_drawdown_monitor
        
        redis = get_redis_client()
        
        print("\n[RESET] Resetting state...")
        
        # 1. Paper ledger
        print("  → Resetting paper ledger...")
        LEDGER.reset(initial_cash=1000.0)
        
        # 2. Live ledger
        print("  → Clearing live ledger...")
        redis.delete("live:ledger:v1")
        
        # 3. Circuit breaker
        print("  → Resetting circuit breaker...")
        cb = get_circuit_breaker()
        cb.reset()
        
        # 4. Drawdown monitor
        print("  → Resetting drawdown tracking...")
        dd = get_drawdown_monitor()
        dd.reset_drawdown()
        
        # 5. Optional: Clear metrics
        clear_metrics = input("\n  Clear metrics history? (yes/no): ")
        if clear_metrics.lower() == "yes":
            print("  → Clearing metrics...")
            # Clear all metrics keys
            keys = redis.keys("metrics:*")
            if keys:
                redis.delete(*keys)
                print(f"  → Deleted {len(keys)} metric keys")
        
        print("\n✓ State reset complete!")
        
    except Exception as e:
        print(f"\n✗ Reset failed: {e}")
        sys.exit(1)


def main():
    """Reset script main"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Reset bot state")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation")
    
    args = parser.parse_args()
    
    reset_state(confirm=args.yes)


if __name__ == "__main__":
    main()
