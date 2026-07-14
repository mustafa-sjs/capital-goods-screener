"""Stock Screener — the centre of the application.

One universe selector, one subgroup filter and one search box feed five
tabs (Overview / Valuation / Fundamentals / Price Trend / Risk). The
selected universe controls BOTH which companies are displayed AND which
companies rankings/percentiles are calculated across. Default tables are
compact; more columns are optional, methodology sits in tooltips.
"""
import json, os, sys

import numpy as np
import pandas as pd
import streamlit as st
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from components.data import (payload, data_version, get_db, q, ph,
                             status_strip, price_history, core_freshness)
from components.ui import (style_table, df_show, page_header, section,
                           CLASS_COLORS, POS, NEG, WARN, TEAL7)
from src.utils.universe import (universe_service, universe_keys,
                                UNIVERSE_OPTIONS, DEFAULT_UNIVERSE)
from src.utils import metrics as M
from src.features.momentum import momentum_config
from src.screening.momentum import (build_table, heatmap_frame,
                                    HEATMAP_COLS_DEFAULT, HEATMAP_COLS,
                                    backtest_payload)

page_header('Stock Screener',
            'Find and compare the 30 core coverage companies using '
            'valuation, fundamentals and share-price trends.')
status_strip()

D = payload(data_version())
svc = universe_service()

# ---------------------------------------------------------------- frame ----
_, _, _, STALE_KEYS = core_freshness()


def _peer_row(k):
    """Best-available row for a direct peer (no silent dropping: metrics the
    engine only computes for coverage companies show as missing)."""
    m = (D.get('all_metrics') or {}).get(k) or {}
    cr = next((x for x in D['close_rows'] if x['key'] == k), {})
    return dict(
        key=k, company=svc['names'].get(k, k), ticker=svc['tickers'].get(k, ''),
        subgroup=svc['sub_of'].get(k, ''), role='peer',
        price=cr.get('close_px'), quote_ccy=svc['qccy'].get(k, ''),
        ev_ebitda_ltm=m.get('ev_ebitda'), ev_ebit_ltm=m.get('ev_ebit'),
        pe_ltm=m.get('pe'), ev_rev_ltm=m.get('ev_rev'),
        fcf_yield_pct=(round(m['fcf_yield'] * 100, 1)
                       if m.get('fcf_yield') is not None else None),
        ebitda_margin_pct=(round(m['ebitda_margin'] * 100, 1)
                           if m.get('ebitda_margin') is not None else None),
        nd_ebitda=m.get('nd_ebitda'),
        move_3m_pct=cr.get('move_3m_pct'), move_12m_pct=cr.get('move_12m_pct'),
        data_quality='OK')


@st.cache_data(ttl=900)
def base_frame(_version=None):
    cov = pd.DataFrame(D['screener'])
    cov['role'] = 'coverage'
    peers = pd.DataFrame([_peer_row(k) for k in svc['peers']])
    df = pd.concat([cov, peers], ignore_index=True)
    df['freshness'] = df['key'].map(
        lambda k: 'Stale' if k in set(STALE_KEYS) else 'Current')
    return df


df_all = base_frame(data_version())

# ------------------------------------------------------------- filters -----
fc0, fc1, fc2 = st.columns([1.4, 1.4, 1.2])
uni_pick = fc0.selectbox('Universe', UNIVERSE_OPTIONS,
                         index=UNIVERSE_OPTIONS.index(DEFAULT_UNIVERSE),
                         help='Core coverage = the 30 companies of the pack. '
                              'The selection controls both which companies '
                              'are shown and which companies rankings are '
                              'calculated across.')
sub = fc1.multiselect('Subgroup', sorted({svc['sub_of'][k] for k in svc['core']}))
search = fc2.text_input('Search company or ticker')

with st.expander('More filters'):
    m1, m2, m3, m4 = st.columns(4)
    mcap_min = m1.number_input('Minimum market cap ($bn)', 0.0)
    ev_max = m2.number_input('Maximum EV/EBITDA (0 = any)', 0.0)
    fdir = m3.multiselect('Fundamental direction',
                          ['improving', 'stable', 'deteriorating'])
    trend_f = m4.multiselect('Trend', ['Uptrend', 'Downtrend', 'No clear trend'])
    m5, m6, m7 = st.columns(3)
    disc_min = m5.number_input('Minimum discount to direct peers (%)', 0.0,
                               help='20 keeps companies at least 20% below '
                                    'their direct-peer median EV/EBITDA.')
    nd_max = m6.number_input('Maximum net debt / EBITDA (0 = any)', 0.0)
    dq_ok = m7.checkbox('Hide companies with data warnings')

uni_set = set(universe_keys(uni_pick, svc))
f = df_all[df_all['key'].isin(uni_set)].copy()
if sub:
    f = f[f['subgroup'].isin(sub)]
if search:
    s = search.lower()
    f = f[f['company'].str.lower().str.contains(s)
          | f['ticker'].fillna('').str.lower().str.contains(s)]
if mcap_min:
    f = f[f['mcap_usd_bn'].fillna(0) >= mcap_min]
if ev_max:
    f = f[f['ev_ebitda_ltm'].notna() & (f['ev_ebitda_ltm'] <= ev_max)]
if fdir:
    f = f[f['fundamental_state'].isin(fdir)]
if trend_f and 'trend' in f:
    f = f[f['trend'].isin(trend_f)]
if disc_min:
    f = f[f['prem_disc_vs_peers_pct'].notna()
          & (f['prem_disc_vs_peers_pct'] <= -disc_min)]
if nd_max:
    f = f[f['nd_ebitda'].fillna(0) <= nd_max]
if dq_ok:
    f = f[f['data_quality'] == 'OK']

# ------------------------------------------------------ presets & saved ----
OPS_EN = {'<=': 'at most', '>=': 'at least', 'in': 'one of'}


def rule_sentence(col, op, val):
    """'prem_disc_vs_peers_pct <= -20' -> 'Premium / discount to direct
    peers: at most -20%'."""
    d = M.METRIC_DEFINITIONS.get(col)
    name = d['display_name'] if d else col
    if op == 'in':
        vals = val if isinstance(val, (list, tuple)) else \
            [v.strip() for v in str(val).split('|')]
        return f'{name}: {" or ".join(vals)}'
    unit = '%' if d and d['format'] in ('pct_signed', 'pct') else \
        (' pp' if d and d['format'] == 'pp' else '')
    return f'{name}: {OPS_EN.get(op, op)} {val}{unit}'


presets = {}
ppath = os.path.join(ROOT, 'config', 'screen_presets.yaml')
if os.path.exists(ppath):
    presets = yaml.safe_load(open(ppath)) or {}

pcol1, pcol2 = st.columns([1.5, 3])
preset = pcol1.selectbox('Saved screen preset', ['None'] + list(presets),
                         format_func=lambda p: p.replace('_', ' ').capitalize()
                         if p != 'None' else 'None')
if preset != 'None' and preset in presets:
    rules = presets[preset].get('rules', {})
    sentences = []
    for col, rule in rules.items():
        op, val = rule.split(' ', 1)
        sentences.append(rule_sentence(col, op, val))
        if col not in f.columns:
            continue
        if op == 'in':
            f = f[f[col].isin([v.strip() for v in val.split('|')])]
            continue
        val = float(val)
        f = f[f[col].notna()]
        f = f[f[col] <= val] if op == '<=' else (f[f[col] >= val] if op == '>=' else f)
    pcol2.info(f"{presets[preset].get('description', '')}  \n"
               + '  \n'.join('• ' + s2 for s2 in sentences))

with st.expander('Custom screen builder (saved screens)'):
    NUM_COLS = ['prem_disc_vs_peers_pct', 'prem_disc_vs_sector_pct',
                'ev_ebitda_ltm', 'pe_ltm', 'fcf_yield_pct', 'rev_growth_pct',
                'ebitda_margin_pct', 'margin_chg_pp', 'nd_ebitda',
                'rel_1m_pct', 'rel_3m_pct', 'rel_12m_pct', 'hist_percentile',
                'hist_zscore', 'drawdown_52w_pct', 'mcap_usd_bn', 'hist_years']
    STATE_COLS = {
        'trend': ['Uptrend', 'Downtrend', 'No clear trend'],
        'momentum_change': ['Strengthening', 'Stable', 'Weakening'],
        'recent_signal': ['New positive crossover', 'New negative crossover',
                          'No recent crossover'],
        'momentum_state': sorted(df_all['momentum_state'].dropna().unique()),
        'valuation_state': sorted(df_all['valuation_state'].dropna().unique()),
        'fundamental_state': sorted(df_all['fundamental_state'].dropna().unique()),
    }
    ALL_CONDS = NUM_COLS + list(STATE_COLS)
    db = get_db()
    saved = {r[1]: (r[0], r[2]) for r in q(
        'SELECT screen_id, name, definition FROM saved_screens ORDER BY name')
        if not r[1].startswith('THESIS LOG')}
    pickd = st.selectbox('Load saved screen', ['—'] + list(saved))
    conds = json.loads(saved[pickd][1]) if pickd != '—' else []
    n_rows = st.number_input('Conditions', 1, 6,
                             value=max(1, len(conds)), key='nconds')
    new_conds = []
    for i in range(int(n_rows)):
        c1x, c2x, c3x = st.columns([2, 1, 2])
        prev_c = conds[i] if i < len(conds) else {}
        metric_pick = c1x.selectbox(
            f'Metric {i + 1}', ALL_CONDS,
            index=(ALL_CONDS.index(prev_c['metric'])
                   if prev_c.get('metric') in ALL_CONDS else 0),
            format_func=lambda mid: M.label(mid), key=f'm{i}',
            help=M.describe(prev_c.get('metric', '')) or None)
        if metric_pick in STATE_COLS:
            op = 'in'
            val = c3x.multiselect(f'States {i + 1}', STATE_COLS[metric_pick],
                                  default=[v for v in (prev_c.get('value') or [])
                                           if v in STATE_COLS[metric_pick]],
                                  key=f'v{i}')
            c2x.markdown('&nbsp;\none of')
        else:
            op = c2x.selectbox(f'Rule {i + 1}', ['<=', '>='],
                               index=0 if prev_c.get('op', '<=') == '<=' else 1,
                               format_func=lambda o: OPS_EN[o], key=f'o{i}')
            val = c3x.number_input(f'Value {i + 1}',
                                   value=float(prev_c.get('value', 0)),
                                   key=f'n{i}')
        new_conds.append(dict(metric=metric_pick, op=op, value=val))
    st.caption('This screen: ' + '; '.join(
        rule_sentence(c['metric'], c['op'], c['value']) for c in new_conds))
    apply_custom = st.checkbox('Apply custom screen')
    if apply_custom:
        for cnd in new_conds:
            m_, op, v = cnd['metric'], cnd['op'], cnd['value']
            if m_ not in f.columns:
                continue
            if op == 'in':
                if v:
                    f = f[f[m_].isin(v)]
            else:
                f = f[f[m_].notna()]
                f = f[f[m_] <= v] if op == '<=' else f[f[m_] >= v]
        st.caption(f'{len(f)} companies match the custom screen.')
    sc1, sc2, sc3 = st.columns(3)
    sname = sc1.text_input('Save as', value=pickd if pickd != '—' else '')
    if sc2.button('Save screen') and sname:
        import uuid as _uuid
        from datetime import datetime as _dt, timezone as _tz
        sid = saved.get(sname, (_uuid.uuid4().hex[:12],))[0]
        db.upsert('saved_screens', ['screen_id', 'name', 'definition', 'created_at'],
                  [(sid, sname, json.dumps(new_conds),
                    _dt.now(_tz.utc).replace(tzinfo=None))], ['screen_id'])
        st.success(f'saved "{sname}"'); st.cache_data.clear()
    if pickd != '—' and sc3.button('Delete screen'):
        db.execute(f'DELETE FROM saved_screens WHERE screen_id = {ph()}',
                   [saved[pickd][0]])
        st.cache_data.clear(); st.rerun()

# ------------------------------------------------------------- tab views ---
TAB_COLS = {
    'Overview': ['company', 'subgroup', 'price', 'mcap_usd_bn',
                 'ev_ebitda_ltm', 'prem_disc_vs_peers_pct', 'rev_growth_pct',
                 'margin_chg_pp', 'trend'],
    'Valuation': ['company', 'ev_ebitda_ltm', 'peer_median_ev_ebitda',
                  'prem_disc_vs_peers_pct', 'sector_median_ev_ebitda',
                  'prem_disc_vs_sector_pct', 'hist_percentile',
                  'fcf_yield_pct', 'pe_ltm'],
    'Fundamentals': ['company', 'rev_growth_pct', 'ebitda_margin_pct',
                     'margin_chg_pp', 'fcf_yield_pct', 'nd_ebitda',
                     'fundamental_state'],
    'Risk': ['company', 'nd_ebitda', 'fcf_yield_pct', 'margin_chg_pp',
             'drawdown_52w_pct', 'freshness', 'data_quality'],
}
CLASS_IDS = ['trend', 'momentum_change', 'recent_signal', 'valuation_state',
             'fundamental_state', 'momentum_state', 'classification']
OPTIONAL_IDS = [c for c in M.METRIC_DEFINITIONS
                if c in df_all.columns and c not in ('company',)]


def render_tab(tab_name, sort_by='prem_disc_vs_peers_pct'):
    cols = TAB_COLS[tab_name]
    extra = st.multiselect('Optional columns',
                           [c for c in OPTIONAL_IDS if c not in cols],
                           format_func=M.label, key=f'extra_{tab_name}')
    use = cols + [c for c in extra if c not in cols]
    view = f[[c for c in use if c in f.columns]].copy()
    if sort_by in view.columns:
        view = view.sort_values(sort_by, na_position='last')
    rename, style_kw, help_map = M.table_spec(
        [c for c in view.columns], short=True)
    rename['freshness'] = 'Data freshness'
    help_map.setdefault('Data freshness',
                        'Whether this company\'s latest price matches the '
                        'latest completed date for its market.')
    class_disp = [rename.get(c, c) for c in CLASS_IDS + ['freshness']
                  if c in view.columns]
    view = view.rename(columns=rename)
    if tab_name == 'Risk' and 'Data warnings' in view.columns:
        view['Data warnings'] = view['Data warnings'].map(
            lambda v: 'None' if v == 'OK' else v)
    sty = style_table(
        view,
        pct_cols=[c for c in style_kw.get('pct_cols', []) if c in view],
        pct_plain_cols=[c for c in style_kw.get('pct_plain_cols', []) if c in view],
        mult_cols=[c for c in style_kw.get('mult_cols', []) if c in view],
        num_cols=[c for c in style_kw.get('num_cols', []) if c in view],
        int_cols=[c for c in style_kw.get('int_cols', []) if c in view],
        price_cols=[c for c in style_kw.get('price_cols', []) if c in view],
        class_cols=class_disp,
        val_scale_col=rename.get('prem_disc_vs_peers_pct')
        if 'prem_disc_vs_peers_pct' in use else None)
    df_show(sty, height=min(640, 38 * (len(view) + 1) + 4), help_map=help_map)
    st.caption(f'{len(view)} of {len(uni_set)} companies in the selected '
               f'universe shown. Valuation colour scale: blue = cheaper than '
               f'direct peers, orange = more expensive. "Not available" / "–" '
               f'means the input is missing, never zero-filled.')
    st.download_button('Download this view (CSV)', view.to_csv(index=False),
                       f'screener_{tab_name.lower().replace(" ", "_")}.csv',
                       key=f'dl_{tab_name}')


tabs = st.tabs(['Overview', 'Valuation', 'Fundamentals', 'Price Trend', 'Risk'])

with tabs[0]:
    render_tab('Overview')
    with st.expander('Why did these companies surface?'):
        for _, r in f[f['role'] == 'coverage'].sort_values(
                'prem_disc_vs_peers_pct').head(12).iterrows():
            bits = []
            if pd.notna(r.get('prem_disc_vs_peers_pct')):
                side = 'below' if r['prem_disc_vs_peers_pct'] < 0 else 'above'
                bits.append(f"{abs(r['prem_disc_vs_peers_pct']):.0f}% {side} "
                            f"its direct-peer median EV/EBITDA "
                            f"({r['ev_ebitda_ltm']}× vs "
                            f"{r['peer_median_ev_ebitda']}×)")
            if pd.notna(r.get('hist_percentile')):
                bits.append(f"at the {r['hist_percentile']:.0f}th percentile "
                            f"of its own valuation history "
                            f"({int(r['hist_years'] or 0)} years)")
            if pd.notna(r.get('rel_3m_pct')):
                bits.append(f"3M performance {r['rel_3m_pct']:+.1f}pp vs peers")
            if pd.notna(r.get('margin_chg_pp')):
                bits.append(f"EBITDA margin {r['margin_chg_pp']:+.1f}pp "
                            f"year on year")
            if r.get('trend'):
                bits.append(f"price trend: {r['trend']}")
            st.markdown(f"**{r['company']}** — " + '; '.join(bits) + '.')
with tabs[1]:
    render_tab('Valuation')
with tabs[2]:
    render_tab('Fundamentals', sort_by='rev_growth_pct')

# =================== Price Trend (consolidated momentum) ====================
with tabs[3]:
    cfg = momentum_config()
    bt = backtest_payload()
    pairs = [tuple(p) for p in cfg['ewma']['pairs']]
    default_pair = tuple(cfg['ewma']['default_pair'])
    if 'mom_pair' not in st.session_state:
        st.session_state['mom_pair'] = default_pair

    t0, t1, t2, t3, t4 = st.columns([1.3, 1.2, 1.2, 1.3, 0.8])
    pair = t0.selectbox(
        'Trend setting (fast/slow average, days)', pairs,
        index=pairs.index(st.session_state['mom_pair']),
        format_func=lambda p: f'{p[0]}/{p[1]}'
        + (' — best-tested' if p == default_pair else ''),
        help='Exponentially weighted moving averages of the total-return '
             'price. The best-tested setting ranked highest out of sample, '
             'but did not beat buy-and-hold after costs — it mainly reduced '
             'drawdowns.')
    trend_pick = t1.multiselect('Trend ',
                                ['Uptrend', 'Downtrend', 'No clear trend'],
                                key='pt_trend')
    chg_pick = t2.multiselect('Momentum change',
                              ['Strengthening', 'Stable', 'Weakening'])
    sig_pick = t3.multiselect('Recent signal',
                              ['New positive crossover',
                               'New negative crossover',
                               'No recent crossover'])
    topn = t4.number_input('Top N', 5, 79, 40, step=5)
    with st.expander('Advanced signal settings'):
        confirm = st.selectbox('Confirmation (sessions a crossover must '
                               'persist before it counts)', [1, 3, 5], index=2)
        st.caption('Historical-evidence columns and the backtest apply the '
                   'same confirmation. Backtest costs: '
                   f"{cfg['backtest']['transaction_cost_bps'] + cfg['backtest']['slippage_bps']}"
                   'bps per side, next-close execution.')

    @st.cache_data(ttl=900, show_spinner='Calculating price trends…')
    def _mom_table(keys, pair_, confirm_, _version=None):
        return build_table(sorted(keys), svc['names'], svc['sub_of'],
                           svc['peers_of'], pair_, confirm_)

    # ranks/percentiles calculated WITHIN the selected universe, then shown
    mdf = _mom_table(tuple(sorted(uni_set)), pair, confirm, data_version())
    mf = mdf.copy()
    if sub:
        mf = mf[mf['subgroup'].isin(sub)]
    if search:
        mf = mf[mf['company'].str.lower().str.contains(search.lower())]
    if trend_pick:
        mf = mf[mf['trend'].isin(trend_pick)]
    if chg_pick:
        mf = mf[mf['momentum_change'].isin(chg_pick)]
    if sig_pick:
        mf = mf[mf['recent_signal'].isin(sig_pick)]
    mf = mf.head(int(topn))

    k1, k2, k3, k4 = st.columns(4)
    k1.metric('Companies shown', len(mf))
    k2.metric('In uptrend', int((mdf['trend'] == 'Uptrend').sum()),
              help='Across the selected universe, before filters.')
    k3.metric('New positive crossovers',
              int((mdf['recent_signal'] == 'New positive crossover').sum()))
    k4.metric('New negative crossovers',
              int((mdf['recent_signal'] == 'New negative crossover').sum()))
    if bt:
        ud = bt['universe_default']
        st.caption(f"**Best-tested trend setting: {ud['pair'][0]}/{ud['pair'][1]}day "
                   f"averages** (backtest of {bt['generated'][:10]}). This "
                   f"setting reduced drawdowns but did **not** beat "
                   f"buy-and-hold after costs "
                   f"({bt['ranked'][0]['oos']['excess_ann_pct']}% annualised "
                   f"vs buy-and-hold out of sample; max drawdown "
                   f"{bt['ranked'][0]['oos']['max_drawdown_pct']}%). Treat "
                   f"crossovers as research prompts, not trade signals.")

    section('Ranked by price trend')
    MOM_IDS = ['company', 'subgroup', 'trend', 'momentum_change',
               'recent_signal', 'rel_3m_universe', 'ret_6m', 'spread',
               'cross_date', 'pos_3m_rate', 'n_signals']
    mextra = st.multiselect(
        'Optional columns',
        [c for c in ['ret_1m', 'ret_3m', 'ret_12m', 'rel_strength',
                     'dist_chg', 'days_since_cross', 'median_3m_fwd',
                     'momentum_score'] if c in mf.columns],
        format_func=M.label, key='extra_pt')
    mrename, mstyle, mhelp = M.table_spec(MOM_IDS + mextra, short=True)
    mview = mf[[c for c in MOM_IDS + mextra if c in mf.columns]].rename(
        columns=mrename)
    df_show(style_table(
        mview,
        pct_cols=[c for c in mstyle.get('pct_cols', []) if c in mview],
        pct_plain_cols=[c for c in mstyle.get('pct_plain_cols', []) if c in mview],
        num_cols=[c for c in mstyle.get('num_cols', []) if c in mview],
        int_cols=[c for c in mstyle.get('int_cols', []) if c in mview],
        class_cols=[mrename.get(c) for c in
                    ('trend', 'momentum_change', 'recent_signal')]),
        height=min(600, 38 * (len(mview) + 1) + 4), help_map=mhelp)
    st.caption('Historical-evidence columns state their sample size — a rate '
               'built on three signals is an anecdote, not a statistic.')
    st.download_button('Download this view (CSV)', mview.to_csv(index=False),
                       'price_trend_screen.csv')

    section('Trend heatmap',
            'Colour = percentile rank within the selected universe '
            '(green = strongest). Hover for the raw value.')
    expanded = st.toggle('Expanded heatmap (all return periods and factors)')
    hm_cols = HEATMAP_COLS if expanded else HEATMAP_COLS_DEFAULT
    hm = heatmap_frame(mf, hm_cols)
    import altair as alt
    hm_long = hm.reset_index().melt('company', var_name='metric',
                                    value_name='pctile')
    raw_long = mf[['company'] + hm_cols].melt('company', var_name='metric',
                                              value_name='raw')
    hm_long = hm_long.merge(raw_long, on=['company', 'metric'])
    hm_long['metric_label'] = hm_long['metric'].map(lambda c: M.label(c, True))
    order = mf['company'].tolist()
    col_order = [M.label(c, True) for c in hm_cols]
    chart = alt.Chart(hm_long).mark_rect().encode(
        x=alt.X('metric_label:N', sort=col_order, title=None),
        y=alt.Y('company:N', sort=order, title=None),
        color=alt.Color('pctile:Q',
                        scale=alt.Scale(scheme='redyellowgreen',
                                        domain=[0, 100]),
                        legend=alt.Legend(title='Percentile')),
        tooltip=[alt.Tooltip('company:N', title='Company'),
                 alt.Tooltip('metric_label:N', title='Measure'),
                 alt.Tooltip('raw:Q', format='.1f', title='Value'),
                 alt.Tooltip('pctile:Q', format='.0f', title='Percentile')]
    ).properties(height=max(220, 16 * len(mf)))
    st.altair_chart(chart, use_container_width=True)

    section('Selected company')
    if len(mf):
        sel = st.selectbox('Company', mf['key'].tolist(),
                           format_func=lambda k: svc['names'].get(k, k))
        row = mdf[mdf['key'] == sel].iloc[0]
        p1, p2, p3, p4 = st.columns(4)
        p1.metric('Trend', row['trend'] or '–')
        p2.metric('Momentum change', row['momentum_change'] or '–')
        p3.metric('Recent signal', row['recent_signal'] or '–',
                  help=f"latest crossover {row['cross_date']} "
                       f"({row['days_since_cross']} sessions ago)"
                  if row['cross_date'] else None)
        if row['pos_3m_rate'] is not None and row['n_signals']:
            n_pos = int(round(row['pos_3m_rate'] / 100 * row['n_signals']))
            p4.metric('After similar signals',
                      f"{n_pos} of {int(row['n_signals'])} positive 3M",
                      help='How many of this company\'s past confirmed '
                           'positive crossovers were followed by a positive '
                           '3-month return. Historical, not predictive.')
        else:
            p4.metric('After similar signals', 'Too few signals')
        hp, src_label = price_history(sel, data_version())
        px = pd.Series(hp['close_tr'].values,
                       index=pd.to_datetime(hp['session_date']),
                       dtype='float64')
        fast = px.ewm(span=pair[0], adjust=False, min_periods=pair[0]).mean()
        slow = px.ewm(span=pair[1], adjust=False, min_periods=pair[1]).mean()
        state = (fast > slow).astype(int).where(fast.notna() & slow.notna())
        crosses = state.diff()
        import plotly.graph_objects as go
        log_y = st.toggle('Log scale', key='pt_log')
        fig = go.Figure()
        fig.add_scatter(x=px.index, y=px, name='Adjusted price',
                        line=dict(color='#175d63', width=1.4))
        fig.add_scatter(x=fast.index, y=fast, name=f'{pair[0]}-day average',
                        line=dict(color='#2a78d6', width=1))
        fig.add_scatter(x=slow.index, y=slow, name=f'{pair[1]}-day average',
                        line=dict(color='#eda100', width=1))
        bx = crosses[crosses == 1].index
        sx = crosses[crosses == -1].index
        fig.add_scatter(x=bx, y=px.reindex(bx), mode='markers',
                        name='positive crossover',
                        marker=dict(symbol='triangle-up', size=10,
                                    color='#0a7d38'))
        fig.add_scatter(x=sx, y=px.reindex(sx), mode='markers',
                        name='negative crossover',
                        marker=dict(symbol='triangle-down', size=10,
                                    color='#c0392b'))
        fig.update_layout(
            title=dict(text=f"{svc['names'].get(sel, sel)} — share price and "
                            f"trend averages", font=dict(size=14)),
            height=420, margin=dict(l=10, r=10, t=48, b=10),
            yaxis_type='log' if log_y else 'linear',
            yaxis_title='Total-return adjusted price',
            legend=dict(orientation='h', y=1.1),
            xaxis=dict(rangeselector=dict(buttons=[
                dict(count=1, label='1y', step='year'),
                dict(count=3, label='3y', step='year'),
                dict(count=5, label='5y', step='year'),
                dict(step='all')])))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f'Dividends reinvested (total-return basis) · price '
                   f'source: {src_label} · latest session '
                   f'{hp["session_date"].max()}. The full company picture '
                   f'is on Company Analysis → Price Trend.')

    with st.expander('Historical strategy comparison (advanced)'):
        if not bt:
            st.info('Run `python scripts/backtest_momentum.py` to generate '
                    'results.')
        else:
            rows = []
            for i, r in enumerate(bt['ranked'][:5], 1):
                o = r['oos']
                rows.append({
                    'Rank': i,
                    'Setting': f"{r['pair'][0]}/{r['pair'][1]} day averages",
                    'Confirmation (days)': r['confirm'],
                    'Annual return % (test period)': o['ann_return_pct'],
                    'vs buy-and-hold %': o['excess_ann_pct'],
                    'Worst drawdown %': o['max_drawdown_pct'],
                    'Trades': o['n_trades'], 'Winning trades %': o['win_rate_pct']})
            df_show(pd.DataFrame(rows))
            st.caption('Selection used the first 60% of history; the figures '
                       'above come from the untouched final 40% (out of '
                       'sample). Next-close execution, 25bps per side all-in '
                       'costs. The universe is today\'s coverage, so results '
                       'carry survivorship bias — a stated limitation.')
            pick = st.selectbox('Apply a setting from the table',
                                ['—'] + [f"{r['pair'][0]}/{r['pair'][1]}"
                                         for r in bt['ranked'][:5]])
            if pick != '—':
                fp, sp = map(int, pick.split('/'))
                if (fp, sp) != st.session_state['mom_pair']:
                    st.session_state['mom_pair'] = (fp, sp)
                    st.rerun()
            full = pd.json_normalize(bt['ranked'])
            st.download_button('Full results (CSV)', full.to_csv(index=False),
                               'momentum_backtest_full.csv')

with tabs[4]:
    render_tab('Risk', sort_by='nd_ebitda')
