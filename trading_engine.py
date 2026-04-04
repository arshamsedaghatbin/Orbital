import asyncio
import os
import json
import time
from metaapi_cloud_sdk import MetaApi
from dotenv import load_dotenv

load_dotenv()

OWNED_TICKETS_FILE = os.path.join(os.path.dirname(__file__), "bot_owned_tickets.json")

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
        self.symbol = "XAUUSD"
        self._load_owned_tickets()

    def _load_owned_tickets(self):
        if os.path.exists(OWNED_TICKETS_FILE):
            try:
                with open(OWNED_TICKETS_FILE, "r") as f:
                    self.owned_tickets = set(json.load(f))
            except:
                self.owned_tickets = set()
        else:
            self.owned_tickets = set()

    def _save_owned_tickets(self):
        try:
            with open(OWNED_TICKETS_FILE, "w") as f:
                json.dump(list(self.owned_tickets), f)
        except Exception as e:
            print(f"Error saving owned tickets: {e}")

    async def connect(self, retries=2):
        last_error = None
        for attempt in range(1, retries + 2):
            try:
                print(f"🔄 Attempting connection to MetaTrader {self.account_id} (Attempt {attempt})...")
                if not self.api:
                    self.api = MetaApi(self.token)
                
                self.account = await self.api.metatrader_account_api.get_account(self.account_id)
                print(f"✅ Account Found: {self.account.name}")
                
                await self.account.wait_connected()
                print("🔗 Connected to account. Getting RPC connection...")
                
                self.connection = self.account.get_rpc_connection()
                await self.connection.connect()
                
                print("⏳ Synchronizing...")
                await self.connection.wait_synchronized()
                
                print(f"✅ Fully Connected and Synchronized for {self.account_id}")
                return True
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
                await self.api.close_instance()
                print("🚪 MetaApi instance closed.")
        except Exception as e:
            print(f"⚠️ Error during MT5 disconnect: {e}")
        finally:
            self.connection = None
            self.account = None
            self.api = None

    async def execute_trade(self, data, settings=None, source="Manual"):
        """
        Executes a trade based on refined AI signal data.
        settings: dict with risk_usd, rr_target etc. If None, falls back to env.
        source: 'Telegram' or 'Manual' for win-rate tracking.
        """
        if not self.connection:
            if not await self.connect():
                return None

        symbol = data.get('symbol', 'XAUUSD').upper()
        entry = float(data['entry'])
        sl = float(data['sl'])
        side = data['side'].upper()
        s = settings or {}
        risk_usd = float(s.get('risk_usd', os.getenv('RISK_USD', 50)))
        rr_target = float(s.get('rr_target', os.getenv('RR_TARGET', 6)))

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
        tp = round(entry + (distance * rr_target) if side == "BUY" else entry - (distance * rr_target), 5)

        # Get current price to decide order type
        price_info = await self.connection.get_symbol_price(symbol)
        market_price = price_info['ask'] if side == "BUY" else price_info['bid']

        try:
            if side == "BUY":
                if entry > market_price:
                    result = await self.connection.create_stop_buy_order(symbol, lot, entry, sl, tp)
                else:
                    # Restrict to STOP orders only. If entry is already hit, it's a price error for queuing.
                    print(f"⚠️ BUY_STOP entry {entry} <= market {market_price}. Sending to queue.")
                    return {"id": None, "error": "PRICE_ERROR"}
            else:
                if entry < market_price:
                    result = await self.connection.create_stop_sell_order(symbol, lot, entry, sl, tp)
                else:
                    # Restrict to STOP orders only.
                    print(f"⚠️ SELL_STOP entry {entry} >= market {market_price}. Sending to queue.")
                    return {"id": None, "error": "PRICE_ERROR"}
            
            order_id = result['orderId']
            if source == "Telegram":
                self.owned_tickets.add(order_id)
                self._save_owned_tickets()

            self.active_trades[order_id] = {
                'symbol': symbol,
                'entry': entry,
                'sl': sl,
                'tp': tp,
                'side': side,
                'lot': lot,
                'status': 'OPEN',
                'be_hit': False,
                'partial_hit': False,
                'source': source
            }
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
                
            return {"id": None, "error": "FATAL_ERROR", "msg": str(e)}

    async def close_trade(self, ticket_id):
        """Force closes an active position (handle both position and order IDs)."""
        if not self.connection: return False
        try:
            print(f"📡 Attempting to close trade {ticket_id}...")
            # Try to close as a position
            try:
                await self.connection.close_position(ticket_id, {})
            except Exception as e:
                # If it's a pending order, cancel it instead
                if "not found" in str(e).lower() or "invalid position" in str(e).lower():
                    await self.connection.cancel_order(ticket_id)
                else:
                    raise e
            
            if ticket_id in self.active_trades:
                trade_data = self.active_trades.pop(ticket_id)
                trade_data['status'] = 'CLOSED'
                self.closed_trades.append(trade_data)
            return True
            
        except Exception as e:
            err_msg = str(e).lower()
            if any(x in err_msg for x in ["not found", "invalid position", "already closed"]):
                # Already gone, just clear local state
                if ticket_id in self.active_trades:
                    trade_data = self.active_trades.pop(ticket_id)
                    trade_data['status'] = 'ALREADY_CLOSED'
                    self.closed_trades.append(trade_data)
                return True
            
            print(f"❌ Close Trade Error: {e}")
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
            sym_positions = [p for p in positions if p['symbol'] == symbol]
            if sym_positions:
                pos = sym_positions[-1]   # most recent
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
            sym_orders = [o for o in orders if o['symbol'] == symbol]
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
                    if ticket not in self.active_trades:
                        source = "Telegram" if ticket in self.owned_tickets else "Manual"
                        d = item['data']
                        self.active_trades[ticket] = {
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
                        if ticket not in self.original_sls:
                            self.original_sls[ticket] = d.get('stopLoss', 0)
                
                # Update profits for existing ones
                for p in positions:
                    if p['id'] in self.active_trades:
                        self.active_trades[p['id']]['profit'] = p.get('unrealizedProfit', 0.0)

                # ── Monitor Logic (Only for Positions) ───────────────────────
                for pos in positions:
                    ticket = pos['id']
                    symbol = pos['symbol']
                    data = self.active_trades.get(ticket)
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
                        print(f"🚀 Moving {symbol} to Break-Even for ticket {ticket}")
                        await self.connection.modify_position(ticket, entry, data['tp'])
                        data['be_hit'] = True
                        data['sl'] = entry
                    
                    # Partial Close
                    if current_rr >= partial_rr and not data['partial_hit']:
                        print(f"💰 Taking {symbol} Partial for ticket {ticket}")
                        partial_lot = round(data['lot'] * partial_pct, 2)
                        pos_volume = pos['volume']
                        if partial_lot >= 0.01 and partial_lot < pos_volume:
                            await self.connection.close_position(ticket, {'action': 'PARTIAL', 'volume': partial_lot})
                        data['partial_hit'] = True
                
            except Exception as e:
                print(f"Monitoring Loop Error: {e}")
            
            await asyncio.sleep(2) # Faster sync for responsive UI

    async def set_be(self, ticket):
        """Moves Stop Loss to Entry price."""
        if not self.connection or ticket not in self.active_trades:
            return False
        try:
            data = self.active_trades[ticket]
            entry = data['entry']
            tp = data['tp']
            print(f"⚡ Setting Break-Even for ticket {ticket}")
            await self.connection.modify_position(str(ticket), entry, tp)
            data['sl'] = entry
            data['be_hit'] = True
            return True
        except Exception as e:
            print(f"Error setting BE for {ticket}: {e}")
            return False

    async def restore_sl(self, ticket):
        """Restores the original Stop Loss from before BE was set."""
        if not self.connection or ticket not in self.active_trades:
            return False
        try:
            original_sl = self.original_sls.get(ticket)
            if not original_sl:
                return False
            data = self.active_trades[ticket]
            tp = data['tp']
            print(f"↩️ Restoring SL for ticket {ticket} to {original_sl}")
            await self.connection.modify_position(str(ticket), original_sl, tp)
            data['sl'] = original_sl
            data['be_hit'] = False
            return True
        except Exception as e:
            print(f"Error restoring SL for {ticket}: {e}")
            return False

    async def partial_close(self, ticket, fraction):
        """Closes a percentage of the position volume (e.g. 0.5 for 50%)."""
        if not self.connection:
            return False
        try:
            # Get fresh position data to ensure volume is correct
            positions = await self.connection.get_positions()
            pos = next((p for p in positions if p['id'] == str(ticket)), None)
            if not pos:
                print(f"❌ Position {ticket} not found for partial close")
                return False
            
            current_volume = pos['volume']
            close_volume = round(current_volume * fraction, 2)
            
            # Minimum allowed volume is usually 0.01
            if close_volume < 0.01:
                close_volume = 0.01
            
            # Don't close more than exists
            if close_volume >= current_volume:
                print(f"⚠️ Partial close volume {close_volume} >= current {current_volume}. Full close.")
                await self.connection.close_position(str(ticket))
                return True

            print(f"💰 Partial close: {close_volume} lots of {current_volume} for ticket {ticket}")
            # MetaApi close_position(ticket, volume) for partial
            await self.connection.close_position(str(ticket), close_volume)
            return True
        except Exception as e:
            print(f"Error in partial_close for {ticket}: {e}")
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
                    print(f"💰 Closing profitable position: {p['id']} ({sym}) with profit {profit}")
                    await self.connection.close_position(p['id'])
                    count += 1
            return count
        except Exception as e:
            print(f"Error in close_all_profitable: {e}")
            return 0
