import asyncio
import os
from ai_brain import AIBrain
from dotenv import load_dotenv
from google import genai

load_dotenv()

async def test():
    gemini_key = os.getenv('GEMINI_API_KEY')
    client = genai.Client(api_key=gemini_key)
    
    print("🌍 Checking available models...")
    try:
        for model_info in client.models.list():
             print(f"Model: {model_info.name}")
    except Exception as e:
        print(f"Error listing models: {e}")

    brain = AIBrain(gemini_key)
    
    test_cases = [
        "xauusd\nsell\nentry 4646.7\nsl 4655.1",
        "Eurusd\nSellstop\nE 1.14780\nSl 1.14810"
    ]
    
    for text in test_cases:
        print(f"\nTesting AI with text:\n{text}")
        result = await brain.filter_signal(text)
        print(f"AI Filter Result: {result}")

if __name__ == "__main__":
    asyncio.run(test())
