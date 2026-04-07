"""
Vector Intelligence Index
=========================
Embeds example sentences per signal type using Gemini text-embedding-004
and provides fast cosine similarity search as a fallback stage in the
signal parsing waterfall.

Architecture:
    - Built once at startup from parsing_config.json vector_datasets
    - Queried in parallel with Gemini AI call
    - Returns (type, confidence) where confidence is cosine similarity [0-1]
    - Confidence > THRESHOLD triggers early exit, cancelling the AI call
"""

import asyncio
import json
import math
import os
import time
from typing import Optional


VECTOR_THRESHOLD = 0.79          # Min similarity to trust the result
EMBED_MODEL      = "models/gemini-embedding-001"
CONFIG_PATH      = os.path.join(os.path.dirname(__file__), "parsing_config.json")
CACHE_PATH       = os.path.join(os.path.dirname(__file__), "vector_cache.json")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity (no numpy required)."""
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[VectorIndex] Cache save error: {e}")


# ── Main Class ─────────────────────────────────────────────────────────────────

class VectorIndex:
    """
    Manages semantic embeddings for signal-type classification.

    Types tracked:
        REENTRY  → reentry_dataset
        PULLBACK → pullback_dataset
        CANCEL   → cancel_dataset
        TP_HIT   → tp_hit_dataset
        STOP     → stop_dataset
        NOISE    → noise_dataset  (explicitly negative examples)
    """

    DATASET_KEYS = {
        "REENTRY":  "reentry_dataset",
        "PULLBACK": "pullback_dataset",
        "CANCEL":   "cancel_dataset",
        "TP_HIT":   "tp_hit_dataset",
        "STOP":     "stop_dataset",
        "NOISE":    "noise_dataset",
    }

    def __init__(self, gemini_client):
        self._client   = gemini_client
        self._index    = {}          # { type: [ [float,...], ... ] }
        self._built    = False
        self._lock     = asyncio.Lock()
        self._build_ts = 0.0        # Unix timestamp of last build

    # ── Public API ─────────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._built and bool(self._index)

    @property
    def stats(self) -> dict:
        """Return per-type example counts."""
        return {t: len(vecs) for t, vecs in self._index.items()}

    async def build(self, force: bool = False) -> dict:
        """
        Load datasets from config and embed them.
        Uses disk cache to avoid re-embedding unchanged sentences.
        Returns {"status": "ok"|"error", "counts": {...}, "message": str}
        """
        async with self._lock:
            config   = _load_config()
            cache    = _load_cache()
            new_index = {}
            total    = 0
            new_embeds = 0

            for sig_type, config_key in self.DATASET_KEYS.items():
                sentences = config.get(config_key, [])
                if not sentences:
                    continue

                vecs = []
                for sentence in sentences:
                    s = sentence.strip()
                    if not s:
                        continue

                    # Check disk cache first
                    if not force and s in cache:
                        vecs.append(cache[s])
                    else:
                        # Embed via Gemini
                        try:
                            vec = await self._embed(s)
                            if vec:
                                cache[s] = vec
                                vecs.append(vec)
                                new_embeds += 1
                        except Exception as e:
                            print(f"[VectorIndex] Embed error for '{s[:30]}': {e}")

                if vecs:
                    new_index[sig_type] = vecs
                    total += len(vecs)

            self._index    = new_index
            self._built    = True
            self._build_ts = time.time()

            if new_embeds:
                _save_cache(cache)

            counts = {t: len(v) for t, v in new_index.items()}
            print(f"[VectorIndex] Built: {counts} | New embeddings: {new_embeds}")
            return {"status": "ok", "counts": counts, "new_embeds": new_embeds, "total": total}

    async def search(self, text: str, threshold: float = VECTOR_THRESHOLD) -> tuple[Optional[str], float]:
        """
        Embed `text` and find the closest signal type.
        Returns (signal_type, confidence) or (None, 0.0) if below threshold.
        """
        if not self._built or not self._index:
            return None, 0.0

        try:
            query_vec = await self._embed(text)
            if not query_vec:
                return None, 0.0

            best_type  = None
            best_score = 0.0

            for sig_type, vecs in self._index.items():
                if sig_type == "NOISE":
                    continue  # NOISE is used only for negative filtering
                for vec in vecs:
                    score = _cosine(query_vec, vec)
                    if score > best_score:
                        best_score = score
                        best_type  = sig_type

            # Reject if a NOISE example is even closer
            if "NOISE" in self._index and best_type:
                noise_score = max(
                    _cosine(query_vec, v) for v in self._index["NOISE"]
                ) if self._index["NOISE"] else 0.0
                if noise_score >= best_score:
                    return None, best_score

            if best_score >= threshold:
                return best_type, best_score

        except Exception as e:
            print(f"[VectorIndex] Search error: {e}")

        return None, 0.0

    async def add_example(self, sig_type: str, sentence: str) -> bool:
        """
        Add a single sentence to the index and persist to config.
        Returns True on success.
        """
        s = sentence.strip()
        if not s or sig_type not in self.DATASET_KEYS:
            return False

        config     = _load_config()
        config_key = self.DATASET_KEYS[sig_type]
        existing   = config.get(config_key, [])

        if s in existing:
            return True  # Already there

        existing.append(s)
        config[config_key] = existing

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[VectorIndex] Config write error: {e}")
            return False

        # Embed and add to live index
        try:
            vec = await self._embed(s)
            if vec:
                async with self._lock:
                    if sig_type not in self._index:
                        self._index[sig_type] = []
                    self._index[sig_type].append(vec)

                # Persist to cache
                cache    = _load_cache()
                cache[s] = vec
                _save_cache(cache)
        except Exception as e:
            print(f"[VectorIndex] Live-add embed error: {e}")

        return True

    async def remove_example(self, sig_type: str, sentence: str) -> bool:
        """Remove a sentence from config and live index."""
        s = sentence.strip()
        if not s or sig_type not in self.DATASET_KEYS:
            return False

        config     = _load_config()
        config_key = self.DATASET_KEYS[sig_type]
        existing   = config.get(config_key, [])

        if s not in existing:
            return False

        existing.remove(s)
        config[config_key] = existing

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[VectorIndex] Config write error: {e}")
            return False

        # Trigger full rebuild to remove from live index
        await self.build()
        return True

    async def test_query(self, text: str) -> dict:
        """
        Run a full similarity search and return all type scores.
        Used by the dashboard for live testing.
        """
        if not self._built or not self._index:
            return {"error": "Index not built yet."}

        try:
            query_vec = await self._embed(text)
            if not query_vec:
                return {"error": "Embedding failed."}

            scores = {}
            for sig_type, vecs in self._index.items():
                if not vecs:
                    continue
                scores[sig_type] = round(max(_cosine(query_vec, v) for v in vecs), 4)

            best_type   = max(scores, key=scores.get) if scores else None
            best_score  = scores.get(best_type, 0.0)
            above_threshold = best_score >= VECTOR_THRESHOLD

            return {
                "scores":    scores,
                "best_type": best_type,
                "best_score": best_score,
                "matched":   above_threshold,
                "threshold": VECTOR_THRESHOLD,
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _embed(self, text: str) -> Optional[list[float]]:
        """Call Gemini embedding API in executor (SDK is sync)."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._client.models.embed_content(
                    model=EMBED_MODEL,
                    contents=text,
                )
            )
            # Gemini SDK: EmbedContentResponse → embeddings[0].values
            if hasattr(result, "embeddings") and result.embeddings:
                return list(result.embeddings[0].values)
            return None
        except Exception as e:
            print(f"[VectorIndex] _embed error: {e}")
            return None
