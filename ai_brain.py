import json
import re
import asyncio
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()


class AIBrain:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model_id = "gemini-flash-latest" 

    async def filter_signal(self, text: str, image_bytes: bytes = None):
        """
        Analyzes a message (text and/or image) to determine if it's a valid signal.
        Returns a dict with entry, sl, and side or None if NOISE.
        """
        system_instruction = """
        You are a highly accurate specialized trading signal parser for the London Gold Bot.
        Analyze Telegram messages (text and/or charts) to extract trading signals for Forex (including Gold/XAUUSD, EURUSD, GBPUSD, etc.).

        RULES:
        1. VALID SIGNAL: If the text or chart contains a symbol (e.g., XAUUSD, GOLD, EURUSD), side (BUY/SELL/SELLSTOP/BUYSTOP), and an entry and SL price.
           - BE EXTREMELY AGGRESSIVE: If you see prices (numbers like 2350.4, 1.14780) and a symbol, it IS a signal.
           - Side Detection: SELL/SELLSTOP/SHORT are all SELLS. BUY/BUYSTOP/LONG are all BUYS.
           - If no side is found but SL is > Entry, it's a SELL. If SL < Entry, it's a BUY.
           - "E", "Ent", "Price", "Entry" all mean ENTRY.
           - "SL", "Stop", "StopLoss", "S/L" all mean SL.
        2. UPDATES: If the message starts with "Update" or mentions "Change" for a symbol.
           - Map these to { "type": "UPDATE", ... }
        3. NOISE: Only use this for greetings ("Hello"), links (https://...), or pure news analysis with no trade numbers.
           - Never mark a message with a symbol and TWO price numbers as NOISE.
        4. NUMERIC ACCURACY: Extract prices exactly as written.
        5. IMAGE ANALYSIS: If a chart image is provided:
           - Look for watermark or header symbols (XAUUSD, GOLD).
           - Look for horizontal lines: Red/Orange is usually SL. Green/Blue is usually Entry/TP.
           - Extract SL and Entry from the numeric labels next to these lines.
        6. DEFAULT SYMBOL: "XAUUSD" if not specified.
        7. OUTPUT: Return ONLY a JSON object.

        EXAMPLES:
        "XAUUSD Sellstop Entry 4739.4 Sl 4742.9" -> { "type": "NEW", "symbol": "XAUUSD", "entry": 4739.4, "sl": 4742.9, "side": "SELL" }
        "Update Xauusd Sellstop Entry 4740 Sl 4742.9" -> { "type": "UPDATE", "symbol": "XAUUSD", "entry": 4740.0, "sl": 4742.9, "side": "SELL" }
        "Gold Sell 2345 Sl 2355" -> { "type": "NEW", "symbol": "XAUUSD", "entry": 2345.0, "sl": 2355.0, "side": "SELL" }
        "EURUSD Buy 1.08500 Sl 1.08200" -> { "type": "NEW", "symbol": "EURUSD", "entry": 1.08500, "sl": 1.08200, "side": "BUY" }
        """

        try:
            # Prepare contents
            contents = []
            if image_bytes:
                # Add image as first priority if available
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
            
            # If text is provided, add it
            if text:
                contents.append(types.Part.from_text(text=text))

            # If neither, return None
            if not contents:
                return None

            # Running in executor since the SDK might not be fully async yet
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: self.client.models.generate_content(
                    model=self.model_id,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json"
                    ),
                    contents=contents
                )
            )
            
            output = response.text.strip()
            # print(f"DEBUG AI OUTPUT: {output}") # For debugging
            
            if "NOISE" in output.upper() or not output:
                return None
            
            match = re.search(r"\{.*\}", output, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                # Only return if it's a valid trading action (NEW or UPDATE)
                if data.get('type') in ['NEW', 'UPDATE']:
                    return data
                return None
        except Exception as e:
            print(f"AI Filter Error: {e}")
        return None

    async def generate_audio_brief(self, stats_text: str):
        """
        Generates a 30-second audio summary of today's performance.
        Returns the audio file path.
        """
        prompt = f"Provide a concise, energetic 30-second audio briefing of today's trading performance based on these stats: {stats_text}. Mention total P/L and win rate."
        
        try:
            # Gemini Native Audio generation (simplified representation)
            # In a real implementation, we'd use the speech generation capabilities if available in the SDK
            # For now, we'll generate the text and the user can play it via a speech synthesis library or Gemini's native output.
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model_id,
                    contents=prompt
                )
            )
            return response.text
        except Exception as e:
            return f"Error generating audio summary: {e}"
