import os
import json
import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

# Import project services
from trading_engine import TradingEngine
from direct_mt5_engine import DirectMT5Engine
from ai_brain import AIBrain

load_dotenv()

app = FastAPI(title="Orbital Trading API", description="REST Interface for MT5 Signal Processing & Execution")

# --- Persistent State ---
# In a real production app, we'd use a better singleton pattern or dependency injection.
# For this project, we'll initialize them globally to mimic the main.py behavior.
engine: Optional[DirectMT5Engine] = None
ai: Optional[AIBrain] = None

HISTORY_FILE = "signals_history.json"
PENDING_QUEUE_FILE = "pending_queue.json"

class SignalRequest(BaseModel):
    text: str
    source: str = "API"

class TradeRequest(BaseModel):
    symbol: str
    side: str
    entry: Optional[float] = None
    sl: float
    risk_level: str = "normal"

# --- Initialization ---
@app.on_event("startup")
async def startup_event():
    global engine, ai
    mt5_path = os.getenv('MT5_FILE_PATH', '')
    gemini_key = os.getenv('GEMINI_API_KEY')
    
    if not mt5_path:
        print("⚠️ MT5_FILE_PATH not set in .env. API will run in degraded mode.")
    
    engine = DirectMT5Engine(mt5_path)
    ai = AIBrain(gemini_key or None)
    
    # Connect engine
    try:
        success = await engine.connect()
        if success:
            print("✅ Engine connected to MT5 Bridge.")
        else:
            print("❌ Engine failed to find status.txt.")
    except Exception as e:
        print(f"❌ Error connecting engine: {e}")

# --- Helper Functions ---
def load_history():
    if not os.path.exists(HISTORY_FILE): return []
    try:
        with open(HISTORY_FILE, "r") as f: return json.load(f)
    except: return []

def load_pending_queue():
    if not os.path.exists(PENDING_QUEUE_FILE): return []
    try:
        with open(PENDING_QUEUE_FILE, "r") as f: return json.load(f)
    except: return []

# --- Endpoints ---

@app.get("/")
async def root():
    return {
        "service": "Orbital Trading API",
        "status": "online",
        "engine": "connected" if engine and engine.connection else "disconnected",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/account")
async def get_account():
    """Returns account metrics (Balance, Equity, Profit)."""
    if not engine or not engine.connection:
        raise HTTPException(status_code=503, detail="MT5 Bridge not connected")
    
    status = engine.connection._read_status()
    acc = status.get("account", {})
    return {
        "balance": acc.get("balance", 0.0),
        "equity": acc.get("equity", 0.0),
        "profit": acc.get("profit", 0.0),
        "currency": acc.get("currency", "USD")
    }

@app.get("/trades")
async def get_trades():
    """Returns active positions and pending orders."""
    if not engine or not engine.connection:
        raise HTTPException(status_code=503, detail="MT5 Bridge not connected")
    
    status = engine.connection._read_status()
    return {
        "positions": status.get("positions", []),
        "orders": status.get("orders", []),
        "timestamp": status.get("timestamp")
    }

@app.post("/signal")
async def process_signal_endpoint(request: SignalRequest):
    """Processes a raw text signal (Regex + AI)."""
    if not ai or not engine:
        raise HTTPException(status_code=503, detail="Core services not initialized")
    
    # 1. Parse signal
    # We use a simplified context for API requests
    ctx = {"symbol": "XAUUSD", "text": "API Request"}
    signal_data = await ai.filter_signal(request.text, parent_context=ctx)
    
    if not signal_data:
        return {"status": "ignored", "reason": "No tradable signal detected"}
    
    sig_type = signal_data.get('type', 'NEW').upper()
    sym = signal_data.get('symbol', 'XAUUSD')
    
    # 2. Execution logic
    # (Note: This mimics the logic in main.py)
    if sig_type == 'NEW':
        # Get settings (hardcoded for now or loaded from file)
        # Using a default risk level
        risk_settings = {"risk_usd": 50.0, "rr_target": 6.0}
        resp = await engine.execute_trade(signal_data, risk_settings, source="API")
        return {"status": "executed", "signal": signal_data, "response": resp}
    
    elif sig_type == 'CANCEL':
        success = await engine.cancel_last_order(sym)
        return {"status": "cancelled" if success else "failed", "symbol": sym}

    elif sig_type == 'REENTRY':
        # Reuse history fallback logic if needed
        params = await engine.get_last_trade_params(sym)
        if params:
            resp = await engine.execute_trade(params, {"risk_usd": 50.0}, source="API", fallback_to_market=True)
            return {"status": "reentry_sent", "response": resp}
        return {"status": "failed", "reason": "No previous trade found"}

    return {"status": "parsed_but_unhandled", "data": signal_data}

@app.get("/history")
async def get_history(limit: int = 20):
    """Returns signal history and pending queue."""
    history = load_history()
    queue = load_pending_queue()
    return {
        "history": history[:limit],
        "pending_queue": queue
    }

@app.delete("/trade/{ticket}")
async def close_trade(ticket: str):
    """Closes an active position or deletes a pending order."""
    if not engine: raise HTTPException(status_code=503, detail="Engine offline")
    
    # Try closing as position first
    success = await engine.close_trade(ticket)
    if not success:
        # Try cancelling as pending order
        status = engine.connection._read_status()
        orders = status.get("orders", [])
        if any(str(o.get('ticket')) == ticket for o in orders):
            success = await engine.connection.delete_order(ticket)
            
    return {"status": "success" if success else "failed"}

# --- Start Command ---
if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
