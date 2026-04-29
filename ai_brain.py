import json
import re
import asyncio
import urllib.request
import urllib.error
import os
from dotenv import load_dotenv

from enum import Enum
import time

load_dotenv()

VECTOR_THRESHOLD = 0.79   # Early-exit confidence level
OLLAMA_HOST      = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL     = "llama3.2"

class ExecutionStrategy(Enum):
    CLOUD_PRIORITY = "CLOUD_PRIORITY"
    LOCAL_PRIORITY = "LOCAL_PRIORITY"
    RACE           = "RACE"

# ── Shared system prompt used by both Ollama and Gemini ────────────────────────
SIGNAL_SYSTEM_PROMPT = """[CRITICAL: DO NOT RETURN 'NOISE' IF SYMBOL + DIRECTION ARE PRESENT. EVER.]
You are a highly accurate specialized trading signal parser.

STRICT INSTRUCTIONS:
1. PERSIAN/FARSI: Messages starting with "خرید" (Buy), "فروش" (Sell), or mentioning price are VALID commands.
2. AGGRESSIVE DETECTION: Look for Entry, SL, and Symbol. If found, it IS a NEW signal.
3. VISION: When a chart image is provided, read entry, SL, and TP prices DIRECTLY from the chart's drawn lines, labels, or annotations — even if the text contains only a symbol and direction (e.g. "EURUSD BUYstop", "GBPUSD SELL", "طلا خرید"). Never return NOISE when a chart image is present alongside any recognisable symbol and direction.
4. RISK SCAN: Always check for risk markers. Tag `risk_level: "high"` if words like "پرریسک", "با احتیاط", or "high risk" are near.
5. SIDE MAPPING — map any direction keyword to one of these exact values:
   "BUY"       → buy, long, خرید
   "SELL"      → sell, short, فروش
   "BUY_STOP"  → buystop, buy stop, buy_stop, بای استاپ, باي استاپ
   "SELL_STOP" → sellstop, sell stop, sell_stop, سل استاپ
   "BUY_LIMIT" → buylimit, buy limit, buy_limit
   "SELL_LIMIT"→ selllimit, sell limit, sell_limit
6. UPDATE KEYWORD: If the message/caption contains "update", "آپدیت", or "بروزرسانی" AND provides new entry/SL prices, return type="NEW" with all prices filled — the previous signal will be cancelled by the system automatically. Do NOT return type="UPDATE" for these messages.
7. PULLBACK DETECTION: If the user provides a chart image showing a trajectory or zig-zag arrow that plunges down into a support area *before* rising back up to the entry level (or vice-versa for sells), OR if the text explicitly says "deep pullback", "activation zone", or "bounce", YOU MUST output `"pullback": true`. Otherwise, output `"pullback": false`.
8. JSON ONLY: Return nothing but the JSON object.
9. OUTPUT: Return ONLY JSON with keys: type, symbol, entry, sl, side, tps (list), risk_level, and pullback (boolean).
"""


class AIBrain:
    def __init__(self, api_key: str | None = None):
        """
        Hybrid AI Brain.
        api_key: Gemini API key (optional). If not provided, Ollama is the only AI engine.
        """
        self.gemini_key = api_key or ""
        self.client     = None
        self.model_id   = "gemini-1.5-flash-8b-latest"
        self._vector_index = None   # Injected after construction by bot_worker

        # Only init Gemini client if a key is available
        if self.gemini_key:
            try:
                from google import genai as _genai
                self.client = _genai.Client(api_key=self.gemini_key)
            except Exception as e:
                print(f"⚠️ [AIBrain] Gemini client init failed: {e}")
        
        # Init Ollama Async Client
        try:
            from ollama import AsyncClient
            self.ollama_client = AsyncClient(host=OLLAMA_HOST)
        except Exception as e:
            print(f"⚠️ [AIBrain] Ollama client init failed: {e}")
            self.ollama_client = None

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

    # ── STAGE 0: Regex Templates (Instant Extraction) ──────────────────────────

    def _template_parse(self, text: str, channel_id: str | None = None) -> dict | None:
        """
        Match text against stored Named-Group Regex templates.
        Returns full signal data if matched, else None.
        """
        templates_path = os.path.join(os.path.dirname(__file__), "signal_templates.json")
        if not os.path.exists(templates_path):
            return None
        
        try:
            with open(templates_path, "r") as f:
                data = json.load(f)
        except: return None

        # Build list of templates to try: Channel-specific first, then Global.
        # For non-Telegram sources (Bale, Manual, etc.) that have no stored channel ID,
        # try every channel's templates so they get the same coverage as Telegram.
        channels = data.get("channels", {})
        channel_key = str(channel_id) if channel_id else ""
        if channel_key in channels:
            all_templates = channels[channel_key] + data.get("global", [])
        else:
            # Flatten all channel-specific templates + global (deduplicated by object identity)
            all_channel = [t for ch_templates in channels.values() for t in ch_templates]
            all_templates = all_channel + data.get("global", [])
        
        compact = self._normalize_text(text)
        
        for t in all_templates:
            if not t.get("enabled", True): continue
            
            try:
                pattern = t.get("regex", "")
                match = re.search(pattern, compact, re.IGNORECASE | re.MULTILINE)
                if match:
                    groups = match.groupdict()
                    extracted_sym = groups.get("symbol", "XAUUSD") or "XAUUSD"
                    extracted_sym = extracted_sym.upper().strip()
                    
                    # Symbol Blacklist to prevent 'High risk' being 'HIGH'
                    if extracted_sym in ["HIGH", "RISK", "BUY", "SELL", "STOP", "LIMIT", "ORDER"]:
                        extracted_sym = "XAUUSD"
                        
                    signal = {
                        "type": "NEW",
                        "symbol": extracted_sym.replace("GOLD", "XAUUSD"),
                        "side": groups.get("side", "").upper(),
                        "entry": float(groups.get("entry", 0)) if groups.get("entry") else None,
                        "sl": float(groups.get("sl", 0)) if groups.get("sl") else None,
                        "tps": [],
                        "risk_level": "normal",
                        "pullback": False,
                        "parsed_by": "magic" if groups.get("type", "NEW").upper() == "NEW" else "regex"
                    }
                    
                    # Optional TP extraction (tp1, tp2...)
                    for i in range(1, 5):
                        tp_val = groups.get(f"tp{i}")
                        if tp_val: signal["tps"].append(float(tp_val))
                    
                    # --- [USER REQUEST] INCREMENT MATCH COUNTER ---
                    try:
                        t["matches"] = t.get("matches", 0) + 1
                        with open(templates_path, "w") as fw:
                            json.dump(data, fw, indent=2)
                    except Exception as fe:
                        print(f"⚠️ [Template] Match count save fail: {fe}")

                    # Valid if we have at least symbol/side or standard signal structure
                    if signal["side"] and (signal["entry"] or signal["type"] != "NEW"):
                        print(f"🎯 [Template Engine] Mode: {t.get('name')} | Match Found! (Total: {t['matches']})")
                        return signal
            except Exception as e:
                print(f"⚠️ [Template Error] Pattern {t.get('name')} failed: {e}")

        return None

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
        Call local Ollama using AsyncClient.
        """
        if not self.ollama_client:
            return None

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

        try:
            response = await self.ollama_client.generate(model=OLLAMA_MODEL, prompt=prompt, stream=False)
            return self._parse_json_output(response.get("response", ""))
        except Exception as e:
            print(f"⚠️ [AIBrain] Ollama internal error: {e}")
            return None

    def _compress_image(self, image_bytes: bytes, max_size=(1024, 1024), quality=80) -> bytes:
        """Resize and compress image to speed up upload and processing."""
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(image_bytes))
            
            # Convert to RGB if necessary (e.g. RGBA/PNG to JPEG)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            
            # Resize while maintaining aspect ratio
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=quality, optimize=True)
            return output.getvalue()
        except Exception as e:
            print(f"⚠️ [AIBrain] Image compression failed: {e}")
            return image_bytes

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
            compressed = self._compress_image(image_bytes)
            contents.append(types.Part.from_bytes(data=compressed, mime_type="image/jpeg"))
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
        _t_gemini = time.time()
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
        _gemini_ms = int((time.time() - _t_gemini) * 1000)
        mode = "vision" if image_bytes else "text"
        print(f"⏱ [Gemini] {mode} response: {_gemini_ms}ms")
        result = self._parse_json_output(response.text.strip())
        if result:
            result["gemini_ms"] = _gemini_ms
        return result

    # ── Main AI dispatcher (text routing + fallback) ─────────────────────────


    async def _route_ai(self, text: str, image_bytes: bytes | None, parent_context: dict | None, strategy: ExecutionStrategy) -> dict | None:
        """
        Hybrid AI Router following user-selectable strategies.
        """
        # --- VISION GATE ---
        if image_bytes:
            if not self.has_gemini:
                return {"type": "NOT_SUPPORTED", "reason": "GEMINI_REQUIRED_FOR_VISION"}
            res = await self._gemini_parse(text, image_bytes, parent_context)
            if res:
                res["engine"] = "gemini"
                res["raw_text"] = text
            return res

        # --- ROUTING STRATEGIES ---
        t_start = time.time()

        async def _run_gemini():
            if not self.has_gemini: return None
            res = await self._gemini_parse(text, None, parent_context)
            if res:
                res["engine"] = "gemini"
                res["raw_text"] = text
            return res

        async def _run_ollama():
            if not self.ollama_client: return None
            res = await self._ollama_parse(text, parent_context)
            if res:
                res["engine"] = "ollama"
                res["raw_text"] = text
            return res

        if strategy == ExecutionStrategy.CLOUD_PRIORITY:
            # Gemini primary, silent failover to Ollama
            result = await _run_gemini()
            if not result:
                print("🔄 [Router] Gemini failed/timeout. Falling back to local Ollama...")
                result = await _run_ollama()
            return result

        elif strategy == ExecutionStrategy.LOCAL_PRIORITY:
            # Ollama primary, silent failover to Gemini
            result = await _run_ollama()
            if not result:
                print("🔄 [Router] Ollama failed. Falling back to Gemini...")
                result = await _run_gemini()
            return result

        elif strategy == ExecutionStrategy.RACE:
            # Execute both, return first valid result
            tasks = [asyncio.create_task(_run_gemini()), asyncio.create_task(_run_ollama())]
            
            while tasks:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    res = t.result()
                    if res:
                        # Success! Cancel others
                        for p in pending: p.cancel()
                        print(f"🏎️ [Router] RACE won by: {res.get('engine')} in {time.time()-t_start:.2f}s")
                        return res
                    tasks.remove(t)
                if not tasks: break
            return None

        return await _run_ollama() # Global default

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

    async def filter_signal(self, text: str, image_bytes: bytes | None = None, parent_context: dict | None = None, channel_id: str | None = None):
        """
        4-Stage Waterfall Signal Parser
        ════════════════════════════════
        Stage 0 — TEMPLATE    (sync,  ~0.01ms) → Instant Named-Group extraction
        Stage 1 — REGEX       (sync,  ~0.01ms) → Fast command extraction (cancel/tp)
        Stage 2 — AI Engine   (async, ~300ms)  → Router (Ollama/Gemini)
        Stage 3 — VECTOR      (async, ~80ms)   → Similarity exit
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
        strategy_str = config.get("execution_strategy", "LOCAL_PRIORITY")
        provider = self._get_ai_provider(config)
        
        # --- HARD BLOCK: Any message/caption containing 'TP' is immediately dropped as NOISE ---
        if text and "tp" in text.lower():
            print("⚡ [Fast Path] Instantly dropping message as NOISE due to 'tp' hard block.")
            return {"type": "NOISE", "reason": "TP_keyword_banned"}
            
        # ── STAGE 0: TEMPLATE (Instant extraction) ─────────────────────────────
        # Also run on image captions — if caption alone is a complete signal, skip vision AI
        if text:
            t_res = self._template_parse(text, channel_id)
            if t_res:
                t_res["raw_text"] = text
                # Final check for high-risk text override
                text_low = text.lower()
                hr_keywords = ["highrisk", "risky", "پرریسک", "ریسک بالا", "با احتیاط", "حجم کم", "0.01"]
                if any(k in text_low for k in hr_keywords):
                    t_res["risk_level"] = "high"
                if image_bytes:
                    print(f"📝 [Caption] Template matched from image caption — skipping vision AI")
                return t_res

        # ── STAGE 1: REGEX (sync gate) ─────────────────────────────────────────
        # Single-line text: regex result is sufficient — return immediately.
        # Multi-line text: regex may only partially match; always continue to AI.
        if text and not image_bytes:
            _lines = [l for l in text.splitlines() if l.strip()]
            _is_multiline = len(_lines) > 1
            result = self._regex_parse(text, config, parent_context=parent_context)
            if result and not _is_multiline:
                result['parsed_by'] = 'regex'
                result["raw_text"] = text
                if any(k in text.lower() for k in ["highrisk", "risky", "پرریسک", "ریسک بالا", "با احتیاط", "حجم کم", "0.01"]):
                    result["risk_level"] = "high"
                return result
            # Multi-line: fall through to AI regardless of regex result

        # AI required if no text or image present
        if not use_ai and not image_bytes:
            print("🛑 [Config] AI is OFF and Fast-Regex missed. Ignored as NOISE.")
            return None

        # ── STAGES 2 + 3: PARALLEL ─────────────────────────────────────────────
        import re as _re
        # Match both decimal (4900.5) and integer (4900) prices — 3+ digit numbers
        _has_prices = bool(text and _re.search(r'\b\d{3,}\b', text))
        # vec_index = self._vector_index                          # [TEMP DISABLED]
        # has_vector = (vec_index is not None and vec_index.is_ready
        #               and text and not image_bytes and not _has_prices)
        vec_index = None                                          # [TEMP DISABLED]
        has_vector = False                                        # [TEMP DISABLED]

        # Determine Strategy
        strategy_str = config.get("execution_strategy", "LOCAL_PRIORITY")
        try:
            strategy = ExecutionStrategy[strategy_str]
        except:
            strategy = ExecutionStrategy.LOCAL_PRIORITY

        # Create AI task
        ai_task = asyncio.create_task(
            self._route_ai(text, image_bytes, parent_context=parent_context, strategy=strategy)
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
                        # Only inherit parent symbol when text has no explicit symbol keyword.
                        # If text mentions gold/xau/eurusd etc., the AI result is authoritative.
                        text_l = (text or "").lower()
                        has_explicit_symbol = any(k in text_l for k in [
                            "xauusd", "xau", "gold", "eurusd", "gbpusd", "usdcad",
                            "usdjpy", "audusd", "usdchf", "nzdusd", "eurgbp"
                        ])
                        if not has_explicit_symbol and (not ai_result.get('symbol') or ai_result.get('symbol') == 'XAUUSD'):
                            if parent_context.get('symbol'):
                                ai_result['symbol'] = parent_context['symbol']
                    ai_result['parsed_by'] = f"ai:{ai_result.pop('engine', provider)}"
                    
                    # High risk check
                    if text:
                        text_l = text.lower()
                        if any(k in text_l for k in ["highrisk", "risky", "پرریسک", "ریسک بالا", "با احتیاط", "حجم کم", "0.01"]):
                            ai_result["risk_level"] = "high"
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
_GEMINI_KEY_REQUIRED_SENTINEL = {"type": "NOT_SUPPORTED", "reason": "GEMINI_REQUIRED_FOR_VISION"}
