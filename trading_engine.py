import asyncio
import os
import json
import time
from metaapi_cloud_sdk import MetaApi
from dotenv import load_dotenv

load_dotenv()

OWNED_TICKETS_FILE = os.path.join(os.path.dirname(__file__), "bot_owned_tickets.json")
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")
ACTIVE_TRADES_FILE = os.path.join(os.path.dirname(__file__), "active_trades_metadata.json")
IGNORED_TICKETS_FILE = os.path.join(os.path.dirname(__file__), "ignored_tickets.json")

class TradingEngine:
    def __init__(self, token, account_id, region):
        self.token = token
        self.account_id = account_id
        self.region = region
        self.api = None
        self.account = None
        self.connection = None
        self.active_trades = {} # {ticket_id: {data}}
        self.closed_trades = []
        self.original_sls = {} # {ticket_id: sl}
        self.ignored_tickets = set()
        self.symbol = "XAUUSD"
        self._load_owned_tickets()
        self._load_history()
        self._load_active_trades()
        self._load_ignored_tickets()

    def _load_ignored_tickets(self):
        if os.path.exists(IGNORED_TICKETS_FILE):
            try:
                with open(IGNORED_TICKETS_FILE, "r") as f:
                    self.ignored_tickets = {str(x) for x in json.load(f)}
            except:
                self.ignored_tickets = set()
        else:
            self.ignored_tickets = set()

    def _save_ignored_tickets(self):
        try:
            with open(IGNORED_TICKETS_FILE, "w") as f:
                json.dump(sorted(list(self.ignored_tickets)), f, indent=4)
        except Exception as e:
            print(f"Error saving ignored tickets: {e}")

    def _load_active_trades(self):
        if os.path.exists(ACTIVE_TRADES_FILE):
            try:
                with open(ACTIVE_TRADES_FILE, "r") as f:
                    self.active_trades = json.load(f)
            except:
                self.active_trades = {}
        else:
            self.active_trades = {}

    def _save_active_trades(self):
        try:
            with open(ACTIVE_TRADES_FILE, "w") as f:
                json.dump(self.active_trades, f, indent=2)
        except Exception as e:
            print(f"Error saving active trades: {e}")

    def _load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r") as f:
                    self.closed_trades = json.load(f)
            except:
                self.closed_trades = []
        else:
            self.closed_trades = []

    def _save_history(self):
        try:
            # Keep history to last 100 trades for performance
            if len(self.closed_trades) > 100:
                self.closed_trades = self.closed_trades[-100:]
            with open(HISTORY_FILE, "w") as f:
                json.dump(self.closed_trades, f, indent=2)
        except Exception as e:
            print(f"Error saving history: {e}")

    def _load_owned_tickets(self):
        if os.path.exists(OWNED_TICKETS_FILE):
            try:
                with open(OWNED_TICKETS_FILE, "r") as f:
                    self.owned_tickets = {str(x) for x in json.load(f)}
            except:
                self.owned_tickets = set()
        else:
            self.owned_tickets = set()

    def _save_owned_tickets(self):
        try:
            with open(OWNED_TICKETS_FILE, "w") as f:
                json.dump(sorted(list(self.owned_tickets)), f, indent=4)
        except Exception as e:
            print(f"Error saving owned tickets: {e}")

    async def connect(self, retries=2):
        last_error = None
        for attempt in range(1, retries + 2):
            try:
                print(f"🔄 Attempting connection to MetaTrader {self.account_id} (Attempt {attempt})...")
                if not self.api:
                    self.api = MetaApi(self.token)
                
                # Get account info with timeout
                print("⏳ Fetching account info...")
                self.account = await asyncio.wait_for(self.api.metatrader_account_api.get_account(self.account_id), timeout=20)
                print(f"✅ Account Found: {self.account.name}")
                
                # Wait for connection to MetaTrader backend with timeout
                print("⏳ Waiting for account connection...")
                await asyncio.wait_for(self.account.wait_connected(), timeout=30)
                print("🔗 Connected to account. Getting RPC connection...")
                
                # Get and connect RPC with timeout
                self.connection = self.account.get_rpc_connection()
                print("⏳ Connecting RPC...")
                await asyncio.wait_for(self.connection.connect(), timeout=30)
                
                print("⏳ Synchronizing...")
                # Synchronization is the most common point of hanging
                await asyncio.wait_for(self.connection.wait_synchronized(), timeout=45)
                
                print(f"✅ Fully Connected and Synchronized for {self.account_id}")
                return True
            except asyncio.TimeoutError:
                last_error = "Connection/Sync Timed Out (Check Region or Broker Status)"
                print(f"❌ Connection Attempt {attempt} Timed Out.")
            except Exception as e:
                last_error = str(e)
                print(f"❌ Connection Attempt {attempt} Failed: {last_error}")
                if attempt <= retries:
                    await asyncio.sleep(2) # Small delay between retries
                else:
                    print(f"🚨 All {retries + 1} connection attempts failed.")
        return False

    async def disconnect(self):
        """Gracefully disconnect from MetaApi."""
        try:
            if self.connection:
                await self.connection.close()
                print("🏁 MetaApi connection closed.")
            if self.api:
                # Use api.close() if it exists (MetaApi SDK v2+)
                if hasattr(self.api, 'close'):
                    await self.api.close()
                elif hasattr(self.api, 'close_instance'):
                    await self.api.close_instance()
                print("🚪 MetaApi instance closed.")
        except Exception as e:
            print(f"⚠️ Error during MT5 disconnect: {e}")
        finally:
            self.connection = None
            self.account = None
            self.api = None

    async def sync_active_trades(self):
        """Syncs local active_trades with actual broker positions/orders, moving closed ones to closed_trades."""
        if not self.connection: return
        try:
            positions = await self.connection.get_positions()
            orders = await self.connection.get_orders()
            
            # IDs currently on broker
            broker_ids = {p['id'] for p in positions} | {o['id'] for o in orders}
            
            # Find tickets that are in active_trades but no longer on broker
            to_move = []
            for ticket_id in list(self.active_trades.keys()):
                if str(ticket_id) not in broker_ids:
                    to_move.append(ticket_id)
            
            for ticket_id in to_move:
                trade_data = self.active_trades.pop(ticket_id)
                trade_data['status'] = 'CLOSED_BY_BROKER'
                self.closed_trades.append(trade_data)
                self._save_history() # Persist
                self._save_active_trades() # Update active trades pool
                print(f"📉 detected trade {ticket_id} closed by broker/SL. Moved to history.")

        except Exception as e:
            print(f"Error syncing trades: {e}")

    async def get_last_trade_params(self, symbol, side=None):
        """Finds the most recent trade for a symbol and returns (side, sl_distance, risk_level)."""
        await self.sync_active_trades()
        
        target = symbol.upper()
        # Combine closed and active trades to find most recent
        all_relevant = []
        for t in self.closed_trades:
            if t['symbol'].upper().startswith(target):
                all_relevant.append(t)
        for t_id, t in self.active_trades.items():
            if t['symbol'].upper().startswith(target):
                all_relevant.append(t)
        
        if not all_relevant:
            # Maybe search by partial match if no exact match
            all_relevant = [t for t in self.closed_trades if target in t['symbol'].upper()]
        
        if not all_relevant:
            # 3. Last Resort: Search MT5 Deal History (last 24 hours)
            print(f"🔍 No local history for {target}, searching broker deals...")
            try:
                # Get deals for the last 24 hours
                from datetime import datetime, timedelta
                from_date = datetime.now() - timedelta(days=1)
                to_date = datetime.now()
                deals = await self.connection.get_deals(from_date, to_date)
                
                # Sort by time, most recent first
                deals.sort(key=lambda d: d['time'], reverse=True)
                
                for deal in deals:
                    if deal['symbol'].upper().startswith(target):
                        # Construct a basic trade structure from the deal
                        # For re-entry, we need entry and sl. MT5 deals don't always store SL easily, 
                        # but we can try to find the matching entry/sl from position history if needed.
                        # For now, let's just use the side.
                        # For now, let's just use the side.
                        entry = float(deal['price'])
                        # If MT5 deals don't give SL, we'll have to use default SL distance for XAUUSD (e.g., 3.0 points)
                        sl_dist = 3.0 if "XAU" in target else 0.00100 # Default fallback
                        return {
                            'side': side if side else ("BUY" if deal['type'] == 'DEAL_TYPE_BUY' else "SELL"),
                            'entry': entry,
                            'sl_dist': sl_dist,
                            'sl': entry - sl_dist if deal['type'] == 'DEAL_TYPE_BUY' else entry + sl_dist,
                            'risk_level': 'normal',
                            'symbol': deal['symbol']
                        }
            except Exception as e:
                print(f"⚠️ Failed to fetch broker deals: {e}")
            return None
            
        # ── Filter to only valid, executed price trades ──────────────────────────
        # Exclude entries with missing/UNKNOWN side, missing entry/sl, or SL on wrong side
        VALID_SIDES = {'BUY', 'SELL', 'BUY_STOP', 'SELL_STOP', 'BUY_LIMIT', 'SELL_LIMIT'}

        def _is_valid_trade(t: dict) -> bool:
            s = (t.get('side') or '').upper()
            if s not in VALID_SIDES:
                return False
            try:
                e = float(t['entry'])
                sl = float(t['sl'])
            except (TypeError, KeyError, ValueError):
                return False
            # For BUY variants, SL must be below entry
            if 'BUY' in s and sl >= e:
                return False
            # For SELL variants, SL must be above entry
            if 'SELL' in s and sl <= e:
                return False
            return True

        valid_trades = [t for t in all_relevant if _is_valid_trade(t)]

        # Fall back to unfiltered list only if ALL are invalid (edge case)
        candidates = valid_trades if valid_trades else all_relevant

        # Last one is most recent (assuming they were appended in order)
        last_trade = candidates[-1]

        # SAFETY: only inherit an explicit valid side — never inherit 'UNKNOWN' or empty
        if side and side.upper() in VALID_SIDES:
            use_side = side.upper()
        else:
            use_side = last_trade.get('side', 'BUY').upper()
            if use_side not in VALID_SIDES:
                print(f"⚠️ [REENTRY] Previous trade side '{use_side}' invalid — defaulting to BUY")
                use_side = 'BUY'

        # SL distance in points/absolute value
        # Dist = abs(Entry - SL)
        try:
            entry = float(last_trade['entry'])
            sl = float(last_trade['sl'])
            dist = abs(entry - sl)
            risk_level = last_trade.get('risk_level', 'normal')
            return {
                'side': use_side,
                'entry': entry,
                'sl_dist': dist,
                'sl': sl,
                'risk_level': risk_level,
                'symbol': last_trade['symbol']
            }
        except:
            return None

    async def execute_trade(self, data, settings=None, source="Manual", fallback_to_market: bool = False):
        """
        Executes a trade based on refined AI signal data.
        settings: dict with risk_usd, rr_target etc. If None, falls back to env.
        source: 'Telegram' or 'Manual' for win-rate tracking.
        fallback_to_market: If True, executes at market if price has passed the stop entry.
        """
        if not self.connection:
            if not await self.connect():
                return {"id": None, "error": "DISCONNECTED"}

        symbol = data.get('symbol', 'XAUUSD').upper()
        side = data['side'].upper()
        
        # Get current price for market execution or deciding order type
        try:
            price_info = await self.connection.get_symbol_price(symbol)
            is_buy_side = side.startswith("BUY")
            current_market_price = price_info['ask'] if is_buy_side else price_info['bid']
        except Exception as e:
            err_msg = str(e).upper()
            if any(x in err_msg for x in ["TIMEOUT", "TIMED OUT", "SOCKET", "WEBSOCKET", "FAILED TO CONNECT", "CONNECTION"]):
                print(f"📡 Connection instability detected during trade prep: {e}")
                return {"id": None, "error": "DISCONNECTED"}
            raise e
        
        # Determine if Market or Pending
        is_market = False
        if data.get('entry') is None:
            is_market = True
            entry = current_market_price
            print(f"🚀 Re-entry Market Execution for {symbol} at {entry}")
        else:
            entry = float(data['entry'])

        # SL handling: either absolute or distance-based
        if data.get('sl') is not None:
            sl = float(data['sl'])
        elif data.get('sl_dist') is not None:
            dist = float(data['sl_dist'])
            sl = entry - dist if side == "BUY" else entry + dist
        else:
            raise ValueError("Trade data must contain either 'sl' or 'sl_dist'")
        side = data['side'].upper()
        s = settings or {}
        risk_usd = float(s.get('risk_usd', os.getenv('RISK_USD', 50)))
        rr_target = float(s.get('rr_target', os.getenv('RR_TARGET', 6)))

        # ── Risk Level: halve lot size for high-risk signals ──────────────
        risk_level = str(data.get('risk_level', 'normal')).lower()
        if risk_level == 'high':
            risk_usd = risk_usd / 2.0
            print(f"⚠️ HIGH RISK signal — using half risk: ${risk_usd:.2f}")

        # --- Lot Calculation ---
        try:
            symbol_info = await self.connection.get_symbol(symbol)
            contract_size = symbol_info.get('contractSize', 100)
            pip_value_per_lot = contract_size 
        except:
            if 'XAU' in symbol:
                pip_value_per_lot = 100.0
            else:
                pip_value_per_lot = 100000.0 # Standard Forex lot

        distance = abs(entry - sl)
        if distance == 0: return None

        lot = round(risk_usd / (distance * pip_value_per_lot), 2)
        lot = max(0.01, min(lot, 2.0))  # Capped at 2.0 for safety

        # Ensure TP is rounded to valid tick size if possible
        tp = round(entry + (distance * rr_target) if is_buy_side else entry - (distance * rr_target), 5)

        try:
            if is_market:
                # Market order — direction from is_buy_side
                if is_buy_side:
                    result = await self.connection.create_market_buy_order(symbol, lot, sl, tp)
                else:
                    result = await self.connection.create_market_sell_order(symbol, lot, sl, tp)
            else:
                if is_buy_side:
                    if entry > current_market_price:
                        result = await self.connection.create_stop_buy_order(symbol, lot, entry, sl, tp)
                    else:
                        if fallback_to_market:
                            print(f"🚀 BUY entry {entry} <= market {current_market_price}. Entering at MARKET.")
                            result = await self.connection.create_market_buy_order(symbol, lot, sl, tp)
                        else:
                            print(f"⏳ BUY entry {entry} <= market {current_market_price}. Queueing (PRICE_ERROR).")
                            return {"id": None, "error": "PRICE_ERROR"}
                else:
                    if entry < current_market_price:
                        result = await self.connection.create_stop_sell_order(symbol, lot, entry, sl, tp)
                    else:
                        if fallback_to_market:
                            print(f"🚀 SELL entry {entry} >= market {current_market_price}. Entering at MARKET.")
                            result = await self.connection.create_market_sell_order(symbol, lot, sl, tp)
                        else:
                            print(f"⏳ SELL entry {entry} >= market {current_market_price}. Queueing (PRICE_ERROR).")
                            return {"id": None, "error": "PRICE_ERROR"}
            
            order_id = str(result['orderId'])
            if source == "Telegram":
                self.owned_tickets.add(order_id)
                self._save_owned_tickets()

            self.active_trades[order_id] = {
                'symbol': symbol,
                'entry': entry,
                'sl': sl,
                'tp': tp,
                'tps': data.get('tps', []),
                'side': side,
                'lot': lot,
                'status': 'OPEN',
                'be_hit': False,
                'partial_hit': False,
                'source': source
            }
            self._save_active_trades()
            return {"id": order_id, "error": None}
        except Exception as e:
            err_msg = str(e).upper()
            print(f"MetaApi Execution Error: {e}")
            
            # Detect specific MetaAPI / Broker errors
            if any(k in err_msg for k in ["MARKET_CLOSED", "MARKET IS CLOSED", "RETCODE_MARKET_CLOSED"]):
                return {"id": None, "error": "MARKET_CLOSED"}
            
            if any(k in err_msg for k in ["TRADE_DISABLED", "DISABLED", "RETCODE_DISABLED"]):
                return {"id": None, "error": "TRADE_DISABLED"}

            if any(k in err_msg for k in ["INVALID STOPS", "INVALID_STOPS", "RETCODE_INVALID_STOPS"]):
                return {"id": None, "error": "INVALID_STOPS"}

            # Detect retryable price errors
            # Common patterns: "Invalid Price", "Price is higher/lower than...", "Too close to market"
            price_keywords = ["PRICE", "INVALID_PRICE", "RETCODE_INVALID", "TOO_CLOSE"]
            if any(k in err_msg for k in price_keywords):
                return {"id": None, "error": "PRICE_ERROR"}
            # Final check for connection/timeout keywords
            if any(k in err_msg for k in ["TIMEOUT", "TIMED OUT", "SOCKET", "WEBSOCKET", "DISCONNECTED", "FAILED TO CONNECT"]):
                return {"id": None, "error": "DISCONNECTED"}
                
            return {"id": None, "error": "FATAL_ERROR", "msg": str(e)}

    async def close_trade(self, ticket_id):
        """Force closes an active position (handle both position and order IDs)."""
        if not self.connection:
            print(f"❌ Cannot close trade {ticket_id}: No active MetaTrader connection.")
            return False
        try:
            print(f"📡 Attempting to close trade {ticket_id}...")
            # Try to determine if it's a pending order or a position from local state
            t_id_str = str(ticket_id)
            trade_info = self.active_trades.get(t_id_str, {})
            is_pending = trade_info.get('side', '').endswith('_STOP') or trade_info.get('side', '').endswith('_LIMIT')
            
            # Use appropriate broker function
            try:
                if is_pending:
                    print(f"📉 Calling cancel_order for pending trade {ticket_id}...")
                    await self.connection.cancel_order(ticket_id)
                else:
                    print(f"📉 Calling close_position for live trade {ticket_id}...")
                    await self.connection.close_position(ticket_id, {})
            except Exception as e:
                err_msg_inner = str(e).lower()
                # If we guessed wrong or the broker requires the other function, try it
                if any(x in err_msg_inner for x in ["not found", "invalid position", "invalid request", "invalid order", "retcode_invalid"]):
                    if is_pending:
                        await self.connection.close_position(ticket_id, {})
                    else:
                        await self.connection.cancel_order(ticket_id)
                else:
                    # Reroute general errors (like 'Market is closed') to the outer handler
                    raise e
            
            # Success: Synchronize local state
            if t_id_str in self.active_trades:
                trade_data = self.active_trades.pop(t_id_str)
                trade_data['status'] = 'CLOSED'
                self.closed_trades.append(trade_data)
                self._save_active_trades()
                self._save_history()
            print(f"✅ Trade {ticket_id} resolved successfully.")
            return True
            
        except Exception as e:
            err_msg = str(e).lower()
            if any(x in err_msg for x in ["not found", "invalid position", "already closed", "invalid order", "market is closed"]):
                print(f"📉 Trade {ticket_id} (Broker: {err_msg}). Clearing local state from tracking.")
                # Already gone OR market closed (user choice to purge locally)
                t_id_str = str(ticket_id)
                # Keep in ignore list so monitor_trades loop doesn't re-add it
                self.ignored_tickets.add(t_id_str)
                self._save_ignored_tickets()
                
                if t_id_str in self.active_trades:
                    trade_data = self.active_trades.pop(t_id_str)
                    trade_data['status'] = 'CLEARED_LOCALLY'
                    self.closed_trades.append(trade_data)
                    self._save_active_trades()
                    self._save_history()
                return True
            
            print(f"❌ Close Trade Error for {ticket_id}: {e}")
            return False

    async def modify_last_trade(self, symbol: str, new_entry: float, new_sl: float, settings=None):
        """
        UPDATE scenario: finds the last open position for the symbol,
        modifies its SL. If the position is a pending order, cancels and
        re-places it at the new entry price.
        Returns the order_id of the modified/replaced trade, or None on failure.
        """
        if not self.connection:
            if not await self.connect():
                return None

        try:
            positions = await self.connection.get_positions()
            orders    = await self.connection.get_orders()

            # ── Try open positions first ──────────────────────────────────────
            # Use robust matching (ignore case, handle potential suffixes like .m)
            target = symbol.upper()
            sym_positions = [p for p in positions if p['symbol'].upper().startswith(target)] or [p for p in positions if target in p['symbol'].upper()]
            
            if sym_positions:
                pos = sym_positions[-1]   # take most recent
                ticket = pos['id']
                # Keep existing TP, just move SL
                tp = self.active_trades.get(ticket, {}).get('tp', pos.get('takeProfit', 0))
                await self.connection.modify_position(ticket, new_sl, tp)
                # Update local tracking
                if ticket in self.active_trades:
                    self.active_trades[ticket]['sl'] = new_sl
                    self.active_trades[ticket]['entry'] = new_entry
                print(f"🔄 Modified position {ticket}: entry≈{new_entry} SL={new_sl}")
                return ticket

            # ── Try pending orders ────────────────────────────────────────────
            sym_orders = [o for o in orders if o['symbol'].upper().startswith(target)] or [o for o in orders if target in o['symbol'].upper()]
            if sym_orders:
                ord_ = sym_orders[-1]
                ticket = ord_['id']
                # Cancel old pending order
                await self.connection.cancel_order(ticket)
                print(f"🗑 Cancelled pending order {ticket}")
                # Re-place with new entry/SL using same settings
                old_data = self.active_trades.pop(ticket, {})
                side = old_data.get('side', ord_.get('type', 'BUY').replace('ORDER_TYPE_', '').split('_')[0])
                new_data = {
                    'symbol': symbol,
                    'entry':  new_entry,
                    'sl':     new_sl,
                    'side':   side,
                }
                new_id_resp = await self.execute_trade(new_data, settings)
                new_id = new_id_resp.get("id")
                if new_id:
                    print(f"✅ Re-placed updated order: {new_id}")
                return new_id

            print(f"[ModifyTrade] No open position or pending order found for {symbol}")
            return None

        except Exception as e:
            print(f"Modify Trade Error: {e}")
            return None

    async def cancel_last_order(self, symbol: str) -> bool:
        """
        CANCEL scenario: finds the most recent pending order for the symbol on MT5
        and cancels it. Returns True on success, False otherwise.
        """
        if not self.connection:
            if not await self.connect():
                return False
        try:
            orders = await self.connection.get_orders()
            target = symbol.upper()
            sym_orders = [o for o in orders if o['symbol'].upper().startswith(target)] or \
                         [o for o in orders if target in o['symbol'].upper()]
            
            if not sym_orders:
                print(f"[CancelOrder] No pending orders found for {symbol}")
                return False

            ord_ = sym_orders[-1]  # most recent
            ticket = ord_['id']
            await self.connection.cancel_order(ticket)
            print(f"🚫 Cancelled pending order {ticket} for {symbol}")
            
            # Clean up local tracking
            if ticket in self.active_trades:
                trade_data = self.active_trades.pop(ticket)
                trade_data['status'] = 'CANCELLED'
                self.closed_trades.append(trade_data)
            
            return True
        except Exception as e:
            print(f"Cancel Order Error: {e}")
            return False

    async def set_be_for_symbol(self, symbol: str):
        """Moves all active positions of a symbol to Break-Even."""
        if not self.connection: return False
        try:
            positions = await self.connection.get_positions()
            target = symbol.upper()
            found = False
            for pos in positions:
                if pos['symbol'].upper().startswith(target) or target in pos['symbol'].upper():
                    ticket = pos['id']
                    # Use Entry from local metadata if possible, else openPrice
                    entry = self.active_trades.get(ticket, {}).get('entry', pos.get('openPrice', 0))
                    tp = pos.get('takeProfit', 0)
                    await self.connection.modify_position(ticket, entry, tp)
                    if ticket in self.active_trades:
                        self.active_trades[ticket]['sl'] = entry
                        self.active_trades[ticket]['be_hit'] = True
                    print(f"🚀 [Signal] Moved {symbol} position {ticket} to BE at {entry}")
                    found = True
            return found
        except Exception as e:
            print(f"Error setting BE for symbol {symbol}: {e}")
            return False

    async def lock_profit_for_symbol(self, symbol: str, tp_level: int = 1):
        """Moves SL to a profit-locked level (e.g., TP1 price) for all positions of a symbol."""
        if not self.connection: return False
        try:
            positions = await self.connection.get_positions()
            target = symbol.upper()
            found = False
            for pos in positions:
                if pos['symbol'].upper().startswith(target) or target in pos['symbol'].upper():
                    ticket = pos['id']
                    data = self.active_trades.get(ticket, {})
                    entry = data.get('entry', pos.get('openPrice', 0))
                    tp = pos.get('takeProfit', 0)
                    side = pos['type'].replace('POSITION_TYPE_', '') # BUY or SELL
                    tps = data.get('tps', [])
                    
                    new_sl = None
                    # If we have stored TPs from the original signal, use the requested level
                    if tp_level <= len(tps):
                        new_sl = tps[tp_level-1]
                    else:
                        # Fallback: estimate TP1 at RR 1.5 if not found
                        dist_to_tp = abs(tp - entry)
                        if dist_to_tp > 0:
                            lock_dist = dist_to_tp * 0.2 # Lock 20% of the target profit
                            new_sl = entry + lock_dist if "BUY" in side else entry - lock_dist

                    if new_sl:
                        await self.connection.modify_position(ticket, new_sl, tp)
                        if ticket in self.active_trades:
                            self.active_trades[ticket]['sl'] = new_sl
                        print(f"💰 [Signal] Locked Profit for {symbol} ({ticket}) at {new_sl} (TP{tp_level} logic)")
                        found = True
            return found
        except Exception as e:
            print(f"Error locking profit for symbol {symbol}: {e}")
            return False

    async def cancel_all_pending(self, symbol: str):
        """Hard reset: Robustly cancels ALL pending orders on MT5 for the symbol."""
        if not self.connection: return False
        try:
            orders = await self.connection.get_orders()
            target = symbol.upper()
            count = 0
            for ord_ in orders:
                if ord_['symbol'].upper().startswith(target) or target in ord_['symbol'].upper():
                    await self.connection.cancel_order(ord_['id'])
                    if ord_['id'] in self.active_trades:
                        data = self.active_trades.pop(ord_['id'])
                        data['status'] = 'CANCELLED_HARD_STOP'
                        self.closed_trades.append(data)
                    count += 1
            if count > 0:
                print(f"🛑 [Signal] Hard Stop: Cancelled {count} pending orders for {symbol}")
                self._save_active_trades()
                self._save_history()
            return count > 0
        except Exception as e:
            print(f"Error in hard stop for {symbol}: {e}")
            return False



    async def modify_sl(self, ticket_id: str, new_sl: float):
        """Modifies the SL of an existing position or order."""
        if not self.connection: return False
        try:
            # Check positions
            positions = await self.connection.get_positions()
            for pos in positions:
                if str(pos['id']) == str(ticket_id):
                    tp = pos.get('takeProfit', 0)
                    await self.connection.modify_position(pos['id'], new_sl, tp)
                    if pos['id'] in self.active_trades:
                        self.active_trades[pos['id']]['sl'] = new_sl
                    print(f"🔄 Modified SL for position {ticket_id} to {new_sl}")
                    return True
            
            # Check orders
            orders = await self.connection.get_orders()
            for ord_ in orders:
                if str(ord_['id']) == str(ticket_id):
                    # We don't have modify_order in this SDK usually, or it's similar
                    # For simplicity, if modify_order fails, we use modify_position's equivalent
                    try:
                        await self.connection.modify_order(ord_['id'], ord_.get('openPrice'), new_sl, ord_.get('takeProfit', 0))
                    except:
                        # Fallback to cancel/re-place if needed, but usually modify_order exists
                        pass
                    if ord_['id'] in self.active_trades:
                        self.active_trades[ord_['id']]['sl'] = new_sl
                    print(f"🔄 Modified SL for order {ticket_id} to {new_sl}")
                    return True
            return False
        except Exception as e:
            print(f"❌ Modify SL Error: {e}")
            return False

    async def close_all_profitable(self, symbol="GLOBAL"):
        """Closes all positions with profit > 0 for a specific symbol or globally."""
        if not self.connection: return 0
        try:
            positions = await self.connection.get_positions()
            count = 0
            for pos in positions:
                if symbol != "GLOBAL" and pos['symbol'] != symbol:
                    continue
                
                # Check unrealized profit
                if pos.get('unrealizedProfit', 0) > 0:
                    print(f"💰 Auto-closing profitable position {pos['id']} (${pos['unrealizedProfit']})")
                    await self.close_trade(pos['id'])
                    count += 1
            return count
        except Exception as e:
            print(f"Close All Profitable Error: {e}")
            return 0

    async def get_metrics(self, symbol=None):
        """
        Fetches account balance, equity, and calculates win rate.
        If symbol is provided, metrics are filtered for that pair.
        """
        if not self.connection: 
            return {"balance": 0, "equity": 0, "floating_pl": 0, "win_rate": 0}
            
        try:
            account_info = await self.connection.get_account_information()
            
            # --- Win Rate Calculation (Telegram Only) ---
            # Filter trades by Telegram source AND symbol if specified
            trades = self.closed_trades
            if symbol and symbol != "GLOBAL":
                trades = [t for t in trades if t.get('symbol') == symbol]
            
            telegram_trades = [t for t in trades if t.get('source') == "Telegram"]
            
            # Simple win rate calculation from existing bot history
            if telegram_trades:
                wins = sum(1 for t in telegram_trades if t.get('profit', 0) > 0)
                win_rate = int((wins / len(telegram_trades)) * 100)
            else:
                win_rate = 0
            
            # For floating P/L, we filter current positions if symbol is specified
            floating_pl = account_info['equity'] - account_info['balance']
            if symbol and symbol != "GLOBAL":
                positions = await self.connection.get_positions()
                sym_positions = [p for p in positions if p['symbol'] == symbol]
                floating_pl = sum(p.get('unrealizedProfit', 0) for p in sym_positions)

            return {
                "balance": account_info['balance'],
                "equity": account_info['equity'],
                "floating_pl": floating_pl,
                "win_rate": win_rate
            }
        except Exception as e:
            print(f"Metrics Error: {e}")
            return {"balance": 0, "equity": 0, "floating_pl": 0, "win_rate": 0}

    async def monitor_trades(self, get_settings=None):
        """
        Background monitor for active trades:
        - Syncs ALL broker trades (Manual + Telegram).
        - Move SL to BE at configured RR.
        - Partial Close at configured RR.
        get_settings: callable that returns a settings dict given a symbol
        """
        while True:
            if not self.connection:
                await asyncio.sleep(5)
                continue
            
            try:
                # ── Synchronization ──────────────────────────────────────────
                positions = await self.connection.get_positions()
                orders = await self.connection.get_orders()
                
                broker_tickets = {p['id'] for p in positions} | {o['id'] for o in orders}

                # 1. Handle Closed Trades
                to_remove = [t for t in self.active_trades if t not in broker_tickets]
                for ticket in to_remove:
                    print(f"🧹 Clearing closed ticket {ticket} from local state.")
                    data = self.active_trades.pop(ticket)
                    data['status'] = 'CLOSED'
                    self.closed_trades.append(data)

                # 2. Add/Sync Broker Trades to Local State
                all_items = []
                for p in positions:
                    all_items.append({'ticket': p['id'], 'symbol': p['symbol'], 'type': 'POSITION', 'data': p})
                for o in orders:
                    all_items.append({'ticket': o['id'], 'symbol': o['symbol'], 'type': 'ORDER', 'data': o})

                for item in all_items:
                    ticket = item['ticket']
                    t_id_str = str(ticket)
                    if t_id_str in self.ignored_tickets:
                        continue
                    if t_id_str not in self.active_trades:
                        source = "Telegram" if ticket in self.owned_tickets or t_id_str in self.owned_tickets else "Manual"
                        d = item['data']
                        self.active_trades[t_id_str] = {
                            'symbol': d['symbol'],
                            'entry': d.get('openPrice', d.get('price', 0)),
                            'sl': d.get('stopLoss', 0),
                            'tp': d.get('takeProfit', 0),
                            'side': d['type'].replace('ORDER_TYPE_', '').split('_')[0],
                            'lot': d.get('volume', 1.0),
                            'profit': d.get('unrealizedProfit', 0.0),
                            'status': 'OPEN',
                            'be_hit': False,
                            'partial_hit': False,
                            'source': source
                        }
                        # Capture original SL if not already stored
                        if t_id_str not in self.original_sls:
                            self.original_sls[t_id_str] = d.get('stopLoss', 0)
                
                # Update profits for existing ones
                for p in positions:
                    t_id_str = str(p['id'])
                    if t_id_str in self.active_trades:
                        self.active_trades[t_id_str]['profit'] = p.get('unrealizedProfit', 0.0)

                # ── Monitor Logic (Only for Positions) ───────────────────────
                for pos in positions:
                    ticket_id = pos['id']
                    t_id_str = str(ticket_id)
                    symbol = pos['symbol']
                    data = self.active_trades.get(t_id_str)
                    if not data:
                        continue 
                        
                    # Get Symbol-Specific Settings
                    if get_settings:
                        s = get_settings(symbol)
                    else:
                        s = {}

                    be_rr = float(s.get('be_rr', os.getenv('BE_RR', 2)))
                    partial_rr = float(s.get('partial_rr', os.getenv('PARTIAL_RR', 4)))
                    partial_pct = float(s.get('partial_percent', os.getenv('PARTIAL_PERCENT', 0.7)))

                    current_price = pos['currentPrice']
                    entry = data['entry']
                    sl = data['sl']
                    side = data['side']
                    dist_to_sl = abs(entry - sl)
                    
                    if dist_to_sl == 0: continue

                    if side == "BUY":
                        gain = current_price - entry
                    else:
                        gain = entry - current_price
                    
                    current_rr = gain / dist_to_sl
                    
                    # Move to Break-Even
                    if current_rr >= be_rr and not data['be_hit']:
                        print(f"🚀 Moving {symbol} to Break-Even for ticket {t_id_str}")
                        await self.connection.modify_position(ticket_id, entry, data['tp'])
                        data['be_hit'] = True
                        data['sl'] = entry
                    
                    # Partial Close
                    if current_rr >= partial_rr and not data['partial_hit']:
                        print(f"💰 Taking {symbol} Partial for ticket {t_id_str}")
                        partial_lot = round(data['lot'] * partial_pct, 2)
                        pos_volume = pos['volume']
                        if partial_lot >= 0.01 and partial_lot < pos_volume:
                            await self.connection.close_position(ticket_id, {'action': 'PARTIAL', 'volume': partial_lot})
                        data['partial_hit'] = True
                
            except Exception as e:
                print(f"Monitoring Loop Error: {e}")
            
            await asyncio.sleep(2) # Faster sync for responsive UI

    async def set_be(self, ticket):
        """Moves Stop Loss to Entry price."""
        t_id = str(ticket)
        if not self.connection or t_id not in self.active_trades:
            return False
        try:
            data = self.active_trades[t_id]
            entry = data['entry']
            tp = data['tp']
            print(f"⚡ Setting Break-Even for ticket {t_id}")
            await self.connection.modify_position(t_id, entry, tp)
            data['sl'] = entry
            data['be_hit'] = True
            return True
        except Exception as e:
            print(f"Error setting BE for {t_id}: {e}")
            return False

    async def restore_sl(self, ticket):
        """Restores the original Stop Loss from before BE was set."""
        t_id = str(ticket)
        if not self.connection or t_id not in self.active_trades:
            return False
        try:
            original_sl = self.original_sls.get(t_id)
            if not original_sl:
                return False
            data = self.active_trades[t_id]
            tp = data['tp']
            print(f"↩️ Restoring SL for ticket {t_id} to {original_sl}")
            await self.connection.modify_position(t_id, original_sl, tp)
            data['sl'] = original_sl
            data['be_hit'] = False
            return True
        except Exception as e:
            print(f"Error restoring SL for {t_id}: {e}")
            return False

    async def partial_close(self, ticket, fraction):
        """Closes a percentage of the position volume (e.g. 0.5 for 50%)."""
        t_id = str(ticket)
        if not self.connection:
            return False
        try:
            # Get fresh position data to ensure volume is correct
            positions = await self.connection.get_positions()
            pos = next((p for p in positions if str(p['id']) == t_id), None)
            if not pos:
                print(f"❌ Position {t_id} not found for partial close")
                return False
            
            current_volume = pos['volume']
            close_volume = round(current_volume * fraction, 2)
            
            # Minimum allowed volume is usually 0.01
            if close_volume < 0.01:
                close_volume = 0.01
            
            # Don't close more than exists
            if close_volume >= current_volume:
                print(f"⚠️ Partial close volume {close_volume} >= current {current_volume}. Full close.")
                await self.connection.close_position(t_id)
                return True

            print(f"💰 Partial close: {close_volume} lots of {current_volume} for ticket {t_id}")
            # MetaApi close_position(ticket, volume) for partial
            await self.connection.close_position(t_id, close_volume)
            return True
        except Exception as e:
            print(f"Error in partial_close for {t_id}: {e}")
            return False
    async def close_all_profitable(self, symbol_filter="GLOBAL"):
        """
        Closes all positions with positive floating profit for a given symbol (or all if GLOBAL).
        """
        if not self.connection:
            return 0
            
        try:
            positions = await self.connection.get_positions()
            count = 0
            for p in positions:
                sym = p['symbol']
                if symbol_filter != "GLOBAL" and sym != symbol_filter:
                    continue
                
                profit = p.get('unrealizedProfit', 0.0)
                if profit > 0:
                    t_id = str(p['id'])
                    print(f"💰 Closing profitable position: {t_id} ({sym}) with profit {profit}")
                    try:
                        await self.connection.close_position(t_id)
                        # Clean up locally
                        if t_id in self.active_trades:
                            del self.active_trades[t_id]
                        self.ignored_tickets.add(t_id)
                        self._save_ignored_tickets()
                        count += 1
                    except Exception as e:
                        print(f"Failed to close profitable position {t_id}: {e}")
            return count
        except Exception as e:
            print(f"Error in close_all_profitable: {e}")
            return 0
