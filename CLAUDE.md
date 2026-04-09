# CLAUDE.md — Instructions for Claude Code

## How to run the project

```bash
streamlit run main.py
```

The app starts on http://localhost:8501 by default.

## Important commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run with custom port
streamlit run main.py --server.port 8502

# Check for syntax errors
python -m py_compile main.py trading_engine.py direct_mt5_engine.py dashboard.py
```

## Architecture

```
Telegram → AI Brain (Gemini) → Signal Router → Execution Engine → MetaTrader 5
                                                    ├─ MetaAPI (cloud)
                                                    └─ Direct MT5 (file bridge via Socket EA)
```

## Execution Engines

### MetaAPI (default)
- Uses MetaAPI Cloud SDK over WebSocket
- Requires: `META_API_TOKEN`, `META_ACCOUNT_ID` in `.env`
- Class: `TradingEngine` in `trading_engine.py`

### Direct MT5 (file bridge)
- Writes `order.txt` to MT5's MQL5/Files directory; EA executes it
- Reads `status.txt` written by the Socket EA every second
- Requires: `MT5_FILE_PATH` in `.env` pointing to the MQL5/Files directory
- Class: `DirectMT5Engine` in `direct_mt5_engine.py`
- Engine inherits all logic from `TradingEngine`, replaces `self.connection` with `DirectMT5Connection`

## Config keys (`.env`)

| Key | Required | Description |
|-----|----------|-------------|
| `TELEGRAM_API_ID` | Always | From my.telegram.org |
| `TELEGRAM_API_HASH` | Always | From my.telegram.org |
| `GEMINI_API_KEY` | Always | From Google AI Studio |
| `EXECUTION_ENGINE` | Always | `metaapi` or `direct_mt5` |
| `META_API_TOKEN` | MetaAPI only | MetaAPI dashboard token |
| `META_ACCOUNT_ID` | MetaAPI only | MetaAPI account UUID |
| `META_REGION` | MetaAPI only | e.g., `london` |
| `MT5_FILE_PATH` | Direct MT5 only | Path to MQL5/Files directory |
| `CHANNEL_IDS` | Always | Comma-separated Telegram channel IDs |
| `RISK_USD` | Optional | Default risk per trade in USD (default 50) |
| `RR_TARGET` | Optional | Default RR target (default 6) |
| `BE_RR` | Optional | RR at which to move to break-even (default 2) |

## Files NOT to touch

- `*.session` — Telegram session files (Telethon creates these)
- `bot_owned_tickets.json` — Track bot-placed trades
- `active_trades_metadata.json` — Live trade state
- `signals_history.json` — Full signal/execution history
- `pending_queue.json` — Retry queue

## Project conventions

- All engine methods are `async` — always `await` them
- `engine.connection` is `None` when disconnected, truthy (MetaAPI RPC or `DirectMT5Connection`) when connected
- Settings per symbol are in `state.settings[symbol]` dict with keys: `risk_usd`, `rr_target`, `be_rr`, `partial_rr`, `partial_percent`
- All order IDs are strings (`str(ticket)`)
- `state.commands` is the UI→worker queue; push dicts with `type` field
- The bot worker loop restarts when `state.restart_event.set()` is called

## EA file actions (Direct MT5)

The Socket EA in MT5 reads `order.txt` and supports these actions:
`BUY`, `SELL`, `BUY_STOP`, `SELL_STOP`, `BUY_LIMIT`, `SELL_LIMIT`,
`CLOSE`, `DELETE`, `MODIFY_POSITION`, `MODIFY_ORDER`, `BREAKEVEN`, `PARTIAL_CLOSE`
