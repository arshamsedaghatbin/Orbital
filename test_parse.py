import asyncio
from ai_brain import AIBrain

async def check():
    brain = AIBrain()
    try:
        res = await brain.parse_signal("دوباره با سل استاپ اعتبار دارد", "XAUUSD")
        print("RESULT:")
        print(res)
    except Exception as e:
        print("ERROR:", e)

if __name__ == "__main__":
    asyncio.run(check())
