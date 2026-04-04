import asyncio
import os
from trading_engine import TradingEngine
from dotenv import load_dotenv

load_dotenv()

async def test_stops():
    try:
        token = os.getenv('META_API_TOKEN')
        account_id = os.getenv('META_ACCOUNT_ID')
        region = os.getenv('META_REGION', 'london')
        
        print(f"Initializing Engine with {account_id}...")
        engine = TradingEngine(token, account_id, region)
        
        # Test 1: Invalid BUY_STOP (Entry < Market)
        # Assuming Market is ~4787 (ask)
        print("\n--- Test 1: Invalid BUY_STOP (Entry < Market) ---")
        data_invalid_buy = {'symbol': 'XAUUSD', 'entry': 4750.0, 'sl': 4740.0, 'side': 'BUY'}
        resp1 = await engine.execute_trade(data_invalid_buy)
        print(f"Result: {resp1}")
        if resp1 and resp1.get('error') == 'PRICE_ERROR':
            print("✅ PASS: Correctly rejected as PRICE_ERROR (Queue trigger)")
        else:
            print("❌ FAIL: Should have been PRICE_ERROR")

        # Test 2: Invalid SELL_STOP (Entry > Market)
        print("\n--- Test 2: Invalid SELL_STOP (Entry > Market) ---")
        data_invalid_sell = {'symbol': 'XAUUSD', 'entry': 4850.0, 'sl': 4860.0, 'side': 'SELL'}
        resp2 = await engine.execute_trade(data_invalid_sell)
        print(f"Result: {resp2}")
        if resp2 and resp2.get('error') == 'PRICE_ERROR':
            print("✅ PASS: Correctly rejected as PRICE_ERROR (Queue trigger)")
        else:
            print("❌ FAIL: Should have been PRICE_ERROR")

    except Exception as e:
        print(f"Test Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_stops())
