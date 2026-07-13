"""Data-quality validation framework.

run_checks(db, run_id) executes every check against the database, writes
rows into validation_results, and returns a summary dict with counts by
severity. CRITICAL findings mean staged data must not be published.

Nothing is auto-deleted: suspicious observations are flagged for review
(raw_daily_prices.quality = 'flagged'), never removed.
"""
import json
from datetime import datetime, timezone, timedelta

SEVERITIES = ['info', 'warning', 'error', 'critical']


def _emit(db, run_id, results, check, severity, subject, message):
    results.append((run_id, check, severity, subject, message,
                    datetime.now(timezone.utc).replace(tzinfo=None)))


def run_checks(db, run_id):
    res = []
    ph = db.ph

    # duplicate raw price rows for the same (key, date) across sources is
    # expected (factiq + mixed); duplicates WITHIN a source are not possible
    # by PK — instead check for conflicting closes across sources > 2%
    rows = db.fetchall("""
        SELECT a.key, a.price_date, a.close, b.close
        FROM raw_daily_prices a JOIN raw_daily_prices b
          ON a.key=b.key AND a.price_date=b.price_date AND a.source < b.source
        WHERE a.close > 0 AND b.close > 0
          AND abs(a.close/b.close - 1) > 0.02""")
    for k, d, c1, c2 in rows[:50]:
        _emit(db, run_id, res, 'cross_source_price_conflict', 'warning',
              f'{k}:{d}', f'sources disagree: {c1} vs {c2}')

    # extreme unexplained daily moves (>30%) in the most recent 90 days
    rows = db.fetchall("""
        WITH r AS (
          SELECT key, price_date, close,
                 lag(close) OVER (PARTITION BY key, source ORDER BY price_date) prev
          FROM raw_daily_prices)
        SELECT key, price_date, close, prev FROM r
        WHERE prev > 0 AND abs(close/prev - 1) > 0.30
          AND price_date > current_date - INTERVAL '90 days'""")
    for k, d, c, p in rows[:50]:
        _emit(db, run_id, res, 'extreme_daily_move', 'warning',
              f'{k}:{d}', f'{p} -> {c} ({(c/p-1)*100:+.0f}%) — verify split/action')

    # suspicious price-scale change (possible unadjusted split / GBp mixups)
    rows = db.fetchall("""
        WITH r AS (
          SELECT key, price_date, close,
                 lag(close) OVER (PARTITION BY key, source ORDER BY price_date) prev
          FROM raw_daily_prices)
        SELECT key, price_date, close, prev FROM r
        WHERE prev > 0 AND (close/prev > 3 OR close/prev < 0.33)""")
    for k, d, c, p in rows[:20]:
        _emit(db, run_id, res, 'price_scale_change', 'error',
              f'{k}:{d}', f'scale jump {p} -> {c} — quarantine candidate')

    # stale quotes: quote_date older than 6 calendar days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=6)).strftime('%Y-%m-%d')
    rows = db.fetchall(f"SELECT key, quote_date FROM raw_quotes WHERE quote_date < {ph}",
                       [cutoff])
    for k, d in rows:
        _emit(db, run_id, res, 'stale_quote', 'warning', k, f'last quote {d}')

    # currency mismatch: quote currency vs securities reference
    rows = db.fetchall("""
        SELECT q.key, q.currency, s.quote_ccy FROM raw_quotes q
        JOIN securities s ON s.key = q.key
        WHERE q.currency IS NOT NULL AND q.currency <> s.quote_ccy""")
    for k, qc, sc in rows:
        _emit(db, run_id, res, 'currency_mismatch', 'critical', k,
              f'quote in {qc} but reference says {sc} — do not publish')

    # missing FX pair for any quote currency (vs USD, ex-USD)
    rows = db.fetchall("""
        SELECT DISTINCT s.quote_ccy FROM securities s
        WHERE s.quote_ccy NOT IN ('USD','GBp')
          AND NOT EXISTS (SELECT 1 FROM raw_fx_rates f
                          WHERE f.pair = s.quote_ccy || 'USD')""")
    for (ccy,) in rows:
        _emit(db, run_id, res, 'missing_fx_pair', 'error', ccy, 'no FX series stored')

    # estimate-basis integrity: every screener row must carry the same basis
    rows = db.fetchall("""
        SELECT snapshot_date, count(DISTINCT json_extract_string(payload,'$.estimate_basis'))
        FROM feat_screener GROUP BY 1 HAVING count(DISTINCT
             json_extract_string(payload,'$.estimate_basis')) > 1""") \
        if db.kind == 'duckdb' else db.fetchall("""
        SELECT snapshot_date, count(DISTINCT payload::json->>'estimate_basis')
        FROM feat_screener GROUP BY 1
        HAVING count(DISTINCT payload::json->>'estimate_basis') > 1""")
    for snap, n in rows:
        _emit(db, run_id, res, 'mixed_estimate_basis', 'critical', str(snap),
              f'{n} different bases in one snapshot — NTM/LTM mixing forbidden')

    # coverage integrity: every coverage member has a securities row
    rows = db.fetchall("""
        SELECT DISTINCT m.key FROM coverage_members m
        LEFT JOIN securities s ON s.key = m.key WHERE s.key IS NULL""")
    for (k,) in rows:
        _emit(db, run_id, res, 'unmapped_member', 'critical', k,
              'coverage member missing from securities')

    # flat price over 15+ sessions (possible dead listing)
    rows = db.fetchall("""
        SELECT key, count(*) FROM (
          SELECT key, close, price_date,
                 row_number() OVER (PARTITION BY key ORDER BY price_date DESC) rn
          FROM raw_daily_prices WHERE source IN ('mixed','yahoo')) t
        WHERE rn <= 15 GROUP BY key, close HAVING count(*) >= 15""")
    for k, n in rows:
        _emit(db, run_id, res, 'flat_price', 'warning', k,
              f'unchanged close over last {n} sessions')

    db.upsert('validation_results',
              ['run_id', 'check_name', 'severity', 'subject', 'message', 'created_at'],
              res, ['run_id', 'check_name', 'subject'])
    counts = {s: sum(1 for r in res if r[2] == s) for s in SEVERITIES}
    counts['total'] = len(res)
    return counts


def run_candidate_checks(db, run_id):
    """Candidate-vs-production gate: the NEW engine output must not regress
    the live snapshot. CRITICAL findings block publication (refresh.py)."""
    import json, os
    from datetime import datetime, timezone, timedelta
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    res = []
    try:
        cand = json.load(open(os.path.join(ROOT, 'data', 'computed',
                                           'dashboard_data.json')))
    except Exception as e:
        _emit(db, run_id, res, 'candidate_missing', 'critical', 'payload', repr(e))
        cand = None
    if cand:
        prod = db.fetchall('SELECT snapshot_date, payload FROM app_payload '
                           'ORDER BY snapshot_date DESC LIMIT 1')
        n_cand = len(cand.get('screener', []))
        if prod:
            p = json.loads(prod[0][1])
            n_prod = len(p.get('screener', []))
            if n_prod and n_cand < 0.9 * n_prod:
                _emit(db, run_id, res, 'universe_coverage_drop', 'critical',
                      'screener', f'candidate {n_cand} rows vs production {n_prod}')
            if str(cand.get('generated', '')) < str(prod[0][0]):
                _emit(db, run_id, res, 'snapshot_regression', 'warning',
                      'generated', f"candidate {cand.get('generated')} older "
                      f"than production {prod[0][0]}")
        # feature date must not be ahead of canonical price data
        latest_px = db.fetchall('SELECT max(session_date) FROM canonical_prices')
        if latest_px and latest_px[0][0]:
            if str(cand.get('generated', '')) > str(latest_px[0][0]):
                _emit(db, run_id, res, 'feature_after_price', 'error',
                      'generated', f"features {cand.get('generated')} vs "
                      f"canonical {latest_px[0][0]}")
    # canonical staleness: newest session older than 7 calendar days
    latest = db.fetchall('SELECT max(session_date) FROM canonical_prices')
    if latest and latest[0][0]:
        age = (datetime.now(timezone.utc).date()
               - datetime.strptime(str(latest[0][0])[:10], '%Y-%m-%d').date()).days
        if age > 7:
            _emit(db, run_id, res, 'canonical_stale', 'error', 'canonical_prices',
                  f'newest session {latest[0][0]} is {age} days old')
    # securities missing from canonical entirely
    missing = db.fetchall("""SELECT s.key FROM securities s
        WHERE s.active AND NOT EXISTS (SELECT 1 FROM canonical_prices c
                                       WHERE c.key = s.key)""")
    for (k,) in missing:
        _emit(db, run_id, res, 'missing_canonical_history', 'error', k,
              'no canonical price rows')
    # one security, multiple currencies (unexplained)
    for k, n in db.fetchall("""SELECT key, count(DISTINCT currency)
                               FROM canonical_prices GROUP BY key
                               HAVING count(DISTINCT currency) > 1"""):
        _emit(db, run_id, res, 'multi_currency', 'error', k,
              f'{n} currencies in canonical history')
    db.upsert('validation_results',
              ['run_id', 'check_name', 'severity', 'subject', 'message', 'created_at'],
              res, ['run_id', 'check_name', 'subject'])
    return {s: sum(1 for r in res if r[2] == s) for s in SEVERITIES} | \
           {'total': len(res)}
