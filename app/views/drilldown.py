import os
import pandas as pd
import streamlit as st
from components.data import payload, q, ph, BASIS_BANNER
from components.ui import style_table, df_show, group_header

st.title('Company drill-down')
st.caption(BASIS_BANNER)

D = payload()
scr = {r['key']: r for r in D['screener']}
key = st.selectbox('Coverage company', list(scr),
                   format_func=lambda k: f"{D['names'][k]} ({D['tickers'][k]})")
d = D['drill'][key]; r = scr[key]

cols = st.columns(6)
for col, (label, val) in zip(cols, [
        ('Price', f"{r['price']} {r['quote_ccy']}"),
        ('EV/EBITDA', f"{r['ev_ebitda_ltm']}× LTM" if r['ev_ebitda_ltm'] else 'NM'),
        ('EV/EBIT', f"{r['ev_ebit_ltm']}×" if r['ev_ebit_ltm'] else 'NM'),
        ('P/E', f"{r['pe_ltm']}×" if r['pe_ltm'] else 'NM'),
        ('FCF yield', f"{r['fcf_yield_pct']}%" if r['fcf_yield_pct'] is not None else 'NM'),
        ('ND/EBITDA', f"{r['nd_ebitda']}×" if r['nd_ebitda'] is not None else '–')]):
    col.metric(label, val)

# grounded interpretation (same facts the engine computed)
bits = []
if r.get('prem_disc_vs_peers_pct') is not None:
    side = 'discount' if r['prem_disc_vs_peers_pct'] < 0 else 'premium'
    bits.append(f"trades at a {abs(r['prem_disc_vs_peers_pct']):.0f}% {side} to its "
                f"direct-peer median EV/EBITDA ({r['peer_median_ev_ebitda']}× vs "
                f"{r['ev_ebitda_ltm']}×, LTM basis)")
if r.get('hist_percentile') is not None:
    bits.append(f"sits at the {r['hist_percentile']:.0f}th percentile of its own "
                f"2020-25 range ({r['hist_years']} annual obs.)")
if r.get('rev_growth_pct') is not None:
    bits.append(f"reported {r['rev_growth_pct']:+.1f}% revenue growth latest FY "
                f"with margin change {r.get('margin_chg_pp')}pp")
if r.get('rel_3m_pct') is not None:
    verb = 'outperformed' if r['rel_3m_pct'] > 0 else 'underperformed'
    bits.append(f"has {verb} its peer basket by {abs(r['rel_3m_pct']):.1f}pp over 3M")
st.info(f"**{D['names'][key]}** " + '; '.join(bits) +
        f". Consensus revisions unavailable. States — valuation: **{r['valuation_state']}**, "
f"fundamentals: **{r['fundamental_state']}**, momentum: **{r['momentum_state']}** "
f"(descriptive, not backtested).")
try:
    from src.features.pit import fundamentals_asof, median_filing_lag
    pit = fundamentals_asof(key, D.get('generated', '2026-01-01'))
    if pit['status'] == 'ok':
        st.caption(f"**Point-in-time aware** (SEC filing dates): latest period "
                   f"{pit['period_end']} became public {pit['filed_date']} "
                   f"({pit['lag_days']} days after period end; median lag "
                   f"{median_filing_lag(key)}d; {pit['periods_known']} filings "
                   f"tracked since 2020). Historical screens for this name can "
                   f"be reconstructed without look-ahead bias.")
    else:
        st.caption('Point-in-time filing dates unavailable for this name '
                   '(non-US listing or not in the SEC filings feed) — '
                   'historical fundamental analysis is approximate and '
                   'labelled as such.')
except Exception:
    pass
if d.get('flags'):
    st.warning('**Data-quality flags:** ' + ' · '.join(d['flags']))

c1, c2 = st.columns(2)
with c1:
    import os as _os, altair as alt
    ROOT2 = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    basis = st.radio('Price basis', ['Total return', 'Raw', 'Split-adjusted'],
                     horizontal=True, help='Total return reinvests dividends & '
                     'special distributions — the default for momentum. Raw = '
                     'as traded. 5y canonical daily history.')
    bcol = {'Total return': 'close_tr', 'Raw': 'close_raw',
            'Split-adjusted': 'close_split'}[basis]
    rows_db = q(f'SELECT session_date, {bcol} FROM canonical_prices '
                f'WHERE key = {ph()} ORDER BY session_date', [key])
    if rows_db:
        hp = pd.DataFrame(rows_db, columns=['session_date', 'px'])
        hp['session_date'] = hp['session_date'].astype(str)
        src_label = 'database (canonical_prices)'
    else:
        st.warning('Database has no canonical history — using the committed '
                   'parquet fallback (development mode). Charts may be older '
                   'than headline metrics.')
        hp = pd.read_parquet(_os.path.join(ROOT2, 'data', 'history',
                                           'prices_daily.parquet'))
        hp = hp[hp.key == key][['session_date', bcol]].rename(columns={bcol: 'px'})
        src_label = 'parquet fallback'
    hp['date'] = pd.to_datetime(hp['session_date'])
    hp['EMA 20'] = hp['px'].ewm(span=20, adjust=False, min_periods=20).mean()
    hp['EMA 60'] = hp['px'].ewm(span=60, adjust=False, min_periods=60).mean()
    base = alt.Chart(hp).encode(x=alt.X('date:T', title=None))
    lines = (base.mark_line(color='#175d63', strokeWidth=1.6).encode(
                 y=alt.Y('px:Q', title=f'{basis} price', scale=alt.Scale(zero=False)),
                 tooltip=['date:T', alt.Tooltip('px:Q', format='.2f')]) +
             base.mark_line(color='#2a78d6', strokeWidth=1).encode(y='EMA 20:Q') +
             base.mark_line(color='#eda100', strokeWidth=1).encode(y='EMA 60:Q'))
    arows = q(f'SELECT action_date, kind, value FROM corporate_actions '
              f'WHERE key = {ph()} ORDER BY action_date', [key])
    if arows:
        acts = pd.DataFrame(arows, columns=['action_date', 'kind', 'value'])
        acts['action_date'] = acts['action_date'].astype(str)
    else:
        acts = pd.read_parquet(_os.path.join(ROOT2, 'data', 'history',
                                             'corporate_actions.parquet'))
        acts = acts[acts.key == key].copy()
    if len(acts):
        acts['date'] = pd.to_datetime(acts['action_date'])
        marks = alt.Chart(acts).mark_rule(color='#b07100', strokeDash=[3, 3],
                                          opacity=0.6).encode(
            x='date:T', tooltip=['kind:N', 'value:Q', 'date:T'])
        lines = lines + marks
    st.altair_chart(lines.properties(height=320,
        title=f'{basis} price with 20/60-session EMAs; amber rules = '
              f'dividends/splits ({len(acts)})'), use_container_width=True)
    st.caption(f'Price source: {src_label} · latest session '
               f'{hp["session_date"].max()} · basis: {basis}')
with c2:
    st.markdown('**EV/EBITDA vs own history** — annual, approximate')
    hist = pd.DataFrame(d['hist'], columns=['year', 'EV/EBITDA'])
    if not hist.empty:
        hist['year'] = hist['year'].astype(str)
        st.bar_chart(hist.set_index('year'))

group_header('Direct-peer comparison (LTM)')
g = None
for sg in D['subgroups']:
    for grp in sg['groups']:
        if key in grp['coverage']:
            g = grp
allm = D.get('all_metrics', {})
rows = []
for p in [key] + (g['peers'] if g else []):
    m = D['drill'].get(p, {}).get('metrics') or allm.get(p) or {}
    cr = next((x for x in D['close_rows'] if x['key'] == p), {})
    rows.append({'Name': ('▮ ' if p == key else '') + D['names'].get(p, p),
                 'EV/EBITDA': m.get('ev_ebitda'), 'EV/EBIT': m.get('ev_ebit'),
                 'P/E': m.get('pe'), 'EV/Rev': m.get('ev_rev'),
                 'FCF yld %': round(m['fcf_yield'] * 100, 1) if m.get('fcf_yield') else None,
                 'EBITDA mgn %': round(m['ebitda_margin'] * 100, 1) if m.get('ebitda_margin') else None,
                 'ND/EBITDA': m.get('nd_ebitda'), '1D %': cr.get('move_1d_pct'),
                 '3M %': cr.get('move_3m_pct'), '12M %': cr.get('move_12m_pct')})
pdf2 = pd.DataFrame(rows)
df_show(style_table(pdf2,
    pct_cols=['1D %', '3M %', '12M %'],
    mult_cols=['EV/EBITDA', 'EV/EBIT', 'P/E', 'ND/EBITDA'],
    num_cols=['EV/Rev', 'FCF yld %', 'EBITDA mgn %'],
    bold_rows={0}))
group_header('Momentum & trend (descriptive — not backtested)')
mo = d.get('momentum') or {}
mc1, mc2, mc3, mc4, mc5 = st.columns(5)
mc1.metric('Momentum state', (mo.get('momentum_state') or '?').replace('_', ' '))
ema = (mo.get('ema') or {}).get('ema_20_60') or {}
mc2.metric('20/60 EMA gap', f"{ema.get('gap_pct', '–')}%",
           help=f"crossed {ema.get('cross_date')} ({ema.get('sessions_since_cross')} sessions ago); "
                f"slope {ema.get('gap_slope_5s')}, percentile {ema.get('gap_percentile')}")
am = mo.get('abs_momentum') or {}
mc3.metric('63D total return', f"{am.get('63D', '–')}%")
mc4.metric('12–1 momentum', f"{mo.get('mom_12_1_pct', '–')}%",
           help='Fama-French style: TR return from 12 months ago to 1 month ago')
mc5.metric('Trend strength', f"{mo.get('trend_strength_pct', '–')}%",
           help='share of EMA pairs (10/30, 20/60, 50/200) in a bullish state')
risk = mo.get('risk') or {}
if risk:
    st.caption(f"Risk: EW vol 20D {risk.get('ewvol_20d_pct')}% ann. · 60D "
               f"{risk.get('ewvol_60d_pct')}% · 52w drawdown "
               f"{risk.get('drawdown_52w_pct')}% · max DD {risk.get('max_drawdown_pct')}%")

group_header('Return horizons — exact windows')
rd = d.get('returns_detail') or {}
rows2 = []
for h in ('1D', '5D', '21D', '63D', '126D', '252D', '1M', '3M', '6M', '12M'):
    raw = rd.get(f'{h}_raw') or {}
    tr = rd.get(f'{h}_tr') or {}
    rows2.append({'Horizon': h, 'Raw %': raw.get('pct'), 'Total return %': tr.get('pct'),
                  'Window': f"{raw.get('start')} → {raw.get('end')}" if raw else '–',
                  'Sessions': raw.get('sessions')})
df_show(style_table(pd.DataFrame(rows2), pct_cols=['Raw %', 'Total return %']))
st.caption('Session horizons (ND) count exact trading sessions on this security\'s '
           'own calendar; calendar horizons (NM) roll back to the last session on '
           'or before the same calendar date N months earlier. '
           'Lineage: canonical 5y daily history (Yahoo, exchange-timezone dated) + '
           'FactIQ statements & SEC XBRL. Full definitions: capital_goods_methodology.md.')
