import asyncio
import threading
import time
import os
import json
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv
import streamlit as st

st.set_page_config(page_title="🛰️ London Gold Bot", layout="wide", initial_sidebar_state="collapsed")

# Modules
from ai_brain import AIBrain
from trading_engine import TradingEngine
from telegram_listener import TelegramListener
from dashboard import Dashboard
from vector_index import VectorIndex

load_dotenv()

HISTORY_FILE = os.path.join(os.path.dirname(__file__), "signals_history.json")
PENDING_QUEUE_FILE = os.path.join(os.path.dirname(__file__), "pending_queue.json")
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")


def save_history(history: list):
    """Persist all messages to local JSON file."""
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2, default=str)
    except Exception as e:
        print(f"[Storage] Save error: {e}")


def load_history() -> list:
    """Load persisted messages from local JSON file."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Storage] Load error: {e}")
        return []


def save_settings(settings: dict):
    """Persist system settings to disk."""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"[Storage] Settings save error: {e}")


def load_settings() -> dict:
    """Load persisted system settings."""
    if not os.path.exists(SETTINGS_FILE):
        return None
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Storage] Settings load error: {e}")
        return None


def save_pending_queue(queue: list):
    """Persist pending queue to disk."""
    try:
        with open(PENDING_QUEUE_FILE, "w") as f:
            json.dump(queue, f, indent=2, default=str)
    except Exception as e:
        print(f"[Storage] Pending queue save error: {e}")


def load_pending_queue() -> list:
    """Load pending queue from disk on startup."""
    if not os.path.exists(PENDING_QUEUE_FILE):
        return []
    try:
        with open(PENDING_QUEUE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Storage] Pending queue load error: {e}")
        return []



def update_env_file(new_values: dict):
    """Safely update or create values in the active .env file."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    current_lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            current_lines = f.readlines()
            
    # Parse existing keys
    updated_lines = []
    keys_found = set()
    
    for line in current_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            updated_lines.append(line)
            continue
            
        key, _ = stripped.split("=", 1)
        if key in new_values:
            updated_lines.append(f"{key}={new_values[key]}\n")
            keys_found.add(key)
        else:
            updated_lines.append(line)
            
    # Append new keys
    for key, val in new_values.items():
        if key not in keys_found:
            updated_lines.append(f"{key}={val}\n")
            
    with open(env_path, "w") as f:
        f.writelines(updated_lines)
    print(f"[Config] .env file updated with {len(new_values)} values.")


# --- Shared State ---
class BotState:
    def __init__(self):
        self.logs = []
        self.history = load_history()   # Loaded from disk on startup
        self.seen_ids = set()           # Tracks Telegram message IDs
        self.boot_time = datetime.now(timezone.utc) # Track when bot started
        
        # Segmented Metrics
        self.metrics = {
            "GLOBAL": {"balance": 0.0, "equity": 0.0, "floating_pl": 0.0, "win_rate": 0},
            "XAUUSD": {"balance": 0.0, "equity": 0.0, "floating_pl": 0.0, "win_rate": 0},
            "EURUSD": {"balance": 0.0, "equity": 0.0, "floating_pl": 0.0, "win_rate": 0}
        }
        
        # Populate seen_ids from history
        for entry in self.history:
            if 'msg_id' in entry:
                self.seen_ids.add(entry['msg_id'])
        
        self.is_running = False
        self.telegram_connected = False
        self.mt5_connected = False
        self.lock = None                # Initialized in worker loop
        self.restart_event = None       # Initialized in worker loop
        
        self.active_trades = []
        self.active_positions = []
        self.active_orders = []
        self.pending_queue = load_pending_queue()  # Restored from disk on startup
        self.commands = []
        self.ai_connected = True  # Default to true, updated in loop
        self.setup_needed = False
        self.setup_step = 1
        self.setup_data = {}
        self.tg_code_requested = False
        self.tg_phone_code_hash = None
        self.temp_tg_client = None
        self.worker_started = False
        self.channels = [] # List of {"id": str/int, "name": str}
        self.verify_result = None # Temporary storage for verification name
        self.tg_me = None
        self.tg_auth_status = None
        self.vector_index = None   # Populated by bot_worker after AI init
        
        # Per-symbol settings
        default_conf = {
            'risk_usd':       float(os.getenv('RISK_USD', 50)),
            'rr_target':      float(os.getenv('RR_TARGET', 6)),
            'be_rr':          float(os.getenv('BE_RR', 2)),
            'partial_rr':     float(os.getenv('PARTIAL_RR', 4)),
            'partial_percent':float(os.getenv('PARTIAL_PERCENT', 0.7)),
        }
        self.settings = {
            "GLOBAL": default_conf.copy(),
            "XAUUSD": default_conf.copy(),
            "EURUSD": {**default_conf, 'risk_usd': 25, 'rr_target': 4}
        }

        # Load persisted settings if they exist
        saved = load_settings()
        if saved:
            for symbol, conf in saved.items():
                if symbol in self.settings:
                    self.settings[symbol].update(conf)

    def save_settings(self):
        """Helper to trigger settings save."""
        save_settings(self.settings)


@st.cache_resource
def get_bot_state_v3():
    """V3 naming forces a streamlit cache invalidation to fix attribute errors."""
    return BotState()


# --- Async Background Worker ---
async def bot_worker(state: BotState):
    print("🤖 Bot worker starting...")
    # Initialize asyncio primitives locally in the worker loop for thread safety
    state.lock = asyncio.Lock()
    state.restart_event = asyncio.Event()

    state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "System Booting...", "type": "BOOT"})
    state.boot_time = datetime.now(timezone.utc) # Reset boot_time for filtering

    # --- Setup Detection ---
    def is_setup_incomplete():
        keys = ['GEMINI_API_KEY', 'META_API_TOKEN', 'META_ACCOUNT_ID', 'TELEGRAM_API_ID', 'TELEGRAM_API_HASH']
        for k in keys:
            val = os.getenv(k)
            if not val or val.startswith("YOUR_"):
                return True
        # Check if session file exists
        session_name = os.getenv('TELEGRAM_SESSION_NAME', 'london_bot_session')
        if not os.path.exists(f"{session_name}.session"):
            return True
        return False

    if is_setup_incomplete():
        state.setup_needed = True
        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🚀 Initialization Required. Redirecting to Setup Wizard...", "type": "SYSTEM"})
    else:
        state.setup_needed = False

    # Define variables as None initially; they will be populated if setup is NOT needed
    ai = None
    engine = None
    listener = None

    if not state.setup_needed:
        # For survival across reloads, always force reload .env
        from dotenv import load_dotenv
        load_dotenv(override=True)
        
        gemini_key  = os.getenv('GEMINI_API_KEY')
        meta_token  = os.getenv('META_API_TOKEN')
        meta_account= os.getenv('META_ACCOUNT_ID')
        meta_region = os.getenv('META_REGION', 'london')
        tg_id       = os.getenv('TELEGRAM_API_ID')
        tg_hash     = os.getenv('TELEGRAM_API_HASH')
        tg_session  = os.getenv('TELEGRAM_SESSION_NAME', 'london_bot_session')
        
        def parse_channel_ids():
            raw = os.getenv('CHANNEL_IDS')
            if not raw:
                # Fallback to single ID
                sid = os.getenv('CHANNEL_ID')
                return [int(sid)] if sid else []
            
            ids = []
            for part in raw.split(','):
                part = part.strip()
                if not part: continue
                try:
                    ids.append(int(part))
                except:
                    ids.append(part) # Strings work too (usernames)
            return ids

        c_ids = parse_channel_ids()
        ai       = AIBrain(gemini_key)
        engine   = TradingEngine(meta_token, meta_account, meta_region)
        listener = TelegramListener(api_id=int(tg_id), api_hash=tg_hash, channel_ids=c_ids, session_name=tg_session)

        # Build Vector Intelligence Index
        state.vector_index = VectorIndex(ai.client)
        try:
            build_result = await state.vector_index.build()
            ai.set_vector_index(state.vector_index)
            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"🔮 Vector Index ready: {build_result['counts']}", "type": "SYSTEM"})
        except Exception as ve:
            print(f"[VectorIndex] Build failed: {ve}")
            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"⚠️ Vector Index unavailable: {ve}", "type": "ERROR"})

    # ── Helpers ────────────────────────────────────────────────────────────────
    async def process_signal(raw_text: str, source: str, msg_id: int = None, quiet: bool = False, image_bytes: bytes = None, msg_date: datetime = None, reply_to_id: int = None):
        """Parse text with AI, auto-execute if signal, persist to disk."""
        if not ai:
            print("⚠️ AI not initialized yet.")
            return
            
        # ── UNIQUE CHECK (LOCKED) ──────────────────────────────────────────────
        if msg_id and msg_id in state.seen_ids:
            if not quiet:
                print(f"⏩ Skipping duplicate signal: ID {msg_id}")
            return
        
        # ── BOOT TIME FILTER ──────────────────────────────────────────────────
        is_historical = False
        if msg_date:
            # Ensure msg_date is offset-aware for comparison if it is, else make it naive
            # Telethon dates are usually UTC offset-aware
            if msg_date.tzinfo is None:
                # If naive, assume it's local or match boot_time's naivety
                # But best to keep everything offset-aware
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            
            if msg_date < state.boot_time:
                if not quiet:
                    print(f"⏳ Ignoring historical signal from {msg_date} (Boot: {state.boot_time})")
                return
        
        async with (state.lock if state.lock else asyncio.Lock()):
            if msg_id:
                state.seen_ids.add(msg_id)

        # ── CONTEXT RESOLUTION ─────────────────────────────────────────────
        parent_context = None
        if reply_to_id:
            # 1. Explicit Reply (highest priority)
            parent = next((h for h in state.history if h.get('msg_id') == reply_to_id), None)
            if parent:
                parent_context = {
                    "text": parent.get('text'),
                    "symbol": (parent.get('signal') or {}).get('symbol')
                }
                if not quiet:
                    print(f"🔗 [Context] Found explicit parent signal {reply_to_id}: {parent_context['symbol']}")
        
        if not parent_context:
            # 2. Implicit Context: Most recent pending/active trade
            # Check pending queue first (most likely destination for recent 'cancel' or 'update')
            if state.pending_queue:
                last_p = state.pending_queue[-1]
                parent_context = {
                    "text": "[Implicit Context from Pending Queue]",
                    "symbol": last_p.get('symbol', 'XAUUSD')
                }
                if not quiet:
                    print(f"🧠 [Context] Implicit from Pending Queue -> {parent_context['symbol']}")
            
            # 3. Last Active trade
            elif getattr(state, 'active_trades', []):
                last_t = state.active_trades[0] # most recent from synced trades
                parent_context = {
                    "text": "[Implicit Context from Active Trade]",
                    "symbol": last_t.get('symbol', 'XAUUSD')
                }
                if not quiet:
                    print(f"🧠 [Context] Implicit from Active Trade -> {parent_context['symbol']}")

        signal_data = await ai.filter_signal(raw_text, image_bytes=image_bytes, parent_context=parent_context)
        entry = {
            "msg_id": msg_id,
            "text":   raw_text,
            "date":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "signal": signal_data,
        }
        state.history.insert(0, entry)
        save_history(state.history)

        if not signal_data:
            state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "NOISE",
                "preview": f"[{source}] Ignored (Noise): {raw_text[:40]}..."
            })
            return

        # ── Auto-learn: AI-parsed categorical signals → add to vector index ──
        # Only short texts (no price numbers) to avoid memorizing specific trade data
        if (signal_data.get('parsed_by') == 'ai'
                and raw_text
                and len(raw_text.strip()) < 80
                and signal_data.get('type') in ('REENTRY', 'PULLBACK', 'CANCEL', 'TP_HIT', 'STOP')
                and ai._vector_index is not None):
            sig_type = signal_data['type']
            added = await ai._vector_index.add_example(sig_type, raw_text.strip())
            if added:
                print(f"🧠 [AutoLearn] Added '{raw_text.strip()[:40]}' → {sig_type} to vector index")


        if is_historical:
            state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "SYSTEM",
                "preview": f"[{source}] Historical signal logged but NOT executed (sent before boot)."
            })
            return

        sym    = signal_data.get('symbol', 'XAUUSD')
        sig_type = signal_data.get('type', 'NEW').upper()

        if sig_type == 'UPDATE':
            # ── UPDATE: first check pending queue, then fallback to live positions ──
            found_in_queue = False
            async with (state.lock if state.lock else asyncio.Lock()):
                for q_item in state.pending_queue:
                    if q_item['symbol'] == sym:
                        q_item['data']['entry'] = float(signal_data.get('entry', q_item['data']['entry']))
                        q_item['data']['sl'] = float(signal_data.get('sl', q_item['data']['sl']))
                        q_item['retries'] = 0 # Priority retry
                        found_in_queue = True
                        break
            
            if found_in_queue:
                state.logs.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "type": "SIGNAL",
                    "preview": f"✅ [{source}] Updated PENDING {sym} in queue."
                })
                entry['order_id'] = "QUEUED_UPD" # Marker for UI
                save_history(state.history)
                return

            # Fallback to live trades on MT5
            state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "SIGNAL",
                "preview": f"[{source}] 🔄 UPDATE {sym} (MT5) → entry:{signal_data['entry']} SL:{signal_data['sl']}"
            })
            entry['updated'] = True
            save_history(state.history)
            
            if engine:
                order_id = await engine.modify_last_trade(
                    sym,
                    float(signal_data['entry']),
                    float(signal_data['sl']),
                    state.settings.get(sym, state.settings["GLOBAL"])
                )
                if order_id:
                    state.logs.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "type": "SIGNAL",
                        "preview": f"✅ [{source}] Live trade updated: {order_id}"
                    })
                    entry['order_id'] = order_id
                    save_history(state.history)
                else:
                    state.logs.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "type": "NOISE",
                        "preview": f"❌ [{source}] Update failed — no active {sym} found."
                    })
                    entry['error'] = "UPDATE_FAILED"
                    save_history(state.history)


        elif sig_type == 'CANCEL':
            # ── CANCEL: drop from pending queue first, then cancel on MT5 ──
            state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "SIGNAL",
                "preview": f"[{source}] 🚫 CANCEL signal received for {sym}"
            })
            cancelled_from_queue = False
            async with (state.lock if state.lock else asyncio.Lock()):
                before_len = len(state.pending_queue)
                state.pending_queue = [q for q in state.pending_queue if q['symbol'] != sym]
                cancelled_from_queue = len(state.pending_queue) < before_len
                if cancelled_from_queue:
                    save_pending_queue(state.pending_queue)

            if cancelled_from_queue:
                state.logs.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "type": "SIGNAL",
                    "preview": f"✅ [{source}] Cancelled pending {sym} order from queue."
                })
                entry['order_id'] = "CANCELLED_Q"
                save_history(state.history)

            # Also try to cancel any live pending order on MT5
            if engine:
                cancelled_live = await engine.cancel_last_order(sym)
                if cancelled_live:
                    state.logs.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "type": "SIGNAL",
                        "preview": f"✅ [{source}] Cancelled live MT5 order for {sym}."
                    })
                    entry['order_id'] = entry.get('order_id', '') or "CANCELLED_MT5"
                    save_history(state.history)
                elif not cancelled_from_queue:
                    state.logs.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "type": "NOISE",
                        "preview": f"⚠️ [{source}] No open order found to cancel for {sym}."
                    })

        elif sig_type == 'REENTRY':
            state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "SIGNAL",
                "preview": f"[{source}] 🔄 RE-ENTRY request for {sym}"
            })
            if engine:
                # Only pass a side override if the message explicitly named one
                # 'UNKNOWN' means the reentry message had no side keyword — inherit from previous trade
                raw_side = signal_data.get('side', '')
                side_override = raw_side if raw_side and raw_side not in ('UNKNOWN', '') else None
                params = await engine.get_last_trade_params(sym, side=side_override)
                
                if params:
                    side_to_use = params['side'].upper()
                    VALID_SIDES = {'BUY', 'SELL', 'BUY_STOP', 'SELL_STOP', 'BUY_LIMIT', 'SELL_LIMIT'}

                    # SAFETY: abort if side is still invalid
                    if side_to_use not in VALID_SIDES:
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "ERROR",
                            "preview": f"🚨 [{source}] REENTRY ABORTED — invalid side '{side_to_use}'. Refusing to open."
                        })
                        entry['error'] = "REENTRY_INVALID_SIDE"
                        save_history(state.history)
                    else:
                        entry_price = params.get('entry')
                        sl_price    = params.get('sl')
                        base_side   = side_to_use.replace("_STOP","").replace("_LIMIT","")  # BUY or SELL

                        # ── Smart pending vs market decision ───────────────────
                        # Get current price to decide if entry is still pending
                        actual_side = side_to_use  # start with what history says
                        try:
                            if entry_price and engine and engine.connection:
                                price_info = await engine.connection.get_symbol_price(params['symbol'])
                                if price_info:
                                    ask = float(price_info.get('ask', 0))
                                    bid = float(price_info.get('bid', 0))
                                    current = ask if base_side == 'BUY' else bid

                                    if base_side == 'BUY' and current < float(entry_price):
                                        # Price is below entry → BUY_STOP is still valid (pending)
                                        actual_side = 'BUY_STOP'
                                    elif base_side == 'SELL' and current > float(entry_price):
                                        # Price is above entry → SELL_STOP is still valid (pending)
                                        actual_side = 'SELL_STOP'
                                    else:
                                        # Price already past entry → go market on same side
                                        actual_side = base_side
                                        entry_price = None  # market order ignores entry
                        except Exception as e:
                            print(f"⚠️ [REENTRY] Price check failed: {e} — using stored side")

                        is_pending  = "STOP" in actual_side or "LIMIT" in actual_side
                        entry_to_use = entry_price if is_pending else None

                        reentry_data = {
                            'type': 'NEW',
                            'symbol': params['symbol'],
                            'side': actual_side,
                            'entry': entry_to_use,
                            'sl': sl_price,
                            'risk_level': signal_data.get('risk_level', params.get('risk_level', 'normal'))
                        }

                        price_str = f"@{entry_to_use}" if entry_to_use else "@ Market"
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SIGNAL",
                            "preview": f"🚀 [{source}] Re-entering {params['symbol']} {actual_side} {price_str} | SL: {sl_price}"
                        })

                        sym_settings = state.settings.get(params['symbol'], state.settings["GLOBAL"])
                        resp = await engine.execute_trade(reentry_data, sym_settings, source="Telegram", fallback_to_market=True)

                        if resp.get('id'):
                            state.logs.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "type": "SIGNAL",
                                "preview": f"✅ [{source}] Re-entry successful: {resp['id']}"
                            })
                            entry['order_id'] = resp['id']
                            save_history(state.history)
                        else:
                            state.logs.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "type": "NOISE",
                                "preview": f"❌ [{source}] Re-entry failed: {resp.get('error')}"
                            })
                            entry['error'] = resp.get('error', "REENTRY_FAILED")
                            save_history(state.history)
                else:
                    state.logs.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "type": "NOISE",
                        "preview": f"⚠️ [{source}] No previous trade found for {sym} to re-enter."
                    })
                    entry['error'] = "NO_PRIOR_TRADE"
                    save_history(state.history)


        elif sig_type == 'PULLBACK':
            state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "SIGNAL",
                "preview": f"[{source}] 🧲 PULLBACK request for {sym}"
            })
            if engine:
                # Find last trade params
                side_override = signal_data.get('side')
                params = await engine.get_last_trade_params(sym, side=side_override)
                
                if params and params.get('entry'):
                    # Force side to a STOP order using the original side logic
                    base_side = params['side'].replace("_STOP", "").replace("_LIMIT", "")
                    side_to_use = f"{base_side}_STOP"
                    
                    entry_to_use = params['entry']

                    pullback_data = {
                        'type': 'NEW',
                        'symbol': params['symbol'],
                        'side': side_to_use,
                        'entry': entry_to_use,
                        'sl': params['sl'],
                        'risk_level': signal_data.get('risk_level', params['risk_level'])
                    }
                    
                    price_str = f"@{entry_to_use}"
                    state.logs.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "type": "SIGNAL",
                        "preview": f"🚀 [{source}] Pullback {params['symbol']} {side_to_use} {price_str}"
                    })
                    
                    # Execute (fallback_to_market=True means if price already passed entry, it goes Market!)
                    sym_settings = state.settings.get(params['symbol'], state.settings["GLOBAL"])
                    resp = await engine.execute_trade(pullback_data, sym_settings, source="Telegram", fallback_to_market=True)
                    
                    if resp.get('id'):
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SIGNAL",
                            "preview": f"✅ [{source}] Pullback successful: {resp['id']}"
                        })
                        entry['order_id'] = resp['id']
                        save_history(state.history)
                    else:
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "NOISE",
                            "preview": f"❌ [{source}] Pullback failed: {resp.get('error')}"
                        })
                        entry['error'] = resp.get('error', "PULLBACK_FAILED")
                        save_history(state.history)
                else:
                    state.logs.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "type": "NOISE",
                        "preview": f"⚠️ [{source}] No previous trade/entry found for {sym} for pullback."
                    })
                    entry['error'] = "NO_PRIOR_TRADE_ENTRY"
                    save_history(state.history)

        elif sig_type == 'TP_HIT':
            tp_level = signal_data.get('tp_level', 1)
            state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "SIGNAL",
                "preview": f"🎯 [{source}] TP{tp_level} Hit for {sym}. Executing profit management..."
            })
            if engine:
                if tp_level == 1:
                    success = await engine.set_be_for_symbol(sym)
                    msg = f"{'✅ Moved to BE' if success else '⚠️ No active positions found'} for {sym}"
                else:
                    success = await engine.lock_profit_for_symbol(sym, tp_level)
                    msg = f"{'✅ Profit Locked (TP' + str(tp_level) + ')' if success else '⚠️ Failed to lock profit'} for {sym}"
                
                state.logs.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "type": "SIGNAL",
                    "preview": f"[{source}] {msg}"
                })
                entry['managed'] = True
                save_history(state.history)

        elif sig_type == 'STOP':
            state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "SIGNAL",
                "preview": f"🛑 [{source}] HARD STOP received for {sym}. Cancelling all orders..."
            })
            if engine:
                success = await engine.cancel_all_pending(sym)
                state.logs.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "type": "SIGNAL",
                    "preview": f"{'✅' if success else '⚠️'} Hard stop executed for {sym}."
                })
                entry['hard_stop'] = True
                save_history(state.history)

        else:
            # ── NEW: open a fresh trade ───────────────────────────────────
            state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "SIGNAL",
                "preview": f"[{source}] {sym} {signal_data['side']} @ {signal_data['entry']} SL:{signal_data['sl']}{' (⚠️ High Risk)' if signal_data.get('risk_level') == 'high' else ''}"
            })
            
            # Derive clean source tag for win-rate tracking
            clean_source = "Telegram" if "Telegram" in source else "Manual"
            
            # Use symbol-specific settings
            sym_settings = state.settings.get(sym, state.settings["GLOBAL"])
            
            order_id = None
            error = None
            
            if engine:
                resp = await engine.execute_trade(signal_data, sym_settings, source=clean_source, fallback_to_market=True)
                order_id = resp.get('id')
                error = resp.get('error')
            else:
                error = "DISCONNECTED"

            if order_id:
                state.logs.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "type": "SIGNAL",
                    "preview": f"✅ [{source}] Order placed: {order_id}"
                })
                entry['order_id'] = order_id
                save_history(state.history)
            elif error in ["DISCONNECTED", "PRICE_ERROR", "MARKET_CLOSED", "TRADE_DISABLED", "INVALID_STOPS"]:
                # Added to Pending Queue for retry/visibility
                queue_item = {
                    'id': f"pending_{int(time.time())}",
                    'symbol': sym,
                    'data': signal_data,
                    'source': clean_source,
                    'added_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'retries': 0,
                    'error_type': error
                }
                async with (state.lock if state.lock else asyncio.Lock()):
                    state.pending_queue.append(queue_item)
                    save_pending_queue(state.pending_queue)
                
                state.logs.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "type": "SIGNAL",
                    "preview": f"⏳ [{source}] {sym} {error} — Added to Activity Queue"
                })
                entry['queued'] = True
                entry['error'] = error
                save_history(state.history)
            else:
                state.logs.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "type": "NOISE",
                    "preview": f"❌ [{source}] Execution failed: {error or 'Check MT5 connection'}"
                })
                entry['error'] = error or "EXECUTION_FAILED"
                save_history(state.history)

    # ── Command Processor ──────────────────────────────────────────────────────
    async def command_processor_loop():
        """Handles incoming commands from the UI."""
        nonlocal ai, engine, listener
        while True:
            # Yield control back to the event loop so other tasks can run
            await asyncio.sleep(0.5) 
            
            if state.commands:
                print(f"DEBUG WORKER: commands found: {len(state.commands)}")
                cmd = state.commands.pop(0)
                try:
                    if cmd['type'] == 'PARSE_AND_EXECUTE':
                        await process_signal(cmd['text'], source="MANUAL")

                    elif cmd['type'] == 'EXECUTE_TRADE':
                        if not engine: continue
                        # Direct execute (from history "Set as Order")
                        sym = cmd['data'].get('symbol', 'XAUUSD')
                        sym_settings = state.settings.get(sym, state.settings["GLOBAL"])
                        resp = await engine.execute_trade(cmd['data'], sym_settings, source="MANUAL", fallback_to_market=True)
                        order_id = resp.get('id')
                        error = resp.get('error')

                        if order_id:
                            state.logs.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "type": "SIGNAL",
                                "preview": f"✅ Order placed: {order_id}"
                            })
                        elif error in ["DISCONNECTED", "PRICE_ERROR", "MARKET_CLOSED", "TRADE_DISABLED", "INVALID_STOPS"]:
                            # Added to Pending Queue for retry/visibility
                            queue_item = {
                                'id': f"pending_{int(time.time())}",
                                'symbol': sym,
                                'data': cmd['data'],
                                'source': "MANUAL",
                                'added_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                'retries': 0,
                                'error_type': error
                            }
                            async with (state.lock if state.lock else asyncio.Lock()):
                                state.pending_queue.append(queue_item)
                                save_pending_queue(state.pending_queue)
                            
                            state.logs.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "type": "SIGNAL",
                                "preview": f"⏳ [Manual] {sym} {error} — Queued for retry"
                            })
                        else:
                            state.logs.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "type": "NOISE",
                                "preview": f"❌ [Manual] Execution failed: {error or 'Connection Error'}"
                            })

                    elif cmd['type'] == 'DROP_QUEUED_TRADE':
                        queue_id = cmd['queue_id']
                        state.pending_queue = [q for q in state.pending_queue if q['id'] != queue_id]
                        save_pending_queue(state.pending_queue)
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SYSTEM",
                            "preview": f"🗑 Dropped queued trade"
                        })

                    elif cmd['type'] == 'FORCE_RETRY_TRADE':
                        if not engine: continue
                        queue_id = cmd['queue_id']
                        item = next((q for q in state.pending_queue if q['id'] == queue_id), None)
                        if item:
                            state.logs.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "type": "SIGNAL",
                                "preview": f"⚡ Force retrying {item['symbol']}..."
                             })
                            sym = item['symbol']
                            sym_settings = state.settings.get(sym, state.settings["GLOBAL"])
                            resp = await engine.execute_trade(item['data'], sym_settings, fallback_to_market=True)
                            if resp.get('id'):
                                state.logs.append({
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                    "type": "SIGNAL",
                                    "preview": f"✅ Retried trade placed: {resp['id']}"
                                })
                                # Remove from queue
                                state.pending_queue = [q for q in state.pending_queue if q['id'] != queue_id]
                                save_pending_queue(state.pending_queue)
                            else:
                                state.logs.append({
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                    "type": "NOISE",
                                    "preview": f"❌ Retry failed: {resp.get('error')}"
                                })

                    elif cmd['type'] == 'CLOSE_TRADE':
                        print(f"DEBUG WORKER: Received CLOSE_TRADE for {cmd['id']}")
                        if not engine: 
                            print(f"DEBUG WORKER: engine is NONE, cannot close trade!")
                            continue
                        print(f"💰 Command: CLOSE_TRADE {cmd['id']}")
                        success = await engine.close_trade(cmd['id'])
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SYSTEM",
                            "preview": f"{'✅' if success else '❌'} Trade closed: {cmd['id']}"
                        })

                    elif cmd['type'] == 'SET_BE':
                        if not engine: continue
                        print(f"💰 Command: SET_BE for {cmd['id']}")
                        success = await engine.set_be(cmd['id'])
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SYSTEM",
                            "preview": f"{'✅' if success else '❌'} BE set for {cmd['id']}"
                        })

                    elif cmd['type'] == 'RESTORE_SL':
                        if not engine: continue
                        print(f"💰 Command: RESTORE_SL for {cmd['id']}")
                        success = await engine.restore_sl(cmd['id'])
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SYSTEM",
                            "preview": f"{'✅' if success else '❌'} SL restored for {cmd['id']}"
                        })

                    elif cmd['type'] == 'TRAIL_SL':
                        if not engine: continue
                        print(f"💰 Command: TRAIL_SL to {cmd['sl']} for {cmd['id']}")
                        success = await engine.modify_sl(cmd['id'], cmd['sl'])
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SYSTEM",
                            "preview": f"{'✅' if success else '❌'} SL adjusted to {cmd['sl']} for {cmd['id']}"
                        })

                    elif cmd['type'] == 'PARTIAL_CLOSE':
                        if not engine: continue
                        print(f"💰 Command: Partial {int(cmd['fraction']*100)}% for {cmd['id']}")
                        success = await engine.partial_close(cmd['id'], cmd['fraction'])
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SYSTEM",
                            "preview": f"{'✅' if success else '❌'} Partial {int(cmd['fraction']*100)}% for {cmd['id']}"
                        })

                    elif cmd['type'] == 'CLOSE_ALL_PROFITABLE':
                        if not engine: continue
                        sym = cmd.get('symbol', 'GLOBAL')
                        print(f"💰 Command: CLOSE_ALL_PROFITABLE for {sym}")
                        count = await engine.close_all_profitable(sym)
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SYSTEM",
                            "preview": f"✅ Closed {count} profitable positions for {sym}"
                        })
                    elif cmd['type'] == 'CLEAR_HISTORY':
                        state.history = []
                        save_history([])
                        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🧹 Signal history cleared.", "type": "SYSTEM"})

                    elif cmd['type'] == 'CLEAR_LOGS':
                        state.logs.clear() # Fix: Ensure logs are actually cleared
                        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🧹 Logs cleared.", "type": "SYSTEM"})

                    elif cmd['type'] == 'FACTORY_RESET':
                        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🧨 FACTORY RESET INITIATED...", "type": "SYSTEM"})
                        try:
                            # 1. Delete .env
                            if os.path.exists(".env"):
                                os.remove(".env")
                            
                            # 2. Delete session files
                            for f in ["london_bot_session.session", "auth_session.session", "london_bot_session.session-journal"]:
                                if os.path.exists(f):
                                    os.remove(f)
                            
                            # 3. Clear relevant environment variables in memory
                            reset_keys = [
                                'GEMINI_API_KEY', 'META_API_TOKEN', 'META_ACCOUNT_ID', 
                                'TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'CHANNEL_ID', 'CHANNEL_IDS', 'PHONE'
                            ]
                            for k in reset_keys:
                                if k in os.environ:
                                    del os.environ[k]
                            
                            # 4. Completely reset state cache flags
                            state.telegram_connected = False
                            state.gemini_connected = False
                            state.meta_connected = False
                            state.bot_active = False
                            state.setup_needed = True
                            state.setup_step = 1
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "✅ All configurations cleared. Restarting to Setup Wizard.", "type": "SYSTEM"})
                            
                            # Trigger restart
                            state.restart_event.set()
                        except Exception as e:
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"❌ Reset Error: {str(e)}", "type": "ERROR"})
                            state.restart_event.set()

                    elif cmd['type'] == 'UPDATE_CONFIG':
                        # Persist and then trigger restart
                        data = cmd['data']
                        update_env_file(data)
                        
                        # Update memory settings immediately so they propagate before/during restart
                        risk = float(data.get('RISK_USD', 50))
                        rr = float(data.get('RR_TARGET', 6))
                        
                        for sym in state.settings:
                            state.settings[sym]['risk_usd'] = risk
                            state.settings[sym]['rr_target'] = rr
                        
                        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "📁 Config saved. Settings synced globally. Restarting core...", "type": "SYSTEM"})
                        # Reuse the restart logic
                        state.commands.append({"type": "RESTART_BOT"})

                    elif cmd['type'] == 'TEST_TELEGRAM':
                        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🧪 Testing Telegram connection...", "type": "SYSTEM"})
                        if listener:
                            asyncio.create_task(connect_tg())
                        else:
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "❌ Telegram not initialized.", "type": "ERROR"})
                    
                    elif cmd['type'] == 'TEST_AI':
                        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🧪 Testing AI Brain...", "type": "SYSTEM"})
                        if ai:
                            try:
                                # Simple probe
                                test_res = await ai.filter_signal("Test probe")
                                state.ai_connected = True
                                state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "✅ AI Brain responsive.", "type": "SYSTEM"})
                            except Exception as e:
                                state.ai_connected = False
                                state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"❌ AI Error: {str(e)}", "type": "ERROR"})
                        else:
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "❌ AI not initialized.", "type": "ERROR"})

                    elif cmd['type'] == 'TEST_MT5':
                        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🧪 Testing MT5/MetaApi...", "type": "SYSTEM"})
                        if engine:
                            asyncio.create_task(connect_mt5())
                        else:
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "❌ Engine not initialized.", "type": "ERROR"})

                    elif cmd['type'] == 'VERIFY_CHANNEL':
                        channel_id = cmd['data'].get('id')
                        if channel_id and listener:
                            try:
                                name = await listener.get_entity_name(channel_id)
                                if name:
                                    state.verify_result = {"id": channel_id, "name": name}
                                    state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"✅ Verified: {name}", "type": "SYSTEM"})
                                else:
                                    state.verify_result = {"id": channel_id, "error": "Entity not found or access denied. Ensure you have JOINED the channel and the ID is correct."}
                                    state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "❌ Verification Failed: Entity not found.", "type": "ERROR"})
                            except Exception as e:
                                state.verify_result = {"id": channel_id, "error": str(e)}
                                state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"❌ Verification Failed: {str(e)}", "type": "ERROR"})
                        else:
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "❌ Listener not ready for verification.", "type": "ERROR"})

                    elif cmd['type'] == 'REMOVE_CHANNEL':
                        target_id = cmd['data'].get('id')
                        # Remove from current .env string
                        current_ids = [str(c["id"]) for c in state.channels]
                        if str(target_id) in current_ids:
                            new_ids = [cid for cid in current_ids if cid != str(target_id)]
                            update_env_file({"CHANNEL_IDS": ",".join(new_ids)})
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"🗑️ Channel {target_id} removed. Restarting...", "type": "SYSTEM"})
                            state.commands.append({"type": "RESTART_BOT"})

                    elif cmd['type'] == 'ADD_CHANNEL':
                        new_id = str(cmd['data'].get('id'))
                        # Use channel_ids (env) as truth
                        env_ids = [c.strip() for c in os.getenv('CHANNEL_IDS', '').split(',') if c.strip()]
                        if new_id not in env_ids:
                            env_ids.append(new_id)
                            update_env_file({"CHANNEL_IDS": ",".join(env_ids)})
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"➕ Channel {new_id} added. Restarting...", "type": "SYSTEM"})
                            state.commands.append({"type": "RESTART_BOT"})
                        state.verify_result = None 

                    elif cmd['type'] == 'RESTART_BOT':
                        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🚀 Bot Restarting...", "type": "SYSTEM"})
                        state.restart_event.set()

                    elif cmd['type'] == 'REBUILD_VECTOR_INDEX':
                        if state.vector_index:
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🔮 Rebuilding Vector Index...", "type": "SYSTEM"})
                            try:
                                result = await state.vector_index.build(force=True)
                                state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"✅ Vector Index rebuilt: {result['counts']} | New embeddings: {result['new_embeds']}", "type": "SYSTEM"})
                            except Exception as ve:
                                state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"❌ Rebuild failed: {ve}", "type": "ERROR"})
                        else:
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "⚠️ Vector Index not initialized yet.", "type": "ERROR"})

                    elif cmd['type'] == 'CLEAR_PENDING':
                        count = len(state.pending_queue)
                        state.pending_queue.clear()
                        save_pending_queue(state.pending_queue)
                        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"🧹 Cleared all {count} pending trades.", "type": "SYSTEM"})

                    # ── Setup Wizard Commands ───
                    elif cmd['type'] == 'REQUEST_TG_CODE':
                        try:
                            from telethon import TelegramClient
                            api_id = int(cmd['data']['api_id'])
                            api_hash = cmd['data']['api_hash']
                            phone = cmd['data']['phone']
                            print(f"📡 Command: REQUEST_TG_CODE for {phone}")
                            
                            state.setup_data['PHONE'] = phone
                            state.temp_tg_client = TelegramClient('auth_session', api_id, api_hash)
                            await state.temp_tg_client.connect()
                            
                            send_rv = await state.temp_tg_client.send_code_request(phone)
                            state.tg_phone_code_hash = send_rv.phone_code_hash
                            state.tg_code_requested = True
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "type": "SYSTEM", "preview": f"📲 Code sent to {phone}."})
                            print(f"✅ Code sent request successful for {phone}")
                        except Exception as e:
                            print(f"❌ TG Code Error: {e}")
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "type": "ERROR", "preview": f"❌ TG Code Error: {e}"})

                    elif cmd['type'] == 'VERIFY_TG_CODE':
                        try:
                            code = cmd['data']['code']
                            phone = state.setup_data.get('PHONE')
                            print(f"🔐 Command: VERIFY_TG_CODE for {phone} with code {code}")
                            
                            if not state.temp_tg_client:
                                raise Exception("Auth client not initialized. Request code again.")

                            # Sign in 
                            await state.temp_tg_client.sign_in(phone, code, phone_code_hash=state.tg_phone_code_hash)
                            print(f"✅ Sign-in successful for {phone}")
                            
                            # Disconnect to release file lock before renaming
                            await state.temp_tg_client.disconnect()
                            
                            # Move session to main bot session
                            if os.path.exists("auth_session.session"):
                                if os.path.exists("london_bot_session.session"):
                                    os.remove("london_bot_session.session")
                                os.rename("auth_session.session", "london_bot_session.session")
                                print("📂 Session file promoted to main.")

                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "type": "SYSTEM", "preview": "✅ Telegram Authorized! Step 1 Complete."})
                            state.setup_step = 2 
                            state.tg_code_requested = False
                            print(f"⏩ Transitioning to step {state.setup_step}")
                        except Exception as e:
                            print(f"❌ Verification Failed: {e}")
                            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "type": "ERROR", "preview": f"❌ Verification Failed: {e}"})

                    elif cmd['type'] == 'FINISH_SETUP':
                        print("💾 Command: FINISH_SETUP")
                        # Use the standardized helper
                        data = cmd['data']
                        updates = {
                            "TELEGRAM_API_ID": data['TELEGRAM_API_ID'],
                            "TELEGRAM_API_HASH": data['TELEGRAM_API_HASH'],
                            "GEMINI_API_KEY": data['GEMINI_API_KEY'],
                            "META_API_TOKEN": data['META_API_TOKEN'],
                            "META_ACCOUNT_ID": data['META_ACCOUNT_ID'],
                            "CHANNEL_IDS": data.get('CHANNEL_IDS', '-1002047709770'),
                        }
                        update_env_file(updates)
                        
                        state.setup_needed = False
                        # The main thread reruns automatically every 2s, so we just signal finish.
                        state.commands.append({"type": "RESTART_BOT"})

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"Command Error: {e}")
            await asyncio.sleep(1)

    # ── Metrics Loop ───────────────────────────────────────────────────────────
    async def update_metrics_loop():
        while True:
            try:
                if not engine:
                    await asyncio.sleep(5)
                    continue
                # Update Global Metrics
                global_metrics = await engine.get_metrics("GLOBAL")
                state.metrics["GLOBAL"].update(global_metrics)
                
                # Update Per-Symbol Metrics
                for sym in ["XAUUSD", "EURUSD"]:
                    sym_metrics = await engine.get_metrics(sym)
                    state.metrics[sym].update(sym_metrics)

                # Telegram Status
                if not state.setup_needed:
                    state.telegram_connected = listener is not None and listener.is_connected()
                else:
                    state.telegram_connected = False
                
                # MT5 Status: Check if connection exists and is actually healthy
                if engine and engine.connection:
                    # Assume healthy if metrics show data
                    if global_metrics.get('balance', 0) > 0:
                        is_mt5_alive = True
                    else:
                        try:
                            # Heartbeat probe if balance is 0 or potentially stale
                            await engine.connection.get_account_information()
                            is_mt5_alive = True
                        except:
                            is_mt5_alive = False
                    
                    # Error thresholding to prevent flickering
                    if not hasattr(state, '_mt5_fails'): state._mt5_fails = 0
                    if is_mt5_alive:
                        state._mt5_fails = 0
                        state.mt5_connected = True
                    else:
                        state._mt5_fails += 1
                        if state._mt5_fails >= 3: # 15 seconds of sustained failure
                            state.mt5_connected = False
                else:
                    state.mt5_connected = False
                    state._mt5_fails = 0
                
                state.ai_connected = ai is not None
                
                # Sync Active Trades with Source/Symbol Info
                state.active_trades = [
                    {
                        "order_id": k, 
                        "side": v['side'], 
                        "entry": v['entry'],
                        "tp": v['tp'], 
                        "sl": v['sl'], 
                        "lot": v['lot'],
                        "profit": v.get('profit', 0.0),
                        "symbol": v.get('symbol', 'XAUUSD'),
                        "source": v.get('source', 'Manual')
                    }
                    for k, v in engine.active_trades.items()
                ]
            except Exception as e:
                print(f"Metrics Update Error: {e}")
            await asyncio.sleep(5)

    # ── Retry Queue Loop ────────────────────────────────────────────────────────
    async def retry_queue_loop():
        """Automatically retry trades in the pending queue every 5 seconds."""
        last_log_time = 0
        while True:
            await asyncio.sleep(5)
            if not engine or not state.pending_queue:
                continue

            # Throttle the "Auto-retrying" log to avoid spam
            current_time = time.time()
            if current_time - last_log_time > 60: # Log once every minute
                state.logs.append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "type": "SYSTEM",
                    "preview": f"🔄 Auto-retrying {len(state.pending_queue)} pending trades..."
                })
                last_log_time = current_time

            # Iterate copy to allow removal
            for item in list(state.pending_queue):
                item['retries'] += 1
                # Preserve original source if available in data, else default to Manual
                orig_source = item.get('source', 'Manual') 
                sym = item['symbol']
                sym_settings = state.settings.get(sym, state.settings["GLOBAL"])
                
                try:
                    resp = await engine.execute_trade(item['data'], sym_settings, source=orig_source, fallback_to_market=True)
                    
                    if resp.get('id'):
                        state.logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "type": "SIGNAL",
                            "preview": f"✅ Queued trade placed: {resp['id']} (Try #{item['retries']})"
                        })
                        state.pending_queue.remove(item)
                        save_pending_queue(state.pending_queue)
                    else:
                        # Still failing, update error info
                        error_type = resp.get('error', 'PRICE_ERROR')
                        item['error_type'] = error_type
                        
                        # CAPPING LOGIC:
                        # Per user request: PRICE_ERROR, MARKET_CLOSED, etc. must NOT be dropped.
                        # Only drops technical connection failures after 3 attempts.
                        is_connectivity_error = error_type in ["DISCONNECTED", "CONNECTION_ERROR", "TIMEOUT", "INTERNAL_ERROR"]
                        
                        if is_connectivity_error and item['retries'] >= 3:
                            state.logs.append({
                                "time": datetime.now().strftime("%H:%M:%S"),
                                "type": "ERROR",
                                "preview": f"🛑 Trade {sym} DROPPED after {item['retries']} failed connection attempts."
                            })
                            state.pending_queue.remove(item)
                        
                        save_pending_queue(state.pending_queue)
                except Exception as e:
                    print(f"Retry Loop Exec Error: {e}")

    # ── Live Telegram Handler ───────────────────────────────────────────
    async def on_new_message(message):
        # We check for media (photos) to support visual signals
        image_bytes = None
        if message.photo:
            try:
                print(f"🖼️ Downloading media for live message {message.id}...")
                image_bytes = await message.download_media(file=bytes)
            except Exception as e:
                print(f"❌ Media download error: {e}")
        
        # Extract reply information
        reply_to_id = message.reply_to_msg_id if hasattr(message, 'reply_to_msg_id') else None
        
        await process_signal(message.text or "", source="Telegram", msg_id=message.id, image_bytes=image_bytes, msg_date=message.date, reply_to_id=reply_to_id)

    # ── High-Frequency Sync Loop ───────────────────────────────────────────────
    async def sync_messages_loop():
        """Periodic safety net to catch any missed signals after startup."""
        while True:
            await asyncio.sleep(60)  # Check every 60 seconds (safety net, not primary)
            if not listener or not listener.is_connected():
                continue
            
            try:
                recent = await listener.get_recent_messages(limit=5)
                for msg in reversed(recent):
                    raw = msg.get('raw')
                    image_bytes = None
                    if raw and raw.photo:
                        try:
                            # We check for media even during sync to ensure no visual signals are missed
                            image_bytes = await raw.download_media(file=bytes)
                        except: pass
                    # Quiet sync: don't spam 'skipping duplicate' logs every minute
                    reply_to_id = raw.reply_to_msg_id if raw and hasattr(raw, 'reply_to_msg_id') else None
                    await process_signal(msg['text'], source="Telegram (Sync)", msg_id=msg['id'], quiet=True, image_bytes=image_bytes, msg_date=msg.get('date'), reply_to_id=reply_to_id)
            except Exception as e:
                print(f"Sync Loop Error: {e}")

    # ── Connections ───────────────────────────────────────────────────────────
    async def connect_mt5():
        if not engine:
            print("❌ Cannot connect MT5: Engine not initialized.")
            return
        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🔗 Connecting to MetaTrader...", "type": "SYSTEM"})
        mt5_success = await engine.connect()
        if mt5_success:
            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "✅ MT5 Connected.", "type": "SYSTEM"})
            state.mt5_connected = True
        else:
            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "⚠️ MT5 Connection Failed.", "type": "ERROR"})
            state.mt5_connected = False

    async def connect_tg():
        if not listener:
            # If setup is needed, we don't even log failure, it's expected
            if not state.setup_needed:
                print("❌ Cannot connect Telegram: Listener not initialized.")
            return
        
        # Don't auto-connect if we're in the middle of setup, unless specifically triggered
        if state.setup_needed:
            return
        state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "📡 Connecting to Telegram...", "type": "SYSTEM"})
        try:
            listener.set_callback(on_new_message)
            # 1. Start and capture 'Me' info
            me = await asyncio.wait_for(listener.start(), timeout=30)
            if me:
                state.tg_me = f"{me.first_name} (@{me.username})" if me.username else me.first_name
            
            state.telegram_connected = True
            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "✅ Telegram Connection Established.", "type": "SYSTEM"})

            # 2. ── Initial Boot Sync ─────────────────
            # Process signals sent while bot was down
            print("📡 Checking for missed signals during downtime...")
            recent = await listener.get_recent_messages(limit=10)
            for msg in reversed(recent):
                msg_id = msg['id']
                if msg_id and msg_id not in state.seen_ids:
                    # Check for image media in synced messages
                    raw = msg.get('raw')
                    image_bytes = None
                    if raw and raw.photo:
                        try: image_bytes = await raw.download_media(file=bytes)
                        except: pass
                    # process_signal with msg_date filter will handle this perfectly.
                    reply_to_id = raw.reply_to_msg_id if raw and hasattr(raw, 'reply_to_msg_id') else None
                    await process_signal(msg['text'], source="Telegram (Sync)", msg_id=msg_id, quiet=True, image_bytes=image_bytes, msg_date=msg.get('date'), reply_to_id=reply_to_id)
            
            # 3. Resolve metadata mapping for display
            print("📡 Updating channel names map...")
            resolved = []
            for cid in channel_ids:
                name = await listener.get_entity_name(cid)
                final_name = name if name else f"Unresolved ID {cid} (Check Membership)"
                resolved.append({"id": cid, "name": final_name})
            state.channels = resolved
            
        except asyncio.TimeoutError:
            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "⚠️ Telegram Connection Timed Out. Retrying in background...", "type": "ERROR"})
            state.telegram_connected = False
        except Exception as e:
            state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": f"❌ Telegram Failed: {str(e)}", "type": "ERROR"})
            state.telegram_connected = False
            print(f"Telegram Startup Error: {e}")

    # ── Execution Logic ───────────────────────────────────────────────────────
    while True:
        try:
            state.restart_event.clear()
            
            # Reload .env for fresh config every reboot
            from dotenv import load_dotenv
            load_dotenv(override=True)
        
            gemini_key  = os.getenv('GEMINI_API_KEY')
            meta_token  = os.getenv('META_API_TOKEN')
            meta_account= os.getenv('META_ACCOUNT_ID')
            meta_region = os.getenv('META_REGION', 'london')
            tg_id       = os.getenv('TELEGRAM_API_ID')
            tg_hash     = os.getenv('TELEGRAM_API_HASH')
            tg_session  = os.getenv('TELEGRAM_SESSION_NAME', 'london_bot_session')
            
            # Get list of channels from env
            chan_ids_raw = os.getenv('CHANNEL_IDS', '').strip()
            chan_id_raw = os.getenv('CHANNEL_ID', '').strip()
            chan_env = chan_ids_raw if chan_ids_raw else chan_id_raw
            channel_ids = [c.strip() for c in chan_env.split(',') if c.strip()]

            # Init Components
            ai       = AIBrain(gemini_key) if gemini_key else None
            if ai and hasattr(state, 'vector_index') and state.vector_index:
                ai.set_vector_index(state.vector_index)
            engine   = TradingEngine(meta_token, meta_account, meta_region) if meta_token and meta_account else None
            
            listener = TelegramListener(
                api_id=int(tg_id), 
                api_hash=tg_hash, 
                channel_ids=channel_ids, 
                session_name=tg_session, 
                on_msg_callback=on_new_message
            ) if tg_id and tg_hash else None

            # Sync UI state.channels (IDs only initially)
            state.channels = [{"id": cid, "name": "Resolving..."} for cid in channel_ids]

            if not state.setup_needed and engine and ai:
                state.is_running = True
                
                # Tasks list for easy management
                tasks = [
                    asyncio.create_task(sync_messages_loop()),
                    asyncio.create_task(engine.monitor_trades(get_settings=lambda sym: state.settings.get(sym, state.settings["GLOBAL"]))),
                    asyncio.create_task(update_metrics_loop()),
                    asyncio.create_task(retry_queue_loop())
                ]
                
                # Managed set for non-critical/background initialization tasks
                bg_tasks = set()
                
                # Connections (Taskified to avoid blocking each other)
                # We do NOT add these to the monitored tasks list because once they finish successfully,
                # we don't want them to trigger a SYSTEM REBOOT.
                bg_tasks.add(asyncio.create_task(connect_mt5()))
                bg_tasks.add(asyncio.create_task(connect_tg()))
                
                # Command processor should always be there to handle UI requests
                tasks.append(asyncio.create_task(command_processor_loop()))
                
                # Wait for RESTART or tasks failure
                restart_wait_task = asyncio.create_task(state.restart_event.wait())
                
                # Check for crash or restart trigger
                done, pending = await asyncio.wait(
                    tasks + [restart_wait_task], 
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # Shutdown phase
                state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": "🛑 Core shutting down for reboot...", "type": "SYSTEM"})
                for t in tasks + [restart_wait_task]:
                    if not t.done():
                        t.cancel()
                
                # ── Explicit Cleanup ──
                if listener:
                    try:
                        await asyncio.wait_for(listener.disconnect(), timeout=5)
                    except: pass
                
                if engine:
                    try:
                        await asyncio.wait_for(engine.disconnect(), timeout=5)
                    except: pass
            else:
                # Setup mode: only command processor is needed to handle onboarding
                tasks = [asyncio.create_task(command_processor_loop())]
                restart_wait_task = asyncio.create_task(state.restart_event.wait())
                
                await asyncio.wait(
                    tasks + [restart_wait_task], 
                    return_when=asyncio.FIRST_COMPLETED
                )
                for t in tasks + [restart_wait_task]:
                    if not t.done(): t.cancel()

        except Exception as e:
            msg = f"💥 CRITICAL BOOT ERROR: {e}"
            if not any(l['preview'] == msg for l in state.logs[-3:]):
                state.logs.append({"time": datetime.now().strftime("%H:%M:%S"), "preview": msg, "type": "ERROR"})
            print(f"CRITICAL BOOT ERROR: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(5) # Cooldown before retry

def run_async_loop(state):
    """Entry point for the background thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot_worker(state))
    except Exception as e:
        print(f"THREAD CRASH: {e}")
    finally:
        loop.close()

# --- Dashboard Fragments for Smooth Updates ---

@st.fragment(run_every=10)
def fragment_header(state, dashboard):
    try:
        dashboard.render_header(state)
    except Exception as e:
        st.error(f"Header Error: {e}")

@st.fragment(run_every=5)
def fragment_symbol_dashboard(state, dashboard, symbol_filter):
    col_left, col_right = st.columns([1, 3.5])
    
    with col_left:
        # 1. History & Logs (Consolidated)
        def on_clear_history():
            state.commands.append({"type": "CLEAR_HISTORY"})
        def on_clear_logs():
            state.commands.append({"type": "CLEAR_LOGS"})
        
        dashboard.render_history(state.history, on_clear_history, symbol_filter=symbol_filter)
        st.markdown("---")
        dashboard.render_intelligence_log(state.logs, on_clear_logs, symbol_filter=symbol_filter)

    with col_right:
        # 2. Metrics & Settings
        m_left, m_right = st.columns([1, 1])
        with m_left:
            try:
                dashboard.render_metrics(state.metrics, symbol=symbol_filter)
            except Exception as e:
                st.error(f"Metrics Error ({symbol_filter}): {e}")
        with m_right:
            if symbol_filter in state.settings:
                dashboard.render_symbol_settings(symbol_filter, state.settings[symbol_filter], state)
        
        st.markdown("---")
        
        # 3. Trading Activity
        def on_drop(queue_id):
            state.commands.append({"type": "DROP_QUEUED_TRADE", "queue_id": queue_id})
        def on_retry(queue_id):
            state.commands.append({"type": "FORCE_RETRY_TRADE", "queue_id": queue_id})
        def on_close(order_id):
            state.commands.append({"type": "CLOSE_TRADE", "id": order_id})
        def on_close_profitable(sym):
            state.commands.append({"type": "CLOSE_ALL_PROFITABLE", "symbol": sym})
        def on_set_be(ticket_id):
            state.commands.append({"type": "SET_BE", "id": str(ticket_id)})
        def on_restore_sl(ticket_id):
            state.commands.append({"type": "RESTORE_SL", "id": str(ticket_id)})
        def on_partial(ticket_id, frac):
            state.commands.append({"type": "PARTIAL_CLOSE", "id": str(ticket_id), "fraction": frac})
        def on_trail(ticket_id, sl):
            state.commands.append({"type": "TRAIL_SL", "id": str(ticket_id), "sl": float(sl)})

        dashboard.render_trading_activity(
            active_trades=state.active_trades,
            pending_queue=state.pending_queue,
            state=state,
            on_close_callback=on_close,
            on_close_profitable_callback=on_close_profitable,
            on_drop_callback=on_drop,
            on_retry_callback=on_retry,
            on_be_callback=on_set_be,
            on_restore_callback=on_restore_sl,
            on_partial_callback=on_partial,
            on_trail_callback=on_trail,
            symbol_filter=symbol_filter
        )

def render_dashboard_ui(state, dashboard):
    # 1. Header (Dynamic Status) - Slower update
    fragment_header(state, dashboard)
    
    # 2. Tabs (Static Layout)
    tabs = st.tabs(["🟡 XAUUSD", "🔵 EURUSD", "⚙️ Profile"])
    
    # Profile Tab
    with tabs[2]:
        def on_save_config(new_config):
            state.commands.append({"type": "UPDATE_CONFIG", "data": new_config})
            st.toast("Configuration received. Core restart pending...", icon="⚙️")
        dashboard.render_profile_tab(state, on_save_config)

    # Symbol Tabs
    for i, tab_label in enumerate(["XAUUSD", "EURUSD"]):
        with tabs[i]:
            fragment_symbol_dashboard(state, dashboard, tab_label)
            st.markdown("---")
            
            # Manual Order (Static)
            def on_manual_order(raw_text):
                state.commands.append({"type": "PARSE_AND_EXECUTE", "text": raw_text})
            dashboard.render_manual_order(on_manual_order, key_suffix=tab_label)

def main():
    dashboard = Dashboard()
    state = get_bot_state_v3()
    # Header now lives inside the render_dashboard_ui fragment for live updates
    # to avoid full-page blinks when connection statuses change.

    # Only start the worker thread if it's not already running
    if not state.worker_started:
        state.worker_started = True
        t = threading.Thread(target=run_async_loop, args=(state,), daemon=True)
        t.start()

    # ── ONBOARDING WIZARD ───
    if state.setup_needed:
        dashboard.render_setup_wizard(state)
        # Short pause then rerun to pick up background state changes without blocking the UI
        time.sleep(1)
        st.rerun()
        return

    # ── CONTENT ──────────────────────────────────────────────────────────────
    render_dashboard_ui(state, dashboard)

if __name__ == "__main__":
    main()
