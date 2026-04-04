import asyncio
import os
from telethon import TelegramClient, events
from dotenv import load_dotenv

load_dotenv()

class TelegramListener:
    def __init__(self, api_id, api_hash, channel_ids, session_name="london_bot_session", on_msg_callback=None):
        print(f"🛠️ [TG_INIT] api_id={api_id}, api_hash={api_hash[:5]}..., session_name={session_name} (Type: {type(session_name)})")
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
        self.channel_ids = channel_ids # Expecting a list of ints/strings
        self.on_message_callback = on_msg_callback
        self._tg_op_lock = asyncio.Lock()

    def is_connected(self):
        """Check if Telegram client is currently connected."""
        return self.client.is_connected() if self.client else False

    async def get_entity_name(self, chat_id):
        """Fetch the name/title of a group or channel with single-threaded lock to avoid DB contention."""
        async with self._tg_op_lock:
            # Cast to int if it's a number (e.g. "-1002047709770")
            current_id = chat_id
            try:
                current_id = int(chat_id)
            except: pass

            async def _try_resolve(cid):
                try:
                    # Attempt to get from internal cache first
                    entity = await self.client.get_entity(cid)
                    if hasattr(entity, 'title'):
                        return entity.title
                    if hasattr(entity, 'first_name'):
                        name = f"{entity.first_name} {getattr(entity, 'last_name', '') or ''}".strip()
                        return name if name else str(entity.id)
                    return str(entity.id)
                except Exception as e:
                    return None

            # First attempt
            name = await _try_resolve(current_id)
            if name: return name

            # If it looks like a Bot-API ID, try the raw version as well (stripping -100)
            if str(current_id).startswith("-100"):
                try:
                    raw_id = int(str(current_id)[4:])
                    name = await _try_resolve(raw_id)
                    if name: return name
                except: pass

            # Second attempt: sync dialogs
            try:
                print(f"🔄 Syncing dialogs to resolve entity: {current_id}...")
                # ── Sync Dialogs (limit for speed) ──
                await self.client.get_dialogs(limit=100)
                name = await _try_resolve(current_id)
                if name: return name
                
                # Check normalized again after sync
                if str(current_id).startswith("-100"):
                    raw_id = int(str(current_id)[4:])
                    name = await _try_resolve(raw_id)
                    if name: return name
            except Exception as e:
                print(f"❌ Dialog resolution failure for {current_id}: {e}")

            return None

    async def start(self):
        """Connect, sync, and register message handlers. Safe for multi-start."""
        try:
            if not self.client.is_connected():
                print(f"📡 Telegram connecting (Session: {self.session_name})...")
                # ── Session Locking Retry logic ──
                for attempt in range(3):
                    try:
                        await self.client.connect()
                        break
                    except Exception as e:
                        if "database is locked" in str(e).lower() and attempt < 2:
                            print(f"⏳ Telethon DB locked, retrying (A:{attempt+1})...")
                            await asyncio.sleep(2)
                        else: raise e

            if not await self.client.is_user_authorized():
                print("❌ Telegram session not authorized! Run setup wizard.")
                return None

            # 1. Sync Dialogs FIRST - essential for name resolution
            print("[Telethon] Syncing dialogs...")
            await self.client.get_dialogs(limit=100)
            
            # 2. Store 'Me' info
            self._me = await self.client.get_me()
            me_str = f"{self._me.first_name} (@{self._me.username})" if self._me.username else self._me.first_name
            print(f"✅ Telegram Connected: {me_str}")

            # 3. Register handlers (Unified entry point)
            self.client.remove_event_handler(self._on_new_message_internal)
            self.client.add_event_handler(self._on_new_message_internal, events.NewMessage)
            
            # 4. Verify membership for IDs in config
            print(f"[Telethon] Verifying sources: {self.channel_ids}")
            verified_count = 0
            for cid in self.channel_ids:
                name = await self.get_entity_name(cid)
                if name:
                    print(f"✅ Source Found: {name} ({cid})")
                    verified_count += 1
                else:
                    print(f"⚠️ Membership Warning: Could not find channel {cid} in joined list!")
            
            return self._me
        except Exception as e:
            print(f"❌ Telegram Startup Error: {e}")
            raise e

    def set_callback(self, callback):
        """Set the function to be called when a new message arrives."""
        self.on_message_callback = callback

    async def _on_new_message_internal(self, event):
        """Internal bridge to route message processing asynchronously."""
        # Check if chat ID is in monitored list
        chat_id = event.chat_id
        is_monitored = False
        target_cid = str(chat_id)
        
        # Check direct string match
        if target_cid in self.channel_ids:
            is_monitored = True
        else:
            # Check integer match for various ID formats
            for cid in self.channel_ids:
                try:
                    if int(cid) == chat_id:
                        is_monitored = True
                        break
                except:
                    continue

        # --- DEBUG: Catch All Events ---
        if not is_monitored:
            pass # Keep it quiet for production, but here's where we'd log unknown pings
            # print(f"DEBUG: Untracked message from {chat_id}")

        if is_monitored and self.on_message_callback:
            snippet = (event.raw_text[:50] + "...") if event.raw_text else "[Media]"
            print(f"📩 Telegram Match: {chat_id} -> {snippet}")
            # Ensure we pass the message object, not the event
            await self.on_message_callback(event.message)

    async def get_recent_messages(self, limit=5):
        """Fetch latest messages from all configured channels."""
        if not self.client.is_connected(): return []
        if not self.channel_ids: return []
        
        all_messages = []
        for chat_id in self.channel_ids:
            try:
                # Convert to int if possible
                try: 
                    target = int(chat_id)
                except:
                    target = chat_id

                print(f"📡 Syncing history for {target} (Limit: {limit})...")
                async for message in self.client.iter_messages(target, limit=limit):
                    all_messages.append({
                        "id": message.id,
                        "text": message.text or "",
                        "date": message.date,
                        "raw": message
                    })
            except Exception as e:
                print(f"⚠️ Error fetching from {chat_id}: {e}")
        
        # Sort by date descending and take global top limit
        all_messages.sort(key=lambda x: x['date'] if x['date'] else 0, reverse=True)
        return all_messages[:limit]
        return messages

    async def run_until_disconnected(self):
        await self.client.run_until_disconnected()

    async def disconnect(self):
        """Disconnect the client and release the session file."""
        if self.client:
            await self.client.disconnect()
            print(f"📡 Telegram session released ({self.session_name}).")
