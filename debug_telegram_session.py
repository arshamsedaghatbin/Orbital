import asyncio
import os
from telethon import TelegramClient
from dotenv import load_dotenv

async def main():
    load_dotenv()
    api_id = int(os.getenv('TELEGRAM_API_ID'))
    api_hash = os.getenv('TELEGRAM_API_HASH')
    session_name = os.getenv('TELEGRAM_SESSION_NAME', 'london_bot_session')
    
    print(f"Connecting to session: {session_name}...")
    client = TelegramClient(session_name, api_id, api_hash)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("❌ Not authorized. Please run the bot first.")
        return
        
    print("✅ Authorized. Fetching dialogs...")
    
    target_id = -1002047709770
    found = False
    
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        # Telethon ID is usually positive for channels
        # Bot API ID is -100 + ID
        bot_api_id = int(f"-100{entity.id}") if hasattr(entity, 'id') else 0
        
        # Check title/id match
        if entity.id == 2047709770 or bot_api_id == target_id:
            print(f"🌟 FOUND TARGET!")
            print(f"Title: {dialog.name}")
            print(f"ID: {entity.id}")
            print(f"Bot API ID equivalent: {bot_api_id}")
            print(f"Type: {type(entity)}")
            found = True
            
        if "Gold" in dialog.name or "Forex" in dialog.name:
            print(f"Channel: {dialog.name} | ID: {entity.id}")

    if not found:
        print(f"\n❌ Target ID {target_id} NOT FOUND in your joined dialogs.")
        print("Please make sure you have JOINED the channel on this Telegram account.")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
