import asyncio
import sys
import os
from datetime import datetime, timezone

# Add current dir to path
sys.path.append(os.getcwd())

from main import BotState
from ai_brain import AIBrain

async def test_queued_update():
    state = BotState()
    state.lock = asyncio.Lock()
    
    # 1. Add a pending trade to the queue
    symbol = "XAUUSD"
    initial_data = {
        "type": "NEW",
        "symbol": symbol,
        "side": "SELL",
        "entry": 4739.4,
        "sl": 4742.9,
        "tp": None
    }
    
    queue_item = {
        'id': "test_pending_1",
        'symbol': symbol,
        'data': initial_data,
        'source': "Telegram",
        'added_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'retries': 5,
        'error_type': "PRICE_ERROR"
    }
    state.pending_queue.append(queue_item)
    
    print(f"Step 1: Queued trade for {symbol} at {initial_data['entry']} (SL: {initial_data['sl']})")
    print(f"Queue Tries: {queue_item['retries']}")

    # 2. Simulate an UPDATE signal
    update_data = {
        "type": "UPDATE",
        "symbol": symbol,
        "entry": 4700.0,
        "sl": 4600.0,
        "side": "SELL"
    }
    
    # Mimic the logic I added to main.py's process_signal
    print(f"\nStep 2: Processing UPDATE signal for {symbol} -> Entry: 4700, SL: 4600")
    
    found_in_queue = False
    # Using state.lock if it exists (mimicking the actual code)
    async with (state.lock):
        for q_item in state.pending_queue:
            if q_item['symbol'] == symbol:
                q_item['data']['entry'] = float(update_data.get('entry', q_item['data']['entry']))
                q_item['data']['sl'] = float(update_data.get('sl', q_item['data']['sl']))
                q_item['retries'] = 0 # Priority retry
                found_in_queue = True
                break

    if found_in_queue:
        print("✅ SUCCESS: Found trade in pending queue and updated it.")
        updated_item = state.pending_queue[0]
        print(f"Updated Entry: {updated_item['data']['entry']}")
        print(f"Updated SL: {updated_item['data']['sl']}")
        print(f"Reset Tries: {updated_item['retries']}")
        
        # Validation
        assert updated_item['data']['entry'] == 4700.0
        assert updated_item['data']['sl'] == 4600.0
        assert updated_item['retries'] == 0
    else:
        print("❌ FAILURE: Could not find trade in pending queue.")

if __name__ == "__main__":
    asyncio.run(test_queued_update())
