import asyncio
from ai_brain import TradingBrain

async def check():
    brain = TradingBrain()
    try:
        res = await brain.parse_signal("دوباره با سل استاپ اعتبار دارد", "XAUUSD")
        print("RESULT:")
        print(res)
    except Exception as e:
        print("ERROR:", e)

asyncio.run(check())
