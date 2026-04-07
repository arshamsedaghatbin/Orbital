import asyncio
import os
from dotenv import load_dotenv
from metaapi_cloud_sdk import MetaApi

# For loading env
load_dotenv('.env')

META_API_TOKEN = os.getenv('META_API_TOKEN')
META_ACCOUNT_ID = os.getenv('META_ACCOUNT_ID')

async def test_metaapi():
    print("Testing MetaApi Connection...")
    api = MetaApi(META_API_TOKEN)
    account = await api.metatrader_account_api.get_account(META_ACCOUNT_ID)
    
    print(f"Account state: {account.state}")
    
    if account.state != 'DEPLOYED':
        print("Deploying account...")
        await account.deploy()
    
    print("Waiting for API to connect...")
    await account.wait_connected()
    
    connection = account.get_rpc_connection()
    await connection.connect()
    
    print("Connecting via RPC...")
    await connection.wait_synchronized()
    
    print("Connection synchronized successfully!")
    
    acc_info = await connection.get_account_information()
    print("Balance:", acc_info.get('balance'))
    
    # Check open positions
    positions = await connection.get_positions()
    print("Open Positions:")
    for p in positions:
        print(" - ", p.get('id'), p.get('symbol'))
        
    # Check pending orders
    orders = await connection.get_orders()
    print("Pending Orders:")
    for o in orders:
        print(" - ", o.get('id'), o.get('symbol'))
        
    print("Disconnecting...")
    # Clean up
    await connection.close()

if __name__ == "__main__":
    asyncio.run(test_metaapi())
