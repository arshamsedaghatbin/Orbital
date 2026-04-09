import json
import re
import asyncio
import urllib.request
import urllib.error
import os
from dotenv import load_dotenv

load_dotenv()

VECTOR_THRESHOLD = 0.79   # Early-exit confidence level
OLLAMA_URL       = "http://localhost:11434/api/generate"
OLLAMA_MODEL     = "llama3.2"

# ── Shared system prompt used by both Ollama and Gemini ────────────────────────
SIGNAL_SYSTEM_PROMPT = """You are a highly accurate specialized trading signal parser for the London Gold Bot.
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
7. REPLIED MESSAGE CONTEXT: If provided, this is the text and symbol of the message being replied to.
   - If the current message is ambiguous (e.g., "Cancel", "Re-entry", "Update") and lacks a symbol, you MUST inherit the symbol and trade side from this context.
   - Example: Parent says "XAUUSD Buy", Reply says "Cancel" -> Parse as CANCEL for XAUUSD.
8. OUTPUT: Return ONLY a JSON object with keys: type ("NEW", "UPDATE", "CANCEL", "REENTRY", "PULLBACK", "TP_HIT", or "STOP"), symbol, entry, sl, side, tps (a list of numbers), tp_level (for TP_HIT), and risk_level.
9. RISK LEVEL: Detect if the signal indicates elevated risk.
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
Text: "دوباره وارد بشید" -> { "type": "REENTRY", "symbol": "XAUUSD" }
"""


class AIBrain:
    def __init__(self, api_key: str | None = None):
        """
        Hybrid AI Brain.
        api_key: Gemini API key (optional). If not provided, Ollama is the only AI engine.
        """
        self.gemini_key = api_key or ""
        self.client     = None
        self.model_id   = "gemini-flash-latest"
        self._vector_index = None   # Injected after construction by bot_worker

        # Only init Gemini client if a key is available
        if self.gemini_key:
            try:
                from google import genai as _genai
                self.client = _genai.Client(api_key=self.gemini_key)
            except Exception as e:
                print(f"⚠️ [AIBrain] Gemini client init failed: {e}")

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_key and self.client)

    def _get_ai_provider(self, config: dict) -> str:
        """
        Returns the active AI provider ('ollama' or 'gemini').
        If Gemini is set as default but no key exists, falls back to 'ollama'.
        """
        preferred = config.get("ai_provider", "ollama").lower()
        if preferred == "gemini" and not self.has_gemini:
            print("⚠️ [AIBrain] Gemini set as default but no key — using Ollama.")
            return "ollama"
        return preferred

    def set_vector_index(self, index):
        """Called by bot_worker to attach the VectorIndex after it is built."""
        self._vector_index = index

    # ── STAGE 1: Fast Regex (sync, microseconds) ───────────────────────────────

    def _regex_parse(self, text: str, config: dict, parent_context: dict | None = None):
        """
        Returns a signal dict if a fast-path keyword match is found, else None.
        This runs synchronously before any async stage is started.
        """
        text_lower = text.lower()
        
        fallback_sym = "XAUUSD"
        if parent_context and parent_context.get('symbol'):
            fallback_sym = parent_context['symbol']
            
        detected_sym = fallback_sym
        if "eurusd" in text_lower: detected_sym = "EURUSD"
        elif "gbpusd" in text_lower: detected_sym = "GBPUSD"
        elif "usdcad" in text_lower: detected_sym = "USDCAD"
        elif "gold" in text_lower or "xau" in text_lower: detected_sym = "XAUUSD"

        if any(kw.lower() in text_lower for kw in config.get("cancel_keywords", [])):
            print(f"⚡ [Fast Path] Matched CANCEL (Sym: {detected_sym})")
            return {"type": "CANCEL", "symbol": detected_sym, "entry": None,
                    "sl": None, "side": None, "tps": [], "risk_level": "normal"}

        if any(kw.lower() in text_lower for kw in config.get("tp_hit_keywords", [])):
            tp_level = 2 if ("2" in text_lower or "دوم" in text_lower) else 1
            print(f"⚡ [Fast Path] Matched TP_HIT (Level {tp_level}, Sym: {detected_sym})")
            return {"type": "TP_HIT", "symbol": detected_sym, "tp_level": tp_level}

        if any(kw.lower() in text_lower for kw in config.get("reentry_keywords", [])):
            side = self._extract_side(text_lower)
            print(f"⚡ [Fast Path] Matched REENTRY (Side: {side}, Sym: {detected_sym})")
            return {"type": "REENTRY", "symbol": detected_sym, "side": side}

        if any(kw.lower() in text_lower for kw in config.get("pullback_keywords", [])):
            side = self._extract_side(text_lower)
            print(f"⚡ [Fast Path] Matched PULLBACK (Side: {side}, Sym: {detected_sym})")
            return {"type": "PULLBACK", "symbol": detected_sym, "side": side}

        return None

    @staticmethod
    def _extract_side(text_lower: str) -> str:
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
        if not result or result.get('type') not in ('NEW', 'UPDATE'):
            return result
        current_side = (result.get('side') or '').upper()
        if current_side in ('BUY', 'SELL', 'UNKNOWN', ''):
            derived = AIBrain._extract_side(text_lower)
            if derived not in ('BUY', 'SELL', 'UNKNOWN'):
                result = dict(result)
                result['side'] = derived
                print(f"🔧 [SideCorrect] AI said '{current_side}' but text implies '{derived}'")
        return result

    @staticmethod
    def _parse_json_output(output: str) -> dict | None:
        """Extract and validate a signal JSON object from raw model output."""
        if not output:
            return None
        if "NOISE" in output.upper():
            return None
        match = re.search(r"\{.*\}", output, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if data.get("type") in ["NEW", "UPDATE", "CANCEL", "REENTRY", "PULLBACK", "TP_HIT", "STOP"]:
                    return data
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        """
        Collapse multi-line signals (one value per line) into a single compact
        line so small local models can parse them reliably.

        Example input:
            Xauusd\n\nSellstop\n\nEntry 4731.1\n\nSl 4732.8
        Example output:
            Xauusd Sellstop Entry 4731.1 Sl 4732.8
        """
        # Remove blank lines, strip each line, join with space
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]  # drop empty
        return " ".join(lines)

    async def _ollama_parse(self, text: str, parent_context: dict | None = None) -> dict | None:
        """
        Call the local Ollama API (llama3.2) for text-only signal parsing.
        Returns a signal dict or None. Raises on connection failure.
        """
        # Normalize multi-line format into single compact line
        compact = self._normalize_text(text)

        content_text = compact
        if parent_context:
            content_text = (
                f"REPLIED MESSAGE CONTEXT:\n"
                f"Symbol: {parent_context.get('symbol')}\n"
                f"Text: {parent_context.get('text')}\n\n"
                f"CURRENT MESSAGE:\n{compact}"
            )

        prompt = f"{SIGNAL_SYSTEM_PROMPT}\n\nMESSAGE TO PARSE:\n{content_text}\n\nReturn ONLY a JSON object."

        payload = json.dumps({
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")

        loop = asyncio.get_event_loop()
        def _call():
            req = urllib.request.Request(
                OLLAMA_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=90) as resp:  # 90s for slow hardware
                body = resp.read().decode("utf-8")
                return json.loads(body).get("response", "")

        response_text = await loop.run_in_executor(None, _call)
        return self._parse_json_output(response_text)

    # ── Gemini Engine (text + vision) ────────────────────────────────────────

    async def _gemini_parse(self, text: str, image_bytes: bytes | None, parent_context: dict | None = None) -> dict | None:
        """
        Call Gemini API for text (and optional image) signal parsing.
        """
        if not self.has_gemini:
            return None

        from google.genai import types

        contents = []
        if image_bytes:
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
        if text:
            content_text = text
            if parent_context:
                content_text = (
                    f"REPLIED MESSAGE CONTEXT:\n"
                    f"Symbol: {parent_context.get('symbol')}\n"
                    f"Text: {parent_context.get('text')}\n\n"
                    f"CURRENT MESSAGE:\n{text}"
                )
            contents.append(types.Part.from_text(text=content_text))
        if not contents:
            return None

        from google.genai import types as _types  # noqa: F811

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model=self.model_id,
                config=_types.GenerateContentConfig(
                    system_instruction=SIGNAL_SYSTEM_PROMPT,
                    response_mime_type="application/json"
                ),
                contents=contents
            )
        )
        return self._parse_json_output(response.text.strip())

    # ── Main AI dispatcher (text routing + fallback) ─────────────────────────

    async def _ai_parse(self, text: str, image_bytes: bytes | None, parent_context: dict | None = None, provider: str = "ollama") -> dict | None:
        """
        Route to the correct AI engine.

        provider: 'ollama' → try Ollama first, fall back to Gemini on failure.
                  'gemini' → go straight to Gemini (manual override).

        Vision (image_bytes): always uses Gemini. Returns None with a logged
        warning if Gemini key is not available.
        """

        # ── Vision guard ────────────────────────────────────────────────────
        if image_bytes:
            if not self.has_gemini:
                print("⚠️ [AIBrain] Vision SKIPPED — Gemini key required for chart analysis.")
                # Signal callers to surface a notification (returns special marker)
                raise GeminiKeyRequiredError("Gemini Key required for Vision.")
            print("🔭 [AIBrain] Routing image to Gemini Vision...")
            return await self._gemini_parse(text, image_bytes, parent_context)

        # ── Text routing ────────────────────────────────────────────────────
        if provider == "gemini":
            print("🌐 [AIBrain] Using Gemini (manual default)...")
            return await self._gemini_parse(text, None, parent_context)

        # Ollama primary path
        try:
            print("🦙 [AIBrain] Routing to Ollama (llama3.2)...")
            result = await self._ollama_parse(text, parent_context)
            if result is not None:
                result["engine"] = "ollama"
                return result
            print("⚠️ [AIBrain] Ollama returned empty/invalid output.")
        except Exception as e:
            print(f"⚠️ [AIBrain] Ollama failed: {e}")

        # Fallback to Gemini
        if self.has_gemini:
            print("🔄 [AIBrain] Falling back to Gemini...")
            result = await self._gemini_parse(text, None, parent_context)
            if result:
                result["engine"] = "gemini_fallback"
            return result

        print("❌ [AIBrain] Both Ollama and Gemini unavailable.")
        return None

    # ── STAGE 3: Vector Search (async, ~80ms) ──────────────────────────────────

    def _vector_result_to_signal(self, sig_type: str, text_lower: str, parent_context: dict | None = None) -> dict:
        """Convert a vector match type into the same signal dict format."""
        fallback_sym = "XAUUSD"
        if parent_context and parent_context.get('symbol'):
            fallback_sym = parent_context['symbol']
            
        detected_sym = fallback_sym
        if "eurusd" in text_lower: detected_sym = "EURUSD"
        elif "gbpusd" in text_lower: detected_sym = "GBPUSD"
        elif "gold" in text_lower or "xau" in text_lower: detected_sym = "XAUUSD"

        if sig_type == "CANCEL":
            return {"type": "CANCEL", "symbol": detected_sym, "entry": None,
                    "sl": None, "side": None, "tps": [], "risk_level": "normal"}
        if sig_type == "TP_HIT":
            tp_level = 2 if ("2" in text_lower or "دوم" in text_lower) else 1
            return {"type": "TP_HIT", "symbol": detected_sym, "tp_level": tp_level}
        if sig_type in ("REENTRY", "PULLBACK", "STOP"):
            side = self._extract_side(text_lower)
            return {"type": sig_type, "symbol": detected_sym, "side": side}
        return None

    # ── Main Entry ──────────────────────────────────────────────────────────────

    async def filter_signal(self, text: str, image_bytes: bytes | None = None, parent_context: dict | None = None):
        """
        3-Stage Waterfall Signal Parser
        ════════════════════════════════
        Stage 1 — REGEX       (sync,  ~0.01ms) → instant exit on keyword hit
        Stage 2 — AI Engine   (async, ~300-900ms) → Ollama or Gemini
        Stage 3 — VECTOR      (async, ~80ms)   → vector > threshold → cancel AI

        Provider selection:
          - Default: Ollama (local)
          - If user set 'gemini' as provider in parsing_config.json → Gemini
          - Vision inputs always go to Gemini (regardless of provider setting)
        """
        # Load config
        config = {}
        config_path = os.path.join(os.path.dirname(__file__), "parsing_config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception as e:
                print(f"Failed to load parsing config: {e}")

        use_ai = config.get("use_ai", True)
        provider = self._get_ai_provider(config)

        # ── STAGE 1: REGEX (sync gate) ─────────────────────────────────────────
        if text and not image_bytes:
            result = self._regex_parse(text, config, parent_context=parent_context)
            if result:
                result['parsed_by'] = 'regex'
                return result

        # AI required if no text or image present
        if not use_ai and not image_bytes:
            print("🛑 [Config] AI is OFF and Fast-Regex missed. Ignored as NOISE.")
            return None

        # ── STAGES 2 + 3: PARALLEL ─────────────────────────────────────────────
        import re as _re
        _has_prices = bool(text and _re.search(r'\d+\.\d+', text))
        vec_index = self._vector_index
        has_vector = (vec_index is not None and vec_index.is_ready
                      and text and not image_bytes and not _has_prices)

        # Create AI task
        ai_task = asyncio.create_task(
            self._ai_parse(text, image_bytes, parent_context=parent_context, provider=provider)
        )

        if has_vector:
            vec_task = asyncio.create_task(vec_index.search(text))
            done, pending = await asyncio.wait(
                [ai_task, vec_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            if vec_task in done:
                sig_type, confidence = vec_task.result()
                if sig_type and confidence >= VECTOR_THRESHOLD:
                    ai_task.cancel()
                    try:
                        await ai_task
                    except (asyncio.CancelledError, GeminiKeyRequiredError):
                        pass
                    signal = self._vector_result_to_signal(sig_type, text.lower() if text else "", parent_context=parent_context)
                    if signal:
                        signal['parsed_by'] = f'vector:{confidence:.2f}'
                        print(f"🔮 [Vector] Early exit: {sig_type} (confidence={confidence:.3f})")
                        return signal

            # Vector uncertain — wait for AI
            try:
                ai_result = await ai_task
                if not vec_task.done():
                    vec_task.cancel()
                ai_result = self._correct_side(ai_result, text.lower() if text else "")
                if ai_result:
                    ai_result['parsed_by'] = f"ai:{ai_result.pop('engine', provider)}"
                return ai_result
            except GeminiKeyRequiredError:
                if not vec_task.done():
                    vec_task.cancel()
                return _GEMINI_KEY_REQUIRED_SENTINEL
            except asyncio.CancelledError:
                return None
            except Exception as e:
                print(f"AI Filter Error: {e}")
                return None
        else:
            try:
                ai_result = await ai_task
                ai_result = self._correct_side(ai_result, text.lower() if text else "")
                if ai_result:
                    if parent_context:
                        if not ai_result.get('symbol') or ai_result.get('symbol') == 'XAUUSD':
                            if parent_context.get('symbol'):
                                ai_result['symbol'] = parent_context['symbol']
                    ai_result['parsed_by'] = f"ai:{ai_result.pop('engine', provider)}"
                return ai_result
            except GeminiKeyRequiredError:
                return _GEMINI_KEY_REQUIRED_SENTINEL
            except Exception as e:
                print(f"AI Filter Error: {e}")
                return None

    async def generate_audio_brief(self, stats_text: str):
        """
        Generates a 30-second audio summary of today's performance.
        Returns the audio file path.
        """
        prompt = f"Provide a concise, energetic 30-second audio briefing of today's trading performance based on these stats: {stats_text}. Mention total P/L and win rate."
        if not self.has_gemini:
            return "Audio brief requires Gemini API key."
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


# ── Sentinel & exception used for vision-without-key flow ──────────────────────
class GeminiKeyRequiredError(Exception):
    """Raised when a vision input arrives but no Gemini key is configured."""

# A sentinel dict returned to process_signal so it can surface a toast/log
_GEMINI_KEY_REQUIRED_SENTINEL = {"_gemini_key_required": True}
