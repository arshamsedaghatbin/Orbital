import os
import asyncio
from dotenv import load_dotenv
from trading_engine import TradingEngine

load_dotenv()

async def test_order_error():
    token = os.getenv('META_API_TOKEN')
    account_id = os.getenv('META_ACCOUNT_ID')
    region = os.getenv('META_REGION')
    
    engine = TradingEngine(token, account_id, region)
    connected = await engine.connect()
    
    if not connected:
        print("❌ Could not connect to MetaTrader for diagnostics.")
        return

    # Signal details from user
    signal = {
        'symbol': 'XAUUSD',
        'side': 'SELL',
        'entry': 4646.7,
        'sl': 4655.1,
        'tp1': 4630.0 # Arbitrary TP for testing
    }
    
    print(f"🚀 Attempting diagnostic trade: {signal}")
    
    try:
        # We use execute_trade directly to see the return object
        response = await engine.execute_trade(signal)
        print(f"\n--- MT5 RESPONSE ---")
        print(f"Status: {response.get('status', 'UNKNOWN')}")
        print(f"Error Code: {response.get('error_code', 'N/A')}")
        print(f"Full Response: {response}")
    except Exception as e:
        print(f"❌ Execution Error: {e}")
    finally:
        # Note: TradingEngine doesn't have an explicit close in its current form 
        # but the process will exit.
        pass

if __name__ == '__main__':
    asyncio.run(test_order_error())
