import streamlit as st
import pandas as pd
import time
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

class Dashboard:
    def __init__(self):
        self.apply_cyber_dark_theme()
        self.state = st.session_state
        if 'commands' not in self.state:
            self.state['commands'] = []
        if 'setup_step' not in self.state:
            self.state['setup_step'] = 1
        if 'setup_data' not in self.state:
            self.state['setup_data'] = {}
        if 'tg_code_requested' not in self.state:
            self.state['tg_code_requested'] = False
        if 'tg_phone_code_hash' not in self.state:
            self.state['tg_phone_code_hash'] = None

    def apply_cyber_dark_theme(self):
        st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&family=JetBrains+Mono&display=swap');
        
        :root {
            --bg-color: #0A0E14;
            --surface-color: #121820;
            --primary-accent: #00F5FF;
            --secondary-accent: #7000FF;
            --success-color: #00FF99;
            --warning-color: #FFD700;
            --error-color: #FF4B4B;
            --text-main: #E2E8F0;
            --text-muted: #94A3B8;
            --glass-bg: rgba(18, 24, 32, 0.7);
            --glass-border: rgba(255, 255, 255, 0.08);
            --shadow-premium: 0 8px 32px 0 rgba(0, 0, 0, 0.4);
        }

        .stApp {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
        }

        /* Glassmorphism Cards */
        .glass-card {
            background: var(--glass-bg);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border-radius: 16px;
            border: 1px solid var(--glass-border);
            padding: 20px;
            box-shadow: var(--shadow-premium);
            margin-bottom: 20px;
        }

        /* Horizontal Trade Row */
        .trade-container {
            display: flex;
            flex-direction: row;
            overflow-x: auto;
            gap: 15px;
            padding: 10px 5px;
            scrollbar-width: thin;
            scrollbar-color: var(--primary-accent) transparent;
        }
        .trade-container::-webkit-scrollbar {
            height: 6px;
        }
        .trade-container::-webkit-scrollbar-thumb {
            background: var(--primary-accent);
            border-radius: 10px;
        }

        /* Streamlit Row Hack */
        div[data-testid="stHorizontalBlock"].trade-row {
            flex-wrap: nowrap !important;
            overflow-x: auto !important;
            padding-bottom: 10px;
            gap: 20px;
        }

        .trade-card {
            min-width: 280px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            border: 1px solid var(--glass-border);
            padding: 15px;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .trade-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 20px rgba(0, 245, 255, 0.1);
            border-color: var(--primary-accent);
        }

        /* Chat UI Styles */
        .chat-container {
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 5px;
        }
        .bubble {
            width: fit-content;
            max-width: 100%;
            padding: 3px 6px;
            border-radius: 8px;
            position: relative;
            font-size: 0.75rem;
            line-height: 1.1;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
            word-wrap: break-word;
        }
        .bubble-signal {
            align-self: flex-start;
            background: linear-gradient(135deg, #1A222C 0%, #121820 100%);
            border: 1px solid var(--primary-accent);
            border-bottom-left-radius: 4px;
            color: var(--text-main);
        }
        .bubble-noise {
            align-self: flex-start;
            background: #1B222B;
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-bottom-left-radius: 4px;
            color: var(--text-muted);
            opacity: 0.9;
        }
        .bubble-meta {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-bottom: 4px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        /* Badges */
        .badge {
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 0.7rem;
            font-weight: 800;
            text-transform: uppercase;
        }
        .badge-telegram { background: rgba(0, 245, 255, 0.15); color: var(--primary-accent); border: 1px solid rgba(0, 245, 255, 0.3); }
        .badge-manual { background: rgba(255, 215, 0, 0.15); color: var(--warning-color); border: 1px solid rgba(255, 215, 0, 0.3); }
        .badge-signal { background: rgba(0, 255, 153, 0.2); color: var(--success-color); }
        .badge-noise { background: rgba(255, 255, 255, 0.05); color: var(--text-muted); }

        [data-testid="stMetricValue"] {
            font-family: 'JetBrains Mono', monospace !important;
            font-size: 2.2rem !important;
            font-weight: 800 !important;
            background: linear-gradient(135deg, #FFF 30%, var(--primary-accent) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            filter: drop-shadow(0 0 10px rgba(0, 245, 255, 0.2));
        }

        [data-testid="stMetricLabel"] {
            font-family: 'Inter', sans-serif !important;
            text-transform: uppercase !important;
            letter-spacing: 2px !important;
            font-size: 0.75rem !important;
            color: var(--text-muted) !important;
        }

        /* Sidebar Styling */
        section[data-testid="stSidebar"] {
            background-color: var(--surface-color);
            border-right: 1px solid var(--glass-border);
        }
        
        /* Status Dot */
        .status-pill {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 12px;
            border: 1px solid var(--glass-border);
        }
        .dot {
            height: 10px;
            width: 10px;
            border-radius: 50%;
            display: inline-block;
        }
        .dot-online { background-color: var(--success-color); box-shadow: 0 0 12px var(--success-color); animation: pulse 2s infinite; }
        .dot-offline { background-color: var(--error-color); box-shadow: 0 0 12px var(--error-color); }

        @keyframes pulse {
            0% { transform: scale(0.95); opacity: 0.8; }
            50% { transform: scale(1.05); opacity: 1; }
            100% { transform: scale(0.95); opacity: 0.8; }
        }

        /* Interactive Elements */
        .stButton button {
            border-radius: 10px !important;
            border: 1px solid var(--glass-border) !important;
            background: rgba(255, 255, 255, 0.05) !important;
            transition: all 0.3s !important;
        }
        .stButton button:hover {
            border-color: var(--primary-accent) !important;
            background: rgba(0, 245, 255, 0.05) !important;
            box-shadow: 0 0 15px rgba(0, 245, 255, 0.1);
        }

        /* Hide Streamlit components */
        [data-testid="stAppDeployButton"], div[data-testid="stToolbar"], [data-testid="collapsedControl"] {
            display: none !important;
        }
        </style>
        """, unsafe_allow_html=True)

    def render_header(self, state):
        statuses = [
            ("TG", state.telegram_connected),
            ("MT5", state.mt5_connected),
            ("AI", state.ai_connected)
        ]
        
        status_html = ""
        for label, active in statuses:
            color = "#00FFA3" if active else "#FF3D00"
            shadow = f"0 0 15px {color}"
            status_html += f'<div class="status-item" style="display: flex; flex-direction: column; align-items: center; gap: 6px;">'
            status_html += f'<div style="width: 12px; height: 12px; background: {color}; border-radius: 50%; box-shadow: {shadow};"></div>'
            status_html += f'<div style="font-size: 0.65rem; font-weight: 800; color: #8C99A8; text-transform: uppercase; letter-spacing: 1px;">{label}</div>'
            status_html += f'</div>'

        # Use columns for the header to include the button
        cols = st.columns([1, 1, 0.4])
        with cols[0]:
            st.markdown('<h1 class="header-title" style="margin: 0; color: #00F5FF; letter-spacing: 4px; font-weight: 900; font-size: 1.4rem;">🛰️ TERMINAL CORE</h1>', unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f'<div class="status-group" style="display: flex; gap: 40px; justify-content: center;">{status_html}</div>', unsafe_allow_html=True)
        with cols[2]:
            if st.button("🔄 RESTART CORE", key="header_restart_btn", use_container_width=True):
                state.commands.append({"type": "RESTART_BOT"})
                st.toast("Restart command queued.", icon="🔄")

        st.markdown(f"""
        <style>
        /* Target the horizontal block containing our header elements */
        div[data-testid="stHorizontalBlock"]:has(h1.header-title) {{
            background: linear-gradient(90deg, rgba(0, 245, 255, 0.05) 0%, rgba(18, 24, 32, 0.8) 50%, rgba(112, 0, 255, 0.05) 100%);
            backdrop-filter: blur(15px);
            border: 1px solid rgba(0, 245, 255, 0.1);
            border-radius: 20px;
            padding: 15px 30px;
            margin-bottom: 30px;
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.3);
            width: 100%;
            display: flex;
            align-items: center;
        }}
        </style>
        """, unsafe_allow_html=True)

    def render_metrics(self, all_metrics, symbol="GLOBAL"):
        metrics = all_metrics.get(symbol, all_metrics["GLOBAL"])
        profit = metrics.get('floating_pl', 0)
        pl_color = "#00FF9D" if profit >= 0 else "#FF4B4B"

        st.markdown(f"""
        <style>
            /* tile-grid ensures we only target the mini-columns for metrics/config */
            .tile-grid [data-testid="column"] {{
                flex-grow: 0 !important;
                flex-shrink: 0 !important;
                flex-basis: 155px !important;
                width: 155px !important;
                padding-right: 10px !important;
            }}
            
            .tile-grid [data-testid="stHorizontalBlock"] {{
                gap: 0px !important;
                margin-left: -5px;
            }}

            .dashboard-grid-header {{
                font-size: 0.77rem;
                font-weight: 800;
                color: var(--primary-accent);
                margin: 20px 0 12px 0;
                letter-spacing: 1.5px;
                text-transform: uppercase;
                opacity: 0.9;
                border-left: 2px solid var(--primary-accent);
                padding-left: 10px;
            }}

            /* Standardized Tiles (Static & Interactive) */
            .dashboard-tile, [data-testid="stNumberInput"], .config-status-tile {{
                background: rgba(255, 255, 255, 0.03) !important;
                backdrop-filter: blur(12px) !important;
                border: 1px solid rgba(255, 255, 255, 0.08) !important;
                border-radius: 12px !important;
                padding: 12px 14px !important;
                height: 85px !important;
                width: 155px !important;
                display: flex !important;
                flex-direction: column !important;
                justify-content: center !important;
                box-sizing: border-box !important;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
                margin-bottom: 8px !important;
                position: relative !important;
                overflow: hidden !important;
            }}

            .dashboard-tile:hover, [data-testid="stNumberInput"]:hover, .config-status-tile:hover {{
                background: rgba(255, 255, 255, 0.06) !important;
                border: 1px solid rgba(0, 245, 255, 0.3) !important;
                transform: translateY(-2px);
                box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            }}

            /* Config Tiles Specific: Add Left Accent & Edit Icon */
            [data-testid="stNumberInput"] {{
                border-left: 2px solid rgba(0, 245, 255, 0.4) !important;
            }}
            
            /* Visual edit indicator */
            [data-testid="stNumberInput"]::after {{
                content: '✎';
                position: absolute;
                top: 12px;
                right: 14px;
                font-size: 0.7rem;
                color: var(--primary-accent);
                opacity: 0.5;
                pointer-events: none;
            }}

            .tile-label, [data-testid="stWidgetLabel"] p {{
                font-size: 0.6rem !important;
                font-weight: 800 !important;
                color: #8C99A8 !important;
                text-transform: uppercase !important;
                letter-spacing: 1px !important;
                margin: 0 0 2px 0 !important;
                line-height: 1.2 !important;
                display: flex !important;
                align-items: center !important;
                gap: 4px;
            }}

            /* Aggressive Input Styling: Removing all Streamlit backgrounds */
            .stNumberInput div[data-baseweb="input"],
            .stNumberInput div[data-baseweb="base-input"],
            .stNumberInput input {{
                background-color: transparent !important;
                background: transparent !important;
                border: none !important;
                box-shadow: none !important;
            }}

            .stNumberInput input {{
                font-size: 1.1rem !important;
                font-weight: 700 !important;
                color: #FFFFFF !important;
                padding: 0 !important;
                font-family: 'JetBrains Mono', monospace !important;
                border-bottom: 1px dashed rgba(255, 255, 255, 0.1) !important;
                border-radius: 0 !important;
            }}

            .stNumberInput input:focus {{
                border-bottom: 1px solid var(--primary-accent) !important;
                color: var(--primary-accent) !important;
            }}

            .tile-value {{
                font-size: 1.2rem !important;
                font-weight: 700 !important;
                color: #FFFFFF !important;
                font-family: 'JetBrains Mono', monospace !important;
            }}

            .config-status-tile .status-val {{
                font-size: 1.1rem !important;
                font-weight: 700 !important;
                color: var(--primary-accent);
                text-transform: uppercase;
                margin-top: 4px;
            }}

            /* Remove Streamlit default controls */
            [data-testid="stNumberInput"] button {{
                display: none !important;
            }}
            [data-testid="stNumberInput"] > div[data-baseweb="input"] {{
                background: transparent !important;
                border: none !important;
            }}
            
            /* Metric colors */
            .pl-positive {{ color: #00FF9D !important; }}
            .pl-negative {{ color: #FF4B4B !important; }}

            /* Minimal Trade Row */
            .minimal-trade-row {{
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 8px;
                padding: 10px 15px;
                margin-bottom: 8px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                font-family: 'Inter', sans-serif;
                transition: all 0.2s ease;
            }}
            .minimal-trade-row:hover {{
                background: rgba(255, 255, 255, 0.05);
                border-color: var(--primary-accent);
            }}
            .symbol-badge {{
                font-weight: 800;
                font-size: 1rem;
                color: #FFF;
                min-width: 80px;
            }}
            .type-badge {{
                font-size: 0.7rem;
                font-weight: 800;
                padding: 2px 6px;
                border-radius: 4px;
                margin-right: 15px;
                text-transform: uppercase;
            }}
            .status-tag {{
                font-family: 'JetBrains Mono';
                font-size: 0.65rem;
                font-weight: 700;
                padding: 2px 8px;
                border-radius: 12px;
                background: rgba(0,0,0,0.3);
            }}
            .price-group {{
                display: flex;
                gap: 15px;
                font-family: 'JetBrains Mono';
                font-size: 0.8rem;
                color: var(--text-muted);
            }}
            .price-group b {{ color: #FFF; }}
        </style>
        
        <div class="tile-grid">
            <p class="dashboard-grid-header">LIVE METRICS</p>
        """, unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f'<div class="dashboard-tile"><p class="tile-label">BALANCE</p><p class="tile-value">${metrics["balance"]:,.0f}</p></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="dashboard-tile"><p class="tile-label">FLOATING P/L</p><p class="tile-value {"pl-positive" if profit >= 0 else "pl-negative"}">${metrics["floating_pl"]:+.2f}</p></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="dashboard-tile"><p class="tile-label">EQUITY</p><p class="tile-value">${metrics["equity"]:,.0f}</p></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="dashboard-tile"><p class="tile-label">WIN RATE</p><p class="tile-value">{metrics["win_rate"]}%</p></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    def render_setup_wizard(self, state):
        """Ultra-premium onboarding for first-time setup."""
        st.markdown(f"""
        <div class='glass-card' style='max-width: 800px; margin: 40px auto; text-align: center; border-color: var(--primary-accent);'>
            <h1 style='color: var(--primary-accent); font-size: 2.5rem; margin-bottom: 10px;'>🛸 System Initialization</h1>
            <p style='color: var(--text-muted); font-size: 1.1rem;'>Welcome, Commander. Let's calibrate your London Gold Bot.</p>
            <div style='display: flex; justify-content: center; gap: 20px; margin: 30px 0;'>
                <div style='padding: 10px 20px; border-radius: 30px; background: { "var(--primary-accent)" if state.setup_step == 1 else "rgba(255,255,255,0.05)" }; color: { "black" if state.setup_step == 1 else "white" };'>1. Telegram</div>
                <div style='padding: 10px 20px; border-radius: 30px; background: { "var(--primary-accent)" if state.setup_step == 2 else "rgba(255,255,255,0.05)" }; color: { "black" if state.setup_step == 2 else "white" };'>2. Gemini AI</div>
                <div style='padding: 10px 20px; border-radius: 30px; background: { "var(--primary-accent)" if state.setup_step == 3 else "rgba(255,255,255,0.05)" }; color: { "black" if state.setup_step == 3 else "white" };'>3. Trade Engine</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        cols = st.columns([1, 2, 1])
        with cols[1]:
            if state.setup_step == 1:
                self._render_tg_setup(state)
            elif state.setup_step == 2:
                self._render_gemini_setup(state)
            elif state.setup_step == 3:
                self._render_meta_setup(state)

    def _render_tg_setup(self, state):
        if state.tg_connected:
            st.success("✅ Telegram Connected")
            return

        st.markdown("""
        <div class='glass-card'>
            <h3 style='color: #0088CC;'>📡 1. Telegram Connectivity</h3>
            <p style='font-size: 0.9rem; color: #94A3B8;'>
                <b>How to get these:</b><br>
                1. Log in at <a href='https://my.telegram.org' target='_blank'>my.telegram.org</a>.<br>
                2. Go to 'API development tools'.<br>
                3. Create an app (any name) to get your <b>API ID</b> and <b>API HASH</b>.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.form("tg_form"):
            api_id = st.text_input("API ID", value=os.getenv('TELEGRAM_API_ID', ''), help="From my.telegram.org")
            api_hash = st.text_input("API HASH", value=os.getenv('TELEGRAM_API_HASH', ''), help="From my.telegram.org")
            phone = st.text_input("Phone Number", placeholder="+1234567890", help="Include country code (+)")
            
            submit = st.form_submit_button("🛰️ Initialize Connection", use_container_width=True)
            if submit:
                if not api_id or not api_hash or not phone:
                    st.error("Please fill all fields.")
                else:
                    state.setup_data['TELEGRAM_API_ID'] = api_id
                    state.setup_data['TELEGRAM_API_HASH'] = api_hash
                    state.setup_data['PHONE'] = phone
                    # Trigger code request
                    state.tg_code_requested = True
                    state.commands.append({"type": "REQUEST_TG_CODE", "data": {"api_id": api_id, "api_hash": api_hash, "phone": phone}})
                    st.info("🛰️ Initializing session... Please check Telegram.")
                    st.rerun()

        if state.tg_code_requested:
            st.markdown("---")
            st.markdown("#### 🔐 Verification Code")
            code = st.text_input("Enter code from Telegram", key="tg_setup_code_input")
            if st.button("🏁 Verify & Continue", use_container_width=True, type="primary"):
                if code:
                    state.commands.append({"type": "VERIFY_TG_CODE", "data": {"code": code}})
                    st.toast("Verifying your access code...")
                else:
                    st.error("Please enter the code.")

    def _render_gemini_setup(self, state):
        st.markdown("""
        <div class='glass-card'>
            <h3 style='color: #8E75FF;'>🧠 2. Gemini AI Brain</h3>
            <p style='font-size: 0.9rem; color: #94A3B8;'>
                <b>How to get it:</b><br>
                1. Visit <a href='https://aistudio.google.com/app/apikey' target='_blank'>Google AI Studio</a>.<br>
                2. Click 'Create API key' (it's free for most regions).<br>
                3. Copy your key and paste it below.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.form("gemini_form"):
            api_key = st.text_input("Gemini API Key", type="password", value=os.getenv('GEMINI_API_KEY', ''))
            if st.form_submit_button("🧠 Link Brain", use_container_width=True):
                if api_key:
                    state.setup_data['GEMINI_API_KEY'] = api_key
                    state.setup_step = 3
                    st.rerun()
                else:
                    st.error("API Key is required.")

    def _render_meta_setup(self, state):
        st.markdown("""
        <div class='glass-card'>
            <h3 style='color: var(--primary-accent);'>📊 3. MetaApi Execution Engine</h3>
            <p style='font-size: 0.9rem; color: #94A3B8;'>
                <b>How to get these:</b><br>
                1. Log in to <a href='https://app.metaapi.cloud' target='_blank'>MetaApi Dashboard</a>.<br>
                2. Copy your <b>API Token</b> from the top of the dashboard.<br>
                3. Connected your MT5 account to MetaApi to get your <b>Account ID</b>.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.form("meta_form"):
            token = st.text_input("MetaApi Token", type="password", value=os.getenv('META_API_TOKEN', ''))
            account_id = st.text_input("Meta Account ID", value=os.getenv('META_ACCOUNT_ID', ''))
            # Support multiple channels
            channel_ids = st.text_input("Source Channel IDs (Comma separated)", value=os.getenv('CHANNEL_IDS', '-1002047709770'), help="The channels to monitor (e.g., -1002047709770, -1003749453819)")
            
            if st.form_submit_button("🏁 Complete Calibration", use_container_width=True):
                if token and account_id:
                    state.setup_data['META_API_TOKEN'] = token
                    state.setup_data['META_ACCOUNT_ID'] = account_id
                    state.setup_data['CHANNEL_IDS'] = channel_ids
                    
                    state.commands.append({"type": "FINISH_SETUP", "data": state.setup_data})
                    st.success("Saving configuration and launching...")
                    st.rerun()
                else:
                    st.error("Token and Account ID are required.")

    def render_profile_tab(self, state):
        # Current Config Summary
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### 📡 System Sources")
            tg_api_id = os.getenv('TELEGRAM_API_ID', 'Empty')
            
            # Show connected session info if available in state
            me_info = "Not Connected"
            if state.telegram_connected and hasattr(state, 'tg_me'):
                me_info = state.tg_me
            
            st.write(f"**Connected Account:** `{me_info}`")
            st.write(f"**API ID:** `{tg_api_id}`")
            st.write("**Active Channels:**")
            if state.channels:
                for c in state.channels:
                    st.markdown(f"- `{c['id']}`: **{c['name']}**")
            else:
                st.write("No active channels.")

            st.markdown("#### 🕒 Market Status")
            # Simple heuristic for Forex/Gold (Mon-Fri)
            now = datetime.now()
            is_weekend = now.weekday() >= 5
            status_color = "red" if is_weekend else "green"
            status_text = "CLOSED (Weekend)" if is_weekend else "OPEN"
            st.markdown(f"Status: :**{status_color}[{status_text}]**")
            st.caption("Auto-pending logic active when markets are closed.")

        st.markdown("---")
        st.markdown("#### 🔍 Verify New Channel")
        new_id = st.text_input("Enter Channel ID or Username to Test", placeholder="-100...")
        if st.button("📡 Test Lookup", use_container_width=True):
            if new_id:
                state.commands.append({"type": "VERIFY_CHANNEL", "data": {"id": new_id}})
                st.info("Searching for entity...")
            else:
                st.warning("Enter an ID first")
        
        if state.verify_result and str(state.verify_result.get('id')) == str(new_id):
            if "error" in state.verify_result:
                st.error(f"❌ Lookup Failed: {state.verify_result['error']}")
            elif state.verify_result.get('name'):
                st.success(f"✅ Found entity: **{state.verify_result['name']}**")
                if st.button(f"➕ Add {state.verify_result['name']} to list", use_container_width=True):
                    # Local update to force refresh
                    state.commands.append({"type": "ADD_CHANNEL", "data": {"id": new_id}})
                    st.rerun()
            else:
                st.warning("⚠️ Entity found but name is empty. It might be private.")
                
        if st.button("🗑️ Reset Verification Cache", use_container_width=True):
            state.verify_result = None
            st.rerun()

    def render_trading_activity(self, active_trades, pending_queue, state, on_close_callback, on_close_profitable_callback, on_drop_callback, on_retry_callback, symbol_filter="GLOBAL"):
        st.markdown(f"### 💎 {symbol_filter} Trading Activity")
        
        if symbol_filter == "GLOBAL" and pending_queue:
            if st.button("🧹 Purge All Pending Requests", type="secondary", use_container_width=True):
                state.commands.append({"type": "CLEAR_PENDING", "data": {}})
                st.rerun()

        filtered_active = [t for t in active_trades if symbol_filter == "GLOBAL" or t['symbol'] == symbol_filter]
        filtered_pending = [q for q in pending_queue if symbol_filter == "GLOBAL" or q['symbol'] == symbol_filter]
        
        if not filtered_active and not filtered_pending:
            st.info(f"✨ No trading activity for {symbol_filter} (Pending Queue and Active Positions are empty).")
            return

        # Control Bar
        c1, c2 = st.columns([2, 1])
        with c1:
            if filtered_active:
                if st.button(f"💰 Close All Profitable ({symbol_filter})", use_container_width=True, key=f"btn_close_prof_{symbol_filter}"):
                    on_close_profitable_callback(symbol_filter)
            else:
                st.write("")
        with c2:
            st.markdown(f"""
                <div style='text-align: right; color: var(--text-muted); padding-top: 8px; font-size: 0.8rem;'>
                    {len(filtered_active)} ACTIVE POSITIONS | {len(filtered_pending)} PENDING RETRIES
                </div>
            """, unsafe_allow_html=True)

        # Unified container for all "Rows"
        total_items = len(filtered_pending) + len(filtered_active)
        
        if total_items > 0:
            # Table Header
            hc = st.columns([1.5, 1, 2, 2.5, 3])
            hc[0].markdown('<p style="font-size: 0.65rem; color: var(--text-muted); font-weight: 800; letter-spacing: 1px;">ASSET</p>', unsafe_allow_html=True)
            hc[1].markdown('<p style="font-size: 0.65rem; color: var(--text-muted); font-weight: 800; letter-spacing: 1px;">TYPE</p>', unsafe_allow_html=True)
            hc[2].markdown('<p style="font-size: 0.65rem; color: var(--text-muted); font-weight: 800; letter-spacing: 1px;">STATUS / PROFIT</p>', unsafe_allow_html=True)
            hc[3].markdown('<p style="font-size: 0.65rem; color: var(--text-muted); font-weight: 800; letter-spacing: 1px;">LEVELS (ENTRY/SL)</p>', unsafe_allow_html=True)
            hc[4].markdown('<p style="font-size: 0.65rem; color: var(--text-muted); font-weight: 800; letter-spacing: 1px; text-align: right;">ACTIONS</p>', unsafe_allow_html=True)
            
            st.markdown('<hr style="margin: 5px 0 15px 0; border: none; border-top: 1px solid rgba(255,255,255,0.05);">', unsafe_allow_html=True)

            # Render PENDING first
            for idx, q in enumerate(filtered_pending):
                q_id = q['id']
                error_type = q.get('error_type', 'PRICE_ERROR')
                status_label = "PENDING"
                status_color = "#FF9800"
                
                if error_type == "MARKET_CLOSED":
                    status_label = "CLOSED"
                    status_color = "#FF4B4B"
                elif error_type == "TRADE_DISABLED":
                    status_label = "DISABLED"
                    status_color = "#FF4B4B"
                elif error_type == "INVALID_STOPS":
                    status_label = "STOPS"
                    status_color = "#FF4B4B"

                row = st.columns([1.5, 1, 2, 2.5, 3])
                
                # Column 1: Asset
                row[0].markdown(f'<div class="symbol-badge" style="margin-top: 8px;">{q["symbol"]}</div>', unsafe_allow_html=True)
                
                # Column 2: Type
                side_color = "#00F5FF" if q['data'].get('side','').upper() == 'BUY' else "#FF3D00"
                row[1].markdown(f'<div class="type-badge" style="background: {side_color}20; color: {side_color}; border: 1px solid {side_color}40; margin-top: 8px;">{q["data"].get("side")}</div>', unsafe_allow_html=True)
                
                # Column 3: Status
                row[2].markdown(f'<div style="margin-top: 8px;"><span class="status-tag" style="border: 1px solid {status_color}50; color: {status_color};">{status_label}</span> <span style="font-size: 0.6rem; color: var(--text-muted);">TRIES: {q["retries"]}</span></div>', unsafe_allow_html=True)
                
                # Column 4: Levels
                row[3].markdown(f"""
                    <div class="price-group" style="margin-top: 8px;">
                        <span>E: <b>{q['data'].get('entry')}</b></span>
                        <span>S: <b style="color: #FF4B4B;">{q['data'].get('sl')}</b></span>
                    </div>
                """, unsafe_allow_html=True)
                
                # Column 5: Buttons
                with row[4]:
                    btn_cols = st.columns([1, 1])
                    if btn_cols[0].button("🗑️", key=f"drop_{q_id}_{idx}_{symbol_filter}", help="Drop order", use_container_width=True):
                        on_drop_callback(q_id)
                    if btn_cols[1].button("⚡", key=f"retry_{q_id}_{idx}_{symbol_filter}", help="Immediate Retry", use_container_width=True):
                        on_retry_callback(q_id)

            # Render ACTIVE next
            for idx, t in enumerate(filtered_active):
                ticket = t['order_id']
                profit = t.get('profit', 0.0)
                profit_color = "#00FFA3" if profit >= 0 else "#FF3D00"
                
                row = st.columns([1.5, 1, 2, 2.5, 3])
                
                # Column 1: Asset
                row[0].markdown(f'<div class="symbol-badge" style="margin-top: 8px;">{t["symbol"]}</div>', unsafe_allow_html=True)
                
                # Column 2: Type
                side_color = "#00F5FF" if t['side'].upper() == 'BUY' else "#FF3D00"
                row[1].markdown(f'<div class="type-badge" style="background: {side_color}20; color: {side_color}; border: 1px solid {side_color}40; margin-top: 8px;">{t["side"]} {t["lot"]}</div>', unsafe_allow_html=True)
                
                # Column 3: Status / Profit
                row[2].markdown(f'<div style="margin-top: 8px;"><span class="status-tag" style="border: 1px solid #00F5FF50; color: #00F5FF;">LIVE</span> <b style="color: {profit_color}; font-family: \'JetBrains Mono\'; font-size: 0.9rem;">${profit:,.2f}</b></div>', unsafe_allow_html=True)
                
                # Column 4: Levels
                row[3].markdown(f"""
                    <div class="price-group" style="margin-top: 8px;">
                        <span>E: <b>{t['entry']}</b></span>
                        <span>S: <b style="color: #FF4B4B;">{t['sl']}</b></span>
                    </div>
                """, unsafe_allow_html=True)
                
                # Column 5: Buttons (Condensed)
                with row[4]:
                    act_cols = st.columns([1, 1, 1, 1, 1.5])
                    if act_cols[0].button("BE", key=f"be_{ticket}_{symbol_filter}", help="Set Break-Even", use_container_width=True):
                        state.commands.append({"type": "SET_BE", "id": ticket})
                    if act_cols[1].button("SL", key=f"rst_{ticket}_{symbol_filter}", help="Restore SL", use_container_width=True):
                        state.commands.append({"type": "RESTORE_SL", "id": ticket})
                    if act_cols[2].button("50", key=f"p50_{ticket}_{symbol_filter}", help="Close 50%", use_container_width=True):
                        state.commands.append({"type": "PARTIAL_CLOSE", "id": ticket, "fraction": 0.50})
                    if act_cols[3].button("80", key=f"p80_{ticket}_{symbol_filter}", help="Close 80%", use_container_width=True):
                        state.commands.append({"type": "PARTIAL_CLOSE", "id": ticket, "fraction": 0.80})
                    if act_cols[4].button("🛑", key=f"close_{ticket}_{symbol_filter}", help="Close Full", use_container_width=True, type="primary"):
                        on_close_callback(ticket)
            
            # Apply the horizontal scroll hack if needed
            st.markdown("""
            <script>
                var horizontalBlocks = window.top.document.querySelectorAll('div[data-testid="stHorizontalBlock"]');
                for (var i = 0; i < horizontalBlocks.length; i++) {
                    // Target blocks that contain our trade components
                    if (horizontalBlocks[i].innerText.includes("FULL CLOSE") || 
                        horizontalBlocks[i].innerText.includes("RETRY") ||
                        horizontalBlocks[i].innerText.includes("PENDING")) {
                        horizontalBlocks[i].style.flexWrap = "nowrap";
                        horizontalBlocks[i].style.overflowX = "auto";
                        horizontalBlocks[i].style.paddingBottom = "15px";
                        horizontalBlocks[i].style.gap = "20px";
                    }
                }
            </script>
            """, unsafe_allow_html=True)


    def render_intelligence_log(self, logs, on_clear_logs, symbol_filter=None):
        col1, col2 = st.columns([3, 1])
        col1.write("### 🧠 Intelligence Log")
        if col2.button("🗑️ Clear Logs", key=f"clear_logs_{symbol_filter}"):
            on_clear_logs()

        filtered_logs = logs
        if symbol_filter and symbol_filter != "GLOBAL":
            filtered_logs = [l for l in logs if symbol_filter in l['preview'].upper() or l['type'] == "SYSTEM"]

        log_container = st.container(height=300)
        with log_container:
            for log in reversed(filtered_logs):
                tag_class = "signal-tag" if log['type'] == "SIGNAL" else "noise-tag"
                st.markdown(f"""
                <div class="intelligence-log">
                    [{log['time']}] | {log['preview']} | 
                    <span class="{tag_class}">AI Decision: {log['type']}</span>
                </div>
                """, unsafe_allow_html=True)

    def render_history(self, history, on_clear_history, symbol_filter=None):
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.markdown("### 📜 Signal & Noise History")
        with col2:
            st.caption(f"{len(history)} entries")
        with col3:
            if st.button("🗑️ Clear", key=f"clear_hist_{symbol_filter}"):
                on_clear_history()

        if not history:
            st.info("No messages yet.")
            return

        filtered_history = history
        if symbol_filter and symbol_filter != "GLOBAL":
            filtered_history = [
                h for h in history 
                if (h.get('signal') and h['signal'].get('symbol') == symbol_filter) 
                or (not h.get('signal') and symbol_filter.lower() in h['text'].lower())
            ]

        history_container = st.container(height=600)
        with history_container:
            st.markdown('<div class="chat-container">', unsafe_allow_html=True)
            for i, msg in enumerate(filtered_history):
                is_signal = msg.get('signal') is not None
                bubble_type = "bubble-signal" if is_signal else "bubble-noise"
                badge_type = "badge-signal" if is_signal else "badge-noise"
                tag = "SIGNAL" if is_signal else "NOISE"
                source = msg.get('source', '')
                source_label = f" • {source}" if source else ""
                
                # Combine text and signal details into one block to avoid Streamlit element spacing
                content_html = f"""<div class="bubble {bubble_type}">
<div class="bubble-meta">
<span>{msg['date']}</span>
<span class="badge {badge_type}">{tag}</span>
<span>{source_label}</span>
</div>
<div>{msg['text'][:800]}</div>"""
                
                if is_signal:
                    s = msg['signal']
                    sym = s.get('symbol', 'XAUUSD')
                    order_id = msg.get('order_id', '')
                    error = msg.get('error', '')
                    
                    if order_id:
                        order_status = f"🟢 MT5: {order_id}"
                    elif msg.get('queued'):
                        order_status = "⏳ Price Queued"
                    elif error == "MARKET_CLOSED":
                        order_status = "🌙 Market Closed"
                    elif error == "TRADE_DISABLED":
                        order_status = "🚫 Trade Disabled"
                    elif error == "INVALID_STOPS":
                        order_status = "📍 Invalid Stops"
                    else:
                        order_status = "❌ AI Filtered"

                    content_html += f"""<div style="margin-top: 3px; padding-top: 3px; border-top: 1px dashed rgba(0, 245, 255, 0.2); font-family: 'JetBrains Mono'; font-size: 0.7rem; line-height: 1.1;">
<b>{s['side']} {sym}</b> @ {s['entry']} <br>
SL: {s['sl']} | <span style="font-weight: 800; color: {'#00F5FF' if order_id else '#FF4B4B'};">{order_status}</span>
</div>"""
                
                st.markdown(content_html + "</div>", unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

    def render_manual_order(self, on_place_order_callback, key_suffix=""):
        st.write("### ✍️ Manual Signal (paste as Telegram message)")
        msg = st.text_area(
            "Paste signal message here",
            placeholder="SIGNAL\nXauusd\nSellstop\nEntry 3325.0\nSl 3330.0",
            height=140,
            key=f"manual_msg_{key_suffix}"
        )
        if st.button("🚀 Send to AI & Execute", use_container_width=True, key=f"manual_send_{key_suffix}"):
            if msg.strip():
                on_place_order_callback(msg.strip())
                st.success("📡 Sent to AI — check Intelligence Log for result.")
            else:
                st.warning("Paste a message first.")

    def render_symbol_settings(self, symbol, settings):
        st.markdown('<div class="tile-grid">', unsafe_allow_html=True)
        st.markdown(f'<p class="dashboard-grid-header">{symbol} CONFIG</p>', unsafe_allow_html=True)
        
        c1, c2 = st.columns(2)
        with c1:
            new_risk = st.number_input(
                "RISK ($) ✎", min_value=5, max_value=500, 
                value=int(settings.get('risk_usd', 50)),
                step=5, key=f"risk_{symbol}"
            )
            new_be = st.number_input(
                "DYNAMIC BE ✎", min_value=0.5, max_value=12.0, 
                value=float(settings.get('be_rr', 2.0)),
                step=0.1, key=f"be_{symbol}"
            )

        with c2:
            new_rr = st.number_input(
                "TARGET R/R ✎", min_value=1.0, max_value=25.0, 
                value=float(settings.get('rr_target', 6.0)),
                step=0.5, key=f"rr_{symbol}"
            )
            st.markdown(f'<div class="dashboard-tile"><p class="tile-label">STATUS</p><p class="tile-value" style="color: #00FF9D; font-size: 0.85rem;">ACTIVE</p></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Sync values with settings object
        settings['risk_usd'] = new_risk
        settings['rr_target'] = new_rr
        settings['be_rr'] = new_be

    def render_profile_tab(self, state, on_save_callback):
        """
        Premium Profile/Settings tab for live configuration management.
        """
        st.markdown("""
            <div style='background: linear-gradient(90deg, rgba(0, 245, 255, 0.05) 0%, rgba(112, 0, 255, 0.05) 100%); 
                        padding: 20px; border-radius: 15px; border: 1px solid rgba(255,255,255,0.1); margin-bottom: 30px;'>
                <h2 style='margin: 0; color: var(--primary-accent);'>⚙️ SYSTEM PROFILE</h2>
                <p style='color: var(--text-muted); font-size: 0.9rem;'>Manage your core identities and execution parameters.</p>
            </div>
        """, unsafe_allow_html=True)

        from dotenv import load_dotenv
        load_dotenv(override=True)

        def mask_field(val: str, prefix_len=4):
            if not val: return "NOT SET"
            return f"{val[:prefix_len]}..." if len(val) > prefix_len else val

        # Credentials Overview
        creds_col1, creds_col2 = st.columns(2)
        
        with creds_col1:
            st.markdown("### 📡 TELEGRAM CORE")
            tg_head_col1, tg_head_col2 = st.columns([2, 1])
            with tg_head_col1:
                tg_status_color = "#00FFA3" if state.telegram_connected else "#FF3D00"
                st.markdown(f'<p style="color: {tg_status_color}; font-size: 0.7rem; font-weight: 800; margin-top: -10px;">● { ("CONNECTED" if state.telegram_connected else "OFFLINE") if state.telegram_connected is not None else "PENDING" }</p>', unsafe_allow_html=True)
            with tg_head_col2:
                if st.button("Check 🔄", key="check_tg_p", use_container_width=True):
                    state.commands.append({"type": "TEST_TELEGRAM"})
                    st.toast("Testing Telegram Connection...", icon="📡")
            
            tg_api_id = os.getenv('TELEGRAM_API_ID', 'Empty')
            tg_channel = os.getenv('CHANNEL_ID', 'Empty')
            st.info(f"""**API ID:** `{mask_field(tg_api_id, 3)}`  
**CHANNEL ID:** `{tg_channel}`""")

            st.markdown("---")
            st.markdown("### 🧠 AI INTELLIGENCE")
            ai_head_col1, ai_head_col2 = st.columns([2, 1])
            with ai_head_col1:
                ai_status_color = "#00FFA3" if state.ai_connected else "#FF3D00"
                st.markdown(f'<p style="color: {ai_status_color}; font-size: 0.7rem; font-weight: 800; margin-top: -10px;">● { ("ACTIVE" if state.ai_connected else "OFFLINE") if state.ai_connected is not None else "PENDING" }</p>', unsafe_allow_html=True)
            with ai_head_col2:
                if st.button("Check 🔄", key="check_ai_p", use_container_width=True):
                    state.commands.append({"type": "TEST_AI"})
                    st.toast("Testing AI Brain...", icon="🧠")
            
            gemini_key = os.getenv('GEMINI_API_KEY', 'Empty')
            st.info(f"**GEMINI KEY:** `{mask_field(gemini_key, 6)}`")

        with creds_col2:
            st.markdown("### 📊 EXECUTION ENGINE (MetaApi)")
            mt5_head_col1, mt5_head_col2 = st.columns([2, 1])
            with mt5_head_col1:
                mt5_status_color = "#00FFA3" if state.mt5_connected else "#FF3D00"
                st.markdown(f'<p style="color: {mt5_status_color}; font-size: 0.7rem; font-weight: 800; margin-top: -10px;">● { ("CONNECTED" if state.mt5_connected else "OFFLINE") if state.mt5_connected is not None else "PENDING" }</p>', unsafe_allow_html=True)
            with mt5_head_col2:
                if st.button("Check 🔄", key="check_mt5_p", use_container_width=True):
                    state.commands.append({"type": "TEST_MT5"})
                    st.toast("Testing MT5 Connection...", icon="📊")
            
            mt5_account = os.getenv('META_ACCOUNT_ID', 'Empty')
            mt5_region = os.getenv('META_REGION', 'london')
            st.info(f"""**ACCOUNT ID:** `{mt5_account}`  
**REGION:** `{mt5_region}`""")

            st.markdown("---")
            st.markdown("### 🛡️ RISK PARAMETERS")
            p_risk = float(os.getenv('RISK_USD', 50))
            p_rr = float(os.getenv('RR_TARGET', 6.0))
            st.info(f"**RISK:** `${p_risk}`  \n**RR TARGET:** `{p_rr}x`")

        # MULTI-CHANNEL MANAGEMENT
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 📡 MULTI-CHANNEL LISTENING")
        with st.container(border=True):
            if not state.channels:
                st.warning("No signal sources active. Use the field below to add your first channel.")
            else:
                st.markdown("<p style='font-size: 0.8rem; color: #94A3B8; margin-bottom: 10px;'>Active Signal Sources:</p>", unsafe_allow_html=True)
                for chan in state.channels:
                    c_col1, c_col2 = st.columns([4, 1])
                    with c_col1:
                        st.markdown(f"🔹 **{chan['name']}** (`{chan['id']}`)")
                    with c_col2:
                        if st.button("🗑️", key=f"rm_{chan['id']}", help="Remove this channel"):
                            state.commands.append({"type": "REMOVE_CHANNEL", "data": {"id": chan["id"]}})
                            st.toast(f"Removing {chan['name']}...", icon="🗑️")

            st.markdown("---")
            st.markdown("#### **➕ Add New Signal Source**")
            new_id = st.text_input("Channel ID or Username", placeholder="-100xxxx or @ChannelName", key="new_chan_id")
            
            check_col, save_col = st.columns([1, 1])
            with check_col:
                if st.button("🔍 Check Entity", use_container_width=True):
                    if new_id:
                        state.commands.append({"type": "VERIFY_CHANNEL", "data": {"id": new_id}})
                        st.info("Verifying entity...")
                    else:
                        st.error("Enter an ID or Username first.")
            
            # Show verification result
            if state.verify_result and str(state.verify_result.get('id')) == str(new_id):
                if "error" in state.verify_result:
                    st.error(f"❌ Could not find: {state.verify_result['error']}")
                else:
                    st.success(f"✅ Found entity: **{state.verify_result['name']}**")
                    with save_col:
                        if st.button("💾 Save & Register", type="primary", use_container_width=True):
                            state.commands.append({"type": "ADD_CHANNEL", "data": {"id": state.verify_result["id"]}})
                            st.toast("Adding channel and restarting core...", icon="🚀")

        # --- ADVANCED ZONE ---
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("### 🧨 ADVANCED OPERATIONS")
        with st.container(border=True):
            reset_col1, reset_col2 = st.columns([3, 1])
            with reset_col1:
                st.markdown("#### **Factory Reset & Initial Setup**")
                st.markdown("<p style='font-size: 0.8rem; color: #888;'>This will permanently delete all API keys, stored session files, and credentials. The bot will restart in <b>Initial Setup Wizard</b> mode.</p>", unsafe_allow_html=True)
                confirm_reset = st.checkbox("I understand that all configurations will be deleted.", key="conf_reset_check")
            with reset_col2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("‼️ FACTORY RESET", type="primary", disabled=not confirm_reset, use_container_width=True):
                    state.commands.append({"type": "FACTORY_RESET"})
                    st.toast("Clearing all data... Rebooting wizard.", icon="🧨")
                    import time
                    time.sleep(1)
                    st.rerun()
                
        # Live Status Console for Profile Tab
        st.markdown("### 🖥️ SYSTEM LOGS")
        profile_logs = [l for l in state.logs if l.get('type') in ['SYSTEM', 'ERROR', 'BOOT']][-5:] # Last 5 critical logs
        log_html = '<div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.05); padding: 10px; border-radius: 8px;">'
        if not profile_logs:
            log_html += '<p style="color: grey; font-size: 0.75rem;">Waiting for system events...</p>'
        for log in reversed(profile_logs):
            l_color = "#FF4B4B" if log.get('type') == "ERROR" else ("#00FF9D" if log.get('type') == "BOOT" else "#94A3B8")
            log_html += f'<p style="margin: 0; font-family: monospace; font-size: 0.7rem; color: {l_color};">[{log["time"]}] {log["preview"]}</p>'
        log_html += '</div>'
        st.markdown(log_html, unsafe_allow_html=True)

        st.markdown(f"""
        <div style="margin-top: 40px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 20px;">
            <p style="color: var(--text-muted); font-size: 0.8rem; text-align: center;">
                System Instance: <b>{os.getpid()}</b> | Environment: <b>{os.path.basename(os.getcwd())}</b><br>
                Changes to API credentials require a core restart to take effect.
            </p>
        </div>
        """, unsafe_allow_html=True)

    def render_sidebar(self, on_audio_brief, state):
        with st.sidebar:
            st.markdown(f"""
            <div style="text-align: center; margin-bottom: 25px;">
                <h2 style="margin: 0; color: var(--text-muted); letter-spacing: 2px; font-weight: 400; font-size: 0.8rem;">SYSTEM CONTROLS</h2>
            </div>
            """, unsafe_allow_html=True)
            
            # --- Global Status Summary ---
            st.markdown('<p style="font-size: 0.7rem; font-weight: 800; color: var(--primary-accent); margin-bottom: 15px; letter-spacing: 2px;">CONNECTION MGMT</p>', unsafe_allow_html=True)
            
            if st.button("🔄 RESTART CORE", use_container_width=True):
                state.commands.append({"type": "RESTART_BOT"})
                st.info("Restart command queued.")

            st.markdown(f"""
            <div style="margin-top: 20px; font-size: 0.7rem; color: var(--text-muted); text-align: center;">
                Build: 2026.4.3 [STABLE]<br>
                Terminal ID: {os.getpid()}
            </div>
            """, unsafe_allow_html=True)
