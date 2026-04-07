import asyncio
import os
from ai_brain import AIBrain
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Missing GEMINI_API_KEY")
        return
        
    ai = AIBrain(api_key)
    
    test_messages = [
        "دوباره وارد بشید",
        "با سل دوباره وارد بشید",
        "با بای دوباره وارد بشید",
        "Gold re-entry now",
        "Enter again with Sell"
    ]
    
    for msg in test_messages:
        print(f"\nTesting: {msg}")
        result = await ai.filter_signal(msg)
        print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
