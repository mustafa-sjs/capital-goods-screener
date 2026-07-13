"""EWMA-crossover backtest engine — long-only, cost-aware, look-ahead-safe.

Execution model (config/momentum.yaml):
  signal from close t -> position taken at close t+1 (positions shifted by
  1 + confirmation days before returns apply). No adjusted-open data exists,
  so next-close execution is used and stated as a limitation.
Costs: transaction_cost_bps + slippage_bps per SIDE, deducted on every
position change. All maths on the total-return series.

Out-of-sample: chronological split (first `oos_split` = selection window,
remainder untouched). Robust ranking penalises small samples, single-name
dominance, turnover and IS->OOS decay. NOTHING here claims predictiveness —
it measures what WOULD have happened under stated assumptions, gross and net.
"""
import numpy as np
import pandas as pd

from src.features.momentum import cross_series, momentum_config, load_history

ANN = 252


def position_series(px, fast_n, slow_n, confirm=1):
    """Target position (0/1) per session, look-ahead-safe.

    Signal state must persist `confirm` sessions; the position then applies
    from the NEXT session (shift(1)) — returns earned only after execution.
    """
    cs = cross_series(px, fast_n, slow_n)
    r_min = cs['state'].rolling(confirm).min()
    r_max = cs['state'].rolling(confirm).max()
    persist = pd.Series(np.where(r_min == 1, 1.0,
                                 np.where(r_max == -1, 0.0, np.nan)),
                        index=px.index)
    pos = persist.ffill().fillna(0)          # hold last confirmed state
    return pos.shift(1).fillna(0)            # executed next session


def strategy_returns(px, pos, cost_bps):
    r = px.pct_change().fillna(0)
    gross = pos * r
    trades = pos.diff().abs().fillna(pos.iloc[0])
    net = gross - trades * (cost_bps / 1e4)
    return gross, net, trades


def _metrics(net, gross, pos, trades, bench_r):
    out = {}
    n = len(net)
    if n < 30:
        return None
    eq = (1 + net).prod()
    out['total_return_pct'] = round((eq - 1) * 100, 1)
    out['ann_return_pct'] = round((eq ** (ANN / n) - 1) * 100, 2)
    beq = (1 + bench_r).prod()
    out['bench_ann_pct'] = round((beq ** (ANN / n) - 1) * 100, 2)
    out['excess_ann_pct'] = round(out['ann_return_pct'] - out['bench_ann_pct'], 2)
    vol = net.std() * np.sqrt(ANN)
    out['ann_vol_pct'] = round(vol * 100, 1)
    out['sharpe'] = round(net.mean() / net.std() * np.sqrt(ANN), 2) if net.std() else None
    dn = net[net < 0]
    out['sortino'] = (round(net.mean() / dn.std() * np.sqrt(ANN), 2)
                      if len(dn) > 5 and dn.std() else None)
    curve = (1 + net).cumprod()
    dd = (curve / curve.cummax() - 1).min()
    out['max_drawdown_pct'] = round(dd * 100, 1)
    out['calmar'] = (round(out['ann_return_pct'] / abs(dd * 100), 2)
                     if dd else None)
    out['time_invested_pct'] = round(pos.mean() * 100, 0)
    out['turnover_ann'] = round(trades.sum() / 2 / (n / ANN), 1)
    geq = (1 + gross).prod()
    out['gross_ann_pct'] = round((geq ** (ANN / n) - 1) * 100, 2)
    # per-trade stats
    entries = pos.index[(pos.diff() == 1)]
    exits = pos.index[(pos.diff() == -1)]
    rets, holds = [], []
    for i, e in enumerate(entries):
        x = exits[exits > e]
        x = x[0] if len(x) else pos.index[-1]
        seg = net.loc[e:x]
        rets.append((1 + seg).prod() - 1)
        holds.append(len(seg))
    out['n_trades'] = len(rets)
    if rets:
        out['win_rate_pct'] = round(100 * sum(1 for r in rets if r > 0) / len(rets), 0)
        out['avg_trade_pct'] = round(100 * np.mean(rets), 2)
        out['median_trade_pct'] = round(100 * np.median(rets), 2)
        out['avg_hold_sessions'] = round(np.mean(holds), 0)
        wins = sum(r for r in rets if r > 0)
        losses = -sum(r for r in rets if r < 0)
        out['profit_factor'] = round(wins / losses, 2) if losses > 0 else None
    return out


def run_pair(keys, pair, confirm, hist=None, window='full'):
    """Portfolio backtest: equal-weight across securities with valid data.
    window: 'full' | 'is' | 'oos' (chronological split from config)."""
    cfg = momentum_config()['backtest']
    cost = cfg['transaction_cost_bps'] + cfg['slippage_bps']
    hist = hist or load_history()
    per_sec_net, per_sec_meta = {}, {}
    bench_parts = {}
    for k in keys:
        h = hist.get(k)
        if h is None or len(h) < cfg['min_observations']:
            continue
        px = pd.Series(h['close_tr'].values, dtype='float64',
                       index=pd.to_datetime(h['session_date']))
        px = px[~px.index.duplicated()].sort_index().dropna()
        if window != 'full':
            split = int(len(px) * cfg['oos_split'])
            px = px.iloc[:split] if window == 'is' else px.iloc[split - 300:]
            # oos keeps a warm-up tail so EWMAs are live from day one; returns
            # measured only after the split point
        pos = position_series(px, pair[0], pair[1], confirm)
        gross, net, trades = strategy_returns(px, pos, cost)
        if window == 'oos':
            net, gross = net.iloc[300:], gross.iloc[300:]
            pos, trades = pos.iloc[300:], trades.iloc[300:]
        per_sec_net[k] = net
        bench_parts[k] = px.pct_change()
        m = _metrics(net, gross, pos, trades,
                     px.pct_change().fillna(0))
        if m:
            per_sec_meta[k] = m
    if not per_sec_net:
        return None
    aligned = pd.DataFrame(per_sec_net).fillna(0)
    port_net = aligned.mean(axis=1)
    bench = pd.DataFrame(bench_parts).mean(axis=1).reindex(aligned.index).fillna(0)
    port_pos = pd.Series(1.0, index=aligned.index)   # portfolio-level proxies
    port_trades = pd.Series(0.0, index=aligned.index)
    m = _metrics(port_net, port_net, port_pos, port_trades, bench)
    m['n_trades'] = int(sum(x['n_trades'] for x in per_sec_meta.values()))
    m['win_rate_pct'] = (round(np.mean([x['win_rate_pct'] for x in per_sec_meta.values()
                                        if x.get('win_rate_pct') is not None]), 0)
                         if per_sec_meta else None)
    m['n_securities'] = len(per_sec_meta)
    m['per_security'] = per_sec_meta
    # single-name dominance: share of total portfolio return from best name
    totals = {k: (1 + v).prod() - 1 for k, v in per_sec_net.items()}
    tot = sum(abs(v) for v in totals.values())
    m['max_name_share_pct'] = (round(100 * max(abs(v) for v in totals.values()) / tot, 0)
                               if tot else None)
    return m


def forward_returns(keys, pair, confirm, hist=None):
    """Forward TR returns after CONFIRMED bullish crossovers."""
    cfg = momentum_config()['backtest']
    horizons = cfg['forward_horizons']
    hist = hist or load_history()
    out = {h: [] for h in horizons}
    for k in keys:
        h_ = hist.get(k)
        if h_ is None or len(h_) < cfg['min_observations']:
            continue
        px = pd.Series(h_['close_tr'].values, dtype='float64').dropna().reset_index(drop=True)
        cs = cross_series(px, pair[0], pair[1])
        sig = cs.index[cs['cross'] == 1]
        for i in sig:
            entry = i + confirm            # confirmed, executed next session
            if entry >= len(px):
                continue
            for hz in horizons:
                if entry + hz < len(px):
                    out[hz].append(px.iloc[entry + hz] / px.iloc[entry] - 1)
    res = {}
    for hz, v in out.items():
        if v:
            res[hz] = dict(n=len(v), mean_pct=round(100 * np.mean(v), 2),
                           median_pct=round(100 * np.median(v), 2),
                           pos_rate_pct=round(100 * np.mean([x > 0 for x in v]), 0))
    return res


def robust_rank(results):
    """results: list of dicts with keys pair, confirm, is_/oos_ metric blocks.
    Score = OOS Sharpe & excess, penalised for decay, dominance, tiny samples,
    turnover. Returns list sorted best-first with 'stability' & 'score'."""
    ranked = []
    for r in results:
        o, i = r.get('oos') or {}, r.get('is') or {}
        if not o or o.get('sharpe') is None:
            continue
        score = o['sharpe'] * 2 + (o.get('excess_ann_pct') or 0) / 5
        decay = ((i.get('sharpe') or 0) - o['sharpe'])
        if decay > 0:
            score -= decay                        # IS->OOS deterioration
        if (o.get('n_trades') or 0) < momentum_config()['backtest']['min_trades'] * 10:
            score -= 1.5                          # thin evidence across the pack
        if (o.get('max_name_share_pct') or 0) > 40:
            score -= 1.0                          # one-name-driven
        if (o.get('turnover_ann') or 0) > 6:
            score -= 0.5
        stability = round(max(0, 10 - abs(decay) * 4
                              - ((o.get('max_name_share_pct') or 0) > 40) * 3), 1)
        ranked.append({**r, 'score': round(score, 2), 'stability': stability})
    return sorted(ranked, key=lambda x: -x['score'])
