import json
import re
import asyncio
from google import genai
from google.genai import types
import os
from dotenv import load_dotenv

load_dotenv()

VECTOR_THRESHOLD = 0.79   # Early-exit confidence level


class AIBrain:
    def __init__(self, api_key: str):
        self.client   = genai.Client(api_key=api_key)
        self.model_id = "gemini-flash-latest"
        self._vector_index = None   # Injected after construction by bot_worker

    def set_vector_index(self, index):
        """Called by bot_worker to attach the VectorIndex after it is built."""
        self._vector_index = index

    # ── STAGE 1: Fast Regex (sync, microseconds) ───────────────────────────────

    def _regex_parse(self, text: str, config: dict):
        """
        Returns a signal dict if a fast-path keyword match is found, else None.
        This runs synchronously before any async stage is started.
        """
        text_lower = text.lower()

        if any(kw.lower() in text_lower for kw in config.get("cancel_keywords", [])):
            print("⚡ [Fast Path] Matched CANCEL")
            return {"type": "CANCEL", "symbol": "XAUUSD", "entry": None,
                    "sl": None, "side": None, "tps": [], "risk_level": "normal"}

        if any(kw.lower() in text_lower for kw in config.get("tp_hit_keywords", [])):
            tp_level = 2 if ("2" in text_lower or "دوم" in text_lower) else 1
            print(f"⚡ [Fast Path] Matched TP_HIT (Level {tp_level})")
            return {"type": "TP_HIT", "symbol": "XAUUSD", "tp_level": tp_level}

        if any(kw.lower() in text_lower for kw in config.get("reentry_keywords", [])):
            side = self._extract_side(text_lower)
            print(f"⚡ [Fast Path] Matched REENTRY (Side: {side})")
            return {"type": "REENTRY", "symbol": "XAUUSD", "side": side}

        if any(kw.lower() in text_lower for kw in config.get("pullback_keywords", [])):
            side = self._extract_side(text_lower)
            print(f"⚡ [Fast Path] Matched PULLBACK (Side: {side})")
            return {"type": "PULLBACK", "symbol": "XAUUSD", "side": side}

        return None

    @staticmethod
    def _extract_side(text_lower: str) -> str:
        # Check compound 'stop/limit' forms first (before plain buy/sell check)
        if any(kw in text_lower for kw in ["باي استاپ", "بای استاپ", "buy stop", "buystop", "buy_stop"]):
            return "BUY_STOP"
        if any(kw in text_lower for kw in ["سل استاپ", "sell stop", "sellstop", "sell_stop"]):
            return "SELL_STOP"
        if any(kw in text_lower for kw in ["buy limit", "buylimit", "buy_limit"]):
            return "BUY_LIMIT"
        if any(kw in text_lower for kw in ["sell limit", "selllimit", "sell_limit"]):
            return "SELL_LIMIT"
        if "بای" in text_lower or "buy" in text_lower:
            return "BUY"
        if "سل" in text_lower or "sell" in text_lower:
            return "SELL"
        return "UNKNOWN"

    @staticmethod
    def _correct_side(result: dict, text_lower: str) -> dict:
        """
        The AI often returns 'BUY' for 'Buystop' and 'SELL' for 'Sellstop'.
        For NEW/UPDATE signals, override plain BUY/SELL with stop/limit type
        whenever the original text explicitly contains the compound keyword.
        """
        if not result or result.get('type') not in ('NEW', 'UPDATE'):
            return result
        current_side = (result.get('side') or '').upper()
        # Only correct if AI returned a plain BUY/SELL (not already a STOP/LIMIT)
        if current_side in ('BUY', 'SELL', 'UNKNOWN', ''):
            derived = AIBrain._extract_side(text_lower)
            if derived not in ('BUY', 'SELL', 'UNKNOWN'):  # compound type detected
                result = dict(result)  # don't mutate original
                result['side'] = derived
                print(f"🔧 [SideCorrect] AI said '{current_side}' but text implies '{derived}'")
        return result

    # ── STAGE 2: Gemini AI (async, ~900ms) ─────────────────────────────────────

    async def _ai_parse(self, text: str, image_bytes: bytes | None) -> dict | None:
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
        2. NOISE: Only use this for greetings ("Hello"), links (https://...), or pure news analysis with no trade numbers.
           - Never mark a message with a symbol and TWO price numbers as NOISE.
        3. NUMERIC ACCURACY: Extract prices exactly as written.
        4. SIGNAL TYPE: Identify if it's NEW, UPDATE, CANCEL, REENTRY, PULLBACK, TP_HIT, or STOP.
           - Use `UPDATE` if keywords like "Update," "Modify," "New entry," "New price," or "Revised" are present.
           - Use `CANCEL` if the message means "cancel the order", "order was not triggered", or similar.
             CANCEL keywords (English): "cancel", "cancelled", "close order", "remove order", "order invalid", "ignore", "void", "not triggered", "did not activate".
             CANCEL keywords (Persian/Farsi): "کنسل", "لغو", "فعال نشد", "باطل", "حذف", "بسته شود", "اوردر فعال نشد".
           - Use `REENTRY` if keywords indicate re-entering a previous trade (often as a reply or following a stop loss).
             REENTRY keywords (English): "enter again", "re-entry", "reenter", "open again".
             REENTRY keywords (Persian/Farsi): "دوباره وارد بشید", "مجدد وارد بشید", "دوباره وارد شو", "با سل دوباره وارد", "با بای دوباره وارد", "با sell دوباره وارد", "با buy دوباره وارد", "اعتبار دارد", "دوباره اعتبار دارد".
           - Use `PULLBACK` if keywords indicate entering at a pullback.
             PULLBACK keywords (Persian/Farsi): "پولبک", "روی پولبک".
           - Use `TP_HIT` if the message indicates a Take Profit level was reached.
             Identify the level (1 or 2) and return it in the `tp_level` field.
             Keywords (English): "Tp1✅", "Tp2✅", "TP1 hit", "TP2 reached".
             Keywords (Persian/Farsi): "تارگت اول", "تارگت دوم", "تی پی ۱", "تی پی ۲".
           - Use `STOP` if the message indicates a full stop or global cancellation of orders for a symbol.
             STOP keywords (English): "Stop", "Hard stop", "Clear all", "Stop orders".
             STOP keywords (Persian/Farsi): "استاپ", "توقف", "تمام اوردرها لغو".

        5. IMAGE ANALYSIS: If a chart image is provided:
           - Look for watermark or header symbols (XAUUSD, GOLD).
           - Look for horizontal lines: Red/Orange is usually SL. Green/Blue is usually Entry/TP.
           - Extract SL and Entry from the numeric labels next to these lines.
        6. DEFAULT SYMBOL: "XAUUSD" if not specified.
        7. OUTPUT: Return ONLY a JSON object with keys: type ("NEW", "UPDATE", "CANCEL", "REENTRY", "PULLBACK", "TP_HIT", or "STOP"), symbol, entry, sl, side, tps (a list of numbers), tp_level (for TP_HIT), and risk_level.
        8. RISK LEVEL: Detect if the signal indicates elevated risk.
           - Set risk_level to "high" if keywords like "highrisk", "high risk", "risky", "aggressive", "پرریسک", "ریسک بالا" are present.
           - Otherwise, set risk_level to "normal".

        EXAMPLES:
        Text: "XAUUSD Sellstop Entry 4739.4 Sl 4742.9 TP1 4730 TP2 4720" -> { "type": "NEW", "symbol": "XAUUSD", "entry": 4739.4, "sl": 4742.9, "side": "SELL", "tps": [4730.0, 4720.0], "risk_level": "normal" }
        Text: "Update Xauusd Entry 4700 Sl 4600" -> { "type": "UPDATE", "symbol": "XAUUSD", "entry": 4700.0, "sl": 4600.0, "side": "SELL", "tps": [], "risk_level": "normal" }
        Text: "Tp1✅ XAUUSD" -> { "type": "TP_HIT", "symbol": "XAUUSD", "tp_level": 1 }
        Text: "Tp2✅ Gold" -> { "type": "TP_HIT", "symbol": "XAUUSD", "tp_level": 2 }
        Text: "Stop XAUUSD" -> { "type": "STOP", "symbol": "XAUUSD" }
        Text: "اوردر فعال نشد کنسل شود" -> { "type": "CANCEL", "symbol": "XAUUSD", "entry": null, "sl": null, "side": null, "tps": [], "risk_level": "normal" }
        Text: "XAUUSD order must be cancelled" -> { "type": "CANCEL", "symbol": "XAUUSD", "entry": null, "sl": null, "side": null, "tp": null, "risk_level": "normal" }
        Text: "Gold order not triggered, cancel it" -> { "type": "CANCEL", "symbol": "XAUUSD", "entry": null, "sl": null, "side": null, "tp": null, "risk_level": "normal" }
        """

        contents = []
        if image_bytes:
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
        if text:
            contents.append(types.Part.from_text(text=text))
        if not contents:
            return None

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
        if "NOISE" in output.upper() or not output:
            return None

        match = re.search(r"\{.*\}", output, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            if data.get("type") in ["NEW", "UPDATE", "CANCEL", "REENTRY", "PULLBACK", "TP_HIT", "STOP"]:
                return data
        return None

    # ── STAGE 3: Vector Search (async, ~80ms) ──────────────────────────────────

    def _vector_result_to_signal(self, sig_type: str, text_lower: str) -> dict:
        """Convert a vector match type into the same signal dict format."""
        if sig_type == "CANCEL":
            return {"type": "CANCEL", "symbol": "XAUUSD", "entry": None,
                    "sl": None, "side": None, "tps": [], "risk_level": "normal"}
        if sig_type == "TP_HIT":
            tp_level = 2 if ("2" in text_lower or "دوم" in text_lower) else 1
            return {"type": "TP_HIT", "symbol": "XAUUSD", "tp_level": tp_level}
        if sig_type in ("REENTRY", "PULLBACK", "STOP"):
            side = self._extract_side(text_lower)
            return {"type": sig_type, "symbol": "XAUUSD", "side": side}
        return None

    # ── Main Entry ──────────────────────────────────────────────────────────────

    async def filter_signal(self, text: str, image_bytes: bytes | None = None):
        """
        3-Stage Waterfall Signal Parser
        ════════════════════════════════
        Stage 1 — REGEX       (sync,  ~0.01ms) → instant exit on keyword hit
        Stage 2 — GEMINI AI   (async, ~900ms)  ┐ launched in parallel
        Stage 3 — VECTOR      (async, ~80ms)   ┘ vector > 0.82 → cancel AI
        """
        # Load config
        config     = {}
        config_path = os.path.join(os.path.dirname(__file__), "parsing_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                print(f"Failed to load parsing config: {e}")

        use_ai = config.get("use_ai", True)

        # ── STAGE 1: REGEX (sync gate) ─────────────────────────────────────────
        if text and not image_bytes:
            result = self._regex_parse(text, config)
            if result:
                result['parsed_by'] = 'regex'
                return result  # Saved all API costs

        # AI required if no text or image present
        if not use_ai and not image_bytes:
            print("🛑 [Config] AI is OFF and Fast-Regex missed. Ignored as NOISE.")
            return None

        # ── STAGES 2 + 3: PARALLEL ─────────────────────────────────────────────
        # Both tasks run concurrently. Vector resolves in ~80ms.
        # If vector confidence exceeds threshold → cancel AI task immediately.

        vec_index = self._vector_index
        has_vector = vec_index is not None and vec_index.is_ready and text and not image_bytes

        # Create AI task
        ai_task = asyncio.create_task(self._ai_parse(text, image_bytes))

        if has_vector:
            # Create vector task
            vec_task = asyncio.create_task(vec_index.search(text))
            done, pending = await asyncio.wait(
                [ai_task, vec_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Check if vector finished first (it almost always will)
            if vec_task in done:
                sig_type, confidence = vec_task.result()
                if sig_type and confidence >= VECTOR_THRESHOLD:
                    # High confidence — cancel the AI call and return now
                    ai_task.cancel()
                    try:
                        await ai_task
                    except asyncio.CancelledError:
                        pass
                    signal = self._vector_result_to_signal(sig_type, text.lower() if text else "")
                    if signal:
                        signal['parsed_by'] = f'vector:{confidence:.2f}'
                        print(f"🔮 [Vector] Early exit: {sig_type} (confidence={confidence:.3f})")
                        return signal

            # Vector was uncertain — wait for AI
            try:
                ai_result = await ai_task
                # Cancel vector task if still running
                if not vec_task.done():
                    vec_task.cancel()
                # Correct side if AI under-classified (buystop → BUY etc.)
                ai_result = self._correct_side(ai_result, text.lower() if text else "")
                if ai_result:
                    ai_result['parsed_by'] = 'ai'
                return ai_result
            except asyncio.CancelledError:
                return None
            except Exception as e:
                print(f"AI Filter Error: {e}")
                return None
        else:
            # No vector index — just await AI
            try:
                ai_result = await ai_task
                ai_result = self._correct_side(ai_result, text.lower() if text else "")
                if ai_result:
                    ai_result['parsed_by'] = 'ai'
                return ai_result
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
