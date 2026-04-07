import asyncio
from trading_engine import TradingEngine
import os
import json

async def test_persistence():
    token = os.getenv("META_API_TOKEN")
    account_id = os.getenv("META_ACCOUNT_ID")
    
    # Create mock history and active trades
    history_file = "history.json"
    active_file = "active_trades_metadata.json"
    
    mock_history = [{"symbol": "XAUUSD", "side": "BUY", "entry": 2000, "sl": 1990}]
    mock_active = {"12345": {"symbol": "EURUSD", "side": "SELL", "risk_level": "high"}}
    
    with open(history_file, "w") as f:
        json.dump(mock_history, f)
    with open(active_file, "w") as f:
        json.dump(mock_active, f)
        
    engine = TradingEngine(token, account_id, "uk-1")
    
    print(f"Loaded History: {len(engine.closed_trades)}")
    print(f"Loaded Active: {len(engine.active_trades)}")
    
    assert len(engine.closed_trades) == 1
    assert "12345" in engine.active_trades
    print("✅ Persistence test passed!")

if __name__ == "__main__":
    asyncio.run(test_persistence())
