"""Market & Peers — how did coverage companies and their peer baskets
perform? Two views: classic market performance, and "US since Europe
closed" — the US peer read-across from the 16:30 UK benchmark (hybrid
Finnhub/Yahoo capture, indicative market data, not an execution feed)."""
from datetime import timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from components.data import payload, q, data_version, status_strip
from components.ui import (group_header, basket_caption, style_table, df_show,
                           page_header)
from src.features.us_intraday import (BENCHMARK_NAME, US_EXCHANGES,
                                      benchmark_target, move_since_benchmark,
                                      pick_catalyst)
from src.utils.universe import universe_service

LONDON = ZoneInfo('Europe/London')

page_header('Market & Peers',
            'How each coverage company performed relative to its direct '
            'peers, basket by basket.')
status_strip()
from components.manual_refresh import manual_refresh_button
manual_refresh_button()

D = payload(data_version())
svc = universe_service()

# ---------------------------------------------------------- US benchmark ---
SNAP_COLS = ['key', 'observation_date', 'anchor_price', 'anchor_ts',
             'latest_price', 'latest_ts', 'anchor_source', 'latest_source',
             'anchor_quality', 'updated_at']
today, target_utc = benchmark_target()


def _load_snaps():
    from components.data import ph
    try:
        rows = q(f'SELECT {", ".join(SNAP_COLS)} FROM market_benchmark_snapshots '
                 f'WHERE benchmark_name = {ph()} '
                 f'ORDER BY observation_date DESC LIMIT 400', [BENCHMARK_NAME])
    except Exception:
        return {}, None
    if not rows:
        return {}, None
    latest_date = str(rows[0][1])
    return ({r[0]: dict(zip(SNAP_COLS, r)) for r in rows
             if str(r[1]) == latest_date}, latest_date)


def _load_catalysts(keys, since_date):
    from components.data import ph
    try:
        rows = q('SELECT key, published_at, headline, summary, source_name, '
                 'article_url, category, related_symbol, relevance_score, '
                 f'after_1630_uk FROM market_events WHERE event_date >= {ph()}',
                 [since_date])
    except Exception:
        return {}
    cols = ['key', 'published_at', 'headline', 'summary', 'source_name',
            'article_url', 'category', 'related_symbol', 'relevance_score',
            'after_1630_uk']
    by_key = {}
    for r in rows:
        d = dict(zip(cols, r))
        if d['key'] in keys:
            by_key.setdefault(d['key'], []).append(d)
    return {k: pick_catalyst(evs, target_utc) for k, evs in by_key.items()}


snaps, snap_date = _load_snaps()
us_all = {k for k in svc['all'] if svc['exch'].get(k) in US_EXCHANGES}
us_moves = {k: move_since_benchmark(s) for k, s in snaps.items()}
benchmark_is_todays = snap_date == today

# ------------------------------------------------------------ view picker --
import datetime as _dt
after_benchmark = _dt.datetime.now(timezone.utc) >= target_utc
VIEWS = ['Market performance', 'US since Europe closed']
default_view = 1 if (benchmark_is_todays and after_benchmark
                     and any(v is not None for v in us_moves.values())) else 0
view = st.radio('View', VIEWS, index=default_view, horizontal=True,
                label_visibility='collapsed')

c1, c2 = st.columns([2, 1])
subs = ['All subgroups'] + [s['name'] for s in D['subgroups']]
pick = c1.selectbox('Subgroup', subs, label_visibility='collapsed')


def _uk_time(ts):
    if ts is None:
        return None
    if isinstance(ts, str):
        ts = _dt.datetime.fromisoformat(ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(LONDON)


# ===================================================== view 1: US read-across
if view == 'US since Europe closed':
    st.caption('**Indicative market data** — hybrid Finnhub/Yahoo capture of '
               'the 16:30 UK benchmark and later US prices; not an '
               'execution-grade or guaranteed real-time feed.')
    if not snaps:
        st.info('Finnhub US intraday data is unavailable. Yahoo fallback or '
                'the latest stored observation is being shown. The view '
                'fills once the US intraday workflow has run after 16:30 UK.')
    else:
        qual = [s['anchor_quality'] for s in snaps.values()]
        n_ok = sum(1 for x in qual if x in ('exact', 'acceptable'))
        n_fb = sum(1 for s in snaps.values()
                   if s['anchor_source'] == 'yahoo_intraday_fallback')
        upd = max((s['latest_ts'] or s['updated_at']) for s in snaps.values())
        upd_uk = _uk_time(upd)
        cat_map = _load_catalysts(us_all, snap_date)
        st.markdown(
            f'16:30 benchmark available for **{n_ok} of {len(us_all)}** US '
            f'peers ({qual.count("exact")} exact · '
            f'{qual.count("acceptable")} acceptable · '
            f'{qual.count("stale")} stale · {n_fb} via Yahoo fallback) · '
            f'US prices updated **{upd_uk:%H:%M} UK** · session '
            f'{snap_date} · catalysts checked for {len(cat_map)} names')
        if not benchmark_is_todays:
            st.warning(f'Showing the most recent completed capture '
                       f'({snap_date}) — no benchmark stored for today yet.')

        for g in D['close_groups']:
            if pick != 'All subgroups' and g['subgroup'] != pick:
                continue
            members = [r for r in D['close_rows']
                       if r['coverage_group'] == g['group']]
            us_members = [r for r in members if r['key'] in us_all]
            if not us_members:
                continue
            rows, moves, links = [], [], []
            for r in us_members:
                s = snaps.get(r['key'])
                mv = us_moves.get(r['key'])
                cat = cat_map.get(r['key'])
                if cat:
                    when = _uk_time(cat['published_at'])
                    label = ('Possible catalyst' if cat.get('after_1630_uk')
                             else 'Latest company-specific update')
                    cat_txt = (f"“{cat['headline'][:80]}” — "
                               f"{cat['source_name']}, {when:%H:%M %d %b} UK")
                    if mv is not None and abs(mv) >= 1.0 and cat['article_url']:
                        links.append(f"**{r['company']}** {mv:+.1f}% — {label}: "
                                     f"[{cat['headline'][:90]}]({cat['article_url']}) "
                                     f"({cat['source_name']}, {when:%H:%M} UK)")
                else:
                    cat_txt = 'No recent company-specific catalyst identified'
                if mv is not None:
                    moves.append((r['company'], mv))
                rows.append({
                    'Company': ('▮ ' if r['role'] == 'coverage' else ' ')
                               + r['company'],
                    'Ticker': r['ticker'],
                    '16:30 UK price': s['anchor_price'] if s else None,
                    'Current US price': s['latest_price'] if s else None,
                    'US move since 16:30 UK': mv,
                    'Anchor': (s['anchor_quality'] if s else 'unavailable'),
                    'Latest company-specific update': cat_txt,
                    'Updated (UK)': (f'{_uk_time(s["latest_ts"]):%H:%M}'
                                     if s and s['latest_ts'] else '–')})
            group_header(g['group'], g['subgroup'])
            df = pd.DataFrame(rows)
            bold = {i for i, r in enumerate(rows)
                    if r['Company'].startswith('▮')}
            sty = style_table(df, pct_cols=['US move since 16:30 UK'],
                              price_cols=['16:30 UK price', 'Current US price'],
                              bold_rows=bold)
            df_show(sty, help_map={
                'US move since 16:30 UK': 'Move from the captured 16:30 '
                    'Europe/London benchmark to the latest stored US price. '
                    '“–” = no valid anchor or the market was closed.',
                'Anchor': 'Benchmark quality: exact (≤60s from 16:30), '
                          'acceptable (≤5min), stale (older), unavailable.',
                'Latest company-specific update': 'Most recent company news '
                    'from the provider — a possible catalyst, never an '
                    'asserted cause.'})
            if moves:
                avg = sum(m for _, m in moves) / len(moves)
                up = sum(1 for _, m in moves if m > 0)
                best = max(moves, key=lambda x: x[1])
                worst = min(moves, key=lambda x: x[1])
                st.caption(f'US peer basket (equal weight): **{avg:+.2f}%** · '
                           f'{up} of {len(moves)} peers higher · best '
                           f'{best[0]} {best[1]:+.1f}% · weakest {worst[0]} '
                           f'{worst[1]:+.1f}%')
            for ln in links:
                st.markdown(ln)
        st.caption('▮ = coverage company. European coverage rows are shown '
                   'in the Market performance view — their markets close at '
                   'the benchmark, so a “since 16:30” value would be '
                   'misleading. Catalyst wording never asserts causation.')

# =================================================== view 2: classic close --
else:
    big = c2.checkbox('Big moves only (1-day move beyond ±3%)')
    if snaps and benchmark_is_todays:
        st.caption(f'US intraday benchmark active for {len(snaps)} US names '
                   f'(hybrid Finnhub/Yahoo) — the "since 16:30 UK" column '
                   f'shows US names only; closed markets show "–".')
    else:
        st.caption('The "since 16:30 UK" column fills for US peers once the '
                   'US intraday workflow captures today\'s benchmark; other '
                   'markets show "–" because they close at the benchmark.')

    MOVES = ['1D', '5D', '1M', '3M', '12M', 'vs basket']
    for g in D['close_groups']:
        if pick != 'All subgroups' and g['subgroup'] != pick:
            continue
        members = [r for r in D['close_rows'] if r['coverage_group'] == g['group']]
        rows = []
        for r in members:
            if big and (r.get('move_1d_pct') is None or abs(r['move_1d_pct']) <= 3):
                continue
            rows.append({
                'Company': ('▮ ' if r['role'] == 'coverage' else ' ') + r['company'],
                'Ticker': r['ticker'], 'Ccy': r['ccy'], 'Close': r['close_px'],
                '1D': r.get('move_1d_pct'), '5D': r.get('move_5d_pct'),
                '1M': r.get('move_1m_pct'), '3M': r.get('move_3m_pct'),
                '12M': r.get('move_12m_pct'),
                '30-day correlation': r.get('corr30_display')
                    or ('–' if r.get('corr30') is None
                        else f"{r['corr30']:.2f}"),
                'vs basket': r.get('rel_vs_basket_pct'),
                'since 16:30 UK': us_moves.get(r['key'])
                                  if r['key'] in us_all else None})
        if not rows:
            continue
        df = pd.DataFrame(rows)
        bold = {i for i, r in enumerate(rows) if r['Company'].startswith('▮')}
        group_header(g['group'], g['subgroup'])
        cov_names = ' / '.join(r['company'] for r in members
                               if r['role'] == 'coverage')
        sty = style_table(df, pct_cols=MOVES + ['since 16:30 UK'],
                          price_cols=['Close'], bold_rows=bold)
        df_show(sty, help_map={
            '30-day correlation': 'Correlation of daily returns over the '
                                  'last 30 shared sessions (1 = moves '
                                  'identically, 0 = unrelated). Order: '
                                  f'{cov_names}. In two-company tables, '
                                  'peers show "x / y" (one per coverage '
                                  'name) and each bold row shows its '
                                  'correlation to the other coverage name.',
            'vs basket': 'The company\'s 1-day move minus the equal-weighted '
                         'average move of its peer basket, in percentage points.',
            'since 16:30 UK': 'US move since the 16:30 UK benchmark (hybrid '
                              'Finnhub/Yahoo capture). "–" = market closed '
                              'at the benchmark or no valid anchor — never '
                              'shown as 0.0%.'})
        basket_caption(g['stats'])

    st.caption('▮ = coverage company (bold row); its direct peers are listed '
               'beneath it. Basket lines show the peer group\'s average, '
               'median, correlation-weighted and beta-adjusted moves.')
