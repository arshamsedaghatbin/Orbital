import os
import json
import asyncio
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, Field
import uvicorn
from dotenv import load_dotenv

# Import project services
from trading_engine import TradingEngine
from direct_mt5_engine import DirectMT5Engine
from ai_brain import AIBrain

load_dotenv()

app = FastAPI(
    title="Orbital Trading API",
    description="REST Interface for MT5 Signal Processing & Execution with Full DTO documentation.",
    version="1.1.0"
)

# --- Request DTOs ---

class SignalRequest(BaseModel):
    text: str = Field(..., example="XAUUSD BUY 2500 SL 2480", description="The raw signal text to parse.")
    source: str = Field("API", example="WebUI", description="The source of the signal.")

class TradeRequest(BaseModel):
    symbol: str = Field(..., example="XAUUSD")
    side: str = Field(..., example="BUYSTOP")
    entry: Optional[float] = Field(None, example=2500.0)
    sl: float = Field(..., example=2480.0)
    risk_level: str = Field("normal", example="high")

class SettingsUpdate(BaseModel):
    risk_usd: float = Field(50.0, example=100.0)
    rr_target: float = Field(4.0, example=6.0)
    be_rr: float = Field(2.0, example=1.5)
    partial_rr: Optional[float] = 4.0
    partial_percent: Optional[float] = 0.5

# --- Response DTOs ---

class BaseResponse(BaseModel):
    status: str = Field(..., example="success")
    message: Optional[str] = None

class AccountResponse(BaseModel):
    balance: float
    equity: float
    profit: float
    currency: str = "USD"

class PositionDTO(BaseModel):
    ticket: int
    symbol: str
    type: str
    volume: float
    open_price: float
    current_price: float
    sl: float
    tp: float
    profit: float

class OrderDTO(BaseModel):
    ticket: int
    symbol: str
    type: str
    volume: float
    price: float
    sl: float
    tp: float

class TradesResponse(BaseModel):
    positions: List[PositionDTO]
    orders: List[OrderDTO]
    timestamp: Optional[str]

class SignalExecResponse(BaseModel):
    status: str
    signal: Optional[Dict[str, Any]]
    response: Optional[Dict[str, Any]]
    reason: Optional[str] = None

class SystemStatusResponse(BaseModel):
    engine: str
    ai: str
    history_count: int
    queue_count: int
    account: Optional[AccountResponse]
    timestamp: str

class HistoryItem(BaseModel):
    msg_id: int
    text: str
    date: str
    source: str
    signal: Dict[str, Any]
    parse_ms: int
    order_id: Optional[str] = None

class HistoryResponse(BaseModel):
    history: List[HistoryItem]
    pending_queue: List[Dict[str, Any]]

# --- Persistent State ---
engine: Optional[DirectMT5Engine] = None
ai: Optional[AIBrain] = None

HISTORY_FILE = "signals_history.json"
PENDING_QUEUE_FILE = "pending_queue.json"

# --- Initialization ---
@app.on_event("startup")
async def startup_event():
    global engine, ai
    mt5_path = os.getenv('MT5_FILE_PATH', '')
    gemini_key = os.getenv('GEMINI_API_KEY')
    
    engine = DirectMT5Engine(mt5_path)
    ai = AIBrain(gemini_key or None)
    await connect_engine()

async def connect_engine():
    global engine
    if engine:
        try:
            success = await engine.connect()
            if success: print("✅ Engine connected to MT5 Bridge.")
            return True
        except Exception: pass
    return False

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

@app.get("/", response_model=BaseResponse)
async def root():
    return {"status": "online", "message": "Orbital Trading API is active."}

@app.get("/account", response_model=AccountResponse)
async def get_account():
    """Returns account metrics (Balance, Equity, Profit)."""
    if not engine or not engine.connection:
        raise HTTPException(status_code=503, detail="MT5 Bridge not connected")
    
    status = engine.connection._read_status()
    acc = status.get("account", {})
    return AccountResponse(
        balance=acc.get("balance", 0.0),
        equity=acc.get("equity", 0.0),
        profit=acc.get("profit", 0.0),
        currency=acc.get("currency", "USD")
    )

@app.get("/trades", response_model=TradesResponse)
async def get_trades():
    """Returns active positions and pending orders."""
    if not engine or not engine.connection:
        raise HTTPException(status_code=503, detail="MT5 Bridge not connected")
    
    status = engine.connection._read_status()
    return TradesResponse(
        positions=status.get("positions", []),
        orders=status.get("orders", []),
        timestamp=status.get("timestamp")
    )

@app.post("/signal", response_model=SignalExecResponse)
async def process_signal_endpoint(request: SignalRequest):
    """Processes a raw text signal (Regex + AI)."""
    if not ai or not engine:
        raise HTTPException(status_code=503, detail="Core services not initialized")
    
    ctx = {"symbol": "XAUUSD", "text": "API Request"}
    signal_data = await ai.filter_signal(request.text, parent_context=ctx)
    
    if not signal_data:
        return SignalExecResponse(status="ignored", reason="No tradable signal detected")
    
    sig_type = signal_data.get('type', 'NEW').upper()
    sym = signal_data.get('symbol', 'XAUUSD')
    
    if sig_type == 'NEW':
        risk_settings = {"risk_usd": 50.0, "rr_target": 6.0}
        resp = await engine.execute_trade(signal_data, risk_settings, source="API")
        return SignalExecResponse(status="executed", signal=signal_data, response=resp)
    
    elif sig_type == 'CANCEL':
        success = await engine.cancel_last_order(sym)
        return SignalExecResponse(status="cancelled" if success else "failed", signal=signal_data)

    elif sig_type == 'REENTRY':
        params = await engine.get_last_trade_params(sym)
        if params:
            resp = await engine.execute_trade(params, {"risk_usd": 50.0}, source="API", fallback_to_market=True)
            return SignalExecResponse(status="reentry_sent", signal=params, response=resp)
        return SignalExecResponse(status="failed", reason="No previous trade found")

    return SignalExecResponse(status="parsed_but_unhandled", signal=signal_data)

@app.get("/history", response_model=HistoryResponse)
async def get_history(limit: int = 20):
    """Returns signal history and pending queue."""
    history = load_history()
    queue = load_pending_queue()
    return HistoryResponse(
        history=history[:limit],
        pending_queue=queue
    )

@app.delete("/trade/{ticket}", response_model=BaseResponse)
async def close_trade(ticket: str):
    """Closes an active position or deletes a pending order."""
    if not engine: raise HTTPException(status_code=503, detail="Engine offline")
    
    success = await engine.close_trade(ticket)
    if not success:
        status = engine.connection._read_status()
        orders = status.get("orders", [])
        if any(str(o.get('ticket')) == ticket for o in orders):
            success = await engine.connection.delete_order(ticket)
            
    return BaseResponse(status="success" if success else "failed")

@app.delete("/trades", response_model=Dict[str, Any])
async def cancel_all_trades(symbol: Optional[str] = None):
    """Cancels all pending orders and closes all positions."""
    if not engine: raise HTTPException(status_code=503, detail="Engine offline")
    
    status = engine.connection._read_status()
    counts = {"closed": 0, "cancelled": 0}
    
    for p in status.get("positions", []):
        if not symbol or p.get('symbol', '').upper() == symbol.upper():
            if await engine.close_trade(str(p['ticket'])): counts["closed"] += 1
                
    for o in status.get("orders", []):
        if not symbol or o.get('symbol', '').upper() == symbol.upper():
            if await engine.connection.delete_order(str(o['ticket'])): counts["cancelled"] += 1
                
    return {"status": "success", "counts": counts}

@app.post("/engine/reconnect", response_model=BaseResponse)
async def reconnect_engine():
    success = await connect_engine()
    return BaseResponse(status="success" if success else "failed")

@app.get("/settings", response_model=Dict[str, Any])
async def get_settings():
    if os.path.exists("settings.json"):
        with open("settings.json", "r") as f: return json.load(f)
    return {}

@app.put("/settings", response_model=BaseResponse)
async def update_settings(data: SettingsUpdate):
    with open("settings.json", "w") as f:
        json.dump(data.dict(), f, indent=2)
    return BaseResponse(status="success", message="Settings updated")

@app.get("/system/status", response_model=SystemStatusResponse)
async def get_system_status():
    acc = None
    if engine and engine.connection:
        st = engine.connection._read_status().get("account", {})
        acc = AccountResponse(balance=st.get("balance",0), equity=st.get("equity",0), profit=st.get("profit",0))
    
    return SystemStatusResponse(
        engine="CONNECTED" if engine and engine.connection else "DISCONNECTED",
        ai="ACTIVE" if ai else "OFFLINE",
        history_count=len(load_history()),
        queue_count=len(load_pending_queue()),
        account=acc,
        timestamp=datetime.now().isoformat()
    )

@app.post("/system/vector-rebuild", response_model=BaseResponse)
async def rebuild_vector_index():
    if ai and ai.has_gemini:
        from ai_brain import VectorIndex
        index = VectorIndex(ai.client)
        result = await index.build()
        ai.set_vector_index(index)
        return BaseResponse(status="success", message=f"Indexed {result.get('counts', 0)} templates")
    return BaseResponse(status="failed", message="Gemini not available")

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
