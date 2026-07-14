"""Central user-facing metric dictionary.

Every table, chart, filter and tooltip in the app resolves display labels
through this registry, so the same metric is never described two ways and
no internal column name (rel_3m_pct, hist_zscore, ...) reaches the screen.

Each entry:
  display_name : full label used in tables and filters
  short_name   : compact label where space is tight (defaults to display)
  description  : plain-English definition (tooltip text)
  format       : one of 'pct_signed' (+1.2%), 'pct' (1.2%), 'pp' (+1.2pp),
                 'mult' (12.3x), 'num', 'price', 'usd_bn', 'percentile',
                 'int', 'text', 'date'
  category     : 'identity' | 'valuation' | 'fundamentals' | 'performance'
                 | 'trend' | 'risk' | 'quality'
  higher_means : 'better' | 'worse' | 'more_expensive' | 'cheaper' | 'neutral'
  missing      : what to show when the value is unavailable
"""

MISSING = 'Not available'


def _m(display_name, description, fmt, category, higher_means='neutral',
       short_name=None, missing=MISSING):
    return dict(display_name=display_name, short_name=short_name or display_name,
                description=description, format=fmt, category=category,
                higher_means=higher_means, missing=missing)


METRIC_DEFINITIONS = {
    # ---- identity ----------------------------------------------------------
    'company': _m('Company', 'Company name.', 'text', 'identity'),
    'ticker': _m('Ticker', 'Primary listing ticker.', 'text', 'identity'),
    'subgroup': _m('Subgroup', 'Capital-goods subgroup this company belongs to.',
                   'text', 'identity'),
    'coverage_group': _m('Peer basket',
                         'The coverage group whose direct peers this company '
                         'is compared against.', 'text', 'identity'),
    'price': _m('Price', 'Latest available share price in the quote currency.',
                'price', 'identity'),
    'quote_ccy': _m('Currency', 'Quote currency of the primary listing.',
                    'text', 'identity', short_name='Ccy'),
    'mcap_usd_bn': _m('Market cap ($bn)',
                      'Market capitalisation converted to US dollars.',
                      'usd_bn', 'identity', short_name='Mcap $bn'),

    # ---- valuation ---------------------------------------------------------
    'ev_ebitda_ltm': _m('EV/EBITDA',
                        'Enterprise value divided by EBITDA, both from the '
                        'latest reported financials.', 'mult', 'valuation',
                        'more_expensive'),
    'ev_ebit_ltm': _m('EV/EBIT',
                      'Enterprise value divided by operating profit from the '
                      'latest reported financials.', 'mult', 'valuation',
                      'more_expensive'),
    'pe_ltm': _m('P/E', 'Share price divided by reported earnings per share.',
                 'mult', 'valuation', 'more_expensive'),
    'ev_rev_ltm': _m('EV/Revenue',
                     'Enterprise value divided by reported revenue.', 'mult',
                     'valuation', 'more_expensive', short_name='EV/Rev'),
    'fcf_yield_pct': _m('FCF yield',
                        'Free cash flow as a percentage of market '
                        'capitalisation. Higher means more cash generated per '
                        'unit of market value.', 'pct', 'valuation', 'cheaper'),
    'peer_median_ev_ebitda': _m('Direct-peer median EV/EBITDA',
                                'Median EV/EBITDA of this company\'s direct '
                                'peers.', 'mult', 'valuation',
                                short_name='Peer median'),
    'prem_disc_vs_peers_pct': _m('Premium / discount to direct peers',
                                 'How far the company\'s EV/EBITDA sits above '
                                 '(premium) or below (discount) the median of '
                                 'its direct peers.', 'pct_signed', 'valuation',
                                 'more_expensive', short_name='vs direct peers'),
    'sector_median_ev_ebitda': _m('Sector median EV/EBITDA',
                                  'Median EV/EBITDA across the whole '
                                  'capital-goods universe, each company '
                                  'counted once.', 'mult', 'valuation',
                                  short_name='Sector median'),
    'prem_disc_vs_sector_pct': _m('Premium / discount to sector',
                                  'How far the company\'s EV/EBITDA sits above '
                                  'or below the sector median.', 'pct_signed',
                                  'valuation', 'more_expensive',
                                  short_name='vs sector'),
    'hist_percentile': _m('Valuation vs own history',
                          'Where the current valuation sits within the '
                          'company\'s own historical range (100 = most '
                          'expensive it has been).', 'percentile', 'valuation',
                          'more_expensive', short_name='Own history'),
    'hist_zscore': _m('Historical deviation',
                      'How many standard deviations the current multiple sits '
                      'from its own historical average.', 'num', 'valuation',
                      'more_expensive'),
    'hist_years': _m('Years of usable history',
                     'Number of annual observations behind the own-history '
                     'comparison. Fewer years means a coarser comparison.',
                     'int', 'quality', short_name='History (yrs)'),
    'hist_median_ev_ebitda': _m('Own historical median EV/EBITDA',
                                'Median of the company\'s own annual EV/EBITDA '
                                'history.', 'mult', 'valuation',
                                short_name='Own median'),
    'valuation_state': _m('Valuation',
                          'Classification of the premium/discount to direct '
                          'peers: deep discount, discount, fair, premium or '
                          'extreme premium.', 'text', 'valuation'),

    # ---- fundamentals ------------------------------------------------------
    'rev_growth_pct': _m('Revenue growth',
                         'Change in reported revenue versus the previous '
                         'fiscal year.', 'pct_signed', 'fundamentals', 'better'),
    'ebitda_growth_pct': _m('EBITDA growth',
                            'Change in reported EBITDA versus the previous '
                            'fiscal year.', 'pct_signed', 'fundamentals',
                            'better'),
    'ebitda_margin_pct': _m('EBITDA margin',
                            'EBITDA as a percentage of revenue from the latest '
                            'reported financials.', 'pct', 'fundamentals',
                            'better'),
    'margin_chg_pp': _m('EBITDA margin change',
                        'Change in EBITDA margin versus the previous fiscal '
                        'year, in percentage points.', 'pp', 'fundamentals',
                        'better', short_name='Margin change'),
    'fcf_conversion': _m('Cash conversion',
                         'Free cash flow divided by net income — how much of '
                         'reported profit becomes cash.', 'num', 'fundamentals',
                         'better'),
    'nd_ebitda': _m('Net debt / EBITDA',
                    'Net debt divided by EBITDA — a standard leverage measure. '
                    'Higher means more indebted.', 'mult', 'risk', 'worse'),
    'interest_cover': _m('Interest cover',
                         'Operating profit divided by interest expense.',
                         'mult', 'risk', 'better'),
    'fundamental_state': _m('Fundamental direction',
                            'Whether reported revenue and margin are '
                            'improving, stable or deteriorating.', 'text',
                            'fundamentals'),

    # ---- performance -------------------------------------------------------
    'move_1d_pct': _m('1-day move', 'Share-price change on the latest '
                      'completed session.', 'pct_signed', 'performance',
                      'better', short_name='1D'),
    'ret_1m': _m('1M return', 'Total return over the last month (dividends '
                 'reinvested).', 'pct_signed', 'performance', 'better'),
    'ret_3m': _m('3M return', 'Total return over the last three months '
                 '(dividends reinvested).', 'pct_signed', 'performance',
                 'better'),
    'ret_6m': _m('6M return', 'Total return over the last six months '
                 '(dividends reinvested).', 'pct_signed', 'performance',
                 'better'),
    'ret_12m': _m('12M return', 'Total return over the last twelve months '
                  '(dividends reinvested).', 'pct_signed', 'performance',
                  'better'),
    'rel_1m_pct': _m('1M performance vs peers',
                     'Total return over one month minus the average of the '
                     'direct peers, in percentage points.', 'pp', 'performance',
                     'better', short_name='1M vs peers'),
    'rel_3m_pct': _m('3M performance vs peers',
                     'Total return over three months minus the average of the '
                     'direct peers, in percentage points.', 'pp', 'performance',
                     'better', short_name='3M vs peers'),
    'rel_12m_pct': _m('12M performance vs peers',
                      'Total return over twelve months minus the average of '
                      'the direct peers, in percentage points.', 'pp',
                      'performance', 'better', short_name='12M vs peers'),
    'rel_strength': _m('12M performance vs coverage',
                       'Total return over twelve months minus the equal-'
                       'weighted average of the selected universe, in '
                       'percentage points.', 'pp', 'performance', 'better',
                       short_name='12M vs coverage'),
    'rel_3m_universe': _m('3M performance vs coverage',
                          'Total return over three months minus the equal-'
                          'weighted average of the selected universe, in '
                          'percentage points.', 'pp', 'performance', 'better',
                          short_name='3M vs coverage'),
    'drawdown_52w_pct': _m('Distance from 52-week high',
                           'How far the share price sits below its highest '
                           'point of the last year.', 'pct_signed',
                           'performance', 'better', short_name='vs 52w high'),

    # ---- price trend (momentum) -------------------------------------------
    'trend': _m('Trend',
                'Whether the faster price average is above (uptrend) or below '
                '(downtrend) the slower one.', 'text', 'trend'),
    'momentum_change': _m('Momentum change',
                          'Whether the gap between the fast and slow price '
                          'averages is widening (strengthening) or narrowing '
                          '(weakening).', 'text', 'trend'),
    'recent_signal': _m('Recent signal',
                        'Whether a confirmed crossover of the two price '
                        'averages happened within the recent window.', 'text',
                        'trend'),
    'spread': _m('Trend strength',
                 'Percentage gap between the fast and slow price averages. '
                 'Larger positive values mean a stronger uptrend.',
                 'pct_signed', 'trend', 'better'),
    'dist_chg': _m('Momentum change (5 sessions)',
                   'Change over five sessions in the distance between the '
                   'fast and slow price averages, in percentage points. '
                   'Positive = the trend is strengthening.', 'pp', 'trend',
                   'better', short_name='Momentum chg'),
    'cross_date': _m('Latest signal date',
                     'Date of the most recent crossover between the fast and '
                     'slow price averages.', 'date', 'trend'),
    'days_since_cross': _m('Sessions since signal',
                           'Trading sessions elapsed since the latest '
                           'crossover.', 'int', 'trend'),
    'pos_3m_rate': _m('Positive 3M rate after similar signals',
                      'Share of this company\'s past confirmed positive '
                      'crossovers that were followed by a positive 3-month '
                      'return. Historical evidence, not a prediction.',
                      'pct', 'trend', 'better', short_name='Past +3M rate'),
    'n_signals': _m('Number of prior signals',
                    'How many comparable historical signals sit behind the '
                    'evidence columns. Small samples are anecdotes.', 'int',
                    'quality', short_name='Prior signals'),
    'median_3m_fwd': _m('Median 3M return after signals',
                        'Median 3-month return following this company\'s past '
                        'confirmed positive crossovers.', 'pct_signed', 'trend',
                        'better', short_name='Median 3M after'),
    'momentum_score': _m('Momentum rank score',
                         'Composite 0-100 rank built from return and trend '
                         'percentiles within the selected universe (weights '
                         'in Methodology).', 'num', 'trend', 'better',
                         short_name='Score'),
    'momentum_state': _m('Price trend detail',
                         'Descriptive trend state combining crossover '
                         'recency and direction (legacy five-state label).',
                         'text', 'trend'),

    # ---- quality / status --------------------------------------------------
    'data_quality': _m('Data warnings',
                       'Known measurement issues for this company\'s numbers '
                       '(accounting distortions, missing items, proxies). '
                       '"OK" means none.', 'text', 'quality'),
    'classification': _m('Summary state',
                         'Combined valuation and fundamentals classification.',
                         'text', 'quality'),
}

# format groups consumed by app/components/ui.style_table
FMT_GROUPS = {
    'pct_signed': 'pct_cols', 'pp': 'pct_cols', 'pct': 'pct_plain_cols',
    'mult': 'mult_cols', 'num': 'num_cols', 'usd_bn': 'num_cols',
    'percentile': 'num_cols', 'int': 'int_cols', 'price': 'price_cols',
}


def metric(mid):
    return METRIC_DEFINITIONS[mid]


def label(mid, short=False):
    """Display label for an internal metric id (falls back to the id so an
    unregistered metric is visible, and caught by tests)."""
    d = METRIC_DEFINITIONS.get(mid)
    if not d:
        return mid
    return d['short_name'] if short else d['display_name']


def describe(mid):
    d = METRIC_DEFINITIONS.get(mid)
    return d['description'] if d else ''


def table_spec(metric_ids, short=True):
    """Rename map + style_table kwargs for a list of internal metric ids.

    Returns (rename: {internal: display}, style_kwargs: {pct_cols: [...],
    mult_cols: [...], ...}, help_map: {display: description}).
    """
    rename, style_kwargs, help_map = {}, {}, {}
    for mid in metric_ids:
        disp = label(mid, short=short)
        rename[mid] = disp
        d = METRIC_DEFINITIONS.get(mid)
        if d:
            help_map[disp] = d['description']
            grp = FMT_GROUPS.get(d['format'])
            if grp:
                style_kwargs.setdefault(grp, []).append(disp)
    return rename, style_kwargs, help_map
