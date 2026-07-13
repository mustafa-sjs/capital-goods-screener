#!/usr/bin/env python3
"""Full EWMA-crossover strategy comparison. Run on demand or weekly — NEVER
from a Streamlit page load or the daily refresh.

    .venv/bin/python scripts/backtest_momentum.py

Writes data/computed/momentum_backtest.json (page reads this) and upserts
momentum_backtest_results in the DB. All assumptions from config/momentum.yaml.
"""
import json, os, sys, time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.features.momentum import momentum_config, load_history
from src.screening.backtest import run_pair, robust_rank, forward_returns
from src.utils.universe import load_universe

t0 = time.time()
cfg = momentum_config()
u = load_universe()
hist = load_history()
keys = list(u['sec'])
results = []
for pair in [tuple(p) for p in cfg['ewma']['pairs']]:
    for confirm in cfg['backtest']['confirmation_days']:
        row = dict(pair=list(pair), confirm=confirm)
        for window in ('is', 'oos', 'full'):
            m = run_pair(keys, pair, confirm, hist, window)
            if m:
                m.pop('per_security', None) if window != 'full' else None
                row[window] = {k: v for k, v in m.items() if k != 'per_security'}
                if window == 'full':
                    row['per_security'] = m.get('per_security', {})
        results.append(row)
        print(f"{pair} c{confirm}: OOS sharpe {row.get('oos',{}).get('sharpe')} "
              f"excess {row.get('oos',{}).get('excess_ann_pct')}%", flush=True)

ranked = robust_rank(results)
best = ranked[0]
print(f"\nUNIVERSE WINNER: {best['pair']} confirm={best['confirm']} "
      f"score={best['score']} OOS sharpe={best['oos']['sharpe']}")

# subgroup defaults: test top-5 ranked configs per subgroup
subgroup_best = {}
top5 = ranked[:5]
for sg, groups in u['subgroups']:
    sg_keys = sorted({k for _, cov, peers in groups for k in cov + peers})
    sub_res = []
    for r in top5:
        m = run_pair(sg_keys, tuple(r['pair']), r['confirm'], hist, 'oos')
        if m:
            m.pop('per_security', None)
            sub_res.append(dict(pair=r['pair'], confirm=r['confirm'], oos=m))
    sub_ranked = sorted(sub_res, key=lambda x: -(x['oos'].get('sharpe') or -9))
    if sub_ranked:
        subgroup_best[sg] = sub_ranked[0]

# per-security best pair (full window, min-trade guard; labelled historical)
sec_best = {}
min_tr = cfg['backtest']['min_trades']
for r in ranked:
    for k, m in (r.get('per_security') or {}).items():
        if (m.get('n_trades') or 0) >= min_tr:
            cur = sec_best.get(k)
            cand = dict(pair=r['pair'], confirm=r['confirm'],
                        sharpe=m.get('sharpe'), n_trades=m['n_trades'],
                        ann_return_pct=m.get('ann_return_pct'))
            if not cur or (cand['sharpe'] or -9) > (cur['sharpe'] or -9):
                sec_best[k] = cand

fwd = forward_returns(keys, tuple(best['pair']), best['confirm'], hist)
out = dict(
    generated=str(datetime.now(timezone.utc))[:16],
    price_data_max=max(h['session_date'].max() for h in hist.values()),
    config=dict(cost_bps=cfg['backtest']['transaction_cost_bps'],
                slippage_bps=cfg['backtest']['slippage_bps'],
                execution=cfg['backtest']['execution'],
                oos_split=cfg['backtest']['oos_split'],
                min_observations=cfg['backtest']['min_observations']),
    universe_default=dict(pair=best['pair'], confirm=best['confirm']),
    ranked=[{k: v for k, v in r.items() if k != 'per_security'} for r in ranked],
    subgroup_best=subgroup_best,
    security_best=sec_best,
    forward_returns_winner=fwd,
)
os.makedirs(os.path.join(ROOT, 'data', 'computed'), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, 'data', 'computed',
                                 'momentum_backtest.json'), 'w'), default=str)

# persist ranked table to the DB
from src.database.db import connect
db = connect()
db.execute("""CREATE TABLE IF NOT EXISTS momentum_backtest_results (
    run_date TEXT, fast INTEGER, slow INTEGER, confirm_days INTEGER,
    test_window TEXT, ann_return_pct DOUBLE PRECISION, excess_ann_pct DOUBLE PRECISION,
    sharpe DOUBLE PRECISION, sortino DOUBLE PRECISION,
    max_drawdown_pct DOUBLE PRECISION, n_trades INTEGER,
    win_rate_pct DOUBLE PRECISION, turnover_ann DOUBLE PRECISION,
    time_invested_pct DOUBLE PRECISION, stability DOUBLE PRECISION,
    score DOUBLE PRECISION, cost_bps INTEGER,
    PRIMARY KEY (run_date, fast, slow, confirm_days, test_window))""")
rows = []
rd = out['generated'][:10]
for r in ranked:
    for w in ('is', 'oos', 'full'):
        m = r.get(w) or {}
        if m:
            rows.append((rd, r['pair'][0], r['pair'][1], r['confirm'], w,
                         m.get('ann_return_pct'), m.get('excess_ann_pct'),
                         m.get('sharpe'), m.get('sortino'),
                         m.get('max_drawdown_pct'), m.get('n_trades'),
                         m.get('win_rate_pct'), m.get('turnover_ann'),
                         m.get('time_invested_pct'),
                         r.get('stability'), r.get('score'),
                         cfg['backtest']['transaction_cost_bps'] + cfg['backtest']['slippage_bps']))
db.upsert('momentum_backtest_results',
          ['run_date', 'fast', 'slow', 'confirm_days', 'test_window',
           'ann_return_pct', 'excess_ann_pct', 'sharpe', 'sortino',
           'max_drawdown_pct', 'n_trades', 'win_rate_pct', 'turnover_ann',
           'time_invested_pct', 'stability', 'score', 'cost_bps'],
          rows, ['run_date', 'fast', 'slow', 'confirm_days', 'test_window'])
db.close()
print(f'\n{len(rows)} result rows persisted; JSON written. '
      f'({time.time() - t0:.0f}s)')
