import asyncio
import os
from trading_engine import TradingEngine
from dotenv import load_dotenv

load_dotenv()

async def debug_orders():
    token = os.getenv('META_API_TOKEN')
    account_id = os.getenv('META_ACCOUNT_ID')
    region = os.getenv('META_REGION', 'london')
    engine = TradingEngine(token, account_id, region)
    
    await engine.connect()
    
    print("\n--- Checking Active Orders & Positions ---")
    orders = await engine.connection.get_orders()
    positions = await engine.connection.get_positions()
    
    for o in orders:
        print(f"Order: ID={o['id']}, Symbol={o['symbol']}, Type={o['type']}, Entry={o['openPrice']}")
    
    for p in positions:
        print(f"Position: ID={p['id']}, Symbol={p['symbol']}, Type={p['type']}, Entry={p['openPrice']}")

if __name__ == "__main__":
    asyncio.run(debug_orders())
