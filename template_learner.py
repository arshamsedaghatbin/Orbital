import json
import re
import os
import asyncio
from datetime import datetime
import ai_brain

LEARNER_PROMPT = r"""[CRITICAL: RETURN ONLY RAW REGEX. NO EXPLANATION. NO MARKDOWN.]
Analyze these Telegram signals and generate a SINGLE Python Regex with NAMED GROUPS.

MANDATORY NAMED GROUPS:
- (?P<symbol>...) : Must match XAUUSD, Gold, GBPUSD, etc.
- (?P<side>...) : Must match BUY, SELL, BUYSTOP, SELLSTOP, BUY LIMIT, etc.
- (?P<entry>...) : Must match the entry price (numbers/decimals).
- (?P<sl>...) : Must match stop loss (numbers).
- (?P<tp1>...)? : Optional take profits (tp1, tp2...).

CONSTRAINTS:
1. Return ONLY the regex string. 
2. Ensure it handles extra whitespace and newlines (\s+).
3. Do not include markdown blocks. Do not include 'python' or 'regex' tags.

SIGNALS:
{signals}
"""

class TemplateLearner:
    def __init__(self, ai_brain_inst):
        self.ai = ai_brain_inst
        self.templates_path = os.path.join(os.path.dirname(__file__), "signal_templates.json")

    async def learn_from_history(self, channel_id, messages):
        if not messages: return None
        
        signals_text = "\n---\n".join(messages[:50])
        prompt = LEARNER_PROMPT.format(signals=signals_text)
        
        print(f"🧠 [Learner] Analyzing {len(messages)} messages for channel {channel_id}...")
        
        try:
            raw_response = ""
            # 1. Try Gemini
            if self.ai.client:
                try:
                    # The google-genai Client.models.generate_content is SYNCHRONOUS
                    # We run it in a thread to avoid blocking the event loop
                    def _call_gemini():
                        return self.ai.client.models.generate_content(
                            model=self.ai.model_id,
                            contents=prompt
                        )
                    
                    response = await asyncio.to_thread(_call_gemini)
                    raw_response = response.text
                except Exception as e:
                    print(f"⚠️ [Learner] Gemini generate_content failed: {e}")

            # 2. Try Ollama Fallback
            if not raw_response and hasattr(self.ai, 'ollama_client') and self.ai.ollama_client:
                try:
                    # Ollama client IS usually async
                    # Use the global OLLAMA_MODEL from ai_brain module
                    model_name = getattr(ai_brain, 'OLLAMA_MODEL', 'llama3.2')
                    resp = await self.ai.ollama_client.generate(model=model_name, prompt=prompt)
                    raw_response = resp.get("response", "")
                except Exception as e:
                    print(f"⚠️ [Learner] Ollama generate failed: {e}")

            if not raw_response:
                print("❌ [Learner] No response from AI engines.")
                return None

            # --- AGGRESSIVE CLEANING ---
            clean_regex = raw_response.strip()
            
            md_match = re.search(r'```(?:python|regex)?\n?(.*?)\n?```', raw_response, re.DOTALL)
            if md_match:
                clean_regex = md_match.group(1).strip()
            
            if "(?P<symbol>" not in clean_regex:
                lines = [l.strip() for l in raw_response.split('\n') if "(?P<symbol>" in l]
                if lines: clean_regex = lines[0]

            clean_regex = re.sub(r'^[rfb]*["\']', '', clean_regex)
            clean_regex = re.sub(r'["\']$', '', clean_regex).strip()
            
            if clean_regex and "(?P<symbol>" in clean_regex:
                self._save_template(channel_id, clean_regex)
                return clean_regex
            else:
                print(f"❌ [Learner] Extraction failed. AI Output Preview: {raw_response[:100]}...")
                return None
                
        except Exception as e:
            print(f"❌ [Learner] Master Loop Failed: {e}")
            return None

    def _save_template(self, channel_id, regex):
        try:
            if not os.path.exists(self.templates_path):
                with open(self.templates_path, "w") as f: json.dump({"global": [], "channels": {}}, f)
                
            with open(self.templates_path, "r") as f:
                data = json.load(f)
            
            if "channels" not in data: data["channels"] = {}
            if str(channel_id) not in data["channels"]: data["channels"][str(channel_id)] = []
            
            if not any(t["regex"] == regex for t in data["channels"][str(channel_id)]):
                data["channels"][str(channel_id)].insert(0, {
                    "name": f"Auto-Learned {datetime.now().strftime('%Y%m%d_%H%M')}",
                    "regex": regex,
                    "enabled": True,
                    "matches": 0,
                    "created_at": datetime.now().isoformat()
                })
                # Keep only last 10 templates per channel to avoid bloat
                data["channels"][str(channel_id)] = data["channels"][str(channel_id)][:10]
                
                with open(self.templates_path, "w") as f:
                    json.dump(data, f, indent=2)
                print(f"✅ [Learner] Saved template for {channel_id}")
        except Exception as e:
            print(f"❌ [Learner] Save failed: {e}")
