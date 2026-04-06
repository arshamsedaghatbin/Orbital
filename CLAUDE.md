# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
streamlit run main.py

# Run tests (standalone scripts, no test framework)
python test_ai_brain.py
python test_fix_verification.py
python test_update_parsing.py
python test_specific_order.py
python test_stop_enforcement.py
```

## Required Environment Variables (`.env`)

```
GEMINI_API_KEY=
META_API_TOKEN=
META_ACCOUNT_ID=
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_NAME=london_bot_session   # Optional, default shown
CHANNEL_IDS=                               # Comma-separated list of Telegram channel IDs
META_REGION=london                         # Optional
RISK_USD=50                                # Optional risk settings
```

On first run, if any required keys are missing or the Telethon `.session` file doesn't exist, the app redirects to an in-UI **Setup Wizard** that writes values to `.env` via `update_env_file()` in `main.py`.

## Architecture

**Orbital** is a Streamlit-based trading automation app that ingests Telegram signals, parses them with Gemini AI, and executes trades on MT5 via MetaAPI.

### Data Flow

```
Telegram (Telethon MTProto)
    → TelegramListener (telegram_listener.py)
    → bot_worker loop (main.py)
    → AIBrain.filter_signal() (ai_brain.py)       ← Gemini Flash parses signal JSON
    → TradingEngine (trading_engine.py)            ← MetaAPI executes on MT5
    → BotState (main.py)                           ← Shared state updated
    → Dashboard.render_*() (dashboard.py)          ← Streamlit UI reflects state
```

### Key Modules

- **`main.py`** — Streamlit entrypoint. Defines `BotState` (all runtime state), `bot_worker` (async loop running in a background thread via `threading.Thread`), and the top-level Streamlit render loop. `BotState` is a singleton created once via `@st.cache_resource`. The render loop polls `st.session_state` for a shared reference and re-runs every ~1 second.

- **`ai_brain.py`** — `AIBrain` wraps `google-genai` (Gemini Flash). `filter_signal()` takes text + optional image bytes and returns a structured JSON dict with keys: `type` (`NEW`/`UPDATE`/`CANCEL`), `symbol`, `entry`, `sl`, `side`, `tp`. Uses `loop.run_in_executor` since the Gemini SDK is synchronous.

- **`trading_engine.py`** — `TradingEngine` wraps `metaapi-cloud-sdk` for MT5 via RPC connection. Tracks `owned_tickets` persisted to `bot_owned_tickets.json` so the bot only manages its own trades across restarts. Implements break-even, partial close, and trailing stop logic.

- **`telegram_listener.py`** — `TelegramListener` wraps Telethon's `TelegramClient`. Uses `_tg_op_lock` (asyncio.Lock) to prevent SQLite DB contention when resolving entity names. Calls `on_message_callback` for each new message.

- **`dashboard.py`** — `Dashboard` renders the Streamlit UI. Applies glassmorphism CSS from `style.css` (falls back to inline if missing). Manages the multi-step setup wizard via `st.session_state['setup_step']`. Inter-component communication between the UI and the background worker happens through `BotState.commands` (a list of dicts the worker polls).

### State Management

`BotState` (in `main.py`) is the single source of truth. It is initialized once by `@st.cache_resource`. The background `bot_worker` thread writes to it; the Streamlit render thread reads from it. This avoids the need for explicit queues in most cases, though `BotState.lock` (an asyncio.Lock) is used for critical sections inside the worker.

### Persistence

- `signals_history.json` — All processed signal messages, loaded at boot and saved on each new signal.
- `bot_owned_tickets.json` — MT5 ticket IDs placed by the bot, used to ignore manually-placed trades.
- `*.session` — Telethon session file (name from `TELEGRAM_SESSION_NAME` env var).

### Boot-Time Signal Filtering

`BotState.boot_time` is set to `datetime.now(timezone.utc)` when the worker starts. Any Telegram message with a timestamp before `boot_time` is ignored to prevent re-processing historical signals after a restart.
