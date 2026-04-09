"""
Direct MT5 Engine — file-based execution via the Socket EA.

Inherits all trade-logic from TradingEngine (history, lot calc, monitoring, etc.)
and replaces only the network layer with a DirectMT5Connection that reads/writes
two text files:
  • order.txt  — Python writes JSON order; EA reads, executes, deletes the file
  • status.txt — EA writes account/position/price snapshot every second
"""

import asyncio
import os
import json
import time

from trading_engine import TradingEngine


# ──────────────────────────────────────────────────────────────────────────────
# File-based connection object  (mimics MetaAPI RPC connection interface)
# ──────────────────────────────────────────────────────────────────────────────

class DirectMT5Connection:
    """
    Drop-in replacement for MetaAPI's RPC connection.
    Every method that TradingEngine calls on `self.connection` is implemented here.
    """

    def __init__(self, order_path: str, status_path: str):
        self._order_path = order_path
        self._status_path = status_path

    # ── Low-level helpers ──────────────────────────────────────────────────────

    def _read_status(self) -> dict:
        try:
            with open(self._status_path, "r") as f:
                content = f.read().strip()
            if content:
                return json.loads(content)
        except Exception:
            pass
        return {}

    def _write_order(self, order: dict):
        payload = json.dumps(order)
        print(f"📝 [DirectMT5] _write_order → {payload}")
        print(f"📁 [DirectMT5] Writing to: {self._order_path}")
        with open(self._order_path, "w") as f:
            f.write(payload)
        # Verify file was written
        try:
            with open(self._order_path, "r") as f:
                written = f.read()
            print(f"✅ [DirectMT5] order.txt confirmed on disk: {written}")
        except Exception as e:
            print(f"❌ [DirectMT5] Could not verify order.txt after write: {e}")

    def _all_tickets(self, status: dict) -> set:
        tickets = set()
        for p in status.get("positions", []):
            t = str(p.get("ticket", ""))
            if t:
                tickets.add(t)
        for o in status.get("orders", []):
            t = str(o.get("ticket", ""))
            if t:
                tickets.add(t)
        return tickets

    async def _place_and_get_ticket(self, order: dict, timeout_s: float = 10.0) -> str:
        """Write order.txt, wait for EA to process, return the new ticket ID."""
        before = self._all_tickets(self._read_status())
        self._write_order(order)

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            await asyncio.sleep(1.2)
            after = self._all_tickets(self._read_status())
            new = after - before
            if new:
                return str(next(iter(new)))

        # Timeout — return a deterministic fallback ID so local tracking still works
        return f"direct_{int(time.time())}"

    def _resolve_ticket(self, ticket_id) -> str:
        """
        If ticket_id is a real MT5 ticket number, return it unchanged.
        If it is a fake 'direct_TIMESTAMP' ID, try to find the real ticket
        in status.txt by looking at ALL positions and orders — the most recently
        opened one on any symbol is returned (best-effort when only one trade exists).
        Returns the original string if resolution fails.
        """
        tid = str(ticket_id)
        if not tid.startswith("direct_"):
            return tid  # already a real ticket

        s = self._read_status()
        # Collect all real tickets (positions + orders), sorted descending (newest first)
        real_tickets = []
        for p in s.get("positions", []):
            t = str(p.get("ticket", ""))
            if t and t.isdigit():
                real_tickets.append(t)
        for o in s.get("orders", []):
            t = str(o.get("ticket", ""))
            if t and t.isdigit():
                real_tickets.append(t)

        if len(real_tickets) == 1:
            # Only one trade on the account — must be ours
            print(f"🔄 [DirectMT5] Resolved fake ticket {tid} → real ticket {real_tickets[0]}")
            return real_tickets[0]

        if real_tickets:
            # Multiple trades: return the numerically largest (most recent) ticket
            best = str(max(int(t) for t in real_tickets))
            print(f"🔄 [DirectMT5] Resolved fake ticket {tid} → best-guess real ticket {best}")
            return best

        print(f"⚠️ [DirectMT5] Cannot resolve fake ticket {tid}: no real tickets in status.txt")
        return tid

    # ── Account information ────────────────────────────────────────────────────

    async def get_account_information(self) -> dict:
        s = self._read_status()
        return {
            "balance":    float(s.get("balance",     0) or 0),
            "equity":     float(s.get("equity",      0) or 0),
            "margin":     float(s.get("margin",      0) or 0),
            "freeMargin": float(s.get("free_margin", 0) or 0),
        }

    # ── Positions & orders ────────────────────────────────────────────────────

    async def get_positions(self) -> list:
        s = self._read_status()
        result = []
        for p in s.get("positions", []):
            pos_type = "BUY" if str(p.get("type", "")).upper() == "BUY" else "SELL"
            result.append({
                "id":               str(p.get("ticket", "")),
                "symbol":           p.get("symbol", ""),
                "type":             pos_type,
                "volume":           float(p.get("volume",     0) or 0),
                "openPrice":        float(p.get("open_price", 0) or 0),
                "stopLoss":         float(p.get("sl",         0) or 0),
                "takeProfit":       float(p.get("tp",         0) or 0),
                "unrealizedProfit": float(p.get("profit",     0) or 0),
                "currentPrice":     float(p.get("current_price") or p.get("open_price", 0) or 0),
            })
        return result

    async def get_orders(self) -> list:
        s = self._read_status()
        result = []
        for o in s.get("orders", []):
            raw_type = str(o.get("type", "")).upper()
            if   "BUY_STOP"   in raw_type: normalized = "ORDER_TYPE_BUY_STOP"
            elif "SELL_STOP"  in raw_type: normalized = "ORDER_TYPE_SELL_STOP"
            elif "BUY_LIMIT"  in raw_type: normalized = "ORDER_TYPE_BUY_LIMIT"
            elif "SELL_LIMIT" in raw_type: normalized = "ORDER_TYPE_SELL_LIMIT"
            elif "BUY"        in raw_type: normalized = "ORDER_TYPE_BUY"
            elif "SELL"       in raw_type: normalized = "ORDER_TYPE_SELL"
            else:                          normalized = raw_type
            result.append({
                "id":         str(o.get("ticket", "")),
                "symbol":     o.get("symbol", ""),
                "type":       normalized,
                "volume":     float(o.get("volume", 0) or 0),
                "price":      float(o.get("price",  0) or 0),
                "openPrice":  float(o.get("price",  0) or 0),
                "stopLoss":   float(o.get("sl",     0) or 0),
                "takeProfit": float(o.get("tp",     0) or 0),
            })
        return result

    async def get_deals(self, from_date, to_date) -> list:
        """Direct MT5 file API has no deal history; return empty list."""
        return []

    # ── Market data ───────────────────────────────────────────────────────────

    async def get_symbol_price(self, symbol: str) -> dict:
        """Read bid/ask from the 'prices' section EA writes, or fall back to positions."""
        s = self._read_status()
        prices = s.get("prices", {})
        if symbol in prices:
            return {
                "bid": float(prices[symbol].get("bid", 0) or 0),
                "ask": float(prices[symbol].get("ask", 0) or 0),
            }
        # Fallback: infer from open position on that symbol
        for p in s.get("positions", []):
            if str(p.get("symbol", "")).upper() == symbol.upper():
                price = float(p.get("current_price") or p.get("open_price", 0) or 0)
                return {"bid": price, "ask": price}
        raise Exception(
            f"PRICE_UNAVAILABLE: No price data for {symbol} in status.txt. "
            "Ensure the EA is running and 'Algo Trading' is enabled."
        )

    async def get_symbol_specification(self, symbol: str) -> dict:
        """Return hardcoded symbol specs (Direct MT5 has no spec API via files)."""
        s = symbol.upper()
        if "XAU" in s or "GOLD" in s:
            return {"contractSize": 100,    "tickSize": 0.01,    "tickValue": 1.0,  "lotStep": 0.01, "minLot": 0.01}
        if "XAG" in s or "SILVER" in s:
            return {"contractSize": 5000,   "tickSize": 0.001,   "tickValue": 5.0,  "lotStep": 0.01, "minLot": 0.01}
        if "BTC" in s or "BITCOIN" in s:
            return {"contractSize": 1,      "tickSize": 0.01,    "tickValue": 0.01, "lotStep": 0.01, "minLot": 0.01}
        if "NAS" in s or "SPX" in s or "US30" in s or "INDEX" in s:
            return {"contractSize": 1,      "tickSize": 0.01,    "tickValue": 0.01, "lotStep": 0.01, "minLot": 0.01}
        # Standard Forex pair
        return {"contractSize": 100000, "tickSize": 0.00001, "tickValue": 1.0,  "lotStep": 0.01, "minLot": 0.01}

    # ── Order placement ───────────────────────────────────────────────────────

    async def create_market_buy_order(self, symbol, volume, stop_loss, take_profit):
        ticket = await self._place_and_get_ticket({
            "symbol": symbol, "action": "BUY",
            "volume": str(volume), "price": "0",
            "sl": str(stop_loss), "tp": str(take_profit), "ticket": "0",
        })
        return {"orderId": ticket}

    async def create_market_sell_order(self, symbol, volume, stop_loss, take_profit):
        ticket = await self._place_and_get_ticket({
            "symbol": symbol, "action": "SELL",
            "volume": str(volume), "price": "0",
            "sl": str(stop_loss), "tp": str(take_profit), "ticket": "0",
        })
        return {"orderId": ticket}

    async def create_stop_buy_order(self, symbol, volume, open_price, stop_loss, take_profit):
        ticket = await self._place_and_get_ticket({
            "symbol": symbol, "action": "BUY_STOP",
            "volume": str(volume), "price": str(open_price),
            "sl": str(stop_loss), "tp": str(take_profit), "ticket": "0",
        })
        return {"orderId": ticket}

    async def create_stop_sell_order(self, symbol, volume, open_price, stop_loss, take_profit):
        ticket = await self._place_and_get_ticket({
            "symbol": symbol, "action": "SELL_STOP",
            "volume": str(volume), "price": str(open_price),
            "sl": str(stop_loss), "tp": str(take_profit), "ticket": "0",
        })
        return {"orderId": ticket}

    async def create_limit_buy_order(self, symbol, volume, open_price, stop_loss, take_profit):
        ticket = await self._place_and_get_ticket({
            "symbol": symbol, "action": "BUY_LIMIT",
            "volume": str(volume), "price": str(open_price),
            "sl": str(stop_loss), "tp": str(take_profit), "ticket": "0",
        })
        return {"orderId": ticket}

    async def create_limit_sell_order(self, symbol, volume, open_price, stop_loss, take_profit):
        ticket = await self._place_and_get_ticket({
            "symbol": symbol, "action": "SELL_LIMIT",
            "volume": str(volume), "price": str(open_price),
            "sl": str(stop_loss), "tp": str(take_profit), "ticket": "0",
        })
        return {"orderId": ticket}

    # ── Position / order management ───────────────────────────────────────────

    async def close_position(self, ticket_id, options=None):
        """
        Handles full close, partial close, and dict-style options.
        Signatures used in the codebase:
          close_position(ticket)
          close_position(ticket, {})
          close_position(ticket, volume_float)          — partial
          close_position(ticket, {'action':'PARTIAL', 'volume': x})  — partial

        Auto-detects if the ticket is a pending order (not a position) and sends
        DELETE instead of CLOSE so the EA always receives the right action.
        """
        real_ticket = self._resolve_ticket(ticket_id)
        print(f"🔧 [DirectMT5] close_position called: raw={ticket_id!r} resolved={real_ticket!r} options={options!r}")

        is_partial = (
            (options is not None and isinstance(options, (int, float)) and options > 0)
            or (isinstance(options, dict) and options.get("action") == "PARTIAL")
        )

        if not is_partial:
            # Check status.txt — if the ticket is a pending order, send DELETE not CLOSE
            s = self._read_status()
            raw_orders = s.get("orders", [])
            raw_positions = s.get("positions", [])
            order_tickets = {str(o.get("ticket", "")) for o in raw_orders}
            pos_tickets   = {str(p.get("ticket", "")) for p in raw_positions}
            print(f"🔍 [DirectMT5] status.txt orders   ({len(raw_orders)}): {order_tickets}")
            print(f"🔍 [DirectMT5] status.txt positions({len(raw_positions)}): {pos_tickets}")
            print(f"🔍 [DirectMT5] Looking for real_ticket={real_ticket!r} (type={type(real_ticket).__name__})")
            print(f"🔍 [DirectMT5] real_ticket in order_tickets? {real_ticket in order_tickets}")
            print(f"🔍 [DirectMT5] real_ticket in pos_tickets?   {real_ticket in pos_tickets}")

            if real_ticket in order_tickets:
                print(f"🔄 [DirectMT5] Ticket {real_ticket} is a pending ORDER — sending DELETE instead of CLOSE")
                self._write_order({
                    "symbol": "", "action": "DELETE",
                    "volume": "0", "price": "0",
                    "sl": "0", "tp": "0", "ticket": real_ticket,
                })
                await asyncio.sleep(2.0)
                # Verify the order is gone
                s2 = self._read_status()
                remaining_orders = {str(o.get("ticket", "")) for o in s2.get("orders", [])}
                if real_ticket not in remaining_orders:
                    print(f"✅ [DirectMT5] Confirmed: ticket {real_ticket} removed from orders in status.txt")
                else:
                    print(f"⚠️ [DirectMT5] Ticket {real_ticket} still present in orders after DELETE — EA may not have processed yet")
                return

        if options is not None and isinstance(options, (int, float)) and options > 0:
            # Numeric volume → partial close
            self._write_order({
                "symbol": "", "action": "PARTIAL_CLOSE",
                "volume": str(options), "price": "0",
                "sl": "0", "tp": "0", "ticket": real_ticket,
            })
        elif isinstance(options, dict) and options.get("action") == "PARTIAL":
            vol = options.get("volume", 0)
            self._write_order({
                "symbol": "", "action": "PARTIAL_CLOSE",
                "volume": str(vol), "price": "0",
                "sl": "0", "tp": "0", "ticket": real_ticket,
            })
        else:
            # Full close (position)
            self._write_order({
                "symbol": "", "action": "CLOSE",
                "volume": "0", "price": "0",
                "sl": "0", "tp": "0", "ticket": real_ticket,
            })
        await asyncio.sleep(2.0)
        # Verify the position is gone
        s2 = self._read_status()
        remaining_pos = {str(p.get("ticket", "")) for p in s2.get("positions", [])}
        if real_ticket not in remaining_pos:
            print(f"✅ [DirectMT5] Confirmed: ticket {real_ticket} removed from positions in status.txt")
        else:
            print(f"⚠️ [DirectMT5] Ticket {real_ticket} still present in positions after CLOSE — EA may not have processed yet")

    async def cancel_order(self, ticket_id, symbol: str = ""):
        real_ticket = self._resolve_ticket(ticket_id)
        print(f"🔧 [DirectMT5] cancel_order called: raw={ticket_id!r} resolved={real_ticket!r} symbol={symbol!r}")

        # If ticket is still fake (old EA, no orders in status.txt), fall back to
        # symbol-based cancel. The updated EA supports DELETE with ticket=0 + symbol
        # which cancels all pending orders on that symbol.
        if real_ticket.startswith("direct_"):
            if symbol:
                print(f"⚠️ [DirectMT5] Ticket unresolvable — falling back to symbol-based cancel for {symbol}")
                self._write_order({
                    "symbol": symbol, "action": "DELETE",
                    "volume": "0", "price": "0",
                    "sl": "0", "tp": "0", "ticket": "0",
                })
            else:
                print(f"❌ [DirectMT5] Cannot cancel: no real ticket and no symbol. Update EA to new version.")
                return
        else:
            self._write_order({
                "symbol": symbol, "action": "DELETE",
                "volume": "0", "price": "0",
                "sl": "0", "tp": "0", "ticket": real_ticket,
            })
        await asyncio.sleep(2.0)

    async def modify_position(self, ticket_id, stop_loss, take_profit):
        real_ticket = self._resolve_ticket(ticket_id)
        print(f"🔧 [DirectMT5] modify_position: raw={ticket_id} resolved={real_ticket} sl={stop_loss} tp={take_profit}")
        self._write_order({
            "symbol": "", "action": "MODIFY_POSITION",
            "volume": "0", "price": "0",
            "sl": str(stop_loss), "tp": str(take_profit), "ticket": real_ticket,
        })
        await asyncio.sleep(1.5)

    async def modify_order(self, ticket_id, open_price, stop_loss, take_profit):
        real_ticket = self._resolve_ticket(ticket_id)
        print(f"🔧 [DirectMT5] modify_order: raw={ticket_id} resolved={real_ticket} price={open_price} sl={stop_loss} tp={take_profit}")
        self._write_order({
            "symbol": "", "action": "MODIFY_ORDER",
            "volume": "0", "price": str(open_price),
            "sl": str(stop_loss), "tp": str(take_profit), "ticket": real_ticket,
        })
        await asyncio.sleep(1.5)

    async def close(self):
        """No-op: file connection has no persistent state to tear down."""
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Engine class
# ──────────────────────────────────────────────────────────────────────────────

class DirectMT5Engine(TradingEngine):
    """
    Thin wrapper around TradingEngine that replaces the MetaAPI connection
    with a DirectMT5Connection backed by two text files.

    All trade logic (lot calc, monitoring, BE, partial close, history, etc.)
    is inherited unchanged from TradingEngine.
    """

    def __init__(self, mt5_files_dir: str):
        # Pass dummy credentials; super().__init__ only stores them and loads
        # local JSON files — it never connects at construction time.
        super().__init__(token="direct", account_id="direct", region="direct")
        self._files_dir = mt5_files_dir
        self._order_path  = os.path.join(mt5_files_dir, "order.txt")
        self._status_path = os.path.join(mt5_files_dir, "status.txt")

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(self, retries: int = 2) -> bool:
        """Verify status.txt is readable; set self.connection on success."""
        print(f"🔄 Connecting to Direct MT5 via {self._status_path} ...")
        for attempt in range(1, retries + 2):
            try:
                if os.path.exists(self._status_path):
                    with open(self._status_path, "r") as f:
                        data = json.loads(f.read())
                    balance = data.get("balance", "?")
                    print(f"✅ Direct MT5 Connected. Balance: {balance}")
                    self.connection = DirectMT5Connection(self._order_path, self._status_path)
                    return True
                else:
                    print(
                        f"⏳ status.txt not found (attempt {attempt}). "
                        "Is the Socket EA attached and Algo Trading enabled?"
                    )
            except Exception as e:
                print(f"❌ Direct MT5 Connect Error (attempt {attempt}): {e}")

            if attempt <= retries:
                await asyncio.sleep(2)

        print("❌ Direct MT5: Could not connect. Check EA and Algo Trading.")
        return False

    async def disconnect(self):
        """Release the connection object."""
        self.connection = None
        self.api = None
        print("🏁 Direct MT5 engine disconnected.")

    # ── Bug fixes: price-independent routing + grace-period monitoring ────────

    async def execute_trade(self, data, settings=None, source="Manual", fallback_to_market=False):
        """
        Override to fix two issues vs the parent class:

        1. PRICE FIX: When status.txt has no active positions/orders, get_symbol_price()
           raises PRICE_UNAVAILABLE, which causes execute_trade to crash instead of
           placing the order.  We inject a synthetic market price derived from the entry
           + direction so TradingEngine's market-vs-stop routing works correctly.

        2. SETTINGS FIX: Ensures risk_usd / rr_target are always read from the
           `settings` dict passed by main.py (state.settings), not from fallback env vars
           that may differ between MetaAPI and Direct MT5 paths.

        3. PLACEMENT TIMESTAMP: Tags every placed trade with _placed_at so the
           grace-period monitor_trades override below can keep it visible in the UI
           even if the EA has not yet written it to status.txt.
        """
        if not self.connection:
            if not await self.connect():
                return {"id": None, "error": "DISCONNECTED"}

        side = str(data.get("side", "BUY")).upper()
        entry_val = data.get("entry")

        if entry_val is not None:
            entry_f = float(entry_val)
            is_buy = side.startswith("BUY")

            # Synthetic price: force correct branch in TradingEngine's routing
            #   BUY_STOP  → need entry > market  → synthetic = entry - 1
            #   SELL_STOP → need entry < market  → synthetic = entry + 1
            synthetic = entry_f - 1.0 if is_buy else entry_f + 1.0

            orig_price_fn = self.connection.get_symbol_price

            async def _patched_price(sym):
                try:
                    return await orig_price_fn(sym)
                except Exception:
                    return {"bid": synthetic, "ask": synthetic}

            self.connection.get_symbol_price = _patched_price
            try:
                result = await super().execute_trade(data, settings, source, fallback_to_market)
            finally:
                self.connection.get_symbol_price = orig_price_fn
        else:
            # Market order (no entry) — try live price, fall back to 0 if unavailable
            orig_price_fn = self.connection.get_symbol_price

            async def _patched_market_price(sym):
                try:
                    return await orig_price_fn(sym)
                except Exception:
                    return {"bid": 0.0, "ask": 0.0}

            self.connection.get_symbol_price = _patched_market_price
            try:
                result = await super().execute_trade(data, settings, source, fallback_to_market)
            finally:
                self.connection.get_symbol_price = orig_price_fn

        # Tag the placed trade with a timestamp for the grace-period monitor
        oid = result.get("id")
        if oid and oid in self.active_trades:
            self.active_trades[oid]["_placed_at"] = time.time()

        return result

    async def close_trade(self, ticket_id):
        """
        Override to pass the symbol to cancel_order so that when the old EA is
        running (no orders section in status.txt), we can fall back to
        symbol-based cancel (DELETE with ticket=0 + symbol).
        """
        if not self.connection:
            return False

        t_id_str = str(ticket_id)
        trade_info = self.active_trades.get(t_id_str, {})
        symbol = trade_info.get("symbol", "")
        side = trade_info.get("side", "")
        is_pending = side.endswith("_STOP") or side.endswith("_LIMIT")

        print(f"🔧 [DirectMT5Engine] close_trade: ticket={t_id_str!r} symbol={symbol!r} side={side!r} is_pending={is_pending}")

        try:
            if is_pending:
                # Pass symbol so cancel_order can fall back to symbol-based DELETE
                await self.connection.cancel_order(ticket_id, symbol=symbol)
            else:
                await self.connection.close_position(ticket_id, {})

            # Sync local state
            if t_id_str in self.active_trades:
                trade_data = self.active_trades.pop(t_id_str)
                trade_data["status"] = "CLOSED"
                self.closed_trades.append(trade_data)
                self._save_active_trades()
                self._save_history()
            print(f"✅ [DirectMT5Engine] close_trade {ticket_id} dispatched successfully.")
            return True

        except Exception as e:
            print(f"❌ [DirectMT5Engine] close_trade error for {ticket_id}: {e}")
            return False

    async def monitor_trades(self, get_settings=None):
        """
        Override TradingEngine.monitor_trades to add a grace period.

        The EA may not write pending orders to status.txt (old EA version) or may
        take a few seconds to update.  Without a grace period, locally-tracked
        orders (with a fake direct_TIMESTAMP ticket) would be immediately removed
        by the parent's "not in broker_tickets → close" logic.

        Grace period: trades placed within the last GRACE_SECONDS are kept in
        active_trades even if they are absent from status.txt.  Once the EA writes
        them (or they get filled into a position), normal tracking takes over.
        """
        GRACE_SECONDS = 90

        while True:
            if not self.connection:
                await asyncio.sleep(5)
                continue

            try:
                positions = await self.connection.get_positions()
                orders    = await self.connection.get_orders()

                broker_tickets = {p["id"] for p in positions} | {o["id"] for o in orders}
                now = time.time()

                # 1. Remove trades that are gone from the broker AND past grace period
                to_remove = []
                for ticket in list(self.active_trades.keys()):
                    if ticket not in broker_tickets:
                        placed_at = self.active_trades[ticket].get("_placed_at", 0)
                        if now - placed_at > GRACE_SECONDS:
                            to_remove.append(ticket)

                for ticket in to_remove:
                    print(f"🧹 [Direct MT5] Clearing expired ticket {ticket} from local state.")
                    d = self.active_trades.pop(ticket)
                    d["status"] = "CLOSED"
                    self.closed_trades.append(d)

                # 1b. Upgrade fake direct_* keys to real broker ticket IDs.
                #     When _place_and_get_ticket timed out, we stored the trade under
                #     a "direct_TIMESTAMP" key.  Once the EA writes the real ticket to
                #     status.txt, swap the key so close/cancel use the real ticket.
                fake_keys_by_symbol: dict[str, str] = {}
                for fake_key in list(self.active_trades.keys()):
                    if fake_key.startswith("direct_"):
                        sym = self.active_trades[fake_key].get("symbol", "")
                        if sym:
                            fake_keys_by_symbol[sym.upper()] = fake_key

                if fake_keys_by_symbol:
                    for item_ticket, item_sym in (
                        [(p["id"], p["symbol"]) for p in positions]
                        + [(o["id"], o["symbol"]) for o in orders]
                    ):
                        real_t = str(item_ticket)
                        sym_upper = item_sym.upper()
                        if sym_upper in fake_keys_by_symbol and real_t not in self.active_trades:
                            fake_k = fake_keys_by_symbol[sym_upper]
                            print(f"🔑 [Direct MT5] Upgrading fake key {fake_k} → real ticket {real_t}")
                            # Move the entry under the real ticket key
                            self.active_trades[real_t] = self.active_trades.pop(fake_k)
                            # Fix original_sls if needed
                            if fake_k in self.original_sls:
                                self.original_sls[real_t] = self.original_sls.pop(fake_k)
                            # Update broker_tickets set so grace-period check sees the real key
                            broker_tickets.add(real_t)

                # 2. Add / sync broker trades to local state
                all_items = []
                for p in positions:
                    all_items.append({"ticket": p["id"], "symbol": p["symbol"], "type": "POSITION", "data": p})
                for o in orders:
                    all_items.append({"ticket": o["id"], "symbol": o["symbol"], "type": "ORDER", "data": o})

                for item in all_items:
                    ticket   = item["ticket"]
                    t_id_str = str(ticket)
                    if t_id_str in self.ignored_tickets:
                        continue
                    if t_id_str not in self.active_trades:
                        src = "Telegram" if ticket in self.owned_tickets or t_id_str in self.owned_tickets else "Manual"
                        d = item["data"]
                        self.active_trades[t_id_str] = {
                            "symbol":  d["symbol"],
                            "entry":   d.get("openPrice", d.get("price", 0)),
                            "sl":      d.get("stopLoss", 0),
                            "tp":      d.get("takeProfit", 0),
                            "side":    d["type"].replace("ORDER_TYPE_", "").split("_")[0],
                            "lot":     d.get("volume", 1.0),
                            "profit":  d.get("unrealizedProfit", 0.0),
                            "status":  "OPEN",
                            "be_hit":  False,
                            "partial_hit": False,
                            "source":  src,
                            "_placed_at": now,  # treat broker-synced trades as "fresh"
                        }
                        if t_id_str not in self.original_sls:
                            self.original_sls[t_id_str] = d.get("stopLoss", 0)

                # 3. Update profits for open positions
                for p in positions:
                    t_id_str = str(p["id"])
                    if t_id_str in self.active_trades:
                        self.active_trades[t_id_str]["profit"] = p.get("unrealizedProfit", 0.0)
                        # Also update current price for accurate RR calc
                        if p.get("currentPrice"):
                            self.active_trades[t_id_str]["current_price"] = p["currentPrice"]

                # 4. BE and partial-close monitoring (positions only)
                for pos in positions:
                    ticket_id = pos["id"]
                    t_id_str  = str(ticket_id)
                    symbol    = pos["symbol"]
                    data      = self.active_trades.get(t_id_str)
                    if not data:
                        continue

                    s = get_settings(symbol) if get_settings else {}
                    be_rr       = float(s.get("be_rr",          os.getenv("BE_RR", 2)))
                    partial_rr  = float(s.get("partial_rr",     os.getenv("PARTIAL_RR", 4)))
                    partial_pct = float(s.get("partial_percent", os.getenv("PARTIAL_PERCENT", 0.7)))

                    current_price = pos.get("currentPrice", pos.get("openPrice", 0))
                    entry  = data["entry"]
                    sl     = data["sl"]
                    side   = data["side"]
                    dist   = abs(entry - sl)
                    if dist == 0:
                        continue

                    gain = (current_price - entry) if side == "BUY" else (entry - current_price)
                    current_rr = gain / dist

                    if current_rr >= be_rr and not data["be_hit"]:
                        print(f"🚀 [Direct MT5] Moving {symbol} to BE for ticket {t_id_str}")
                        await self.connection.modify_position(ticket_id, entry, data["tp"])
                        data["be_hit"] = True
                        data["sl"] = entry

                    if current_rr >= partial_rr and not data["partial_hit"]:
                        print(f"💰 [Direct MT5] Taking {symbol} Partial for ticket {t_id_str}")
                        partial_lot = round(data["lot"] * partial_pct, 2)
                        pos_volume  = pos.get("volume", data["lot"])
                        if partial_lot >= 0.01 and partial_lot < pos_volume:
                            await self.connection.close_position(ticket_id, {"action": "PARTIAL", "volume": partial_lot})
                        data["partial_hit"] = True

                if to_remove:
                    self._save_active_trades()
                    self._save_history()

            except Exception as e:
                print(f"Direct MT5 Monitoring Loop Error: {e}")

            await asyncio.sleep(2)
