import asyncio
import os
from dotenv import load_dotenv
from metaapi_cloud_sdk import MetaApi

async def check_symbol_info():
    load_dotenv()
    token = os.getenv('META_API_TOKEN')
    account_id = os.getenv('META_ACCOUNT_ID')
    
    if not token or not account_id:
        print("Missing API Token or Account ID")
        return

    api = MetaApi(token)
    try:
        account = await api.metatrader_account_api.get_account(account_id)
        await account.wait_connected()
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()
        
        for sym in ["XAUUSD", "EURUSD"]:
            try:
                info = await connection.get_symbol_specification(sym)
                print(f"--- {sym} ---")
                print(f"Full Info: {info}")
                # Check for alternative volume keys
                print(f"Volume Step: {info.get('volumeStep')}")
                print(f"Min Volume: {info.get('minVolume')}")
                print(f"Max Volume: {info.get('maxVolume')}")
            except Exception as e:
                print(f"Error getting {sym}: {e}")
                
    except Exception as e:
        print(f"Connection Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_symbol_info())
