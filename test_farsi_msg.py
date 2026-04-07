import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
from ai_brain import AIBrain

async def main():
    brain = AIBrain(api_key=os.getenv("GEMINI_API_KEY"))
    text = "اجازه بدید برگرده دوباره وارد بشید"
    res = await brain.filter_signal(text)
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
