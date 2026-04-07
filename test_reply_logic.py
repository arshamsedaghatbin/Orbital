import asyncio
import os
from ai_brain import AIBrain
from dotenv import load_dotenv

load_dotenv()

async def test_replies():
    print("🧪 Testing Reply Logic in AIBrain...")
    gemini_key = os.getenv('GEMINI_API_KEY')
    if not gemini_key:
        print("❌ Error: GEMINI_API_KEY not found in .env")
        return

    brain = AIBrain(gemini_key)

    # 1. Mock Parent Context: EURUSD Buy Signal
    parent_context = {
        "text": "EURUSD Buy @ 1.0850 SL 1.0800",
        "symbol": "EURUSD"
    }

    print(f"\nScenario 1: Reply 'Cancel' to EURUSD signal")
    reply_text = "Cancel this"
    
    # Run parsing with context
    result = await brain.filter_signal(reply_text, parent_context=parent_context)
    
    print(f"Result: {result}")
    
    # Validation
    if result and result.get('type') == 'CANCEL' and result.get('symbol') == 'EURUSD':
        print("✅ SUCCESS: Corrected matched CANCEL for EURUSD via context.")
    else:
        print("❌ FAILURE: Expected CANCEL for EURUSD.")

    # 2. Mock Parent Context: XAUUSD Sell Signal
    parent_context_xau = {
        "text": "XAUUSD Sell @ 2350 SL 2360",
        "symbol": "XAUUSD"
    }
    
    print(f"\nScenario 2: Reply 'کنسل' (Cancel) to XAUUSD (inheriting context)")
    reply_farsi = "کنسل"
    result_farsi = await brain.filter_signal(reply_farsi, parent_context=parent_context_xau)
    print(f"Result: {result_farsi}")
    
    if result_farsi and result_farsi.get('type') == 'CANCEL' and result_farsi.get('symbol') == 'XAUUSD':
        print("✅ SUCCESS: Correctly matched CANCEL for XAUUSD (Farsi).")
    else:
        print("❌ FAILURE: Expected CANCEL for XAUUSD.")

    # 3. Scenario: Ambiguous Re-entry
    print(f"\nScenario 3: Reply 'دوباره وارد بشید' (Re-entry) to EURUSD signal")
    reply_reentry = "دوباره وارد بشید"
    result_reentry = await brain.filter_signal(reply_reentry, parent_context=parent_context)
    print(f"Result: {result_reentry}")
    
    if result_reentry and result_reentry.get('type') == 'REENTRY' and result_reentry.get('symbol') == 'EURUSD':
        print("✅ SUCCESS: Correctly matched REENTRY for EURUSD via context.")
    else:
        print("❌ FAILURE: Expected REENTRY for EURUSD.")

if __name__ == "__main__":
    asyncio.run(test_replies())
