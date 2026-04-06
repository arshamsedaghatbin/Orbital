import asyncio
import os
from ai_brain import AIBrain
from dotenv import load_dotenv

load_dotenv()

async def test():
    ai = AIBrain(os.getenv('GEMINI_API_KEY'))
    texts = [
        "Xauusd\n\nSellstop \n\nEntry 4739.4\n\nSl 4742.9",
        "Update \nXauusd\n\nSellstop \n\nEntry 4700\n\nSl 4600",
        "Modify Gold SL 4750"
    ]
    
    for t in texts:
        print(f"\n--- Testing text ---\n{t}")
        res = await ai.filter_signal(t)
        print(f"Result: {res}")

if __name__ == "__main__":
    asyncio.run(test())
