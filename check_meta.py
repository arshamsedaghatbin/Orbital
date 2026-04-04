import asyncio
import os
from metaapi_cloud_sdk import MetaApi
from dotenv import load_dotenv

load_dotenv()

async def check_token():
    token = os.getenv('META_API_TOKEN')
    account_id = os.getenv('META_ACCOUNT_ID')
    api = MetaApi(token)
    try:
        print(f"Checking account {account_id}...")
        account = await api.metatrader_account_api.get_account(account_id)
        print(f"✅ Account Found: {account.name}")
        
        print("Waiting for account deployment...")
        await account.wait_connected()
        
        print("Attempting RPC connection...")
        connection = account.get_rpc_connection()
        await connection.connect()
        await connection.wait_synchronized()
        print("✅ RPC Connected and Synchronized.")
        
        account_info = await connection.get_account_information()
        print(f"📊 Account Balance: {account_info['balance']}")
        
        price = await connection.get_symbol_price('XAUUSD')
        print(f"💎 XAUUSD Price: {price}")
        
        positions = await connection.get_positions()
        print(f"📋 Positions Found: {len(positions)}")
        for p in positions:
            print(f"  - Position ID {p['id']} [{p['symbol']}] Type: {p['type']} Volume: {p['volume']} Profit: {p['unrealizedProfit']}")
            
        orders = await connection.get_orders()
        print(f"📄 Pending Orders Found: {len(orders)}")
        for o in orders:
            print(f"  - Order ID {o['id']} [{o['symbol']}] Type: {o['type']} Volume: {o['volume']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_token())



