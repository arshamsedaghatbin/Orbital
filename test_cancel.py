import asyncio
from direct_mt5_engine import DirectMT5Connection

async def test():
    conn = DirectMT5Connection("test_dir")
    import os
    os.makedirs("test_dir", exist_ok=True)
    with open("test_dir/status.txt", "w") as f:
        f.write('{"orders": [{"ticket": "12345"}], "positions": []}')
    
    await conn.close_position("12345")
    
    with open("test_dir/order.txt", "r") as f:
        print(f"Order file contents:\n{f.read()}")

asyncio.run(test())
