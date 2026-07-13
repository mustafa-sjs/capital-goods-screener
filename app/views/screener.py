import json, os
import pandas as pd
import streamlit as st
import yaml
from components.data import payload, data_version, BASIS_BANNER, get_db, q, ph
from components.ui import style_table, df_show

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
st.title('Screener — valuation, quality, performance')
st.caption(BASIS_BANNER + ' Every multiple is **LTM reported** (uniform basis). '
           'No opaque master score — every column is a defined metric; presets '
           'are editable YAML rules.')

D = payload(data_version())
df = pd.DataFrame(D['screener'])

presets = {}
ppath = os.path.join(ROOT, 'config', 'screen_presets.yaml')
if os.path.exists(ppath):
    presets = yaml.safe_load(open(ppath)) or {}

with st.sidebar:
    st.header('Filters')
    preset = st.selectbox('Preset', ['None'] + list(presets))
    sub = st.multiselect('Subgroup', sorted(df['subgroup'].unique()))
    vst = st.multiselect('Valuation state', sorted(df['valuation_state'].dropna().unique()))
    fst = st.multiselect('Fundamental state', sorted(df['fundamental_state'].dropna().unique()))
    mst = st.multiselect('Momentum state', sorted(df['momentum_state'].dropna().unique()))
    mcap_min = st.number_input('Min mcap $bn', 0.0)
    nd_max = st.number_input('Max ND/EBITDA (0 = any)', 0.0)
    search = st.text_input('Search company / ticker')
    dq_ok = st.checkbox('Hide rows with data-quality flags')

f = df.copy()
if sub: f = f[f['subgroup'].isin(sub)]
if vst: f = f[f['valuation_state'].isin(vst)]
if fst: f = f[f['fundamental_state'].isin(fst)]
if mst: f = f[f['momentum_state'].isin(mst)]
if mcap_min: f = f[f['mcap_usd_bn'].fillna(0) >= mcap_min]
if nd_max: f = f[f['nd_ebitda'].fillna(0) <= nd_max]
if search:
    s = search.lower()
    f = f[f['company'].str.lower().str.contains(s) |
          f['ticker'].str.lower().str.contains(s)]
if dq_ok: f = f[f['data_quality'] == 'OK']

with st.expander('Custom screen builder (AND conditions, saved to database)'):
    NUM_COLS = ['prem_disc_vs_peers_pct', 'prem_disc_vs_sector_pct',
                'ev_ebitda_ltm', 'pe_ltm', 'fcf_yield_pct', 'rev_growth_pct',
                'ebitda_margin_pct', 'margin_chg_pp', 'nd_ebitda',
                'rel_1m_pct', 'rel_3m_pct', 'rel_12m_pct', 'hist_percentile',
                'hist_zscore', 'drawdown_52w_pct', 'mcap_usd_bn', 'hist_years']
    STATE_COLS = {'momentum_state': sorted(df['momentum_state'].dropna().unique()),
                  'valuation_state': sorted(df['valuation_state'].dropna().unique()),
                  'fundamental_state': sorted(df['fundamental_state'].dropna().unique())}
    db = get_db()
    saved = {r[1]: (r[0], r[2]) for r in q(
        'SELECT screen_id, name, definition FROM saved_screens ORDER BY name')}
    pickd = st.selectbox('Load saved screen', ['—'] + list(saved))
    conds = json.loads(saved[pickd][1]) if pickd != '—' else []
    n_rows = st.number_input('Conditions', 1, 6,
                             value=max(1, len(conds)), key='nconds')
    new_conds = []
    for i in range(int(n_rows)):
        c1x, c2x, c3x = st.columns([2, 1, 2])
        prev_c = conds[i] if i < len(conds) else {}
        metric = c1x.selectbox(f'Metric {i+1}',
                               NUM_COLS + list(STATE_COLS),
                               index=(NUM_COLS + list(STATE_COLS)).index(
                                   prev_c['metric']) if prev_c.get('metric') in
                               NUM_COLS + list(STATE_COLS) else 0,
                               key=f'm{i}')
        if metric in STATE_COLS:
            op = 'in'
            val = c3x.multiselect(f'States {i+1}', STATE_COLS[metric],
                                  default=[v for v in (prev_c.get('value') or [])
                                           if v in STATE_COLS[metric]],
                                  key=f'v{i}')
            c2x.markdown('&nbsp;\n`in`')
        else:
            op = c2x.selectbox(f'Op {i+1}', ['<=', '>='],
                               index=0 if prev_c.get('op', '<=') == '<=' else 1,
                               key=f'o{i}')
            val = c3x.number_input(f'Value {i+1}',
                                   value=float(prev_c.get('value', 0)),
                                   key=f'n{i}')
        new_conds.append(dict(metric=metric, op=op, value=val))
    apply_custom = st.checkbox('Apply custom screen')
    if apply_custom:
        for cnd in new_conds:
            m, op, v = cnd['metric'], cnd['op'], cnd['value']
            if m not in f.columns:
                continue
            if op == 'in':
                if v:
                    f = f[f[m].isin(v)]
            else:
                f = f[f[m].notna()]
                f = f[f[m] <= v] if op == '<=' else f[f[m] >= v]
        st.caption(f'{len(f)} names match the custom screen.')
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
    st.download_button('Export definition (JSON)', json.dumps(new_conds, indent=1),
                       'screen_definition.json')

if preset != 'None' and preset in presets:
    rules = presets[preset].get('rules', {})
    st.info(f"**{preset.replace('_',' ').title()}** — "
            f"{presets[preset].get('description','')}  \n"
            f"Rules: `{json.dumps(rules)}`")
    for col, rule in rules.items():
        if col not in f.columns:
            continue
        op, val = rule.split(' ', 1)
        if op == 'in':
            f = f[f[col].isin([v.strip() for v in val.split('|')])]
            continue
        val = float(val)
        f = f[f[col].notna()]
        f = f[f[col] <= val] if op == '<=' else (f[f[col] >= val] if op == '>=' else f)

NICE = {'company': 'Company', 'ticker': 'Ticker', 'price': 'Price',
        'quote_ccy': 'Ccy', 'mcap_usd_bn': 'Mcap $bn',
        'ev_ebitda_ltm': 'EV/EBITDA', 'prem_disc_vs_peers_pct': 'vs peers %',
        'peer_median_ev_ebitda': 'Peer med', 'prem_disc_vs_sector_pct': 'vs sector %',
        'hist_percentile': 'Hist %ile', 'hist_zscore': 'Hist z',
        'ev_ebit_ltm': 'EV/EBIT', 'pe_ltm': 'P/E', 'ev_rev_ltm': 'EV/Rev',
        'fcf_yield_pct': 'FCF yld %', 'rev_growth_pct': 'Rev g %',
        'ebitda_margin_pct': 'Margin %', 'margin_chg_pp': 'Dmargin pp',
        'nd_ebitda': 'ND/EBITDA', 'rel_1m_pct': 'rel 1M', 'rel_3m_pct': 'rel 3M',
        'rel_12m_pct': 'rel 12M', 'drawdown_52w_pct': '52w dd %',
        'valuation_state': 'Valuation', 'fundamental_state': 'Fundamentals',
        'momentum_state': 'Momentum', 'hist_years': 'Hist n',
        'data_quality': 'Data quality'}
PRESET_COLS = {
    'Standard': list(NICE.values()),
    'Valuation': ['Company', 'Ticker', 'EV/EBITDA', 'EV/EBIT', 'P/E', 'EV/Rev',
                  'FCF yld %', 'vs peers %', 'vs sector %', 'Hist %ile', 'Hist n',
                  'Valuation'],
    'Quality': ['Company', 'Ticker', 'Rev g %', 'Margin %', 'Dmargin pp',
                'ND/EBITDA', 'FCF yld %', 'Fundamentals', 'Data quality'],
    'Momentum': ['Company', 'Ticker', 'rel 1M', 'rel 3M', 'rel 12M', '52w dd %',
                 'Momentum'],
}
layout = st.radio('Columns', list(PRESET_COLS) + ['Custom'], horizontal=True)
view_all = f[list(NICE)].rename(columns=NICE)
if layout == 'Custom':
    cols_pick = st.multiselect('Choose columns', list(view_all.columns),
                               default=PRESET_COLS['Standard'][:12])
    cols_use = ['Company', 'Ticker'] + [c for c in cols_pick
                                        if c not in ('Company', 'Ticker')]
else:
    cols_use = PRESET_COLS[layout]
view = view_all[[c for c in cols_use if c in view_all.columns]]     .sort_values('vs peers %' if 'vs peers %' in cols_use else 'Company')
sty = style_table(
    view,
    pct_cols=['vs peers %', 'vs sector %', 'rel 1M', 'rel 3M', 'rel 12M',
              'Dmargin pp', 'Rev g %', '52w dd %', 'FCF yld %', 'Margin %'],
    mult_cols=['EV/EBITDA', 'EV/EBIT', 'P/E', 'Peer med', 'ND/EBITDA'],
    num_cols=['Mcap $bn', 'EV/Rev', 'Hist %ile', 'Hist z'],
    price_cols=['Price'], class_col='Valuation', scale_col='vs peers %')
# also color the other two state columns

df_show(sty, height=640)
with st.expander('Why did these names surface? (component-based, not generated text)'):
    for _, r in f.sort_values('prem_disc_vs_peers_pct').head(12).iterrows():
        bits = []
        if r['prem_disc_vs_peers_pct'] is not None and not pd.isna(r['prem_disc_vs_peers_pct']):
            bits.append(f"{abs(r['prem_disc_vs_peers_pct']):.0f}% "
                        f"{'below' if r['prem_disc_vs_peers_pct']<0 else 'above'} direct-peer median EV/EBITDA "
                        f"({r['ev_ebitda_ltm']}x vs {r['peer_median_ev_ebitda']}x)")
        if r.get('hist_percentile') is not None and not pd.isna(r.get('hist_percentile')):
            bits.append(f"{r['hist_percentile']:.0f}th pct of own range (n={int(r['hist_years'] or 0)}, coarse)")
        if r.get('rel_3m_pct') is not None and not pd.isna(r.get('rel_3m_pct')):
            bits.append(f"3M total-return {r['rel_3m_pct']:+.1f}pp vs peers")
        if r.get('margin_chg_pp') is not None and not pd.isna(r.get('margin_chg_pp')):
            bits.append(f"EBITDA margin {r['margin_chg_pp']:+.1f}pp YoY")
        bits.append(f"momentum: {r['momentum_state']}")
        st.markdown(f"**{r['company']}** — " + '; '.join(bits) + '.')
st.download_button('Export visible rows (CSV)', view.to_csv(index=False),
                   'screener_export.csv')
st.caption(f'{len(f)} of {len(df)} coverage names shown - sorted cheapest-vs-'
           'peers first - colour scale on "vs peers %": green = discount, '
           'red = premium - NM = denominator missing, never zero-filled.')
