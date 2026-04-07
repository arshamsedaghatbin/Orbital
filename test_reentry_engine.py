import asyncio
from trading_engine import TradingEngine
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    token = os.getenv("META_API_TOKEN")
    account_id = os.getenv("META_ACCOUNT_ID")
    
    if not token or not account_id:
        print("Missing credentials")
        return
        
    engine = TradingEngine(token, account_id, "uk-1")
    
    # Mock some history
    engine.closed_trades = [
        {
            'symbol': 'XAUUSD',
            'side': 'SELL',
            'entry': 2350.0,
            'sl': 2355.0,
            'tp': 2340.0,
            'status': 'CLOSED'
        }
    ]
    
    print("\nTesting get_last_trade_params for XAUUSD (General)")
    params = await engine.get_last_trade_params("XAUUSD")
    print(f"Result: {params}")
    
    print("\nTesting get_last_trade_params for XAUUSD (Override with BUY)")
    params = await engine.get_last_trade_params("XAUUSD", side="BUY")
    print(f"Result: {params}")

    # Add a more recent one
    engine.closed_trades.append({
        'symbol': 'EURUSD',
        'side': 'BUY',
        'entry': 1.08000,
        'sl': 1.07900,
        'tp': 1.08500,
        'status': 'CLOSED'
    })
    
    print("\nTesting get_last_trade_params for EURUSD")
    params = await engine.get_last_trade_params("EURUSD")
    print(f"Result: {params}")

if __name__ == "__main__":
    asyncio.run(main())
