"""Cross-sectional momentum screening — screener/heatmap-ready tables.

All series maths lives in src/features/momentum.py; backtest evidence comes
from data/computed/momentum_backtest.json (scripts/backtest_momentum.py).
The score is the config-weighted sum of cross-sectional percentiles —
transparent, componentised, never a black box.
"""
import json, os

import numpy as np
import pandas as pd

from src.features.momentum import (momentum_config, pair_features,
                                   cross_series, load_history,
                                   simple_momentum_fields)
from src.features.returns import ret_pct

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BT_PATH = os.path.join(ROOT, 'data', 'computed', 'momentum_backtest.json')


def backtest_payload():
    if os.path.exists(BT_PATH):
        return json.load(open(BT_PATH))
    return None


def _pctile(s):
    return s.rank(pct=True) * 100


def signal_history_stats(key, pair, confirm, hist):
    """Per-security historical evidence for the pair: forward 60d after
    confirmed bullish crossovers (count, positive rate, median)."""
    h = hist.get(key)
    if h is None or len(h) < 400:
        return dict(n_signals=0)
    px = pd.Series(h['close_tr'].values, dtype='float64').dropna().reset_index(drop=True)
    cs = cross_series(px, pair[0], pair[1])
    sig = [i for i in cs.index[cs['cross'] == 1] if i + confirm + 60 < len(px)]
    if not sig:
        return dict(n_signals=0)
    f = [px.iloc[i + confirm + 60] / px.iloc[i + confirm] - 1 for i in sig]
    return dict(n_signals=len(f),
                pos_3m_rate_pct=round(100 * np.mean([x > 0 for x in f]), 0),
                median_3m_fwd_pct=round(100 * float(np.median(f)), 1))


def build_table(universe, names, subgroups_of, peers_of, pair=None, confirm=None):
    """One row per security: returns, relative strength, pair signal, score
    components and composite. `universe` = list of keys."""
    cfg = momentum_config()
    pair = tuple(pair or cfg['ewma']['default_pair'])
    confirm = confirm or 5
    hist = load_history()
    rows = []
    # benchmark = universe equal-weight TR return per horizon
    bench = {h: [] for h in ('1M', '3M', '6M', '12M')}
    per_key = {}
    for k in universe:
        r = {h: ret_pct(k, h, 'tr', hist=hist) for h in ('1M', '3M', '6M', '12M')}
        per_key[k] = r
        for h, v in r.items():
            if v is not None:
                bench[h].append(v)
    bench_mean = {h: (np.mean(v) if v else None) for h, v in bench.items()}
    for k in universe:
        r = per_key[k]
        pf = pair_features(k, pair, hist)
        r12, r1 = r.get('12M'), r.get('1M')
        mom_12_1 = (round(((1 + r12 / 100) / (1 + r1 / 100) - 1) * 100, 1)
                    if None not in (r12, r1) else None)
        rel = (round(r['12M'] - bench_mean['12M'], 1)
               if r.get('12M') is not None and bench_mean['12M'] is not None else None)
        rel3 = (round(r['3M'] - bench_mean['3M'], 1)
                if r.get('3M') is not None and bench_mean['3M'] is not None else None)
        sh = signal_history_stats(k, pair, confirm, hist)
        smf = simple_momentum_fields(pf)
        rows.append(dict(
            key=k, company=names.get(k, k), subgroup=subgroups_of.get(k, ''),
            trend=smf['trend'], momentum_change=smf['momentum_change'],
            recent_signal=smf['recent_signal'],
            ret_1m=r.get('1M'), ret_3m=r.get('3M'), ret_6m=r.get('6M'),
            ret_12m=r.get('12M'), mom_12_1=mom_12_1, rel_strength=rel,
            rel_3m_universe=rel3,
            dist_52w_high=pf.get('dist_52w_high_pct'),
            dist_52w_low=pf.get('dist_52w_low_pct'),
            spread=pf.get('spread_pct'), slow_slope=pf.get('slow_slope_5s'),
            dist_chg=pf.get('dist_chg_5s'),
            acceleration=pf.get('acceleration'),
            signal=pf.get('signal'), cross_type=pf.get('cross_type'),
            cross_date=pf.get('cross_date'),
            days_since_cross=pf.get('sessions_since_cross'),
            status=pf.get('status'),
            n_signals=sh.get('n_signals', 0),
            pos_3m_rate=sh.get('pos_3m_rate_pct'),
            median_3m_fwd=sh.get('median_3m_fwd_pct')))
    df = pd.DataFrame(rows)
    # score: config-weighted percentiles; missing component -> reweight rest
    w = cfg['score']['weights']
    comp = pd.DataFrame(index=df.index)
    comp['ret_3m_pctile'] = _pctile(df['ret_3m'])
    comp['ret_6m_pctile'] = _pctile(df['ret_6m'])
    comp['ret_12m_pctile'] = _pctile(df['ret_12m'])
    comp['rel_strength_pctile'] = _pctile(df['rel_strength'])
    comp['ewma_spread_pctile'] = _pctile(df['spread'])
    comp['slow_slope_pctile'] = _pctile(df['slow_slope'])
    comp['acceleration_pctile'] = _pctile(df['acceleration'])
    weights = pd.Series(w)
    wsum = comp.notna().mul(weights, axis=1).sum(axis=1)
    df['momentum_score'] = (comp.mul(weights, axis=1).sum(axis=1)
                            / wsum.replace(0, np.nan)).round(0)
    for c in comp:
        df[c] = comp[c].round(0)
    # classification from score + acceleration
    def classify(row):
        s, a = row['momentum_score'], row['acceleration']
        if pd.isna(s):
            return 'insufficient data'
        if s >= 75: return 'strong'
        if s >= 55: return 'improving' if (a or 0) > 0 else 'neutral'
        if s >= 35: return 'deteriorating' if (a or 0) < 0 else 'neutral'
        return 'weak'
    df['classification'] = df.apply(classify, axis=1)
    df['rank'] = df['momentum_score'].rank(ascending=False, method='min')
    return df.sort_values('momentum_score', ascending=False).reset_index(drop=True)


# default heatmap: four columns an analyst actually scans; the expanded set
# remains available behind a toggle (progressive disclosure, not deletion)
HEATMAP_COLS_DEFAULT = ['rel_3m_universe', 'ret_6m', 'spread', 'dist_chg']
HEATMAP_COLS = ['ret_1m', 'ret_3m', 'ret_6m', 'ret_12m', 'rel_3m_universe',
                'rel_strength', 'spread', 'dist_chg', 'momentum_score']


def heatmap_frame(df, cols=None):
    """Percentile-rank frame for colouring; raw values shown in hover/table."""
    out = pd.DataFrame({'company': df['company']})
    for c in (cols or HEATMAP_COLS_DEFAULT):
        out[c] = _pctile(df[c]).round(0)
    return out.set_index('company')
