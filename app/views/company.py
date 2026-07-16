"""Company Analysis — the complete picture for one company.

Consolidates the former Company Drill-Down, Sector Rerating and Scenario
Analysis pages into tabs: Summary | Valuation | Financials | Price Trend |
Scenarios. All calculations are unchanged — only organisation, titles and
labels differ.
"""
import json, os, sys

import altair as alt
import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from components.data import (payload, q, ph, data_version, status_strip,
                             price_history)
from components.ui import (style_table, df_show, page_header, section)
from src.utils.universe import universe_service
from src.utils import metrics as M
from src.features.momentum import momentum_config

page_header('Company Analysis',
            'The complete picture for one coverage company: valuation, '
            'financials, price trend and scenarios.')
status_strip()

D = payload(data_version())
svc = universe_service()
scr = {r['key']: r for r in D['screener']}
key = st.selectbox('Coverage company', [k for k in svc['core'] if k in scr],
                   format_func=lambda k: f"{svc['names'][k]} "
                                         f"({svc['tickers'][k]})")
d = D['drill'][key]
r = scr[key]

tabs = st.tabs(['Summary', 'Valuation', 'Financials', 'Price Trend',
                'Scenarios'])

# ------------------------------------------------------------- Summary -----
with tabs[0]:
    cols = st.columns(6)
    for col, (label, val, hlp) in zip(cols, [
            ('Price', f"{r['price']} {r['quote_ccy']}", None),
            ('EV/EBITDA', f"{r['ev_ebitda_ltm']}×" if r['ev_ebitda_ltm']
             else 'NM', M.describe('ev_ebitda_ltm')),
            ('vs direct peers', f"{r['prem_disc_vs_peers_pct']:+.1f}%"
             if r['prem_disc_vs_peers_pct'] is not None else '–',
             M.describe('prem_disc_vs_peers_pct')),
            ('FCF yield', f"{r['fcf_yield_pct']}%"
             if r['fcf_yield_pct'] is not None else 'NM',
             M.describe('fcf_yield_pct')),
            ('Net debt / EBITDA', f"{r['nd_ebitda']}×"
             if r['nd_ebitda'] is not None else '–',
             M.describe('nd_ebitda')),
            ('Trend', r.get('trend') or '–', M.describe('trend'))]):
        col.metric(label, val, help=hlp)

    bits = []
    if r.get('prem_disc_vs_peers_pct') is not None:
        side = 'discount' if r['prem_disc_vs_peers_pct'] < 0 else 'premium'
        bits.append(f"trades at a {abs(r['prem_disc_vs_peers_pct']):.0f}% "
                    f"{side} to its direct-peer median EV/EBITDA "
                    f"({r['ev_ebitda_ltm']}× vs "
                    f"{r['peer_median_ev_ebitda']}× peer median)")
    if r.get('hist_percentile') is not None:
        bits.append(f"sits at the {r['hist_percentile']:.0f}th percentile of "
                    f"its own valuation history "
                    f"({r['hist_years']} annual observations)")
    if r.get('rev_growth_pct') is not None:
        bits.append(f"reported {r['rev_growth_pct']:+.1f}% revenue growth in "
                    f"the latest fiscal year with an EBITDA margin change of "
                    f"{r.get('margin_chg_pp')}pp")
    if r.get('rel_3m_pct') is not None:
        verb = ('outperformed' if r['rel_3m_pct'] > 0 else 'underperformed')
        bits.append(f"has {verb} its direct peers by "
                    f"{abs(r['rel_3m_pct']):.1f}pp over three months")
    if r.get('trend'):
        extra = (f" ({r['momentum_change'].lower()})"
                 if r.get('momentum_change') else '')
        bits.append(f"the price trend is {r['trend'].lower()}{extra}")
    st.info(f"**{svc['names'][key]}** " + '; '.join(bits) + '. States — '
            f"valuation: **{r['valuation_state']}**, fundamentals: "
            f"**{r['fundamental_state']}** (descriptive, not advice).")

    if d.get('flags'):
        st.warning('**Data warnings:** ' + ' · '.join(d['flags']))
    try:
        from src.features.pit import fundamentals_asof, median_filing_lag
        pit = fundamentals_asof(key, D.get('generated', '2026-01-01'))
        if pit['status'] == 'ok':
            st.caption(f"Filing-date aware: the latest period "
                       f"{pit['period_end']} became public {pit['filed_date']} "
                       f"({pit['lag_days']} days after period end).")
        else:
            st.caption('Exact filing dates are unavailable for this listing '
                       '(non-US) — historical fundamental comparisons are '
                       'approximate and labelled as such.')
    except Exception:
        pass

    section('Peer positioning',
            'This company (highlighted) against its direct peers on the '
            'latest reported financials.')
    g = next((grp for sg in D['subgroups'] for grp in sg['groups']
              if key in grp['coverage']), None)
    allm = D.get('all_metrics', {})
    rows = []
    for p in [key] + (g['peers'] if g else []):
        m = D['drill'].get(p, {}).get('metrics') or allm.get(p) or {}
        cr = next((x for x in D['close_rows'] if x['key'] == p), {})
        rows.append({'Company': ('▮ ' if p == key else '') + svc['names'].get(p, p),
                     'EV/EBITDA': m.get('ev_ebitda'), 'EV/EBIT': m.get('ev_ebit'),
                     'P/E': m.get('pe'),
                     'FCF yield': round(m['fcf_yield'] * 100, 1)
                     if m.get('fcf_yield') is not None else None,
                     'EBITDA margin': round(m['ebitda_margin'] * 100, 1)
                     if m.get('ebitda_margin') is not None else None,
                     'Net debt/EBITDA': m.get('nd_ebitda'),
                     '1D': cr.get('move_1d_pct'), '3M': cr.get('move_3m_pct'),
                     '12M': cr.get('move_12m_pct')})
    df_show(style_table(pd.DataFrame(rows),
                        pct_cols=['1D', '3M', '12M'],
                        pct_plain_cols=['FCF yield', 'EBITDA margin'],
                        mult_cols=['EV/EBITDA', 'EV/EBIT', 'P/E',
                                   'Net debt/EBITDA'],
                        bold_rows={0}))

# ----------------------------------------------------------- Valuation -----
with tabs[1]:
    c1v, c2v, c3v, c4v = st.columns(4)
    c1v.metric('EV/EBITDA', f"{r['ev_ebitda_ltm']}×"
               if r['ev_ebitda_ltm'] else 'NM',
               help=M.describe('ev_ebitda_ltm'))
    c2v.metric('vs direct peers', f"{r['prem_disc_vs_peers_pct']:+.1f}%"
               if r['prem_disc_vs_peers_pct'] is not None else '–',
               help=M.describe('prem_disc_vs_peers_pct'))
    c3v.metric('vs sector', f"{r['prem_disc_vs_sector_pct']:+.1f}%"
               if r['prem_disc_vs_sector_pct'] is not None else '–',
               help=M.describe('prem_disc_vs_sector_pct'))
    c4v.metric('Valuation vs own history',
               f"{r['hist_percentile']:.0f}th percentile"
               if r.get('hist_percentile') is not None else 'Not available',
               help=f"{M.describe('hist_percentile')} Based on "
                    f"{r.get('hist_years')} annual observations.")

    section(f"{svc['names'][key]}'s valuation compared with its own history",
            'Based on annual reported financials and year-end share prices.')
    hist = pd.DataFrame(d['hist'], columns=['year', 'EV/EBITDA'])
    if not hist.empty:
        hist['year'] = hist['year'].astype(str)
        st.bar_chart(hist.set_index('year'), y_label='EV/EBITDA (×)')
        hs = d.get('hist_stats') or {}
        if hs.get('median') is not None:
            st.caption(f"Historical median {hs['median']:.1f}× · current "
                       f"{r['ev_ebitda_ltm']}× · deviation "
                       f"{r.get('hist_zscore')} standard deviations from the "
                       f"historical average.")
    else:
        st.info('No usable valuation history for this company.')

    section('How capital-goods valuations have ranged over time',
            'The line shows the median EV/EBITDA across the whole universe; '
            'the shaded area contains the middle 50% of companies. Each '
            'company is counted once.')
    hist_all = pd.DataFrame(D['hist'])
    if not hist_all.empty:
        hist_all['ev_ebitda'] = pd.to_numeric(hist_all['ev_ebitda'],
                                              errors='coerce')
        piv = hist_all.groupby('year')['ev_ebitda'].agg(
            median='median', q1=lambda s: s.quantile(.25),
            q3=lambda s: s.quantile(.75)).reset_index()
        band = alt.Chart(piv).mark_area(opacity=0.18, color='#175d63').encode(
            x=alt.X('year:O', title='Fiscal year'),
            y=alt.Y('q1:Q', title='EV/EBITDA (×)'), y2='q3:Q')
        med = alt.Chart(piv).mark_line(point=True, color='#175d63').encode(
            x='year:O', y='median:Q',
            tooltip=[alt.Tooltip('year:O', title='Year'),
                     alt.Tooltip('median:Q', title='Median', format='.1f'),
                     alt.Tooltip('q1:Q', title='Lower quartile', format='.1f'),
                     alt.Tooltip('q3:Q', title='Upper quartile', format='.1f')])
        st.altair_chart((band + med).properties(height=300),
                        use_container_width=True)

    section('Which companies are cheap and gaining share-price momentum?',
            'Horizontal: 3-month share-price performance vs direct peers. '
            'Vertical: EV/EBITDA premium (top) or discount (bottom) to '
            'direct peers. The selected company is highlighted.')
    pos = pd.DataFrame([{'Company': s['company'],
                         '3M vs peers (pp)': s.get('rel_3m_pct'),
                         'Premium/discount (%)': s.get('prem_disc_vs_peers_pct'),
                         'Trend': s.get('trend') or 'No clear trend',
                         'Selected': s['key'] == key}
                        for s in D['screener']])
    pts = pos.dropna(subset=['3M vs peers (pp)', 'Premium/discount (%)'])
    base = alt.Chart(pts).encode(
        x=alt.X('3M vs peers (pp):Q',
                title='3M share-price performance vs direct peers (pp)'),
        y=alt.Y('Premium/discount (%):Q',
                title='EV/EBITDA premium (+) or discount (−) to direct peers (%)'),
        tooltip=['Company', 'Premium/discount (%)', '3M vs peers (pp)',
                 'Trend'])
    chart = (base.mark_circle(size=90, opacity=0.85).encode(
                 color=alt.condition('datum.Selected', alt.value('#0d9488'),
                                     alt.Color('Trend:N', legend=alt.Legend(
                                         orient='bottom')))) +
             base.mark_text(dy=-9, fontSize=9).encode(text='Company:N') +
             alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(
                 strokeDash=[4, 4], color='#8a9494').encode(y='y:Q') +
             alt.Chart(pd.DataFrame({'x': [0]})).mark_rule(
                 strokeDash=[4, 4], color='#8a9494').encode(x='x:Q')
             ).properties(height=420)
    st.altair_chart(chart, use_container_width=True)
    st.caption('Quadrants: bottom-right = cheap and outperforming · '
               'top-right = expensive and outperforming · bottom-left = '
               'cheap and underperforming · top-left = expensive and '
               'underperforming. Position describes price action, not a '
               'recommendation.')

# ---------------------------------------------------------- Financials -----
with tabs[2]:
    f_ = d.get('fund') or {}
    m_ = d.get('metrics') or {}
    cf1, cf2, cf3, cf4, cf5 = st.columns(5)
    cf1.metric('Revenue growth', f"{r['rev_growth_pct']:+.1f}%"
               if r.get('rev_growth_pct') is not None else 'Not available',
               help=M.describe('rev_growth_pct'))
    cf2.metric('EBITDA margin', f"{r['ebitda_margin_pct']:.1f}%"
               if r.get('ebitda_margin_pct') is not None else 'Not available',
               help=M.describe('ebitda_margin_pct'))
    cf3.metric('Margin change', f"{r['margin_chg_pp']:+.1f}pp"
               if r.get('margin_chg_pp') is not None else 'Not available',
               help=M.describe('margin_chg_pp'))
    cf4.metric('Cash conversion', f"{r['fcf_conversion']:.2f}"
               if r.get('fcf_conversion') is not None else 'Not available',
               help=M.describe('fcf_conversion'))
    cf5.metric('Net debt / EBITDA', f"{r['nd_ebitda']}×"
               if r.get('nd_ebitda') is not None else 'Not available',
               help=M.describe('nd_ebitda'))

    section('Latest reported financials',
            'Figures in the reporting currency; basis: '
            + str(f_.get('basis') or 'latest reported period') + '.')
    fin_rows = []
    for label, k2, scale in [('Revenue', 'rev', 1e6), ('EBITDA', 'ebitda', 1e6),
                             ('Operating profit (EBIT)', 'ebit', 1e6),
                             ('Net income', 'ni', 1e6),
                             ('Free cash flow', 'fcf', 1e6),
                             ('Cash', 'cash', 1e6), ('Debt', 'debt', 1e6)]:
        v = f_.get(k2)
        fin_rows.append({'Item': label,
                         'Value (m)': round(v / scale, 0) if v is not None
                         else None})
    df_show(style_table(pd.DataFrame(fin_rows), num_cols=['Value (m)']))
    st.caption(f"Period end: {f_.get('asof') or 'not reported'} · fundamental "
               f"direction: **{r['fundamental_state']}**.")

    section('Fundamentals vs direct peers')
    g = next((grp for sg in D['subgroups'] for grp in sg['groups']
              if key in grp['coverage']), None)
    allm = D.get('all_metrics', {})
    rows = []
    for p in [key] + (g['peers'] if g else []):
        m2 = D['drill'].get(p, {}).get('metrics') or allm.get(p) or {}
        rows.append({'Company': ('▮ ' if p == key else '')
                                + svc['names'].get(p, p),
                     'EBITDA margin': round(m2['ebitda_margin'] * 100, 1)
                     if m2.get('ebitda_margin') is not None else None,
                     'FCF yield': round(m2['fcf_yield'] * 100, 1)
                     if m2.get('fcf_yield') is not None else None,
                     'Net debt/EBITDA': m2.get('nd_ebitda')})
    df_show(style_table(pd.DataFrame(rows),
                        pct_plain_cols=['EBITDA margin', 'FCF yield'],
                        mult_cols=['Net debt/EBITDA'], bold_rows={0}))

# ---------------------------------------------------------- Price Trend ----
with tabs[3]:
    mo = d.get('momentum') or {}
    tt1, tt2, tt3, tt4 = st.columns(4)
    tt1.metric('Trend', r.get('trend') or '–', help=M.describe('trend'))
    tt2.metric('Momentum change', r.get('momentum_change') or '–',
               help=M.describe('momentum_change'))
    tt3.metric('Recent signal', r.get('recent_signal') or '–',
               help=M.describe('recent_signal'))
    am = mo.get('abs_momentum') or {}
    tt4.metric('3M total return', f"{am.get('63D', '–')}%"
               if am.get('63D') is not None else '–')

    basis = st.radio('Price basis', ['Total return', 'Raw', 'Split-adjusted'],
                     horizontal=True,
                     help='Total return reinvests dividends and special '
                          'distributions — the default for trend analysis. '
                          'Raw = as traded.')
    bcol = {'Total return': 'close_tr', 'Raw': 'close_raw',
            'Split-adjusted': 'close_split'}[basis]
    hp, src_label = price_history(key, data_version())
    cfg = momentum_config()
    pairs = [tuple(p) for p in cfg['ewma']['pairs']]
    default_pair = tuple(cfg['ewma']['default_pair'])
    from components.momentum_ui import (best_setting_for, security_best_line,
                                        security_pairs_table)
    sec_best, _ = best_setting_for(key)
    best_pair = tuple(sec_best['pair']) if sec_best else None
    start_pair = best_pair if best_pair in pairs else default_pair

    def _pair_label(p):
        tags = []
        if p == best_pair:
            tags.append('best for this company')
        if p == default_pair:
            tags.append('universe default')
        return f'{p[0]}/{p[1]}' + (f" — {', '.join(tags)}" if tags else '')

    pair = st.selectbox('Trend setting (fast/slow average, days)', pairs,
                        index=pairs.index(start_pair),
                        format_func=_pair_label,
                        help='Preselected to the setting that tested best on '
                             'this share\'s own history (net of costs, '
                             'minimum-trade guard) — historical evidence, '
                             'not a prediction.')
    security_best_line(key, svc['names'][key])
    security_pairs_table(key, svc['names'][key])
    px = pd.Series(hp[bcol].values, index=pd.to_datetime(hp['session_date']),
                   dtype='float64')
    fast = px.ewm(span=pair[0], adjust=False, min_periods=pair[0]).mean()
    slow = px.ewm(span=pair[1], adjust=False, min_periods=pair[1]).mean()
    state = (fast > slow).astype(int).where(fast.notna() & slow.notna())
    crosses = state.diff()
    import plotly.graph_objects as go
    log_y = st.toggle('Log scale')
    fig = go.Figure()
    fig.add_scatter(x=px.index, y=px, name=f'{basis} price',
                    line=dict(color='#175d63', width=1.4))
    fig.add_scatter(x=fast.index, y=fast, name=f'{pair[0]}-day average',
                    line=dict(color='#2a78d6', width=1))
    fig.add_scatter(x=slow.index, y=slow, name=f'{pair[1]}-day average',
                    line=dict(color='#eda100', width=1))
    bx = crosses[crosses == 1].index
    sx = crosses[crosses == -1].index
    fig.add_scatter(x=bx, y=px.reindex(bx), mode='markers',
                    name='positive crossover',
                    marker=dict(symbol='triangle-up', size=10, color='#0a7d38'))
    fig.add_scatter(x=sx, y=px.reindex(sx), mode='markers',
                    name='negative crossover',
                    marker=dict(symbol='triangle-down', size=10,
                                color='#c0392b'))
    acts = pd.DataFrame()
    arows = q(f'SELECT action_date, kind, value FROM corporate_actions '
              f'WHERE key = {ph()} ORDER BY action_date', [key])
    if arows:
        acts = pd.DataFrame(arows, columns=['action_date', 'kind', 'value'])
    fig.update_layout(
        title=dict(text=f"{svc['names'][key]} — share price with trend "
                        f"averages and crossovers", font=dict(size=14)),
        height=440, margin=dict(l=10, r=10, t=48, b=10),
        yaxis_type='log' if log_y else 'linear',
        yaxis_title=f'{basis} price',
        legend=dict(orientation='h', y=1.09),
        xaxis=dict(rangeselector=dict(buttons=[
            dict(count=1, label='1y', step='year'),
            dict(count=3, label='3y', step='year'),
            dict(count=5, label='5y', step='year'),
            dict(step='all')])))
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f'Price source: {src_label} · latest session '
               f'{hp["session_date"].max()} · dividends and splits: '
               f'{len(acts)} recorded corporate actions in the history.')

    risk = mo.get('risk') or {}
    if risk:
        st.caption(f"Risk context: 20-day volatility "
                   f"{risk.get('ewvol_20d_pct')}% annualised · distance from "
                   f"52-week high {risk.get('drawdown_52w_pct')}% · worst "
                   f"peak-to-trough drawdown in the stored history (from "
                   f"{str(hp['session_date'].min())[:4]}, total-return "
                   f"basis) {risk.get('max_drawdown_pct')}%.")

    section('Return horizons — exact windows',
            'Session horizons count exact trading sessions; month horizons '
            'roll back to the last session on or before the same calendar '
            'date. Total return reinvests dividends.')
    rd = d.get('returns_detail') or {}
    rows2 = []
    for h in ('1D', '5D', '21D', '63D', '126D', '252D', '1M', '3M', '6M', '12M'):
        raw = rd.get(f'{h}_raw') or {}
        tr = rd.get(f'{h}_tr') or {}
        rows2.append({'Horizon': h, 'Price change': raw.get('pct'),
                      'Total return': tr.get('pct'),
                      'Window': f"{raw.get('start')} → {raw.get('end')}"
                      if raw else '–',
                      'Sessions': raw.get('sessions')})
    df_show(style_table(pd.DataFrame(rows2),
                        pct_cols=['Price change', 'Total return'],
                        int_cols=['Sessions']))

# ------------------------------------------------------------ Scenarios ----
with tabs[4]:
    st.warning('**Mechanical valuation scenarios — not analyst price '
               'targets.** The implied return decomposes additively into '
               'earnings, multiple, net-debt and share-count effects.')
    f_ = d['fund']; m_ = d['metrics']
    e0 = f_.get('ebitda'); m0 = r['ev_ebitda_ltm']
    nd0 = m_.get('net_debt') or 0
    sh0 = f_.get('sh'); mino = f_.get('minority') or 0; px0 = r['price']
    if not all([e0, m0, sh0, px0]):
        st.error('Scenario inputs are not available for this company '
                 '(missing EBITDA, multiple, share count or price).')
    else:
        c1s, c2s, c3s, c4s = st.columns(4)
        de = c1s.number_input('Change in EBITDA (%)', value=0.0, step=5.0) / 100
        mt = c2s.number_input('Target EV/EBITDA', value=float(m0), step=0.5)
        nd = c3s.number_input('Net debt (bn, reporting currency)',
                              value=round(nd0 / 1e9, 2)) * 1e9
        sh = c4s.number_input('Shares (m)', value=round(sh0 / 1e6, 1)) * 1e6

        e = e0 * (1 + de)
        eq0 = m0 * e0 - nd0 - mino
        conv = px0 / (eq0 / sh0)
        eqN = mt * e - nd - mino
        px_ = eqN / sh * conv
        ret = px_ / px0 - 1
        earn = m0 * (e - e0) / eq0
        mult = (mt - m0) * e / eq0
        ndef = -(nd - nd0) / eq0
        shef = (eqN / eq0) * (sh0 / sh - 1)

        cols = st.columns(6)
        for col, (l2, v2) in zip(cols, [
                ('Implied price', f'{px_:,.2f} {r["quote_ccy"]}'),
                ('Implied return', f'{ret * 100:+.1f}%'),
                ('Earnings effect', f'{earn * 100:+.1f}%'),
                ('Multiple effect', f'{mult * 100:+.1f}%'),
                ('Net-debt effect', f'{ndef * 100:+.1f}%'),
                ('Share-count effect', f'{shef * 100:+.1f}%')]):
            col.metric(l2, v2)
        st.caption('New enterprise value = target multiple × new EBITDA; '
                   'equity = enterprise value − net debt − minorities; the '
                   'four effects sum exactly to the implied return.')

        section('Preset scenarios')
        pres = [json.loads(p) if isinstance(p, str) else p
                for p in [row for row in D['scenarios'] if row['key'] == key]]
        if pres:
            df = pd.DataFrame(pres)[['scenario', 'ebitda_report_ccy',
                                     'target_multiple', 'implied_ev_bn',
                                     'implied_price', 'current_price',
                                     'implied_return_pct',
                                     'earnings_effect_pct',
                                     'multiple_effect_pct']]
            df.columns = ['Scenario', 'EBITDA (m)', 'Multiple', 'EV (bn)',
                          'Implied price', 'Current price', 'Return',
                          'Earnings effect', 'Multiple effect']
            df_show(style_table(df, pct_cols=['Return', 'Earnings effect',
                                              'Multiple effect'],
                                mult_cols=['Multiple'],
                                num_cols=['EBITDA (m)', 'EV (bn)'],
                                price_cols=['Implied price', 'Current price']),
                    height=int(38 * (len(df) + 1)) + 4)
            st.caption('Bear = −10% EBITDA at the peer lower quartile · '
                       'Base = latest EBITDA at the current multiple · '
                       'Bull = +10% EBITDA at the peer upper quartile · '
                       'plus re-rating rows. Every row is a mechanical '
                       'scenario, not a target.')
