"""Shared Price-Trend UI blocks (Stock Screener + Company Analysis).

One rendering of the per-equity backtest evidence so both pages say exactly
the same thing: which crossover setting tested best FOR THIS SHARE, and how
every configured setting would have traded it (full history, net of costs,
next-close execution). Historical description — never a predictive claim.
"""
import pandas as pd
import streamlit as st

from src.features.momentum import momentum_config
from src.screening.momentum import backtest_payload


def fmt_pair(p):
    return f'{p[0]}/{p[1]}'


def best_setting_for(key, bt=None):
    """(best_row | None, all_rows) for one security from the backtest JSON."""
    bt = bt or backtest_payload() or {}
    return (bt.get('security_best', {}).get(key),
            bt.get('security_pairs', {}).get(key) or [])


def security_best_line(key, name, current_pair=None, allow_apply=False):
    """Headline 'best setting for this company' + optional apply button.
    Returns the best pair tuple (or None) so callers can preselect it."""
    best, rows = best_setting_for(key)
    if not best:
        if rows:
            st.caption('No setting produced enough trades on this share for '
                       'a best-setting call (fewer than '
                       f"{momentum_config()['backtest']['min_trades']} "
                       'round trips each) — see the comparison below.')
        return None
    bp = tuple(best['pair'])
    beat = ((best.get('excess_ann_pct') or 0) > 0)
    line = (f"**Best-tested setting for {name}: {fmt_pair(bp)}-day averages** "
            f"(confirmation {best['confirm']} sessions) — "
            f"{best['ann_return_pct']}% a year net vs "
            f"{best['bench_ann_pct']}% buy-and-hold "
            f"({'beat' if beat else 'lagged'} the share itself), "
            f"worst drawdown {best['max_drawdown_pct']}% vs "
            f"{best['bench_max_drawdown_pct']}% holding throughout, "
            f"{best['n_trades']} trades. Full available history, net of "
            f"costs — historical, not predictive.")
    if allow_apply and current_pair is not None and bp != tuple(current_pair):
        c1, c2 = st.columns([4, 1])
        c1.markdown(line)
        if c2.button(f'Use {fmt_pair(bp)}', key=f'apply_best_{key}'):
            st.session_state['mom_pair'] = bp
            st.rerun()
    else:
        st.markdown(line)
    return bp


def security_pairs_table(key, name):
    """Expander: every configured setting applied to this one share —
    best confirmation per pair, ranked, best row flagged."""
    best, rows = best_setting_for(key)
    if not rows:
        return
    min_tr = momentum_config()['backtest']['min_trades']
    by_pair = {}
    for r in rows:                     # keep best confirmation per pair
        p = tuple(r['pair'])
        if p not in by_pair or (r['sharpe'] or -9) > (by_pair[p]['sharpe'] or -9):
            by_pair[p] = r
    ranked = sorted(by_pair.values(),
                    key=lambda r: -(r['sharpe'] if r['sharpe'] is not None else -9))
    with st.expander(f'How each setting would have traded {name} '
                     '(full history, net of costs)'):
        out = []
        for r in ranked:
            flag = ''
            if best and r['pair'] == best['pair'] and r['confirm'] == best['confirm']:
                flag = '★ best'
            elif (r['n_trades'] or 0) < min_tr:
                flag = 'few trades'
            out.append({
                'Setting (days)': fmt_pair(r['pair']),
                'Confirmation': r['confirm'],
                'Strategy % a year': r['ann_return_pct'],
                'Buy-and-hold % a year': r['bench_ann_pct'],
                'Difference': r['excess_ann_pct'],
                'Worst drawdown (strategy)': r['max_drawdown_pct'],
                'Worst drawdown (holding)': r['bench_max_drawdown_pct'],
                'Time invested %': r['time_invested_pct'],
                'Trades': r['n_trades'],
                'Winning trades %': r['win_rate_pct'],
                '': flag})
        st.dataframe(pd.DataFrame(out), hide_index=True,
                     use_container_width=True)
        st.caption('Same engine and assumptions as the universe backtest: '
                   'total-return prices, signal at one close acted on at the '
                   'next, 25bps per side all-in costs. "Difference" is the '
                   'strategy minus simply holding the share for the same '
                   'period. Settings with few trades are anecdotes, not '
                   'evidence. Past behaviour of a setting on one share does '
                   'not predict its future behaviour.')
