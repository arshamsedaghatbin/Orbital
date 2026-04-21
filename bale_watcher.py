import asyncio
import json
import os
from datetime import datetime, timezone

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

BALE_FOLDER = os.path.expanduser("~/Downloads/bale")
# Small delay after on_created fires to let the writer finish flushing the file
_WRITE_SETTLE_S = 0.2


def _is_bale_file(name: str) -> bool:
    return name.lower().endswith(".jpg") or name.lower().endswith(".json")


class BaleWatcher:
    """
    Watches ~/Downloads/bale/ for files saved by the Chrome extension.

    Handles two file types:
      • *.jpg              — image signal (with optional <stem>.json caption)
      • bale-text-*.json  — plain-text message { type, text }

    Uses watchdog (OS filesystem events) — instant detection, zero CPU cost.
    On startup it also scans for files already present in the folder.
    """

    def __init__(self, process_signal_fn, state):
        self._process_signal = process_signal_fn
        self._state = state
        self._seen: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue = asyncio.Queue()

    async def run(self):
        os.makedirs(BALE_FOLDER, exist_ok=True)
        self._loop = asyncio.get_event_loop()
        print(f"📂 [Bale] Watcher started — monitoring {BALE_FOLDER}")

        # ── Startup scan: pick up files that arrived before observer started ──
        try:
            for name in os.listdir(BALE_FOLDER):
                if _is_bale_file(name):
                    path = os.path.join(BALE_FOLDER, name)
                    if path not in self._seen:
                        self._seen.add(path)
                        await self._queue.put(path)
        except Exception as e:
            print(f"⚠️ [Bale] Startup scan error: {e}")

        handler = _BaleEventHandler(self._queue, self._seen, self._loop)
        observer = Observer()
        observer.schedule(handler, BALE_FOLDER, recursive=False)
        observer.start()

        try:
            while True:
                filepath = await self._queue.get()
                await self._process_file(filepath)
        finally:
            observer.stop()
            observer.join()

    async def _process_file(self, filepath: str):
        filename = os.path.basename(filepath)

        # Give the writer a moment to finish flushing
        await asyncio.sleep(_WRITE_SETTLE_S)

        if not os.path.exists(filepath):
            return

        # ── *.json: text signal (bale-text-* or any standalone JSON without a paired image) ──
        if filename.lower().endswith(".json"):
            stem = os.path.splitext(filename)[0]
            jpg_path = os.path.join(BALE_FOLDER, stem + ".jpg")

            # If a companion image exists this is a caption file — skip it here,
            # the .jpg handler will read it when the image is processed.
            if os.path.exists(jpg_path):
                return

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                raw_text = meta.get("text", "") or meta.get("caption", "") or meta.get("message", "")
            except Exception as e:
                print(f"❌ [Bale] Could not read {filename}: {e}")
                self._seen.discard(filepath)
                return

            if not raw_text:
                try:
                    os.remove(filepath)
                except Exception:
                    pass
                return

            now = datetime.now(tz=timezone.utc)
            print(f"📝 [Bale] JSON signal: {raw_text[:60]!r}")
            self._state.logs.append({
                "time": now.strftime("%H:%M:%S"),
                "type": "SYSTEM",
                "preview": f"📝 [Bale] JSON: {raw_text[:60]!r}"
            })
            try:
                await self._process_signal(raw_text, source="Bale", msg_id=None, image_bytes=None, msg_date=now)
            except Exception as e:
                print(f"❌ [Bale] process_signal error for {filename}: {e}")
            try:
                os.remove(filepath)
            except Exception:
                pass
            return

        # ── *.jpg: image signal ─────────────────────────────────────────
        try:
            with open(filepath, "rb") as f:
                image_bytes = f.read()
        except Exception as e:
            print(f"❌ [Bale] Could not read {filename}: {e}")
            self._seen.discard(filepath)
            return

        # Companion JSON for caption
        stem = os.path.splitext(filename)[0]
        json_path = os.path.join(BALE_FOLDER, stem + ".json")
        caption = ""
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                caption = meta.get("caption", "")
            except Exception as e:
                print(f"⚠️ [Bale] Could not read {stem}.json: {e}")

        now = datetime.now(tz=timezone.utc)
        boot = getattr(self._state, 'boot_time', None)
        print(f"🖼️ [Bale] {filename} | caption={caption[:60]!r} | boot_ok={boot is None or now > boot}")
        self._state.logs.append({
            "time": now.strftime("%H:%M:%S"),
            "type": "SYSTEM",
            "preview": f"🖼️ [Bale] {filename} | caption={caption[:40]!r}"
        })

        try:
            await self._process_signal(caption, source="Bale", msg_id=None, image_bytes=image_bytes, msg_date=now)
            self._state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "SYSTEM",
                "preview": f"✅ [Bale] process_signal completed for {filename}"
            })
        except Exception as e:
            print(f"❌ [Bale] process_signal error for {filename}: {e}")
            self._state.logs.append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "type": "ERROR",
                "preview": f"❌ [Bale] Exception in process_signal: {e}"
            })

        for path in (filepath, json_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as e:
                    print(f"⚠️ [Bale] Could not delete {os.path.basename(path)}: {e}")


class _BaleEventHandler(FileSystemEventHandler):
    """Watchdog handler: enqueues new .jpg and bale-text-*.json files."""

    def __init__(self, queue: asyncio.Queue, seen: set, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self._queue = queue
        self._seen = seen
        self._loop = loop

    def on_created(self, event):
        if event.is_directory:
            return
        path = event.src_path
        if path in self._seen:
            return
        if not _is_bale_file(os.path.basename(path)):
            return
        self._seen.add(path)
        asyncio.run_coroutine_threadsafe(self._queue.put(path), self._loop)
