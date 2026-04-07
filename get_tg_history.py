import asyncio
import os
import datetime
from telethon import TelegramClient
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_id = int(os.getenv('TELEGRAM_API_ID', '0'))
    api_hash = os.getenv('TELEGRAM_API_HASH', 'YOUR_TELEGRAM_API_HASH')
    session = 'copy'
    
    cid = -1002047709770
    three_months_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=90)
    
    print(f"📊 Fetching history for {cid} since {three_months_ago.strftime('%Y-%m-%d')}...")
    
    try:
        with open('history_dump.txt', 'w', encoding='utf-8') as f:
            async with TelegramClient(session, api_id, api_hash) as client:
                await client.get_dialogs()
                msg_count = 0
                
                async for msg in client.iter_messages(cid):
                    if msg.date < three_months_ago:
                        break  # Reached older than 3 months
                    
                    if msg.text:
                        # Optional: filter just looking for common words to keep file clean
                        text = msg.text
                        if any(x in text.lower() for x in ['xauusd', 'buy', 'sell', 'enter', 'entry', 'sl', 'tp', 'دوباره', 'پولبک']):
                            f.write(f"--- [{msg.date}] ---\n{text}\n\n")
                            msg_count += 1
                
                print(f"✅ Dumped {msg_count} signal formats to history_dump.txt")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
