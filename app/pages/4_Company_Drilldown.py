import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + '/app')
import streamlit as st
import pandas as pd
from components.data import payload, q, ph, BASIS_BANNER

st.set_page_config(page_title='Drill-Down', page_icon='🏭', layout='wide')
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
        f". Consensus revisions unavailable — momentum is price/reported-results "
        f"based. Classification: **{r['classification']}**.")
if d.get('flags'):
    st.warning('**Data-quality flags:** ' + ' · '.join(d['flags']))

c1, c2 = st.columns(2)
with c1:
    st.subheader('Share price (daily, stored history)')
    px = q(f"""SELECT price_date, close FROM raw_daily_prices
               WHERE key = {ph()} ORDER BY price_date""", [key])
    pdf = pd.DataFrame(px, columns=['date', 'close']).drop_duplicates('date')
    pdf['date'] = pd.to_datetime(pdf['date'])
    st.line_chart(pdf.set_index('date'))
with c2:
    st.subheader('EV/EBITDA vs own history')
    hist = pd.DataFrame(d['hist'], columns=['year', 'EV/EBITDA'])
    if not hist.empty:
        hist['year'] = hist['year'].astype(str)
        st.bar_chart(hist.set_index('year'))

st.subheader('Direct-peer comparison (LTM)')
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
st.dataframe(pd.DataFrame(rows).round(2), hide_index=True, use_container_width=True)
st.caption('Lineage: FactIQ statements + SEC XBRL; prices FactIQ history + Yahoo '
           'incremental. Full definitions: docs/methodology (repo) and Page 6 of '
           'the embedded dashboard.')
