import streamlit as st
import pandas as pd
import time
from datetime import datetime
import os
from dotenv import load_dotenv
import textwrap

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
        style_path = os.path.join(os.path.dirname(__file__), "style.css")
        if os.path.exists(style_path):
            with open(style_path, "r") as f:
                st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
        else:
            # Fallback inline if file not found
            st.markdown("<style>body { background-color: #0f172a; color: #f8fafc; }</style>", unsafe_allow_html=True)

    def render_header(self, state):
        """Minimalist Apple-style header with status pills."""
        tg_active = getattr(state, 'tg_connected', False)
        mt5_active = getattr(state, 'mt5_connected', False)
        ai_active = getattr(state, 'ai_connected', True)

        def get_status_pill(label, active):
            color = "var(--success-color)" if active else "var(--text-muted)"
            opacity = "1" if active else "0.4"
            return textwrap.dedent(f"""
                <div style="display: flex; align-items: center; gap: 8px; background: rgba(255,255,255,0.03); 
                            border: 1px solid rgba(255,255,255,0.08); padding: 6px 14px; border-radius: 20px; 
                            backdrop-filter: blur(16px); opacity: {opacity}; transition: all 0.3s ease;">
                    <div class="pulse-dot {'pulse-active' if active else ''}" style="background: {color};"></div>
                    <span style="font-size: 0.65rem; font-weight: 500; color: #f8fafc; text-transform: uppercase; 
                                letter-spacing: 0.8px;">{label}</span>
                </div>
            """).strip()

        status_html = textwrap.dedent(f"""
            <div style="display: flex; gap: 10px; justify-content: center; padding: 10px 0;">
                {get_status_pill("TELEGRAM", tg_active)}
                {get_status_pill("BROKER", mt5_active)}
                {get_status_pill("AI CORE", ai_active)}
            </div>
        """).strip()

        header_container = st.container()
        with header_container:
            cols = st.columns([1, 2, 0.8])
            with cols[0]:
                st.markdown('<h2 style="margin: 0; color: #fff; letter-spacing: -1px; font-weight: 200; font-size: 1.6rem; padding-top: 5px;">Orbital <span style="font-weight: 600;">OS</span></h2>', unsafe_allow_html=True)
            with cols[1]:
                st.markdown(status_html, unsafe_allow_html=True)
            with cols[2]:
                if st.button("RESTART CORE", key="header_restart_btn", help="Re-initialize the bot engine"):
                    state.commands.append({"type": "RESTART_BOT"})
                    st.toast("Core restart command queued.")

    def render_metrics(self, all_metrics, symbol="GLOBAL"):
        metrics = all_metrics.get(symbol, all_metrics["GLOBAL"])
        profit = metrics.get('floating_pl', 0)
        
        st.markdown(f'<div class="dashboard-grid-header">{symbol} Metrics</div>', unsafe_allow_html=True)
        cols = st.columns(4)
        with cols[0]:
            st.markdown(f'<div class="dashboard-tile"><p class="tile-label">Balance</p><p class="tile-value">${metrics["balance"]:,.2f}</p></div>', unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f'<div class="dashboard-tile"><p class="tile-label">Equity</p><p class="tile-value">${metrics["equity"]:,.2f}</p></div>', unsafe_allow_html=True)
        with cols[2]:
            dot_color = "var(--success-color)" if profit >= 0 else "var(--error-color)"
            st.markdown(textwrap.dedent(f"""
                <div class="dashboard-tile">
                    <p class="tile-label">Floating P/L</p>
                    <p class="tile-value">
                        <span class="pulse-dot pulse-active" style="background: {dot_color}; margin-right: 4px;"></span>
                        <span class="{"pl-positive" if profit >= 0 else "pl-negative"}">${profit:+.2f}</span>
                    </p>
                </div>
            """).strip(), unsafe_allow_html=True)
        with cols[3]:
            st.markdown(f'<div class="dashboard-tile"><p class="tile-label">Win Rate</p><p class="tile-value">{metrics.get("win_rate", 0)}%</p></div>', unsafe_allow_html=True)

    def render_history(self, history, on_clear_callback, symbol_filter="GLOBAL"):
        """Renders the signal history list with Glassmorphism bubbles."""
        st.markdown('<div class="dashboard-grid-header">Signal & Noise History</div>', unsafe_allow_html=True)
        
        filtered = []
        if symbol_filter == "GLOBAL":
            filtered = history
        else:
            for item in history:
                if item.get('signal') and item['signal'].get('symbol') == symbol_filter:
                    filtered.append(item)
                elif not item.get('signal'): # Generic logs
                    filtered.append(item)

        if not filtered:
            st.info(f"No history found for {symbol_filter}.")
            return

        for item in filtered[:20]: # Show last 20
            sig = item.get('signal')
            is_trade = sig is not None
            
            meta_info = f"[{item['date']}] {item['source']}"
            if is_trade:
                badge = f'<span class="badge badge-signal">SIGNAL: {sig["type"]}</span>'
                content = f"**{sig['symbol']}** | Entry: {sig['entry']} | SL: {sig['sl']} | TP: {sig['tp']}"
            else:
                badge = '<span class="badge badge-noise">NOISE</span>'
                content = item['text'][:200] + ("..." if len(item['text']) > 200 else "")

            st.markdown(textwrap.dedent(f"""
                <div class="bubble">
                    <div class="bubble-meta">{badge} <span>{meta_info}</span></div>
                    <div style="font-size: 0.85rem; line-height: 1.4;">{content}</div>
                </div>
            """).strip(), unsafe_allow_html=True)

        if st.button("🗑️ Clear History", key=f"clear_hist_{symbol_filter}"):
            on_clear_callback()

    def render_intelligence_log(self, logs, on_clear_callback, symbol_filter="GLOBAL"):
        st.markdown('<div class="dashboard-grid-header">Intelligence Log</div>', unsafe_allow_html=True)
        
        filtered = logs
        if symbol_filter != "GLOBAL":
            filtered = [l for l in logs if symbol_filter in l.get('preview', '') or l.get('type') == 'SYSTEM']

        log_html = '<div class="glass-card" style="padding: 10px !important;">'
        for log in reversed(filtered[-30:]):
            l_type = log.get('type', 'INFO')
            color = "var(--primary-accent)" if l_type == 'TRADE' else ("var(--error-color)" if l_type == 'ERROR' else "var(--text-muted)")
            log_html += f'<div class="intelligence-log"><span style="color: {color};">[{log["time"]}]</span> {log["preview"]}</div>'
        log_html += '</div>'
        
        st.markdown(log_html, unsafe_allow_html=True)
        if st.button("🗑️ Clear Logs", key=f"clear_logs_{symbol_filter}"):
            on_clear_callback()

    def render_symbol_settings(self, symbol, config):
        st.markdown(f'<div class="dashboard-grid-header">{symbol} CONFIG</div>', unsafe_allow_html=True)
        with st.container(border=True):
            col1, col2 = st.columns(2)
            config['risk_usd'] = col1.number_input("RISK ($) 💸", value=float(config['risk_usd']), step=5.0, key=f"risk_{symbol}")
            config['rr_target'] = col2.number_input("TARGET R/R 🎯", value=float(config['rr_target']), step=0.5, key=f"rr_{symbol}")
            
            col3, col4 = st.columns(2)
            config['be_rr'] = col3.number_input("BE AT R/R 🛡️", value=float(config['be_rr']), step=0.5, key=f"be_{symbol}")
            config['partial_rr'] = col4.number_input("PARTIAL AT R/R 💰", value=float(config['partial_rr']), step=0.5, key=f"part_{symbol}")

    def render_trading_activity(self, active_trades, pending_queue, state, on_close_callback, on_close_profitable_callback, on_drop_callback, on_retry_callback, symbol_filter="GLOBAL"):
        st.markdown('<div class="dashboard-grid-header">Active & Pending activity</div>', unsafe_allow_html=True)
        
        # Pending Queue
        st.markdown("#### ⏳ PENDING QUEUE")
        q_filtered = pending_queue
        if symbol_filter != "GLOBAL":
            q_filtered = [q for q in pending_queue if q.get('symbol') == symbol_filter]
            
        if not q_filtered:
            st.info("No pending trades.")
        else:
            for q in q_filtered:
                st.markdown(textwrap.dedent(f"""
                    <div class="bubble">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <span style="font-weight: 500; font-size: 0.9rem;">{q['symbol']}</span> 
                                <span style="color: var(--text-muted); font-size: 0.75rem; margin-left: 8px;">{q['type']}</span>
                            </div>
                            <div style="font-size: 0.7rem; color: var(--text-muted);">Status: <code style="background: transparent;">{q.get('status', 'Queued')}</code></div>
                        </div>
                    </div>
                """).strip(), unsafe_allow_html=True)
                
                # We still need the buttons, so we use a minimalist column layout below the glass card or inside it if possible
                # But Streamlit buttons don't easily sit inside custom HTML. 
                # We'll use a tight column layout with glass styling.
                col_btn1, col_btn2 = st.columns([1, 1])
                with col_btn1:
                    if st.button("🗑️ Drop", key=f"drop_{q['id']}", use_container_width=True):
                        on_drop_callback(q['id'])
                with col_btn2:
                    if st.button("🔄 Retry", key=f"retry_{q['id']}", use_container_width=True):
                        on_retry_callback(q['id'])

        st.markdown("---")
        
        # Active Positions
        st.markdown("#### 🚀 ACTIVE POSITIONS")
        t_filtered = active_trades
        if symbol_filter != "GLOBAL":
            t_filtered = [t for t in active_trades if t.get('symbol') == symbol_filter]
            
        if not t_filtered:
            st.info("No active positions.")
        else:
            if st.button(f"🔥 Close All Profitable {symbol_filter}", type="primary"):
                on_close_profitable_callback(symbol_filter)
                
            for t in t_filtered:
                profit = t.get('profit', 0)
                dot_color = "var(--success-color)" if profit >= 0 else "var(--error-color)"
                
                st.markdown(textwrap.dedent(f"""
                    <div class="bubble">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <span style="font-weight: 500; font-size: 0.9rem;">{t['symbol']}</span> 
                                <span style="color: var(--text-muted); font-size: 0.75rem; margin-left: 8px;">{t['type']}</span>
                                <span style="color: var(--text-muted); font-size: 0.75rem; margin-left: 8px;">Lots: {t['volume']}</span>
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <div class="pulse-dot pulse-active" style="background: {dot_color};"></div>
                                <span style="font-weight: 400; font-size: 1rem; color: {dot_color};">${profit:,.2f}</span>
                            </div>
                        </div>
                    </div>
                """).strip(), unsafe_allow_html=True)
                
                if st.button("❌ Close Position", key=f"close_{t['id']}", use_container_width=True):
                    on_close_callback(t['id'])

    def render_manual_order(self, on_manual_order, key_suffix=""):
        st.markdown('<div class="dashboard-grid-header">Manual Signal Parsing</div>', unsafe_allow_html=True)
        raw_text = st.text_area("Paste Signal Text (e.g., 'Buy XAUUSD @ 2030, SL 2025, TP 2045')", height=100, key=f"manual_{key_suffix}")
        if st.button("🚀 Process & Execute", use_container_width=True, key=f"btn_manual_{key_suffix}"):
            if raw_text:
                on_manual_order(raw_text)
                st.toast("Signal sent for processing...")
            else:
                st.warning("Please enter signal text first.")

    def render_setup_wizard(self, state):
        """Elegant multi-step onboarding for first-time automated operation."""
        # Main Title Section
        st.markdown(textwrap.dedent(f"""
            <div style="text-align: center; padding: 60px 0 30px 0;">
                <h1 style="font-weight: 200; font-size: 3.5rem; margin-bottom: 0; letter-spacing: -2px;">Orbital <span style="font-weight: 600;">Setup</span></h1>
                <p style="color: var(--text-muted); font-size: 1.1rem; font-weight: 300;">Step {state.setup_step} of 3: {self._get_step_label(state.setup_step)}</p>
            </div>
        """).strip(), unsafe_allow_html=True)
        
        # Step Progress Indicator
        self._render_step_progress(state.setup_step)

        wizard_container = st.container()
        with wizard_container:
            cols = st.columns([1, 1.5, 1])
            with cols[1]:
                if state.setup_step == 1:
                    self._render_setup_step_1(state)
                elif state.setup_step == 2:
                    self._render_setup_step_2(state)
                elif state.setup_step == 3:
                    self._render_setup_step_3(state)

    def _get_step_label(self, step):
        labels = {1: "Telegram Authentication", 2: "System Credentials", 3: "Final Connectivity"}
        return labels.get(step, "Configuration")

    def _render_step_progress(self, current_step):
        progress_html = '<div style="display: flex; justify-content: center; gap: 20px; margin-bottom: 40px;">'
        for i in range(1, 4):
            active = i <= current_step
            color = "var(--primary-accent)" if i == current_step else ("var(--success-color)" if i < current_step else "var(--glass-border)")
            progress_html += f'<div style="width: 40px; height: 4px; background: {color}; border-radius: 2px; opacity: {1 if active else 0.3};"></div>'
        progress_html += "</div>"
        st.markdown(progress_html, unsafe_allow_html=True)

    def _render_setup_step_1(self, state):
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("### 📡 STEP 1: SIGNAL CONNECT")
        st.write("Authorize Orbital to listen to your Telegram channels for signals.")
        
        # We need API ID/Hash to even start auth
        api_id = st.text_input("TELEGRAM API ID", value=os.getenv("TELEGRAM_API_ID", ""))
        api_hash = st.text_input("TELEGRAM API HASH", value=os.getenv("TELEGRAM_API_HASH", ""))
        phone = st.text_input("REGISTRATION PHONE", placeholder="+1234567890", value=state.setup_data.get('PHONE', ''))

        if state.tg_code_requested:
            st.info("Verification code sent! Please check your Telegram app.")
            code = st.text_input("VERIFICATION CODE", placeholder="12345")
            if st.button("VERIFY & PROCEED", use_container_width=True, type="primary"):
                if code:
                    state.commands.append({"type": "VERIFY_TG_CODE", "data": {"code": code}})
                    st.toast("Verifying code...")
                else:
                    st.warning("Enter the code first.")
        else:
            if st.button("SEND AUTH CODE", use_container_width=True, type="primary"):
                if api_id and api_hash and phone:
                    state.commands.append({"type": "REQUEST_TG_CODE", "data": {
                        "api_id": api_id, "api_hash": api_hash, "phone": phone
                    }})
                    # Save these to env immediately so the worker has them for initialization
                    st.toast("Requesting code...")
                else:
                    st.warning("Please fill all Telegram fields.")

        st.markdown("</div>", unsafe_allow_html=True)
        # Note: Step transition is handled by bot_worker commands

    def _render_setup_step_2(self, state):
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("### 🧠 STEP 2: SYSTEM INTELLIGENCE")
        st.write("Configuring the AI Brain and Broker bridge.")
        
        gemini_key = st.text_input("GEMINI API KEY", type="password", value=os.getenv("GEMINI_API_KEY", ""))
        meta_token = st.text_input("META API TOKEN", type="password", value=os.getenv("META_API_TOKEN", ""))
        meta_id = st.text_input("META ACCOUNT ID", value=os.getenv("META_ACCOUNT_ID", ""))
        
        c1, c2 = st.columns(2)
        if c1.button("← BACK", use_container_width=True):
            state.setup_step = 1
            st.rerun()
        if c2.button("NEXT →", use_container_width=True, type="primary"):
            if gemini_key and meta_token and meta_id:
                state.setup_data.update({
                    "GEMINI_API_KEY": gemini_key,
                    "META_API_TOKEN": meta_token,
                    "META_ACCOUNT_ID": meta_id
                })
                state.setup_step = 3
                st.rerun()
            else:
                st.warning("All keys are required to proceed.")
        st.markdown("</div>", unsafe_allow_html=True)

    def _render_setup_step_3(self, state):
        st.markdown('<div class="glass-card">', unsafe_allow_html=True)
        st.markdown("### 🚦 STEP 3: FINAL DEPLOYMENT")
        st.write("Set your target signal channels and start automation.")
        
        channel_ids = st.text_area("CHANNEL IDs (comma-separated)", 
                                   value=os.getenv("CHANNEL_IDS", "-1002047709770"),
                                   help="Find IDs using @userinfobot or similar.")
        
        risk = st.number_input("INITIAL RISK ($) PER TRADE", value=50.0, step=10.0)
        
        st.info("Orbital will now reboot and initialize all components.")
        
        if st.button("🚀 INITIALIZE CORE & START", use_container_width=True, type="primary"):
            final_data = state.setup_data.copy()
            # Ensure we preserve the TG keys from step 1
            final_data.update({
                "CHANNEL_IDS": channel_ids,
                "RISK_USD": str(risk),
                "TELEGRAM_API_ID": os.getenv("TELEGRAM_API_ID", ""),
                "TELEGRAM_API_HASH": os.getenv("TELEGRAM_API_HASH", "")
            })
            state.commands.append({"type": "FINISH_SETUP", "data": final_data})
            st.toast("Finalizing system...")
        st.markdown("</div>", unsafe_allow_html=True)


    def render_profile_tab(self, state, on_save_callback):
        """Unified Settings and Profile view."""
        st.markdown('<div class="dashboard-grid-header">System Settings & Profile</div>', unsafe_allow_html=True)
        
        with st.container():
            c1, c2 = st.columns([1, 2])
            with c1:
                # Profile Info
                st.markdown("### 👤 OPERATOR")
                if state.tg_me:
                    st.markdown(f"**Name:** {state.tg_me.first_name} {state.tg_me.last_name or ''}")
                    st.markdown(f"**Username:** @{state.tg_me.username or 'N/A'}")
                    st.markdown(f"**Status:** {state.tg_auth_status or 'Active'}")
                else:
                    st.info("No profile data loaded.")
            
            with c2:
                # API Keys
                st.markdown("### 🔑 API KEYS")
                new_gemini = st.text_input("GEMINI API KEY", value=os.getenv("GEMINI_API_KEY", ""), type="password")
                new_meta_token = st.text_input("META API TOKEN", value=os.getenv("META_API_TOKEN", ""), type="password")
                new_meta_id = st.text_input("META ACCOUNT ID", value=os.getenv("META_ACCOUNT_ID", ""))
                
                if st.button("💾 SAVE CONFIGURATION", type="primary"):
                    new_config = {
                        "GEMINI_API_KEY": new_gemini,
                        "META_API_TOKEN": new_meta_token,
                        "META_ACCOUNT_ID": new_meta_id
                    }
                    on_save_callback(new_config)

    def render_sidebar(self, current_view, connections, symbols):
        """
        Renders the system sidebar with navigation and status indicators.
        Returns the newly selected view if a selection was made.
        """
        new_view = current_view
        
        with st.sidebar:
            st.markdown(textwrap.dedent(f"""
                <div style="text-align: center; margin-bottom: 25px;">
                    <h2 style="margin: 0; color: var(--text-muted); letter-spacing: 2px; font-weight: 400; font-size: 0.8rem;">SYSTEM CONTROLS</h2>
                </div>
            """).strip(), unsafe_allow_html=True)
            
            # --- Views / Navigation ---
            st.markdown('<p style="font-size: 0.7rem; font-weight: 800; color: var(--primary-accent); margin-bottom: 15px; letter-spacing: 2px; text-align: center;">VIEWS</p>', unsafe_allow_html=True)
            
            # Symbol Navigation
            for sym in symbols:
                is_active = (current_view == sym)
                label = f"{'● ' if is_active else '○ '}{sym}"
                if st.button(label, key=f"nav_{sym}", use_container_width=True):
                    new_view = sym
            
            if st.button(f"{'● ' if current_view == 'SETTINGS' else '○ '}SETTINGS", key="nav_settings", use_container_width=True):
                new_view = "SETTINGS"
            
            st.markdown("<hr style='margin: 20px 0; opacity: 0.1;'>", unsafe_allow_html=True)
            
            # --- Status Indicators ---
            st.markdown('<p style="font-size: 0.7rem; font-weight: 800; color: var(--primary-accent); margin-bottom: 25px; letter-spacing: 2px; text-align: center;">CONNECTIONS</p>', unsafe_allow_html=True)
            
            sidebar_icons = {
                "TELEGRAM": ('<svg class="sidebar-icon {active}" viewBox="0 0 24 24"><path d="M22 2L11 13M22 2L15 22L11 13M11 13L2 9L22 2"/></svg>', connections.get('tg', False)),
                "MT5": ('<svg class="sidebar-icon {active}" viewBox="0 0 24 24"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>', connections.get('mt5', False)),
                "SHIELD": ('<svg class="sidebar-icon {active}" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>', True)
            }

            for label, (svg, is_active) in sidebar_icons.items():
                active_class = "active" if is_active else ""
                st.markdown(textwrap.dedent(f"""
                    <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 20px; padding: 0 20px;">
                        {svg.replace('{active}', active_class)}
                        <span style="font-size: 0.7rem; color: {'var(--text-main)' if is_active else 'var(--text-muted)'}; 
                                    font-weight: 500; letter-spacing: 1px;">{label}</span>
                    </div>
                """).strip(), unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔄 REBOOT", use_container_width=True, key="sidebar_reboot"):
                st.session_state.commands.append({"type": "RESTART_BOT"})
                st.toast("Reboot command queued.")

            st.markdown(textwrap.dedent(f"""
                <div style="margin-top: 40px; font-size: 0.6rem; color: var(--text-muted); text-align: center; opacity: 0.5;">
                    ORBITAL V3.1 [STABLE]<br>
                    BUILD: {datetime.now().strftime('%Y.%m.%d')}
                </div>
            """).strip(), unsafe_allow_html=True)
            
        return new_view
