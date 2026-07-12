#!/usr/bin/env python3
"""Capital Goods dashboard — metrics engine.

Reads raw FactIQ payloads from data/raw/, computes valuation / quality /
performance / read-across metrics on an LTM reported basis (estimate_basis =
"LTM reported fallback" everywhere: FactIQ carries no consensus estimates),
and writes the output CSVs plus data/computed/dashboard_data.json.

Approximations are flagged in capital_goods_methodology.md. Notably:
- daily/monthly price files are intelligently sampled (recent rows dense,
  older rows thinned); returns use exact or nearest-date matches, and
  correlations use shared dates only with n_obs recorded.
- Historical valuation uses fiscal-year fundamentals with year-end prices
  and same-vintage shares/net debt (approximate point-in-time, no consensus).
"""
import json, os, csv, math, statistics as st
from datetime import date, timedelta

RAW = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'computed')
ROOT = os.path.join(os.path.dirname(__file__), '..')
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- config ---
# key -> (display name, subgroup-agnostic) trading ccy, report ccy, exchange
SEC = {
 'ABBN':  dict(name='ABB Ltd', qccy='CHF', rccy='USD', exch='SIX', sym='ABBN SW'),
 'ALO':   dict(name='Alstom SA', qccy='EUR', rccy='EUR', exch='Euronext Paris', sym='ALO FP'),
 'SRAIL': dict(name='Stadler Rail AG', qccy='CHF', rccy='CHF', exch='SIX', sym='SRAIL SW'),
 'LR':    dict(name='Legrand SA', qccy='EUR', rccy='EUR', exch='Euronext Paris', sym='LR FP'),
 'NEX':   dict(name='Nexans SA', qccy='EUR', rccy='EUR', exch='Euronext Paris', sym='NEX FP'),
 'PRY':   dict(name='Prysmian SpA', qccy='EUR', rccy='EUR', exch='Borsa Italiana', sym='PRY IM'),
 'RXL':   dict(name='Rexel SA', qccy='EUR', rccy='EUR', exch='Euronext Paris', sym='RXL FP'),
 'SU':    dict(name='Schneider Electric SE', qccy='EUR', rccy='EUR', exch='Euronext Paris', sym='SU FP'),
 'SIE':   dict(name='Siemens AG', qccy='EUR', rccy='EUR', exch='XETRA', sym='SIE GY'),
 'DTG':   dict(name='Daimler Truck Holding AG', qccy='EUR', rccy='EUR', exch='XETRA', sym='DTG GY'),
 '8TRA':  dict(name='TRATON SE', qccy='EUR', rccy='EUR', exch='XETRA', sym='8TRA GY'),
 'VOLVB': dict(name='Volvo AB (B)', qccy='SEK', rccy='SEK', exch='Nasdaq Stockholm', sym='VOLVB SS'),
 'KNEBV': dict(name='KONE Oyj (B)', qccy='EUR', rccy='EUR', exch='Nasdaq Helsinki', sym='KNEBV FH'),
 'SCHP':  dict(name='Schindler Holding (PC)', qccy='CHF', rccy='CHF', exch='SIX', sym='SCHP SW'),
 'HLMA':  dict(name='Halma plc', qccy='GBp', rccy='GBP', exch='LSE', sym='HLMA LN'),
 'IMI':   dict(name='IMI plc', qccy='GBp', rccy='GBP', exch='LSE', sym='IMI LN'),
 'ROR':   dict(name='Rotork plc', qccy='GBp', rccy='GBP', exch='LSE', sym='ROR LN'),
 'SMIN':  dict(name='Smiths Group plc', qccy='GBp', rccy='GBP', exch='LSE', sym='SMIN LN'),
 'SPX':   dict(name='Spirax Group plc', qccy='GBp', rccy='GBP', exch='LSE', sym='SPX LN'),
 'WEIR':  dict(name='Weir Group plc', qccy='GBp', rccy='GBP', exch='LSE', sym='WEIR LN'),
 'ASSAB': dict(name='Assa Abloy AB (B)', qccy='SEK', rccy='SEK', exch='Nasdaq Stockholm', sym='ASSAB SS'),
 'ATCOA': dict(name='Atlas Copco AB (A)', qccy='SEK', rccy='SEK', exch='Nasdaq Stockholm', sym='ATCOA SS'),
 'EPIA':  dict(name='Epiroc AB (A)', qccy='SEK', rccy='SEK', exch='Nasdaq Stockholm', sym='EPIA SS'),
 'METSO': dict(name='Metso Oyj', qccy='EUR', rccy='EUR', exch='Nasdaq Helsinki', sym='METSO FH'),
 'SAND':  dict(name='Sandvik AB', qccy='SEK', rccy='SEK', exch='Nasdaq Stockholm', sym='SAND SS'),
 'SKFB':  dict(name='SKF AB (B)', qccy='SEK', rccy='SEK', exch='Nasdaq Stockholm', sym='SKFB SS'),
 'RR':    dict(name='Rolls-Royce Holdings plc', qccy='GBp', rccy='GBP', exch='LSE', sym='RR/ LN'),
 'MRO':   dict(name='Melrose Industries plc', qccy='GBp', rccy='GBP', exch='LSE', sym='MRO LN'),
 'PCAR':  dict(name='PACCAR Inc', qccy='USD', rccy='USD', exch='NASDAQ', sym='PCAR US'),
 'OTIS':  dict(name='Otis Worldwide Corp', qccy='USD', rccy='USD', exch='NYSE', sym='OTIS US'),
 # US peers
 'ETN': dict(name='Eaton Corp plc', qccy='USD', rccy='USD', exch='NYSE', sym='ETN US'),
 'ROK': dict(name='Rockwell Automation', qccy='USD', rccy='USD', exch='NYSE', sym='ROK US'),
 'GE':  dict(name='GE Aerospace', qccy='USD', rccy='USD', exch='NYSE', sym='GE US'),
 'EMR': dict(name='Emerson Electric', qccy='USD', rccy='USD', exch='NYSE', sym='EMR US'),
 'WAB': dict(name='Wabtec', qccy='USD', rccy='USD', exch='NYSE', sym='WAB US'),
 'GBX': dict(name='Greenbrier', qccy='USD', rccy='USD', exch='NYSE', sym='GBX US'),
 'TT':  dict(name='Trane Technologies', qccy='USD', rccy='USD', exch='NYSE', sym='TT US'),
 'ATKR':dict(name='Atkore', qccy='USD', rccy='USD', exch='NYSE', sym='ATKR US'),
 'BDC': dict(name='Belden', qccy='USD', rccy='USD', exch='NYSE', sym='BDC US'),
 'VISN':dict(name='Vistance Networks', qccy='USD', rccy='USD', exch='NASDAQ', sym='VISN US'),
 'GLW': dict(name='Corning', qccy='USD', rccy='USD', exch='NYSE', sym='GLW US'),
 'FAST':dict(name='Fastenal', qccy='USD', rccy='USD', exch='NASDAQ', sym='FAST US'),
 'WCC': dict(name='WESCO International', qccy='USD', rccy='USD', exch='NYSE', sym='WCC US'),
 'VRT': dict(name='Vertiv Holdings', qccy='USD', rccy='USD', exch='NYSE', sym='VRT US'),
 'HON': dict(name='Honeywell', qccy='USD', rccy='USD', exch='NASDAQ', sym='HON US'),
 'JCI': dict(name='Johnson Controls', qccy='USD', rccy='USD', exch='NYSE', sym='JCI US'),
 'CMI': dict(name='Cummins', qccy='USD', rccy='USD', exch='NYSE', sym='CMI US'),
 'OSK': dict(name='Oshkosh', qccy='USD', rccy='USD', exch='NYSE', sym='OSK US'),
 'DE':  dict(name='Deere & Co', qccy='USD', rccy='USD', exch='NYSE', sym='DE US'),
 'CARR':dict(name='Carrier Global', qccy='USD', rccy='USD', exch='NYSE', sym='CARR US'),
 'COHR':dict(name='Coherent', qccy='USD', rccy='USD', exch='NYSE', sym='COHR US'),
 'FN':  dict(name='Fabrinet', qccy='USD', rccy='USD', exch='NYSE', sym='FN US'),
 'LITE':dict(name='Lumentum', qccy='USD', rccy='USD', exch='NASDAQ', sym='LITE US'),
 'AME': dict(name='AMETEK', qccy='USD', rccy='USD', exch='NYSE', sym='AME US'),
 'WTS': dict(name='Watts Water', qccy='USD', rccy='USD', exch='NYSE', sym='WTS US'),
 'BMI': dict(name='Badger Meter', qccy='USD', rccy='USD', exch='NYSE', sym='BMI US'),
 'FLS': dict(name='Flowserve', qccy='USD', rccy='USD', exch='NYSE', sym='FLS US'),
 'CR':  dict(name='Crane Co (Crane NXT line)', qccy='USD', rccy='USD', exch='NYSE', sym='CR US'),
 'ITT': dict(name='ITT Inc', qccy='USD', rccy='USD', exch='NYSE', sym='ITT US'),
 'LII': dict(name='Lennox International', qccy='USD', rccy='USD', exch='NYSE', sym='LII US'),
 'DHR': dict(name='Danaher', qccy='USD', rccy='USD', exch='NYSE', sym='DHR US'),
 'IR':  dict(name='Ingersoll Rand', qccy='USD', rccy='USD', exch='NYSE', sym='IR US'),
 'IEX': dict(name='IDEX', qccy='USD', rccy='USD', exch='NYSE', sym='IEX US'),
 'KMT': dict(name='Kennametal', qccy='USD', rccy='USD', exch='NYSE', sym='KMT US'),
 'CAT': dict(name='Caterpillar', qccy='USD', rccy='USD', exch='NYSE', sym='CAT US'),
 'TEX': dict(name='Terex', qccy='USD', rccy='USD', exch='NYSE', sym='TEX US'),
 'ALLE':dict(name='Allegion plc', qccy='USD', rccy='USD', exch='NYSE', sym='ALLE US'),
 'AMAT':dict(name='Applied Materials', qccy='USD', rccy='USD', exch='NASDAQ', sym='AMAT US'),
 'KLAC':dict(name='KLA Corp', qccy='USD', rccy='USD', exch='NASDAQ', sym='KLAC US'),
 'TKR': dict(name='Timken', qccy='USD', rccy='USD', exch='NYSE', sym='TKR US'),
 'RTX': dict(name='RTX Corp', qccy='USD', rccy='USD', exch='NYSE', sym='RTX US'),
 'HWM': dict(name='Howmet Aerospace', qccy='USD', rccy='USD', exch='NYSE', sym='HWM US'),
 'TDG': dict(name='TransDigm', qccy='USD', rccy='USD', exch='NYSE', sym='TDG US'),
 'WWD': dict(name='Woodward', qccy='USD', rccy='USD', exch='NASDAQ', sym='WWD US'),
 'MOGA':dict(name='Moog Inc (A)', qccy='USD', rccy='USD', exch='NYSE', sym='MOG/A US'),
 'HXL': dict(name='Hexcel', qccy='USD', rccy='USD', exch='NYSE', sym='HXL US'),
 'NSK': dict(name='NSK Ltd', qccy='JPY', rccy='JPY', exch='JPX Tokyo', sym='6471 JP'),
 'NTN': dict(name='NTN Corp', qccy='JPY', rccy='JPY', exch='JPX Tokyo', sym='6472 JP'),
 'EBARA':dict(name='Ebara Corp', qccy='JPY', rccy='JPY', exch='JPX Tokyo', sym='6361 JP'),
 'TKR2': None,
}
del SEC['TKR2']

SUBGROUPS = [
 ('Automation & Electrical Equipment', [
   ('ABB', ['ABBN'], ['ETN','ROK','GE','EMR']),
   ('Alstom & Stadler', ['ALO','SRAIL'], ['WAB','GBX']),
   ('Legrand', ['LR'], ['ETN','TT','EMR']),
   ('Nexans & Prysmian', ['NEX','PRY'], ['ATKR','BDC','VISN','GLW']),
   ('Rexel', ['RXL'], ['FAST','WCC']),
   ('Schneider Electric', ['SU'], ['ETN','VRT','HON','EMR','JCI','ROK']),
   ('Siemens', ['SIE'], ['EMR','HON','GE','JCI','ROK']),
 ]),
 ('Trucks & Elevators', [
   ('Daimler Truck & Traton', ['DTG','8TRA'], ['CMI','PCAR']),
   ('Paccar', ['PCAR'], ['CMI','OSK']),
   ('Volvo', ['VOLVB'], ['CMI','DE','PCAR']),
   ('Kone & Schindler', ['KNEBV','SCHP'], ['JCI','OTIS']),
   ('Otis', ['OTIS'], ['JCI','CARR']),
 ]),
 ('UK Industrials', [
   ('Halma', ['HLMA'], ['COHR','FN','LITE','AME']),
   ('IMI', ['IMI'], ['WTS','EMR','BMI','FLS','CR']),
   ('Rotork', ['ROR'], ['EMR','ITT','FLS','CR']),
   ('Smiths Group', ['SMIN'], ['LII','CARR','EMR','FLS','CR']),
   ('Spirax Group', ['SPX'], ['DHR','IR','WTS','IEX']),
   ('Weir Group', ['WEIR'], ['ITT','KMT','CAT']),
 ]),
 ('Nordic Industrial Machinery', [
   ('Assa Abloy', ['ASSAB'], ['ALLE']),
   ('Atlas Copco', ['ATCOA'], ['AMAT','EBARA','IR','KLAC']),
   ('Epiroc', ['EPIA'], ['CAT']),
   ('Metso', ['METSO'], ['CAT','TEX']),
   ('Sandvik', ['SAND'], ['CAT','KMT']),
   ('SKF', ['SKFB'], ['NSK','NTN','TKR']),
 ]),
 ('Aerospace & Defence', [
   ('Rolls-Royce', ['RR'], ['GE','RTX','CMI','CAT']),
   ('Melrose Industries', ['MRO'], ['HWM','TDG','WWD','MOGA','HXL']),
 ]),
]

COVERAGE = sorted({k for _, groups in SUBGROUPS for _, cov, _ in groups for k in cov})
# config override: config/coverage_packs/capital_goods.yaml is the single
# source of truth when PyYAML is available; the literals above are the
# no-dependency fallback and are kept equivalent by tests.
try:
    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT))
    from src.utils.universe import load_universe as _lu
    _u = _lu()
    if _u:
        SEC, SUBGROUPS = _u['sec'], _u['subgroups']
except Exception:
    pass

ALL_KEYS = sorted({k for _, groups in SUBGROUPS for _, cov, peers in groups for k in cov+peers})
SEC_SCHEMA_US = {'ETN','ROK','GE','EMR','WAB','TT','GLW','FAST','WCC','VRT','HON','JCI','CMI','PCAR','DE','OTIS','CARR','COHR','FN','LITE','AME','WTS','FLS','CR','ITT','LII','DHR','IR','IEX','CAT','ALLE','AMAT','KLAC','RTX','HWM','TDG','WWD'}
DUAL_REV = {'VRT','FLS'}   # sec LTM revenue double-counted (two concepts) -> halve

def load(fn):
    p = os.path.join(RAW, fn)
    if not os.path.exists(p): return None
    return json.load(open(p))

def rowdicts(payload):
    if not payload or not payload.get('results'): return []
    cols = payload['columns']
    return [dict(zip(cols, r)) for r in payload['results']]

def f(x):
    try:
        if x is None or x == '': return None
        return float(x)
    except (TypeError, ValueError):
        return None

# ------------------------------------------------------------------- FX ---
FX = {}
for pair, fn in [('EURUSD','fx_EURUSD.json'), ('GBPUSD','fx_GBPUSD.json'),
                 ('CHFUSD','fx_CHFUSD.json'), ('SEKUSD','fx_SEKUSD.json'),
                 ('JPYUSD','fx_JPYUSD.json')]:
    d = load(fn)
    FX[pair] = {r['date']: f(r['close']) for r in rowdicts(d)} if d else {}

def fx_to_usd(ccy, dt=None):
    """Latest (or nearest historical) ccy->USD rate."""
    if ccy in ('USD',): return 1.0
    key = {'EUR':'EURUSD','GBP':'GBPUSD','GBp':'GBPUSD','CHF':'CHFUSD','SEK':'SEKUSD','JPY':'JPYUSD'}[ccy]
    series = FX[key]
    if not series: return None
    dates = sorted(series)
    if dt is None: return series[dates[-1]]
    prior = [d0 for d0 in dates if d0 <= dt]
    return series[prior[-1]] if prior else series[dates[0]]

FX_ASOF = max(max(v) for v in FX.values() if v)

def xrate(from_ccy, to_ccy, dt=None):
    if from_ccy == 'GBp':
        return 0.01 * xrate('GBP', to_ccy, dt)
    if to_ccy == 'GBp':
        return 100.0 * xrate(from_ccy, 'GBP', dt)
    if from_ccy == to_ccy: return 1.0
    a, b = fx_to_usd(from_ccy, dt), fx_to_usd(to_ccy, dt)
    return (a / b) if a and b else None

# --------------------------------------------------------------- prices ---
quotes, dailies, monthlies = {}, {}, {}
for k in ALL_KEYS:
    q = load(f'quote_{k}.json'); quotes[k] = rowdicts(q)[0] if q and q.get('results') else None
    d = load(f'daily_{k}.json')
    dailies[k] = sorted(((r['date'], f(r['close'])) for r in rowdicts(d)), reverse=True) if d else []
    m = load(f'monthly_{k}.json')
    monthlies[k] = sorted(((r['date'], f(r['close'])) for r in rowdicts(m)), reverse=True) if m else []

# --- canonical session-aware returns (src/features/returns.py) ----------
# Displayed price moves use the RAW basis (market convention); relative /
# momentum comparisons use the TOTAL-RETURN basis (dividends & special
# distributions are not price crashes). The old monthly-sampled px_return
# (partial-month anchor, days*1.45 stretch) is retired — see
# docs/price_data_audit.md for the root-cause report.
from src.features.returns import load_history as _load_hist, ret as _cret
_CHIST = _load_hist()

def px_return(k, days=None, months=None, basis='raw'):
    h = f'{days}D' if days is not None else f'{months}M'
    if h == '21D' or days == 5: h = '5D' if days == 5 else h
    r = _cret(k, h, basis, hist=_CHIST)
    return r['value'] if r['status'] == 'ok' else None

def px_return_tr(k, days=None, months=None):
    return px_return(k, days, months, basis='tr')

# correlations/betas run on the dense canonical TOTAL-RETURN series (economic
# co-movement; ~1250 sessions vs the old ~50 sampled rows)
for _k, _g in _CHIST.items():
    _tr = _g['close_tr'].where(_g['close_tr'].notna(), _g['close_raw'])
    dailies[_k] = list(zip(_g['session_date'].tolist()[::-1],
                           [float(x) for x in _tr.tolist()[::-1]]))

def _dnum(s):
    y, m, d = map(int, s.split('-')); return date(y, m, d).toordinal()

def _shift_months(s, k):
    y, m, d = map(int, s.split('-'))
    m2 = m + k; y += (m2 - 1) // 12; m2 = (m2 - 1) % 12 + 1
    return f'{y:04d}-{m2:02d}-01'

def logret_map(k, lookback_days):
    ser = dailies.get(k) or []
    cutoff = _dnum(ser[0][0]) - lookback_days if ser else 0
    out = {}
    for (d1, p1), (d0, p0) in zip(ser[:-1], ser[1:]):
        if _dnum(d1) < cutoff: break
        gap = _dnum(d1) - _dnum(d0)
        if p1 and p0 and gap <= 4:            # only near-adjacent sessions
            out[d1] = math.log(p1 / p0)
    return out

def corr(k1, k2, lookback):
    a, b = logret_map(k1, lookback), logret_map(k2, lookback)
    shared = sorted(set(a) & set(b))
    if len(shared) < 8: return None, len(shared)
    xs = [a[d] for d in shared]; ys = [b[d] for d in shared]
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
    return (num/den if den else None), len(shared)

def vol(k, lookback=90):
    r = list(logret_map(k, lookback).values())
    return st.pstdev(r) if len(r) >= 8 else None

# --------------------------------------------------- fundamentals (LTM) ---
sec_bs   = {r['ticker']: r for r in rowdicts(load('sec_bs_latest.json'))}
sec_ltm  = {r['ticker']: r for r in rowdicts(load('sec_ltm.json'))}
sec_ptx  = {r['ticker']: r for r in rowdicts(load('sec_ltm_pretax.json'))}
sec_rev  = {r['ticker']: r for r in rowdicts(load('sec_ltm_rev.json'))}
sec_a_ebit = {r['ticker']: r for r in rowdicts(load('sec_annual_ebit.json'))}
sec_a_rev  = {r['ticker']: r for r in rowdicts(load('sec_annual_rev.json'))}
sec_a_da   = {r['ticker']: r for r in rowdicts(load('sec_annual_da.json'))}
sec_a_ni   = {r['ticker']: r for r in rowdicts(load('sec_annual_ni.json'))}
SEC_TICK = {'MOGA':'MOG.A'}   # local key -> sec ticker

def g(row, key): return f(row.get(key)) if row else None

def _bs_parse(r):
    """Support both nested provider format and flat SEC-EDGAR format."""
    if 'assets.total_assets' in r or 'assets.current_assets.cash_and_cash_equivalents' in r:
        cash = g(r,'assets.current_assets.cash_and_cash_equivalents')
        if cash is None: cash = g(r,'assets.current_assets.cash')
        sti  = g(r,'assets.current_assets.other_short_term_investments') or 0
        std  = g(r,'liabilities.current_liabilities.short_term_debt')
        ltd  = g(r,'liabilities.non_current_liabilities.long_term_debt')
        mino = g(r,'shareholders_equity.minority_interest') or 0
        return cash, sti, std, ltd, mino
    cash = g(r,'cash') or g(r,'cash_and_st_investments')
    sti  = g(r,'short_term_investments') or 0
    std  = g(r,'short_term_debt'); ltd = g(r,'long_term_debt')
    return cash, sti, std, ltd, 0

def latest_bs_generic(k):
    """From bsq_/bsa_ provider payloads: cash, debt, minority.
    Prefers the most recent row that carries a long-term-debt figure."""
    rows = (rowdicts(load(f'bsq_{k}.json')) or []) + (rowdicts(load(f'bsa_{k}.json')) or [])
    rows = [r for r in rows if r.get('fiscal_date')]
    rows.sort(key=lambda r: str(r['fiscal_date']), reverse=True)
    best = best_any = None
    for r in rows[:8]:
        cash, sti, std, ltd, mino = _bs_parse(r)
        if cash is None and ltd is None and std is None: continue
        if best_any is None: best_any = (r, cash, sti, std, ltd, mino)
        if ltd is not None:
            best = (r, cash, sti, std, ltd, mino); break
    pick = best or best_any
    if not pick: return None
    r, cash, sti, std, ltd, mino = pick
    return dict(asof=r.get('fiscal_date'), cash=(cash or 0)+(sti or 0),
                debt=(std or 0)+(ltd or 0), minority=mino,
                ltd_missing=(ltd is None))

TODAY_ORD = date.today().toordinal()

def ltm_generic(k):
    """From isq_ (sum newest 4 consecutive quarters, recent) else isa_ newest year."""
    rows = rowdicts(load(f'isq_{k}.json'))
    rows = [r for r in rows if f(r.get('sales')) and r.get('fiscal_date')]
    rows.sort(key=lambda r: r['fiscal_date'], reverse=True)
    use = rows[:4]
    dates = [r['fiscal_date'] for r in use]
    ok = (len(use) == 4
          and TODAY_ORD - _dnum(dates[0]) < 200                    # newest quarter is fresh
          and 240 <= _dnum(dates[0]) - _dnum(dates[-1]) <= 310)    # 4 consecutive quarters
    if ok:
        def s(col):
            vals = [f(r.get(col)) for r in use]
            return sum(v for v in vals if v is not None) if any(v is not None for v in vals) else None
        return dict(basis='LTM (sum of 4 quarters)', asof=dates[0], rev=s('sales'),
                    ebit=s('operating_income'), ebitda=s('ebitda'), ni=s('net_income'),
                    ie=s('non_operating_interest.expense'),
                    sh=f(use[0].get('diluted_shares_outstanding')))
    a = rowdicts(load(f'isa_{k}.json'))
    a = [r for r in a if f(r.get('sales')) and r.get('fiscal_date')]
    a.sort(key=lambda r: r['fiscal_date'], reverse=True)
    if not a: return None
    r = a[0]
    sh = f(r.get('diluted_shares_outstanding'))
    if not sh:
        for r2 in a[1:]:
            sh = f(r2.get('diluted_shares_outstanding'))
            if sh: break
    return dict(basis='latest fiscal year', asof=r['fiscal_date'], rev=f(r.get('sales')),
                ebit=f(r.get('operating_income')), ebitda=f(r.get('ebitda')), ni=f(r.get('net_income')),
                ie=f(r.get('non_operating_interest.expense')), sh=sh)

def annual_hist_generic(k):
    """year -> dict(rev, ebit, ebitda, ni, sh, cash, debt)."""
    out = {}
    for r in rowdicts(load(f'isa_{k}.json')):
        fd = r.get('fiscal_date') or ''
        if not fd: continue
        yr = int(fd[:4])
        out.setdefault(yr, {}).update(rev=f(r.get('sales')), ebit=f(r.get('operating_income')),
            ebitda=f(r.get('ebitda')), ni=f(r.get('net_income')), sh=f(r.get('diluted_shares_outstanding')), asof=fd)
    for r in rowdicts(load(f'bsa_{k}.json')):
        fd = r.get('fiscal_date') or ''
        if not fd: continue
        yr = int(fd[:4])
        cash = (g(r,'assets.current_assets.cash_and_cash_equivalents') or g(r,'assets.current_assets.cash') or 0) + (g(r,'assets.current_assets.other_short_term_investments') or 0)
        debt = (g(r,'liabilities.current_liabilities.short_term_debt') or 0) + (g(r,'liabilities.non_current_liabilities.long_term_debt') or 0)
        out.setdefault(yr, {}).update(cash=cash, debt=debt, mino=g(r,'shareholders_equity.minority_interest') or 0)
    return out

def fcf_generic(k):
    rows = rowdicts(load(f'cfa_{k}.json'))
    rows = [r for r in rows if f(r.get('operating_activities.operating_cash_flow')) is not None]
    rows.sort(key=lambda r: r['fiscal_date'], reverse=True)
    if not rows: return None, None
    r = rows[0]
    fcf = f(r.get('free_cash_flow'))
    if fcf is None:
        ocf = f(r.get('operating_activities.operating_cash_flow'))
        capex = f(r.get('investing_activities.capital_expenditures')) or 0
        fcf = ocf - abs(capex) if ocf is not None else None
    return fcf, r['fiscal_date']

fund = {}
flags = {k: [] for k in ALL_KEYS}
for k in ALL_KEYS:
    tick = SEC_TICK.get(k, k)
    if k in {'MOGA'} or tick in SEC_SCHEMA_US:
        bs = sec_bs.get(tick); lt = sec_ltm.get(tick); rv = sec_rev.get(tick); ptx = sec_ptx.get(tick)
        rev = g(rv,'ltm_rev_raw')
        if rev is not None and tick in DUAL_REV:
            rev /= 2.0; flags[k].append('LTM revenue de-duplicated across two XBRL revenue concepts')
        ebit = g(lt,'ltm_ebit')
        if ebit is not None and g(lt,'n_ebit_q') is not None and g(lt,'n_ebit_q') < 4:
            ebit = None   # partial LTM -- reject
        da = g(lt,'ltm_da'); ni = g(lt,'ltm_ni')
        ie = g(lt,'ltm_int'); ocf = g(lt,'ltm_ocf'); capex = g(lt,'ltm_capex')
        gen_lt = ltm_generic(k); gen_bs = latest_bs_generic(k)
        if ebit is None and gen_lt and gen_lt.get('ebit') is not None:
            ebit = gen_lt['ebit']; flags[k].append('EBIT from provider statements (SEC XBRL gap)')
        if ebit is None and ptx and g(ptx,'n_ptx') == 4 and g(ptx,'ltm_pretax') is not None:
            ebit = g(ptx,'ltm_pretax') + (g(ptx,'ltm_int') or 0)
            flags[k].append('EBIT reconstructed as LTM pretax income + interest expense (approximate)')
        if da is None and ptx and g(ptx,'n_da') == 4:
            da = g(ptx,'ltm_da')
        if ni is None and ptx: ni = g(ptx,'ltm_ni')
        if ni is None and gen_lt: ni = gen_lt.get('ni')
        if rev is None and gen_lt: rev = gen_lt.get('rev')
        ebitda = (ebit + da) if (ebit is not None and da is not None) else (gen_lt.get('ebitda') if gen_lt else None)
        if ebitda is None and ebit is not None:
            ebitda = ebit; flags[k].append('EBITDA approximated by EBIT (no D&A reported)')
        cash = g(bs,'cash_and_st_investments') or g(bs,'cash')
        debt = (g(bs,'st_debt') or 0) + (g(bs,'lt_debt') or 0)
        sh = g(bs,'sh_diluted') or g(bs,'sh_out')
        if (cash is None or g(bs,'lt_debt') is None) and gen_bs:
            if cash is None and gen_bs['cash']: cash = gen_bs['cash']
            if g(bs,'lt_debt') is None and gen_bs['debt'] > debt: debt = gen_bs['debt']
            flags[k].append('cash/debt supplemented from provider balance sheet (SEC XBRL gap)')
        if cash is None:
            flags[k].append('cash unavailable -- net debt overstated'); cash = 0
        if debt == 0 and k not in ('FN',):
            flags[k].append('debt unavailable from XBRL -- EV may be understated')
        mino = (gen_bs or {}).get('minority', 0)
        fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
        if fcf is None:
            fcf, _ = fcf_generic(k)
        fund[k] = dict(rev=rev, ebit=ebit, ebitda=ebitda, ni=ni, ie=ie, cash=cash or 0,
                       debt=debt or 0, minority=mino or 0, sh=sh, fcf=fcf,
                       basis='LTM (sum of 4 quarters, SEC XBRL)', asof=str((lt or {}).get('latest_q') or ''))
    else:
        lt = ltm_generic(k); bs = latest_bs_generic(k); fcf, fcf_asof = fcf_generic(k)
        if not lt or not bs:
            flags[k].append('fundamentals unavailable'); fund[k] = None; continue
        if lt['basis'] != 'LTM (sum of 4 quarters)':
            flags[k].append('income statement uses latest fiscal year (interim quarters unavailable)')
        fund[k] = dict(rev=lt['rev'], ebit=lt['ebit'], ebitda=lt['ebitda'], ni=lt['ni'], ie=lt['ie'],
                       cash=bs['cash'], debt=bs['debt'], minority=bs['minority'], sh=lt['sh'],
                       fcf=fcf, basis=lt['basis'], asof=lt['asof'])

# shares override where diluted missing/stale — use quote-implied when absurd
for k in ALL_KEYS:
    if fund.get(k) and (fund[k]['sh'] is None or fund[k]['sh'] <= 0):
        flags[k].append('share count missing'); fund[k]['sh'] = None

# VISN structural flags
flags['VISN'] += ['recent IPO/carve-out: only ~18 months of trading history',
                  'statements show major restructuring (negative equity in 2024-25, large one-off tax items) — multiples flagged NM where distorted']
flags['GE'].append('GE Aerospace post three-way split (2023-24): pre-2024 history not comparable')
flags['CR'].append('provider CR line maps to Crane NXT after 2023 separation — treated as approximate proxy for Crane Co; history flagged')
flags['MRO'].append('Melrose 2023 Dowlais demerger: pre-2023 figures not comparable')
flags['ALO'].append('Alstom FY ends March; Bombardier Transportation acquired Jan 2021')
flags['SMIN'].append('Smiths FY ends July; latest FY income statement partially unreported in provider data')
flags['SPX'].append('quoted in GBp (pence); financials GBP')
for k in ('HLMA','IMI','ROR','SMIN','WEIR','RR','MRO'):
    flags[k].append('quoted in GBp (pence); financials GBP')
flags['ABBN'].append('trades in CHF, reports in USD — EV built in USD at spot CHF/USD')
for k in ('CAT','DE','PCAR','VOLVB','DTG','8TRA'):
    flags[k].append('captive finance operations: consolidated net debt includes financial-services funding — EV multiples not comparable with industrial-only definitions')

# --------------------------------------------------------- market values ---
mv = {}
for k in ALL_KEYS:
    q = quotes.get(k); fu = fund.get(k)
    if not q: mv[k] = None; continue
    px = f(q['close']); prev = f(q['previous_close'])
    qccy = SEC[k]['qccy']; rccy = SEC[k]['rccy']
    sh = fu['sh'] if fu else None
    mcap_q = px * sh if (px and sh) else None            # in quote ccy
    conv = xrate(qccy, rccy)
    mcap_r = mcap_q * conv if (mcap_q and conv) else None  # in report ccy
    mcap_usd = mcap_q * (xrate(qccy,'USD') or 0) if mcap_q else None
    ev_r = (mcap_r + fu['debt'] - fu['cash'] + fu['minority']) if (mcap_r is not None and fu) else None
    hi52 = f(q.get('fifty_two_week.high'));
    mv[k] = dict(px=px, prev=prev, chg1d=(px/prev-1 if px and prev else None),
                 mcap_r=mcap_r, mcap_usd=mcap_usd, ev_r=ev_r,
                 dd52=(px/hi52-1 if px and hi52 else None),
                 asof=q.get('datetime'))

def ratio(a, b, floor_frac=0.02):
    """NM when denominator missing, non-positive or tiny vs numerator."""
    if a is None or b is None or b <= 0: return None
    if abs(b) < abs(a) * floor_frac: return None
    return a / b

met = {}
for k in ALL_KEYS:
    fu, m = fund.get(k), mv.get(k)
    if not fu or not m or m['mcap_r'] is None:
        met[k] = None; continue
    ev = m['ev_r']
    nd = fu['debt'] - fu['cash']
    met[k] = dict(
        ev_ebitda=ratio(ev, fu['ebitda']), ev_ebit=ratio(ev, fu['ebit']),
        pe=ratio(m['mcap_r'], fu['ni']), ev_rev=ratio(ev, fu['rev'], 0.001),
        fcf_yield=(fu['fcf']/m['mcap_r'] if fu['fcf'] is not None and m['mcap_r'] else None),
        nd_ebitda=(nd/fu['ebitda'] if fu['ebitda'] and fu['ebitda']>0 else None),
        ebitda_margin=(fu['ebitda']/fu['rev'] if fu['ebitda'] and fu['rev'] else None),
        ebit_margin=(fu['ebit']/fu['rev'] if fu['ebit'] and fu['rev'] else None),
        int_cover=(fu['ebit']/fu['ie'] if fu['ebit'] and fu['ie'] and fu['ie']>0 else None),
        fcf_conv=(fu['fcf']/fu['ni'] if fu['fcf'] is not None and fu['ni'] and fu['ni']>0 else None),
        net_debt=nd,
    )
# VISN: distorted -> force NM on earnings multiples
if met.get('VISN'):
    met['VISN']['pe'] = None; met['VISN']['ev_ebitda'] = None; met['VISN']['ev_ebit'] = None
    met['VISN']['nd_ebitda'] = None

# growth & margin change from annual history (report ccy)
hist_fund = {}
for k in ALL_KEYS:
    tick = SEC_TICK.get(k, k)
    if tick in SEC_SCHEMA_US:
        h = {}
        for yr in range(2020, 2026):
            col = f'y{yr}'
            rev = g(sec_a_rev.get(tick), col); ebit = g(sec_a_ebit.get(tick), col)
            da = g(sec_a_da.get(tick), col); ni = g(sec_a_ni.get(tick), col)
            if rev is None and ebit is None: continue
            h[yr] = dict(rev=rev, ebit=ebit, ebitda=(ebit+da if ebit is not None and da is not None else None), ni=ni)
        gen = annual_hist_generic(k)
        for yr, d0 in gen.items():
            h.setdefault(yr, {}).update({kk:vv for kk,vv in d0.items() if h.get(yr,{}).get(kk) is None})
        hist_fund[k] = h
    else:
        hist_fund[k] = annual_hist_generic(k)

growth = {}
for k in ALL_KEYS:
    h = hist_fund.get(k) or {}
    yrs = sorted(y for y in h if h[y].get('rev'))
    gr = mg = eg = None
    if len(yrs) >= 2:
        y1, y0 = yrs[-1], yrs[-2]
        r1, r0 = h[y1].get('rev'), h[y0].get('rev')
        gr = r1/r0 - 1 if r1 and r0 else None
        e1, e0 = h[y1].get('ebitda'), h[y0].get('ebitda')
        eg = e1/e0 - 1 if e1 and e0 and e0 > 0 else None
        m1 = e1/r1 if e1 and r1 else None; m0 = e0/r0 if e0 and r0 else None
        mg = (m1 - m0) if m1 is not None and m0 is not None else None
    growth[k] = dict(rev_g=gr, ebitda_g=eg, margin_chg=mg)

# --------------------------------------------- historical valuation series ---
def year_end_price(k, yr):
    ser = monthlies.get(k) or []
    # prefer Dec of yr, else nearest month within +/-3 months
    cands = [(d0, p) for d0, p in ser if p]
    if not cands: return None
    target = _dnum(f'{yr}-12-01')
    best = min(cands, key=lambda r: abs(_dnum(r[0]) - target))
    if abs(_dnum(best[0]) - target) > 200: return None
    return best

val_hist = {}   # k -> list of (year, ev_ebitda)
for k in ALL_KEYS:
    h = hist_fund.get(k) or {}
    rows = []
    for yr in sorted(h):
        d0 = h[yr]
        e = d0.get('ebitda')
        sh = d0.get('sh') or (fund.get(k) or {}).get('sh')
        cash = d0.get('cash'); debt = d0.get('debt')
        if cash is None or debt is None:   # fall back to current net debt
            nd = (met.get(k) or {}).get('net_debt')
        else:
            nd = debt - cash
        pep = year_end_price(k, yr)
        if not (e and e > 0 and sh and pep and nd is not None): continue
        pd_, px = pep
        conv = xrate(SEC[k]['qccy'], SEC[k]['rccy'], pd_)
        if conv is None: continue
        ev = px * sh * conv + nd + (d0.get('mino') or 0)
        mult = ev / e
        if 0 < mult < 200: rows.append((yr, round(mult, 2)))
    val_hist[k] = rows

def hist_stats(k):
    rows = [m for _, m in (val_hist.get(k) or [])]
    cur = (met.get(k) or {}).get('ev_ebitda')
    if len(rows) < 3 or cur is None: return None
    med = st.median(rows); mean = st.mean(rows)
    lo, hi = min(rows), max(rows)
    q25 = st.quantiles(rows, n=4)[0] if len(rows) >= 4 else lo
    q75 = st.quantiles(rows, n=4)[2] if len(rows) >= 4 else hi
    pct = sum(1 for r in rows if r <= cur) / len(rows)
    sd = st.pstdev(rows)
    z = (cur - mean)/sd if sd else None
    return dict(median=med, mean=mean, q25=q25, q75=q75, min=lo, max=hi,
                pct=pct, z=z, prem_med=cur/med-1 if med else None, n=len(rows))

# --------------------------------------------------------- peer statistics ---
def peer_stats(metric_key, peers):
    vals = [(p, (met.get(p) or {}).get(metric_key)) for p in peers]
    vals = [(p, v) for p, v in vals if v is not None]
    if not vals: return None
    xs = sorted(v for _, v in vals)
    med = st.median(xs)
    q25 = st.quantiles(xs, n=4)[0] if len(xs) >= 4 else xs[0]
    q75 = st.quantiles(xs, n=4)[2] if len(xs) >= 4 else xs[-1]
    return dict(median=med, q25=q25, q75=q75, min=xs[0], max=xs[-1],
                n=len(xs), members={p: v for p, v in vals})

def pct_rank(x, xs):
    if x is None or not xs: return None
    return sum(1 for v in xs if v <= x) / len(xs)

# sector-wide (deduped) universe
sector_vals = {}
for mk in ('ev_ebitda','ev_ebit','pe','ev_rev','fcf_yield'):
    xs = [( k, (met.get(k) or {}).get(mk), (mv.get(k) or {}).get('mcap_usd')) for k in ALL_KEYS]
    xs = [(k, v, w or 0) for k, v, w in xs if v is not None]
    sector_vals[mk] = xs

def sector_median(mk, weighted=False):
    xs = sector_vals[mk]
    if not xs: return None
    if not weighted:
        return st.median([v for _, v, _ in xs])
    rows = sorted(xs, key=lambda r: r[1]); tot = sum(w for _,_,w in rows)
    run = 0
    for _, v, w in rows:
        run += w
        if run >= tot/2: return v
    return rows[-1][1]

# subgroup map for each key
sub_of = {}
group_of = {}
for sg, groups in SUBGROUPS:
    for disp, cov, peers in groups:
        for c in cov:
            sub_of[c] = sg; group_of[c] = disp

# ------------------------------------------------- market close read-across ---
def peer_move_stats(cov, peers):
    moves = [(p, (mv.get(p) or {}).get('chg1d')) for p in peers]
    moves = [(p, x) for p, x in moves if x is not None]
    if not moves: return None
    xs = [x for _, x in moves]
    eq = st.mean(xs); md = st.median(xs)
    # correlation-weighted (30d corr vs first coverage security)
    c0 = cov[0]
    ws, num = 0.0, 0.0
    contrib = []
    corr30_list = []
    for p, x in moves:
        c, n = corr(c0, p, 45)
        corr30_list.append(c)
        w = max(c or 0, 0)
        ws += w; num += w * x
        contrib.append((p, x, c, n))
    cw = num/ws if ws > 0 else None
    # beta-adjusted: beta = corr * vol(cov)/vol(peer)
    v0 = vol(c0)
    bnum, bws = 0.0, 0.0
    for p, x, c, n in contrib:
        vp = vol(p)
        if c is None or not vp or not v0: continue
        beta = c * v0 / vp
        bnum += beta * x; bws += 1
    beta_adj = bnum/bws if bws else None
    pos = sum(1 for x in xs if x > 0); neg = sum(1 for x in xs if x < 0)
    mx = max(moves, key=lambda r: r[1]); mn = min(moves, key=lambda r: r[1])
    c30s = [c for c in corr30_list if c is not None]
    return dict(eq=eq, median=md, cw=cw, beta_adj=beta_adj, pos=pos, neg=neg,
                best=mx, worst=mn, avg_corr30=(st.mean(c30s) if c30s else None),
                outlier=(abs(mx[1]) > 3*abs(md) + 0.02 if md is not None else False),
                contrib=contrib)

# ------------------------------------------------------------- classification ---
# Three SEPARATE state dimensions (valuation / fundamentals / price momentum)
# — never mixed into one ambiguous label. Combined only in screen presets.
# The old classify() mislabelled fundamental deterioration as "weakening
# momentum" and computed-but-ignored mom3; both defects are retired.
from src.features.momentum import momentum_state as _mom_state

def _peer_prem(k):
    m = met.get(k)
    for sg, groups in SUBGROUPS:
        for d2, cov, peers in groups:
            if k in cov:
                ps = peer_stats('ev_ebitda', peers)
                if ps and m and m.get('ev_ebitda'):
                    return m['ev_ebitda'] / ps['median'] - 1
    return None

def valuation_state(k):
    prem = _peer_prem(k)
    if prem is None: return 'insufficient data'
    if prem <= -0.30: return 'deep discount'
    if prem <= -0.10: return 'discount'
    if prem < 0.10:   return 'fair'
    if prem < 0.30:   return 'premium'
    return 'extreme premium'

def fundamental_state(k):
    gr = growth.get(k, {})
    if gr.get('rev_g') is None and gr.get('margin_chg') is None:
        return 'insufficient data'
    if (gr.get('rev_g') or 0) < 0 or (gr.get('margin_chg') or 0) < -0.01:
        return 'deteriorating'
    if (gr.get('rev_g') or 0) > 0.03 and (gr.get('margin_chg') or 0) >= 0:
        return 'improving'
    return 'stable'

_MOMO = {}
def momentum_state_of(k):
    if k not in _MOMO:
        try:
            _MOMO[k] = _mom_state(k, _CHIST)[0].replace('_', ' ')
        except Exception:
            _MOMO[k] = 'indeterminate'
    return _MOMO[k]

# ------------------------------------------------------------------ output ---
def r2(x, n=2): return None if x is None else round(x, n)
def pctf(x, n=1): return None if x is None else round(100*x, n)

rows_screener = []
rows_close = []
close_groups = []
drill = {}

for sg, groups in SUBGROUPS:
    for disp, cov, peers in groups:
        pm = peer_move_stats(cov, peers)
        ps_basket = {mk: peer_stats(mk, peers) for mk in ('ev_ebitda','ev_ebit','pe','ev_rev','fcf_yield')}
        grp = dict(subgroup=sg, group=disp, coverage=cov, peers=peers,
                   stats=None if not pm else dict(
                       eq=pctf(pm['eq'],2), median=pctf(pm['median'],2), cw=pctf(pm['cw'],2),
                       beta_adj=pctf(pm['beta_adj'],2), pos=pm['pos'], neg=pm['neg'],
                       best=[pm['best'][0], pctf(pm['best'][1],2)],
                       worst=[pm['worst'][0], pctf(pm['worst'][1],2)],
                       avg_corr30=r2(pm['avg_corr30']), outlier=pm['outlier']))
        close_groups.append(grp)
        for role, ks in (('coverage', cov), ('peer', peers)):
            for k in ks:
                m = mv.get(k) or {}
                c30, n30 = corr(cov[0], k, 45) if k not in cov else (None, None)
                c90, n90 = corr(cov[0], k, 130) if k not in cov else (None, None)
                rel = None
                if role == 'peer' and pm and m.get('chg1d') is not None and pm['eq'] is not None:
                    rel = m['chg1d'] - pm['eq']
                rows_close.append(dict(subgroup=sg, coverage_group=disp, role=role, key=k,
                    company=SEC[k]['name'], ticker=SEC[k]['sym'], ccy=SEC[k]['qccy'],
                    close_px=r2(m.get('px'),2), prev_close=r2(m.get('prev'),2),
                    move_1d_pct=pctf(m.get('chg1d'),2),
                    move_5d_pct=pctf(px_return(k, days=5),2),
                    move_1m_pct=pctf(px_return(k, months=1),2),
                    move_3m_pct=pctf(px_return(k, months=3),2),
                    move_6m_pct=pctf(px_return(k, months=6),2),
                    move_12m_pct=pctf(px_return(k, months=12),2),
                    corr30=r2(c30), corr30_nobs=n30, corr90=r2(c90), corr90_nobs=n90,
                    rel_vs_basket_pct=pctf(rel,2),
                    big_move=abs(m.get('chg1d') or 0) > 0.03,
                    quote_time=m.get('asof')))

seen = set()
sector_med_eq = sector_median('ev_ebitda', False)
sector_med_w  = sector_median('ev_ebitda', True)
for sg, groups in SUBGROUPS:
    for disp, cov, peers in groups:
        for k in cov:
            if k in seen: continue
            seen.add(k)
            m = met.get(k) or {}; f_ = fund.get(k) or {}; v = mv.get(k) or {}
            ps = peer_stats('ev_ebitda', peers)
            hs = hist_stats(k)
            prem_peers = (m.get('ev_ebitda')/ps['median']-1) if ps and m.get('ev_ebitda') else None
            prem_sector = (m.get('ev_ebitda')/sector_med_eq-1) if sector_med_eq and m.get('ev_ebitda') else None
            g_ = growth.get(k, {})
            rows_screener.append(dict(
                subgroup=sg, coverage_group=disp, key=k, company=SEC[k]['name'], ticker=SEC[k]['sym'],
                price=r2(v.get('px'),2), quote_ccy=SEC[k]['qccy'], report_ccy=SEC[k]['rccy'],
                mcap_usd_bn=r2((v.get('mcap_usd') or 0)/1e9,2) if v.get('mcap_usd') else None,
                ev_report_ccy_bn=r2((v.get('ev_r') or 0)/1e9,2) if v.get('ev_r') else None,
                estimate_basis='LTM reported fallback',
                ev_ebitda_ltm=r2(m.get('ev_ebitda')), ev_ebit_ltm=r2(m.get('ev_ebit')),
                pe_ltm=r2(m.get('pe')), ev_rev_ltm=r2(m.get('ev_rev')),
                fcf_yield_pct=pctf(m.get('fcf_yield')),
                peer_median_ev_ebitda=r2(ps['median']) if ps else None,
                prem_disc_vs_peers_pct=pctf(prem_peers),
                sector_median_ev_ebitda=r2(sector_med_eq),
                prem_disc_vs_sector_pct=pctf(prem_sector),
                hist_median_ev_ebitda=r2(hs['median']) if hs else None,
                hist_percentile=pctf(hs['pct']) if hs else None,
                hist_zscore=r2(hs['z']) if hs else None,
                hist_years=hs['n'] if hs else None,
                rev_growth_pct=pctf(g_.get('rev_g')), ebitda_growth_pct=pctf(g_.get('ebitda_g')),
                ebitda_margin_pct=pctf(m.get('ebitda_margin')),
                margin_chg_pp=pctf(g_.get('margin_chg')),
                fcf_conversion=r2(m.get('fcf_conv')),
                nd_ebitda=r2(m.get('nd_ebitda')), interest_cover=r2(m.get('int_cover')),
                rel_1m_pct=pctf((px_return_tr(k,months=1) or 0) - (st.mean([px_return_tr(p,months=1) for p in peers if px_return_tr(p,months=1) is not None]) if any(px_return_tr(p,months=1) is not None for p in peers) else 0),2),
                rel_3m_pct=pctf((px_return_tr(k,months=3) or 0) - (st.mean([px_return_tr(p,months=3) for p in peers if px_return_tr(p,months=3) is not None]) if any(px_return_tr(p,months=3) is not None for p in peers) else 0),2),
                rel_12m_pct=pctf((px_return_tr(k,months=12) or 0) - (st.mean([px_return_tr(p,months=12) for p in peers if px_return_tr(p,months=12) is not None]) if any(px_return_tr(p,months=12) is not None for p in peers) else 0),2),
                drawdown_52w_pct=pctf(v.get('dd52')),
                valuation_state=valuation_state(k),
                fundamental_state=fundamental_state(k),
                momentum_state=momentum_state_of(k),
                classification=f'{valuation_state(k)} · {fundamental_state(k)} fundamentals',
                data_quality='; '.join(flags.get(k) or []) or 'OK',
            ))
            from src.features.momentum import full_momentum as _fm
            try:
                _momo = _fm(k, peers, _CHIST)
            except Exception:
                _momo = dict(momentum_state='indeterminate')
            _ret_detail = {}
            for _h in ('1D','5D','21D','63D','126D','252D','1M','3M','6M','12M'):
                for _b in ('raw','tr'):
                    _r = _cret(k, _h, _b, hist=_CHIST)
                    if _r['status'] == 'ok':
                        _ret_detail[f'{_h}_{_b}'] = dict(
                            pct=round(_r['value']*100,2), start=_r['start_date'],
                            end=_r['end_date'], sessions=_r['n_sessions'])
            drill[k] = dict(
                momentum=_momo, returns_detail=_ret_detail,
                name=SEC[k]['name'], ticker=SEC[k]['sym'], group=disp, subgroup=sg, peers=peers,
                fund={kk: f_.get(kk) for kk in ('rev','ebit','ebitda','ni','fcf','cash','debt','minority','sh','basis','asof')},
                metrics={kk: m.get(kk) for kk in m} if m else {},
                hist=val_hist.get(k) or [], hist_stats=hs,
                peer_multiples=(ps or {}).get('members') if ps else {},
                flags=flags.get(k) or [])

# scenarios (coverage only)
rows_scen = []
for row in rows_screener:
    k = row['key']; m = met.get(k) or {}; f_ = fund.get(k) or {}; v = mv.get(k) or {}
    base_e = f_.get('ebitda'); mult = m.get('ev_ebitda'); sh = f_.get('sh'); nd = m.get('net_debt')
    if not (base_e and mult and sh and v.get('px')): continue
    ps = None
    for sg, groups in SUBGROUPS:
        for disp, cov, peers in groups:
            if k in cov: ps = peer_stats('ev_ebitda', peers)
    hs = hist_stats(k)
    conv = xrate(SEC[k]['rccy'], SEC[k]['qccy'])
    def scen(name, e_mult, target_mult):
        e = base_e * e_mult
        ev = target_mult * e
        eq = ev - nd - f_.get('minority', 0)
        px = eq / sh * conv
        ret = px / v['px'] - 1
        # bridge (equity-level, additive): earnings effect = ΔEBITDA at constant
        # multiple / current equity; multiple effect = Δmultiple at new EBITDA /
        # current equity. earn + mult == implied return exactly (nd, shares const).
        ev0 = mult * base_e
        eq0 = ev0 - nd - f_.get('minority', 0)
        earn_fx = (mult * (e - base_e)) / eq0 if eq0 else None
        mult_fx = ((target_mult - mult) * e) / eq0 if eq0 else None
        return dict(key=k, company=SEC[k]['name'], scenario=name,
                    ebitda_report_ccy=round(e/1e6,1), target_multiple=r2(target_mult),
                    implied_ev_bn=r2(ev/1e9), net_debt_bn=r2(nd/1e9),
                    implied_price=r2(px,2), current_price=r2(v['px'],2),
                    implied_return_pct=pctf(ret),
                    earnings_effect_pct=pctf(earn_fx),
                    multiple_effect_pct=pctf(mult_fx),
                    note='Mechanical valuation scenario, not a price target')
    rows_scen.append(scen('Bear (-10% EBITDA, peer Q1)', 0.9, (ps['q25'] if ps else mult*0.85)))
    rows_scen.append(scen('Base (LTM EBITDA, current multiple)', 1.0, mult))
    rows_scen.append(scen('Bull (+10% EBITDA, peer Q3)', 1.1, (ps['q75'] if ps else mult*1.15)))
    rows_scen.append(scen('Rerate to peer median', 1.0, (ps['median'] if ps else mult)))
    rows_scen.append(scen('Rerate to sector median', 1.0, sector_med_eq or mult))
    if hs: rows_scen.append(scen('Rerate to own 5y median', 1.0, hs['median']))

# security mapping csv
rows_map = []
for k in ALL_KEYS:
    q = quotes.get(k) or {}
    conf = 'high'
    amb = ''
    if k == 'VISN': conf, amb = 'high', 'Resolved via provider symbol search: Vistance Networks Inc, NASDAQ/XNGS. Fundamentals heavily distorted by restructuring — treat multiples as NM.'
    if k == 'CR': conf, amb = 'medium', 'Provider CR line carries Crane NXT statements post-2023 split; used as approximate proxy for Crane Co.'
    if k == 'EPIA': amb = 'LSE secondary line has no fundamentals; statements from OTC line EPIAF (same issuer).'
    if k in ('VOLVB','ASSAB','ATCOA','SAND','SKFB','METSO','KNEBV','EPIA'):
        amb = (amb + ' ' if amb else '') + 'Priced via LSE international order book line (SEK/EUR native prices; identical issuer).'
    rows_map.append(dict(requested=SEC[k]['name'], resolved=q.get('name') or SEC[k]['name'],
        key=k, bbg_style_ticker=SEC[k]['sym'], provider_symbol=q.get('symbol'),
        exchange=q.get('exchange') or SEC[k]['exch'], mic=q.get('mic_code'),
        currency=q.get('currency') or SEC[k]['qccy'], confidence=conf, notes=amb))

# valuation history csv
rows_hist = []
for k in ALL_KEYS:
    for yr, mult in (val_hist.get(k) or []):
        rows_hist.append(dict(key=k, company=SEC[k]['name'], year=yr, ev_ebitda=mult,
                              basis='fiscal-year fundamentals × year-end price (approximate, no consensus)'))

def write_csv(path, rows):
    if not rows: return
    keys = list(rows[0].keys())
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader()
        for r in rows: w.writerow(r)

write_csv(os.path.join(ROOT,'capital_goods_screener.csv'), rows_screener)
write_csv(os.path.join(ROOT,'capital_goods_market_close.csv'), rows_close)
write_csv(os.path.join(ROOT,'capital_goods_valuation_history.csv'), rows_hist)
write_csv(os.path.join(ROOT,'capital_goods_scenarios.csv'), rows_scen)
write_csv(os.path.join(ROOT,'capital_goods_security_mapping.csv'), rows_map)

# dashboard payload
dash = dict(
    generated=max((q.get('datetime') or '' for q in quotes.values() if q), default=str(date.today())),
    fx_asof=FX_ASOF,
    sector_median_ev_ebitda=r2(sector_med_eq), sector_median_ev_ebitda_mcap_weighted=r2(sector_med_w),
    subgroups=[dict(name=sg, groups=[dict(display=d, coverage=c, peers=p) for d,c,p in gs]) for sg,gs in SUBGROUPS],
    close_rows=rows_close, close_groups=close_groups,
    screener=rows_screener, scenarios=rows_scen, mapping=rows_map,
    hist=rows_hist, drill=drill,
    monthlies={k:[[d0,p] for d0,p in (monthlies.get(k) or [])][:75] for k in COVERAGE},
    names={k: SEC[k]['name'] for k in ALL_KEYS},
    tickers={k: SEC[k]['sym'] for k in ALL_KEYS},
    all_metrics={k: {kk: (met.get(k) or {}).get(kk) for kk in
                     ('ev_ebitda','ev_ebit','pe','ev_rev','fcf_yield','ebitda_margin','nd_ebitda')}
                 for k in ALL_KEYS},
)
json.dump(dash, open(os.path.join(OUT,'dashboard_data.json'),'w'), default=str)
print('screener rows:', len(rows_screener))
print('close rows:', len(rows_close))
print('scenario rows:', len(rows_scen))
print('hist rows:', len(rows_hist))
print('sector median EV/EBITDA (eq/mcap):', r2(sector_med_eq), r2(sector_med_w))
for r in rows_screener:
    print(f"{r['key']:6s} {str(r['ev_ebitda_ltm']):>7} x  prem={str(r['prem_disc_vs_peers_pct']):>7}%  {r['valuation_state']:>15s} | {r['fundamental_state']:>13s} | {r['momentum_state']}")
