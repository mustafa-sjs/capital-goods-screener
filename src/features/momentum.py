"""EWMA momentum & inflection engine on the canonical total-return series.

EMA settings (documented in docs/momentum_methodology.md):
  pandas .ewm(span=N, adjust=False, min_periods=N) — recursive EMA; no
  signal is produced until a full span of observations exists. Missing
  sessions are simply absent rows (each security's own trading calendar);
  no forward-fill across halts.

Pairs: (10,30), (20,60), (50,200) sessions. All *descriptive* — no
predictive claim until point-in-time backtesting exists (see methodology).

Momentum states (explicit rules, evaluated on the tr series):
  emerging_positive_inflection : fast crossed above slow within the last 15
      sessions AND gap slope (5-session) > 0
  established_uptrend          : fast > slow for > 15 sessions AND price >
      slow EMA AND 63D return > 0
  fading_uptrend               : fast > slow AND gap narrowing (slope < 0)
      AND gap acceleration < 0
  emerging_breakdown           : fast crossed below slow within 15 sessions
      AND gap slope < 0
  established_downtrend        : fast < slow for > 15 sessions AND 63D < 0
  indeterminate                : anything else / insufficient data
State uses the 20/60 pair by default (medium horizon).
"""
import numpy as np
import pandas as pd

from .returns import load_history, ret_pct

PAIRS = [(10, 30), (20, 60), (50, 200)]


def ema_metrics(key, hist=None, pair=(20, 60)):
    h = (hist or load_history()).get(key)
    fast_n, slow_n = pair
    out = dict(pair=f'{fast_n}/{slow_n}', status='insufficient_data')
    if h is None or len(h) < slow_n + 10:
        return out
    px = pd.Series(h['close_tr'].values, dtype='float64')
    if px.isna().all():
        px = pd.Series(h['close_raw'].values, dtype='float64')
        out['basis'] = 'raw (tr unavailable)'
    fast = px.ewm(span=fast_n, adjust=False, min_periods=fast_n).mean()
    slow = px.ewm(span=slow_n, adjust=False, min_periods=slow_n).mean()
    gap = (fast / slow - 1.0) * 100
    valid = gap.dropna()
    if len(valid) < 30:
        return out
    above = (fast > slow).astype(int)
    flips = above.diff().fillna(0)
    cross_idx = flips[flips != 0].index
    last_cross = cross_idx[-1] if len(cross_idx) else None
    sessions_since = (int(len(px) - 1 - last_cross)) if last_cross is not None else None
    g = gap.iloc[-1]
    slope5 = gap.iloc[-1] - gap.iloc[-6] if len(valid) > 6 else None
    slope5_prev = gap.iloc[-6] - gap.iloc[-11] if len(valid) > 11 else None
    accel = (slope5 - slope5_prev) if None not in (slope5, slope5_prev) else None
    pct_rank = float((valid < g).mean() * 100)
    z = float((g - valid.mean()) / valid.std()) if valid.std() else None
    out.update(status='ok',
               fast=round(float(fast.iloc[-1]), 4),
               slow=round(float(slow.iloc[-1]), 4),
               gap_pct=round(float(g), 2),
               state='bullish' if g > 0 else 'bearish',
               cross_date=(h['session_date'].iloc[last_cross]
                           if last_cross is not None else None),
               sessions_since_cross=sessions_since,
               gap_slope_5s=round(float(slope5), 3) if slope5 is not None else None,
               gap_accel=round(float(accel), 3) if accel is not None else None,
               gap_percentile=round(pct_rank, 1),
               gap_zscore=round(z, 2) if z is not None else None,
               price_above_slow=bool(px.iloc[-1] > slow.iloc[-1]))
    return out


def momentum_state(key, hist=None):
    m = ema_metrics(key, hist, pair=(20, 60))
    if m.get('status') != 'ok':
        return 'indeterminate', m
    r63 = ret_pct(key, '63D', 'tr', hist=hist)
    recent = (m['sessions_since_cross'] is not None
              and m['sessions_since_cross'] <= 15)
    slope = m.get('gap_slope_5s')
    accel = m.get('gap_accel')
    if m['state'] == 'bullish':
        if recent and slope is not None and slope > 0:
            return 'emerging_positive_inflection', m
        if slope is not None and slope < 0 and accel is not None and accel < 0:
            return 'fading_uptrend', m
        if not recent and m['price_above_slow'] and (r63 or 0) > 0:
            return 'established_uptrend', m
    else:
        if recent and slope is not None and slope < 0:
            return 'emerging_breakdown', m
        if not recent and (r63 or 0) < 0:
            return 'established_downtrend', m
    return 'indeterminate', m


def risk_metrics(key, hist=None):
    h = (hist or load_history()).get(key)
    if h is None or len(h) < 70:
        return {}
    px = pd.Series(h['close_tr'].values, dtype='float64').dropna()
    if len(px) < 70:
        return {}
    lr = np.log(px / px.shift(1)).dropna()
    ann = np.sqrt(252) * 100
    hi252 = px.tail(252).max()
    dd = px.iloc[-1] / hi252 - 1
    run_max = px.cummax()
    maxdd = float((px / run_max - 1).min())
    return dict(ewvol_20d_pct=round(float(lr.ewm(span=20, adjust=False)
                                          .std().iloc[-1] * ann), 1),
                ewvol_60d_pct=round(float(lr.ewm(span=60, adjust=False)
                                          .std().iloc[-1] * ann), 1),
                drawdown_52w_pct=round(float(dd) * 100, 1),
                max_drawdown_pct=round(maxdd * 100, 1))


def full_momentum(key, peers=None, hist=None):
    """Everything the screener/drilldown needs for one security."""
    hist = hist or load_history()
    state, m2060 = momentum_state(key, hist)
    rows = {f'ema_{a}_{b}': ema_metrics(key, hist, (a, b)) for a, b in PAIRS}
    abs_mom = {h: ret_pct(key, h, 'tr', hist=hist)
               for h in ('21D', '63D', '126D', '252D')}
    # Fama-French style 12-1: TR return from 252 to 21 sessions ago
    r252, r21 = abs_mom.get('252D'), abs_mom.get('21D')
    mom_12_1 = (round(((1 + r252 / 100) / (1 + r21 / 100) - 1) * 100, 2)
                if None not in (r252, r21) else None)
    rel = {}
    if peers:
        for h in ('21D', '63D'):
            own = abs_mom.get(h)
            pr = [ret_pct(p, h, 'tr', hist=hist) for p in peers]
            pr = [x for x in pr if x is not None]
            if own is not None and pr:
                rel[f'rel_{h}_vs_eq'] = round(own - sum(pr) / len(pr), 2)
                rel[f'rel_{h}_vs_med'] = round(
                    own - sorted(pr)[len(pr) // 2], 2)
    bullish = [r for r in rows.values() if r.get('status') == 'ok']
    trend_strength = (round(100 * sum(1 for r in bullish
                                      if r['state'] == 'bullish')
                            / len(bullish), 0) if bullish else None)
    pos_h = [v for v in abs_mom.values() if v is not None]
    return dict(momentum_state=state, ema=rows, abs_momentum=abs_mom,
                mom_12_1_pct=mom_12_1, relative=rel,
                trend_strength_pct=trend_strength,
                pct_horizons_positive=(round(100 * sum(1 for v in pos_h if v > 0)
                                             / len(pos_h), 0) if pos_h else None),
                risk=risk_metrics(key, hist),
                validation_status='descriptive — not backtested')


# ===== v2.5 additions: config-driven series primitives for the backtest =====
import os as _os

_CFG = {}


def momentum_config():
    if not _CFG:
        import yaml
        p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(
            _os.path.abspath(__file__)))), 'config', 'momentum.yaml')
        _CFG.update(yaml.safe_load(open(p)))
    return _CFG


def ewma(px, span):
    """The one true EWMA: recursive, full-span warm-up."""
    return px.ewm(span=span, adjust=False, min_periods=span).mean()


def cross_series(px, fast_n, slow_n):
    """Per-session state & crossover events for one price series.

    Returns DataFrame(state: +1 bullish / -1 bearish / 0 warm-up,
                      cross: +1 bullish crossover, -1 bearish crossover, 0 none)
    A crossover requires fast>slow now AND fast<=slow on the PREVIOUS valid
    observation (never 'every day above slow is a new signal').
    """
    fast, slow = ewma(px, fast_n), ewma(px, slow_n)
    state = pd.Series(0, index=px.index, dtype='int64')
    valid = fast.notna() & slow.notna()
    state[valid & (fast > slow)] = 1
    state[valid & (fast <= slow)] = -1
    prev = state.shift(1).fillna(0)
    cross = pd.Series(0, index=px.index, dtype='int64')
    cross[(state == 1) & (prev == -1)] = 1
    cross[(state == -1) & (prev == 1)] = -1
    return pd.DataFrame({'state': state, 'cross': cross,
                         'fast': fast, 'slow': slow})


def pair_features(key, pair, hist=None):
    """Current-signal block for one security & pair (screener/heatmap-ready)."""
    h = (hist or load_history()).get(key)
    fast_n, slow_n = pair
    if h is None or len(h) < slow_n + 10:
        return dict(status='insufficient_data', pair=f'{fast_n}/{slow_n}')
    px = pd.Series(h['close_tr'].values, dtype='float64')
    px.index = range(len(px))
    cs = cross_series(px, fast_n, slow_n)
    if cs['state'].iloc[-1] == 0:
        return dict(status='warm_up', pair=f'{fast_n}/{slow_n}')
    crosses = cs.index[cs['cross'] != 0]
    last_x = crosses[-1] if len(crosses) else None
    spread = (cs['fast'].iloc[-1] / cs['slow'].iloc[-1] - 1) * 100
    slope = lambda s, n: ((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100
                          if len(s.dropna()) > n and s.iloc[-1 - n] else None)
    spread_ser = (cs['fast'] / cs['slow'] - 1) * 100
    # 5-session change in the |fast-slow| distance (pp): the basis for the
    # user-facing "Momentum change" (strengthening / stable / weakening)
    dist_chg = (round(float(abs(spread_ser.iloc[-1]) - abs(spread_ser.iloc[-6])), 3)
                if len(spread_ser.dropna()) > 6 else None)
    accel = None
    sl5, sl5p = slope(spread_ser + 100, 5), None
    if len(spread_ser.dropna()) > 11:
        sl5p = ((spread_ser.iloc[-6] + 100) / (spread_ser.iloc[-11] + 100) - 1) * 100
    if None not in (sl5, sl5p):
        accel = round(sl5 - sl5p, 3)
    return dict(status='ok', pair=f'{fast_n}/{slow_n}',
                signal='bullish' if cs['state'].iloc[-1] == 1 else 'bearish',
                spread_pct=round(float(spread), 2),
                fast_slope_5s=slope(cs['fast'], 5),
                slow_slope_5s=slope(cs['slow'], 5),
                spread_slope_5s=(round(sl5, 3) if sl5 is not None else None),
                dist_chg_5s=dist_chg,
                acceleration=accel,
                cross_date=(h['session_date'].iloc[last_x] if last_x is not None else None),
                cross_type=('bullish' if last_x is not None and cs['cross'][last_x] == 1
                            else ('bearish' if last_x is not None else None)),
                sessions_since_cross=(int(len(px) - 1 - last_x)
                                      if last_x is not None else None),
                dist_52w_high_pct=round(float(px.iloc[-1] / px.tail(252).max() - 1) * 100, 1),
                dist_52w_low_pct=round(float(px.iloc[-1] / px.tail(252).min() - 1) * 100, 1))


# ---- user-facing trend fields (ONE definition, used by every page) ---------
TREND_UP, TREND_DOWN, TREND_NONE = 'Uptrend', 'Downtrend', 'No clear trend'
CHG_STRONGER, CHG_STABLE, CHG_WEAKER = 'Strengthening', 'Stable', 'Weakening'
SIG_POS, SIG_NEG, SIG_NONE = ('New positive crossover',
                              'New negative crossover', 'No recent crossover')
RECENT_SESSIONS = 15        # "recent" window for a new crossover
DIST_CHG_BAND = 0.10        # |distance change| below this (pp/5s) = Stable


def simple_momentum_fields(pf, recent_sessions=RECENT_SESSIONS):
    """Translate one pair_features() block into the three fields every page
    shows: Trend, Momentum change, Recent signal.

      Trend           : fast EWMA above (Uptrend) or below (Downtrend) the
                        slow EWMA; warm-up / no data -> No clear trend.
      Momentum change : the |fast - slow| distance widening (Strengthening),
                        narrowing (Weakening) or flat (Stable) over the last
                        5 sessions.
      Recent signal   : a crossover within the recent window whose direction
                        still holds today; otherwise no recent crossover.
    """
    if not pf or pf.get('status') != 'ok':
        return dict(trend=TREND_NONE, momentum_change=None,
                    recent_signal=None)
    trend = TREND_UP if pf['signal'] == 'bullish' else TREND_DOWN
    dc = pf.get('dist_chg_5s')
    if dc is None:
        chg = CHG_STABLE
    elif dc > DIST_CHG_BAND:
        chg = CHG_STRONGER
    elif dc < -DIST_CHG_BAND:
        chg = CHG_WEAKER
    else:
        chg = CHG_STABLE
    sig = SIG_NONE
    ssc = pf.get('sessions_since_cross')
    if (ssc is not None and ssc <= recent_sessions
            and pf.get('cross_type') == pf['signal']):
        sig = SIG_POS if pf['cross_type'] == 'bullish' else SIG_NEG
    return dict(trend=trend, momentum_change=chg, recent_signal=sig)
