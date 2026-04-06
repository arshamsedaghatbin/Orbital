import streamlit as st
import os
from dotenv import load_dotenv

load_dotenv()

# ── SVG icon set ──────────────────────────────────────────────────────────────
_ICONS = {
    'dash': (
        '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
        '<rect x="3" y="3" width="7" height="7" rx="1"/>'
        '<rect x="14" y="3" width="7" height="7" rx="1"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1"/>'
        '<rect x="14" y="14" width="7" height="7" rx="1"/></svg>'
    ),
    'settings': (
        '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06'
        'a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09'
        'A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83'
        'l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09'
        'A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83'
        'l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09'
        'a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83'
        'l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09'
        'a1.65 1.65 0 0 0-1.51 1z"/></svg>'
    ),
}

_SYM_SHORT = {
    'XAUUSD': 'XAU', 'EURUSD': 'EUR', 'NAS100': 'NAS',
    'GBPUSD': 'GBP', 'US30':   'DJ',  'USDJPY': 'JPY', 'BTCUSD': 'BTC',
}
_SYM_FROM_SHORT = {v: k for k, v in _SYM_SHORT.items()}
_SYMBOLS = ['XAUUSD', 'EURUSD', 'NAS100']
_SYM_COLORS = {
    'XAUUSD': ('#fbbf24', 'rgba(251,191,36,0.04)',  'rgba(251,191,36,0.12)'),
    'EURUSD': ('#38bdf8', 'rgba(56,189,248,0.04)',   'rgba(56,189,248,0.12)'),
    'NAS100': ('#a78bfa', 'rgba(167,139,250,0.04)',  'rgba(167,139,250,0.12)'),
    'GLOBAL': ('#10b981', 'rgba(16,185,129,0.04)',   'rgba(16,185,129,0.12)'),
}
_DEFAULT_CFG = {'risk_usd': 50.0, 'rr_target': 6.0, 'be_rr': 2.0, 'partial_rr': 4.0}


def _sym_class(sym: str) -> str:
    s = str(sym).upper()
    if 'XAU' in s or 'GOLD' in s:
        return 'gold'
    if any(x in s for x in ('EUR', 'GBP', 'JPY', 'USD', 'CHF', 'AUD', 'NZD', 'CAD')):
        return 'fx'
    return 'idx'


def _push_cmd(cmd: dict):
    """Append command to bot_commands list. Used as on_click callback."""
    cmds = st.session_state.get('_bot_commands')
    if cmds is not None:
        cmds.append(cmd)


def _make_cfg_saver(config_dict: dict, field: str, sess_key: str):
    """Return an on_change callback that writes widget value back into config_dict."""
    def _save():
        val = st.session_state.get(sess_key)
        if val is not None:
            config_dict[field] = val
    return _save


def _toggle_edit(key: str):
    st.session_state[key] = not st.session_state.get(key, False)


# ─────────────────────────────────────────────────────────────────────────────

class Dashboard:

    def __init__(self):
        self.apply_cyber_dark_theme()
        self.state = st.session_state
        for k, v in {
            'commands': [],
            'setup_step': 1,
            'setup_data': {},
            'tg_code_requested': False,
            'tg_phone_code_hash': None,
        }.items():
            if k not in self.state:
                self.state[k] = v

    # ── helpers ───────────────────────────────────────────────────────────────

    def _panel(self) -> str:
        return st.query_params.get('panel', 'dash')

    def _symbol_q(self) -> str:
        short = st.query_params.get('sym', 'XAU').upper()
        return _SYM_FROM_SHORT.get(short, 'XAUUSD')

    # ── theme ─────────────────────────────────────────────────────────────────

    def apply_cyber_dark_theme(self):
        path = os.path.join(os.path.dirname(__file__), 'style.css')
        if os.path.exists(path):
            with open(path) as f:
                st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)
        else:
            st.markdown('<style>body{background:#080e1a;color:#f1f5f9}</style>',
                        unsafe_allow_html=True)

    # ── topbar ────────────────────────────────────────────────────────────────

    def render_header(self, state):
        """Topbar + store ALL BotState live references in session_state."""
        # Store live object references — mutations here affect bot_worker
        if hasattr(state, 'commands'):
            st.session_state['_bot_commands'] = state.commands
        if hasattr(state, 'settings'):
            st.session_state['_bot_settings'] = state.settings
        if hasattr(state, 'metrics'):
            st.session_state['_bot_metrics'] = state.metrics
        if hasattr(state, 'active_trades'):
            st.session_state['_bot_active_trades'] = state.active_trades
        if hasattr(state, 'pending_queue'):
            st.session_state['_bot_pending_queue'] = state.pending_queue
        if hasattr(state, 'history'):
            st.session_state['_bot_history'] = state.history
        if hasattr(state, 'logs'):
            st.session_state['_bot_logs'] = state.logs

        tg  = getattr(state, 'tg_connected',  False)
        mt5 = getattr(state, 'mt5_connected', False)
        ai  = getattr(state, 'ai_connected',  True)

        def pill(label, active):
            cls = ' on'    if active else ''
            dot = ' pulse' if active else ''
            return (
                f'<div class="orb-pill{cls}">'
                f'<div class="pdot{dot}"></div>{label}</div>'
            )

        c1, c2, c3 = st.columns([2, 6, 1.5])
        with c1:
            st.markdown(
                '<div class="orb-logo">Orbital <b>OS</b></div>',
                unsafe_allow_html=True)
        with c2:
            st.markdown(
                f'<div class="orb-pills">'
                f'{pill("Telegram", tg)}'
                f'{pill("MetaAPI",  mt5)}'
                f'{pill("Gemini",   ai)}'
                f'</div>',
                unsafe_allow_html=True)
        with c3:
            if st.button('RESTART CORE', key='header_restart_btn'):
                state.commands.append({'type': 'RESTART_BOT'})
                st.toast('Core restart queued.')

        st.markdown('<div class="orb-hr"></div>', unsafe_allow_html=True)

    # ── sidebar ───────────────────────────────────────────────────────────────

    @st.fragment
    def render_sidebar(self, current_view, connections, symbols):
        """Fixed 56px sidebar: logo / static dash / divider / sym tabs / divider / settings."""
        ap       = self._panel()
        asym     = self._symbol_q()

        tabs_html = ''.join(
            f'<a href="?sym={_SYM_SHORT[sk]}" '
            f'class="orb-sym-tab{" active" if asym == sk else ""}">'
            f'{_SYM_SHORT[sk]}</a>'
            for sk in _SYMBOLS
        )

        settings_cls = ' active' if ap == 'settings' else ''

        sb = (
            '<div class="orb-sidebar">'
            # Logo
            '<div class="orb-logo-icon">'
            '<svg width="15" height="15" viewBox="0 0 24 24" fill="none"'
            ' stroke="#38bdf8" stroke-width="2">'
            '<circle cx="12" cy="12" r="3"/>'
            '<path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>'
            '</svg></div>'
            # Dashboard icon — static, no navigation
            f'<div class="orb-ni active" title="Dashboard">'
            f'{_ICONS["dash"]}'
            '</div>'
            '<div class="orb-sdiv"></div>'
            # Symbol tabs
            f'<div class="orb-sym-tabs">{tabs_html}</div>'
            '<div class="orb-sdiv"></div>'
            # Settings icon
            f'<a href="?panel=settings" class="orb-ni{settings_cls}" '
            f'title="Settings" style="margin-top:auto">'
            f'{_ICONS["settings"]}'
            f'<span class="orb-tip">Settings</span></a>'
            '</div>'
        )
        st.markdown(sb, unsafe_allow_html=True)

        if ap == 'settings':
            return 'SETTINGS'
        return asym

    # ── metrics (no-op: data stored via render_header) ────────────────────────

    @st.fragment
    def render_metrics(self, all_metrics, symbol='GLOBAL'):
        pass  # Rendered inside render_history SPA fragment

    # ── symbol settings (store config ref for render_history) ─────────────────

    def render_symbol_settings(self, symbol, config):
        st.session_state[f'_cfg_{symbol}'] = config

    # ── trading activity (no-op) ──────────────────────────────────────────────

    @st.fragment
    def render_trading_activity(
        self, active_trades, pending_queue, state,
        on_close_callback, on_close_profitable_callback,
        on_drop_callback, on_retry_callback,
        symbol_filter='GLOBAL'
    ):
        pass  # Rendered inside render_history SPA fragment

    # ── intelligence log (no-op) ──────────────────────────────────────────────

    @st.fragment
    def render_intelligence_log(self, logs, on_clear_callback, symbol_filter='GLOBAL'):
        pass  # Rendered inside render_history SPA fragment

    # ── manual order (no-op) ─────────────────────────────────────────────────

    def render_manual_order(self, on_manual_order, key_suffix=''):
        pass

    # ── MAIN SPA FRAGMENT ────────────────────────────────────────────────────

    @st.fragment(run_every=2)
    def render_history(self, history, on_clear_callback, symbol_filter='GLOBAL'):
        """SPA god-fragment: entire dashboard. Auto-reruns every 2s."""

        # CSS layout marker — overrides col_left to cover full main area
        st.markdown('<div class="orb-main-fragment"></div>', unsafe_allow_html=True)

        # ── Live data from session_state references ──────────────────────────
        sym_short     = st.query_params.get('sym', 'XAU').upper()
        sym           = _SYM_FROM_SHORT.get(sym_short, 'XAUUSD')
        metrics       = st.session_state.get('_bot_metrics', {})
        raw_settings  = st.session_state.get('_bot_settings', {})
        active_trades = st.session_state.get('_bot_active_trades', [])
        pending_queue = st.session_state.get('_bot_pending_queue', [])
        logs          = st.session_state.get('_bot_logs', [])
        hist          = st.session_state.get('_bot_history', history or [])

        # Resolve live config dict (reference into BotState.settings)
        if sym in raw_settings:
            config = raw_settings[sym]
        else:
            config = dict(_DEFAULT_CFG)
            if raw_settings:
                raw_settings[sym] = config

        # ── TOP ROW (P/L card + 4 metric tiles) ─────────────────────────────
        m       = metrics.get(sym, metrics.get('GLOBAL', {}))
        pl      = m.get('floating_pl',  0.0)
        bal     = m.get('balance',       0.0)
        eq      = m.get('equity',        0.0)
        wr      = m.get('win_rate',      0)
        op      = m.get('open_count',    0)
        pc      = 'pos' if pl >= 0 else 'neg'
        sign    = '+' if pl >= 0 else ''
        stroke  = '#10b981' if pl >= 0 else '#f43f5e'
        wr_cls  = 'pos' if wr >= 50 else ''
        sym_col, sym_bg, sym_border = _SYM_COLORS.get(sym, _SYM_COLORS['GLOBAL'])
        label   = _SYM_SHORT.get(sym, sym)

        st.markdown(f"""
<div class="orb-top-row">
  <div class="orb-pl-card" style="background:{sym_bg};border-color:{sym_border}">
    <div>
      <div class="orb-pl-label" style="color:{sym_col};opacity:0.8">P/L &middot; {label}</div>
      <div class="orb-pl-main {pc}">{sign}${pl:,.2f}</div>
    </div>
    <svg class="orb-spark" viewBox="0 0 70 24">
      <polyline points="0,20 10,16 20,18 32,8 44,12 56,4 70,3"
        fill="none" stroke="{stroke}" stroke-width="1.5"
        stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  </div>
  <div class="orb-tile">
    <div class="orb-tile-label">Balance</div>
    <div class="orb-tile-val">${bal:,.0f}</div>
  </div>
  <div class="orb-tile">
    <div class="orb-tile-label">Equity</div>
    <div class="orb-tile-val">${eq:,.0f}</div>
  </div>
  <div class="orb-tile">
    <div class="orb-tile-label">Win Rate</div>
    <div class="orb-tile-val {wr_cls}">{wr}%</div>
  </div>
  <div class="orb-tile">
    <div class="orb-tile-label">Open</div>
    <div class="orb-tile-val">{op}</div>
  </div>
</div>""", unsafe_allow_html=True)

        # ── PENDING QUEUE ────────────────────────────────────────────────────
        st.markdown('<div class="orb-sec">Pending Queue</div>', unsafe_allow_html=True)

        q_filt = [q for q in pending_queue if q.get('symbol') == sym]
        if not q_filt:
            st.markdown(
                '<div class="orb-empty-mini">No pending trades</div>',
                unsafe_allow_html=True)
        else:
            for idx, q in enumerate(q_filt):
                qid    = q.get('id', idx)
                qsym   = q.get('symbol', '?')
                data   = q.get('data', {})
                side   = data.get('side', q.get('type', '?'))
                entry  = data.get('entry', '—')
                sl_val = data.get('sl', '—')
                status = q.get('status', 'Queued')
                sc     = _sym_class(qsym)
                side_c = 'buy' if str(side).upper() == 'BUY' else 'sell'

                st.markdown(f"""
<div class="orb-queue-row">
  <div class="orb-queue-info">
    <span class="orb-sym {sc}">{qsym}</span>
    <span class="orb-sbadge {side_c}">{side}</span>
    <span class="orb-price-info">E: {entry} &middot; SL: {sl_val}</span>
  </div>
  <span class="orb-queue-status">&#8987; {status}</span>
</div>""", unsafe_allow_html=True)

                bc = st.columns([1, 1, 6])
                bc[0].button(
                    'Drop',  key=f'drop_{qid}_{idx}',
                    on_click=_push_cmd,
                    args=({'type': 'DROP_QUEUE', 'id': qid},))
                bc[1].button(
                    'Retry', key=f'retry_{qid}_{idx}',
                    on_click=_push_cmd,
                    args=({'type': 'RETRY_QUEUE', 'id': qid},))

        # ── ACTIVE POSITIONS ─────────────────────────────────────────────────
        st.markdown('<div class="orb-sec">Active Positions</div>', unsafe_allow_html=True)

        t_filt = [t for t in active_trades if t.get('symbol') == sym]
        if not t_filt:
            st.markdown(
                '<div class="orb-empty-mini">No active positions</div>',
                unsafe_allow_html=True)
        else:
            for t in t_filt:
                ticket  = t.get('order_id', t.get('id', ''))
                profit  = t.get('profit', 0.0)
                tsym    = t.get('symbol', '?')
                side    = t.get('side',   t.get('type',   '?'))
                lot     = t.get('lot',    t.get('volume',  '?'))
                entry   = t.get('entry',  '—')
                sl_val  = t.get('sl',     '—')
                sc      = _sym_class(tsym)
                side_c  = 'buy' if str(side).upper() == 'BUY' else 'sell'
                pl_c    = 'p'   if profit >= 0 else 'n'
                pl_sign = '+' if profit >= 0 else ''

                st.markdown(f"""
<div class="orb-pos-row">
  <span class="orb-sym {sc}">{tsym}</span>
  <span class="orb-sbadge {side_c}">{side} {lot}</span>
  <div class="orb-levels">
    E: {entry} &middot; <span class="sl">SL: {sl_val}</span>
    <div class="orb-pbar"><div class="orb-pfill" style="width:50%"></div></div>
  </div>
  <span class="orb-pnl {pl_c}">{pl_sign}${profit:,.2f}</span>
</div>""", unsafe_allow_html=True)

                eak = f'edit_act_{ticket}'
                ac  = st.columns(6)
                ac[0].button(
                    'BE',  key=f'be_{ticket}',
                    on_click=_push_cmd,
                    args=({'type': 'SET_BE', 'id': ticket},))
                ac[1].button(
                    'SL',  key=f'sl_{ticket}',
                    on_click=_push_cmd,
                    args=({'type': 'RESTORE_SL', 'id': ticket},))
                ac[2].button(
                    '✏️',  key=f'ebtn_{eak}',
                    on_click=_toggle_edit, args=(eak,))
                ac[3].button(
                    '50%', key=f'p50_{ticket}',
                    on_click=_push_cmd,
                    args=({'type': 'PARTIAL_CLOSE', 'id': ticket, 'fraction': 0.50},))
                ac[4].button(
                    '80%', key=f'p80_{ticket}',
                    on_click=_push_cmd,
                    args=({'type': 'PARTIAL_CLOSE', 'id': ticket, 'fraction': 0.80},))
                ac[5].button(
                    '✕',   key=f'close_{ticket}',
                    on_click=_push_cmd,
                    args=({'type': 'CLOSE_TRADE', 'id': ticket},))

                if self.state.get(eak, False):
                    ms, mc = st.columns([3, 1])
                    new_sl = ms.text_input('New SL', value=str(sl_val), key=f'v_{eak}')

                    def _confirm_sl(tid=ticket, eak_key=eak):
                        try:
                            _push_cmd({'type': 'TRAIL_SL', 'id': tid,
                                       'sl': float(st.session_state.get(f'v_{eak_key}', 0))})
                        except (ValueError, TypeError):
                            pass
                        st.session_state[eak_key] = False

                    mc.button('Set', key=f'confirm_{eak}', on_click=_confirm_sl)

        # ── INTELLIGENCE LOG ─────────────────────────────────────────────────
        st.markdown('<div class="orb-sec">Intelligence Log</div>', unsafe_allow_html=True)

        log_filt = [
            l for l in logs
            if sym in l.get('preview', '') or l.get('type') == 'SYSTEM'
        ]
        html = '<div class="orb-log-box">'
        if not log_filt:
            html += '<div class="orb-empty-mini">No log entries</div>'
        else:
            for log in reversed(log_filt[-30:]):
                lt  = log.get('type', 'INFO')
                tc  = ('trade' if lt == 'TRADE'
                       else 'err'   if lt in ('ERROR', 'CANCEL')
                       else 'sys')
                html += (
                    f'<div class="orb-log-row">'
                    f'<span class="orb-ltime">{log.get("time", "—")}</span>'
                    f'<span class="orb-ltype {tc}">[{lt[:5]}]</span>'
                    f'<span class="orb-ltext">{log.get("preview", "")}</span>'
                    f'</div>'
                )
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)

        # ── RIGHT PANEL: SIGNAL FEED (position:fixed via CSS) ────────────────
        filt   = [
            item for item in hist
            if not item.get('signal')
            or item['signal'].get('symbol') == sym
        ]
        recent = list(reversed(filt[-25:]))

        feed = (
            '<div class="orb-rpanel-fixed">'
            '<div class="orb-sec" style="padding:10px 10px 0">Signal Feed</div>'
            '<div class="orb-bubble-list orb-feed-list" style="padding:0 10px">'
        )
        if not recent:
            feed += '<div class="orb-empty-mini">No signals yet</div>'
        else:
            for item in recent:
                sig  = item.get('signal')
                meta = f"[{item.get('date', '—')}]"
                if sig:
                    t = sig.get('type', 'NEW')
                    bcls, blbl = {
                        'UPDATE': ('upd',    'UPDATE'),
                        'CANCEL': ('cancel', 'CANCEL'),
                    }.get(t, ('sig', 'SIGNAL'))
                    content = (
                        f"{sig.get('symbol', '?')} {sig.get('side', '?')}"
                        f" @ {sig.get('entry', '?')}"
                        f" &middot; SL: {sig.get('sl', '?')}"
                    )
                    oid = item.get('order_id', '')
                    if oid:
                        content += f' &#8594; #{oid}'
                else:
                    bcls, blbl = 'noise', 'NOISE'
                    tx = item.get('text', '')
                    content = (tx[:80] + '…') if len(tx) > 80 else tx
                feed += (
                    f'<div class="orb-bubble">'
                    f'<div class="orb-bubble-meta">'
                    f'<span class="orb-badge {bcls}">{blbl}</span>'
                    f'<span class="orb-bmeta">{meta}</span>'
                    f'</div>'
                    f'<div class="orb-btext">{content}</div>'
                    f'</div>'
                )
        feed += '</div></div>'
        st.markdown(feed, unsafe_allow_html=True)

        # ── RIGHT PANEL: CONFIG (position:fixed bottom via CSS) ──────────────
        with st.container():
            st.markdown('<div class="orb-cfg-region"></div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="orb-cfg-labels">'
                '<div class="orb-cfg-lbl">Risk ($)</div>'
                '<div class="orb-cfg-lbl">R/R Target</div>'
                '</div>',
                unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            c1.number_input(
                'Risk', value=float(config.get('risk_usd', 50)),
                step=5.0, min_value=1.0,
                key=f'cfg_risk_{sym}',
                label_visibility='collapsed',
                on_change=_make_cfg_saver(config, 'risk_usd', f'cfg_risk_{sym}'))
            c2.number_input(
                'R/R', value=float(config.get('rr_target', 6)),
                step=0.5, min_value=0.5,
                key=f'cfg_rr_{sym}',
                label_visibility='collapsed',
                on_change=_make_cfg_saver(config, 'rr_target', f'cfg_rr_{sym}'))

            st.markdown(
                '<div class="orb-cfg-labels">'
                '<div class="orb-cfg-lbl">BE at R/R</div>'
                '<div class="orb-cfg-lbl">Partial R/R</div>'
                '</div>',
                unsafe_allow_html=True)

            c3, c4 = st.columns(2)
            c3.number_input(
                'BE R/R', value=float(config.get('be_rr', 2)),
                step=0.5, min_value=0.5,
                key=f'cfg_be_{sym}',
                label_visibility='collapsed',
                on_change=_make_cfg_saver(config, 'be_rr', f'cfg_be_{sym}'))
            c4.number_input(
                'Partial', value=float(config.get('partial_rr', 4)),
                step=0.5, min_value=0.5,
                key=f'cfg_pt_{sym}',
                label_visibility='collapsed',
                on_change=_make_cfg_saver(config, 'partial_rr', f'cfg_pt_{sym}'))

    # ── settings / profile panels ─────────────────────────────────────────────

    def render_profile_tab(self, state, on_save_callback):
        if self._panel() == 'profile':
            self._render_profile_panel(state)
        else:
            self._render_settings_panel(state, on_save_callback)

    def _render_profile_panel(self, state):
        me        = getattr(state, 'tg_me', None)
        name      = (f'{me.first_name} {me.last_name or ""}'.strip()
                     if me else 'Operator')
        uname     = (f'@{me.username or "N/A"}' if me else '')
        initial   = name[0].upper() if name else 'A'
        connected = getattr(state, 'tg_connected', False)
        auth_str  = (getattr(state, 'tg_auth_status', None)
                     or ('Authorized' if connected else 'Disconnected'))
        sess_name = os.getenv('TELEGRAM_SESSION_NAME', 'london_bot_session')
        auth_col  = '#10b981' if connected else '#f43f5e'

        st.markdown(f"""
<div class="orb-sec">Operator</div>
<div class="orb-profile-card">
  <div class="orb-avatar">{initial}</div>
  <div>
    <div class="orb-pname">{name}</div>
    <div class="orb-pusername">{uname} &middot; Session active</div>
  </div>
</div>
<div class="orb-sec" style="margin-top:12px">Session Info</div>
<div class="orb-info-list">
  <div class="orb-info-row">
    <span class="orb-info-label">Session file</span>
    <span class="orb-info-val">{sess_name}</span>
  </div>
  <div class="orb-info-row">
    <span class="orb-info-label">TG auth status</span>
    <span class="orb-info-val" style="color:{auth_col}">{auth_str}</span>
  </div>
  <div class="orb-info-row">
    <span class="orb-info-label">Version</span>
    <span class="orb-info-val">V3.1 STABLE</span>
  </div>
</div>""", unsafe_allow_html=True)

    def _render_settings_panel(self, state, on_save_callback):
        def mask(v):
            if not v or len(v) < 8:
                return '—'
            return v[:4] + '•' * max(1, len(v) - 7) + v[-3:]

        gk  = os.getenv('GEMINI_API_KEY',  '')
        mt  = os.getenv('META_API_TOKEN',  '')
        mid = os.getenv('META_ACCOUNT_ID', '')

        st.markdown(f"""
<div class="orb-sec">API Credentials</div>
<div class="orb-info-list">
  <div class="orb-info-row">
    <span class="orb-info-label">Gemini API Key</span>
    <span class="orb-info-val">{mask(gk)}</span>
  </div>
  <div class="orb-info-row">
    <span class="orb-info-label">MetaAPI Token</span>
    <span class="orb-info-val">{mask(mt)}</span>
  </div>
  <div class="orb-info-row">
    <span class="orb-info-label">Account ID</span>
    <span class="orb-info-val">{mask(mid)}</span>
  </div>
</div>""", unsafe_allow_html=True)

        with st.expander('Edit API Keys'):
            ng  = st.text_input('Gemini API Key',  type='password', key='cfg_gemini')
            nm  = st.text_input('Meta API Token',  type='password', key='cfg_meta_t')
            ni2 = st.text_input('Meta Account ID',               key='cfg_meta_id')
            if st.button('Save Configuration', type='primary', key='save_cfg'):
                on_save_callback({
                    'GEMINI_API_KEY':  ng,
                    'META_API_TOKEN':  nm,
                    'META_ACCOUNT_ID': ni2,
                })

        settings  = getattr(state, 'settings', {})
        sym_order = [s for s in ['XAUUSD', 'EURUSD', 'NAS100'] if s in settings]
        if not sym_order:
            sym_order = list(settings.keys())

        colors = {
            'XAUUSD': '#fbbf24', 'EURUSD': '#38bdf8',
            'NAS100': '#a78bfa', 'GLOBAL': '#94a3b8',
        }
        cards = ''.join(
            f'<div class="orb-cfg-card">'
            f'<div class="orb-cfg-sym" style="color:{colors.get(s, "#94a3b8")}">{s}</div>'
            f'<div class="orb-cfg-row">Risk'
            f'<span>${settings[s].get("risk_usd", "—")}</span></div>'
            f'<div class="orb-cfg-row">R/R Target'
            f'<span>{settings[s].get("rr_target", "—")}</span></div>'
            f'<div class="orb-cfg-row">BE at R/R'
            f'<span>{settings[s].get("be_rr", "—")}</span></div>'
            f'<div class="orb-cfg-row">Partial at'
            f'<span>{settings[s].get("partial_rr", "—")}</span></div>'
            f'</div>'
            for s in sym_order
        )
        if cards:
            st.markdown(
                '<div class="orb-sec" style="margin-top:12px">Per-Symbol Config</div>'
                f'<div class="orb-sym-config">{cards}</div>',
                unsafe_allow_html=True)

    # ── setup wizard ──────────────────────────────────────────────────────────

    def render_setup_wizard(self, state):
        st.markdown(f"""
<div style="text-align:center;padding:60px 0 30px">
  <h1 style="font-weight:200;font-size:3rem;margin:0;letter-spacing:-2px;color:#f1f5f9">
    Orbital <span style="font-weight:600">Setup</span>
  </h1>
  <p style="color:var(--text-muted);font-size:1rem;margin-top:8px">
    Step {state.setup_step} of 3 &middot; {self._get_step_label(state.setup_step)}
  </p>
</div>""", unsafe_allow_html=True)

        self._render_step_progress(state.setup_step)
        _, col, _ = st.columns([1, 1.5, 1])
        with col:
            if state.setup_step == 1:
                self._render_setup_step_1(state)
            elif state.setup_step == 2:
                self._render_setup_step_2(state)
            elif state.setup_step == 3:
                self._render_setup_step_3(state)

    def _get_step_label(self, step):
        return {
            1: 'Telegram Authentication',
            2: 'System Credentials',
            3: 'Final Deployment',
        }.get(step, 'Configuration')

    def _render_step_progress(self, step):
        bars = ''
        for i in range(1, 4):
            if i < step:
                c = 'var(--success-color)'
            elif i == step:
                c = 'var(--primary-accent)'
            else:
                c = 'var(--glass-border)'
            bars += (
                f'<div style="width:40px;height:4px;background:{c};'
                f'border-radius:2px"></div>'
            )
        st.markdown(
            f'<div style="display:flex;justify-content:center;gap:20px;'
            f'margin-bottom:40px">{bars}</div>',
            unsafe_allow_html=True)

    def _render_setup_step_1(self, state):
        with st.container(border=True):
            st.markdown('### STEP 1 · SIGNAL CONNECT')
            st.write('Authorize Orbital to listen to your Telegram channels for signals.')
            api_id   = st.text_input(
                'TELEGRAM API ID',   value=os.getenv('TELEGRAM_API_ID',   ''), key='wiz_api_id')
            api_hash = st.text_input(
                'TELEGRAM API HASH', value=os.getenv('TELEGRAM_API_HASH', ''), key='wiz_api_hash')
            phone    = st.text_input(
                'PHONE NUMBER', placeholder='+1234567890',
                value=state.setup_data.get('PHONE', ''), key='wiz_phone')

            if state.tg_code_requested:
                st.info('Verification code sent to your Telegram app.')
                code = st.text_input(
                    'VERIFICATION CODE', placeholder='12345', key='wiz_code')
                if st.button('VERIFY & PROCEED', use_container_width=True,
                             type='primary', key='wiz_verify'):
                    if code:
                        state.commands.append(
                            {'type': 'VERIFY_TG_CODE', 'data': {'code': code}})
                        st.toast('Verifying…')
                    else:
                        st.warning('Enter the code first.')
            else:
                if st.button('SEND AUTH CODE', use_container_width=True,
                             type='primary', key='wiz_send'):
                    if api_id and api_hash and phone:
                        state.commands.append({
                            'type': 'REQUEST_TG_CODE',
                            'data': {
                                'api_id':   api_id,
                                'api_hash': api_hash,
                                'phone':    phone,
                            },
                        })
                        st.toast('Requesting code…')
                    else:
                        st.warning('Fill all fields.')

    def _render_setup_step_2(self, state):
        with st.container(border=True):
            st.markdown('### STEP 2 · SYSTEM INTELLIGENCE')
            st.write('Configure the AI Brain and broker bridge.')
            gemini  = st.text_input(
                'GEMINI API KEY', type='password',
                value=os.getenv('GEMINI_API_KEY', ''), key='wiz_gemini')
            meta_t  = st.text_input(
                'META API TOKEN', type='password',
                value=os.getenv('META_API_TOKEN', ''), key='wiz_meta_t')
            meta_id = st.text_input(
                'META ACCOUNT ID',
                value=os.getenv('META_ACCOUNT_ID', ''), key='wiz_meta_id')

            c1, c2 = st.columns(2)
            if c1.button('← BACK', use_container_width=True, key='wiz_back2'):
                state.setup_step = 1
                st.rerun()
            if c2.button('NEXT →', use_container_width=True,
                         type='primary', key='wiz_next2'):
                if gemini and meta_t and meta_id:
                    state.setup_data.update({
                        'GEMINI_API_KEY':  gemini,
                        'META_API_TOKEN':  meta_t,
                        'META_ACCOUNT_ID': meta_id,
                    })
                    state.setup_step = 3
                    st.rerun()
                else:
                    st.warning('All keys required.')

    def _render_setup_step_3(self, state):
        with st.container(border=True):
            st.markdown('### STEP 3 · FINAL DEPLOYMENT')
            st.write('Set your signal channels and start automation.')
            channels = st.text_area(
                'CHANNEL IDs (comma-separated)',
                value=os.getenv('CHANNEL_IDS', ''), key='wiz_channels')
            risk = st.number_input(
                'INITIAL RISK ($)', value=50.0, step=10.0, key='wiz_risk')
            st.info('Orbital will reboot and initialize all components.')
            if st.button('INITIALIZE CORE & START', use_container_width=True,
                         type='primary', key='wiz_start'):
                final = state.setup_data.copy()
                final.update({
                    'CHANNEL_IDS':       channels,
                    'RISK_USD':          str(risk),
                    'TELEGRAM_API_ID':   os.getenv('TELEGRAM_API_ID',  ''),
                    'TELEGRAM_API_HASH': os.getenv('TELEGRAM_API_HASH', ''),
                })
                state.commands.append({'type': 'FINISH_SETUP', 'data': final})
                st.toast('Finalizing system…')