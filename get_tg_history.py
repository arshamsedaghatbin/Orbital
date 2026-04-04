import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_id = int(os.getenv('TELEGRAM_API_ID', '0'))
    api_hash = os.getenv('TELEGRAM_API_HASH', 'YOUR_TELEGRAM_API_HASH')
    session = 'london_bot_session'
    
    ids = [-1002047709770, 7385884580]
    print(f"📊 Checking history for: {ids}")
    
    async with TelegramClient(session, api_id, api_hash) as client:
        await client.get_dialogs()
        for cid in ids:
            print(f"--- Chat: {cid} ---")
            try:
                msg_count = 0
                async for msg in client.iter_messages(cid, limit=5):
                    if msg.text:
                        print(f"[{msg.date}] (ID:{msg.id}) {msg.text[:60]}...")
                        msg_count += 1
                if msg_count == 0:
                    print(" No text messages found in last 5.")
            except Exception as e:
                print(f" ❌ Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
