import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_id = int(os.getenv('TELEGRAM_API_ID'))
    api_hash = os.getenv('TELEGRAM_API_HASH')
    session = os.getenv('TELEGRAM_SESSION_NAME', 'london_bot_session')
    channel_ids_str = os.getenv('CHANNEL_IDS', '')
    
    ids = [c.strip() for c in channel_ids_str.split(',') if c.strip()]
    print(f"Checking IDs: {ids}")
    
    async with TelegramClient(session, api_id, api_hash) as client:
        await client.get_dialogs()
        for cid in ids:
            try:
                # Try cast to int
                try: target = int(cid)
                except: target = cid
                
                entity = await client.get_entity(target)
                print(f"✅ Found entity for {cid}: {getattr(entity, 'title', getattr(entity, 'first_name', 'Unknown'))}")
            except Exception as e:
                print(f"❌ Failed to find {cid}: {e}")

if __name__ == '__main__':
    asyncio.run(main())
