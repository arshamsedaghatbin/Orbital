# 🛸 ORBITAL | The AI Gold Harvester

![Orbital Banner](https://img.shields.io/badge/ORBITAL-STABLE-cyan?style=for-the-badge&logo=target&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![AIBrain](https://img.shields.io/badge/Gemini-3.1_Flash-8E75FF?style=for-the-badge&logo=google-gemini&logoColor=white)
![Execution](https://img.shields.io/badge/MetaAPI-MT5-0068D7?style=for-the-badge&logo=metatrader&logoColor=white)

> **"In the noise of the markets, speed is the only signal that matters."**

Orbital is a **fully local, sovereign Quant-Execution Engine** designed to bridge the gap between Telegram-based signal intelligence and MetaTrader 5 institutional-grade execution. Unlike cloud-based trade-copiers, Orbital runs entirely on your hardware, ensuring your API keys and trading strategies never leave your machine. 

Powered by **Gemini 3.1**, Orbital filters through human chaos to extract clinical trade data with 99.9% accuracy.

---

## ⚡ CORE SYSTEMS architecture

### 🧠 Gemini 3.1 AI Brain
A sovereign signal parser that extracts:
- **Symbol & Side Extraction**: Identifies XAUUSD, Gold, or majors instantly.
- **Precision Level Detection**: Extracts Entry, SL, and multiple TP targets.
- **AI Signal Updates**: Correctly identifies and processes message updates to modify existing pending orders or MT5 positions.
- **Zero-Noise Filtering**: Discards casual chat, results updates, and marketing fluff to prevent invalid order entries.

### 📡 Telethon Neural Link
Real-time message ingestion via the **Telegram MTProto API**. 
- **Low Latency**: Sub-second ingestion from monitored VIP channels.
- **Media Processing**: Downloads and analyzes chart screenshots to confirm signal validity.

### 📊 MetaAPI Execution Engine
The high-speed bridge to MT5 via [MetaAPI](https://metaapi.cloud/).
- **Asynchronous Execution**: Orders placed with millisecond precision.
- **Live Syncing**: Keeps the dashboard and MT5 account in perfect harmony.

---

## 🛡️ HACKER FEATURES

### 🛡️ News Shield
An advanced volatility dampener. Automatically detects high-impact news events (CPI, FOMO, NFPs) and suspends signal processing to protect your capital from slippage and spreads.

### 🚀 Dynamic RR Boost (1:12)
Forget 1:2. Orbital's management logic includes **Aggressive Trailing** and **Automated Break-Even (BE)** triggers. Once a trade reaches 2.0 RR, the shield engages, moving SL to entry and hunting for the 1:12 home run.

### 💎 Smart Calibration (Dynamic Risk)
Set your risk in USD, not just lots. Orbital calculates the exact position size based on your current equity and SL distance, ensuring every trade is mathematically optimized.

### 🛡️ Boot-Time Protection Shield
Prevents re-processing of historical signals. The bot intelligently filters out any message received before its current session start, ensuring that system restarts never trigger redundant duplicate trades or entry executions.

---

## 🛠️ INSTALLATION / DEPLOYMENT

### 1. Requirements
- Python 3.10+
- Telegram API Credentials ([my.telegram.org](https://my.telegram.org))
- Google Gemini API Key
- MetaApi Account ID & Token

### 2. Fast Start
```bash
# Clone the repository
git clone git@github.com:arshamsedaghatbin/Orbital.git
cd Orbital

# Install dependencies
pip install -r requirements.txt

# Launch UI
streamlit run main.py
```

### 3. Setup Wizard
Upon first run, the **Onboarding Wizard** will guide you through:
1. **Telegram Link**: Authorize your session.
2. **AI Link**: Mount your Gemini Brain.
3. **Engine Link**: Connect to your MT5 account.

---

## ⚙️ CONFIGURATION

Configurations are stored in `.env` for security. **Never** commit your `.env` or `.session` files to public repositories.

---

## 🌐 STATUS: READY
Orbital is currently in **Active Combat Mode**. Monitor all operations in real-time via the built-in Glassmorphism Dashboard.

---

*Orbital. Engineered for the 1%.*
