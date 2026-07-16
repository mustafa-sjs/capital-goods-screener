"""Trader-facing forced refresh.

The Streamlit app stays passive by design: it never holds the Finnhub key
and never calls a market-data provider. This button instead asks GitHub to
run the existing refresh workflows (workflow_dispatch); the runner does the
fetch with its own secrets, writes to the database, and data_version()
invalidates the page cache when the new rows land (~2-4 minutes).

Requires a fine-grained GitHub token (Actions read+write on the repo only)
in the environment or Streamlit secrets as GH_ACTIONS_TOKEN. Without it the
button renders an explanation instead of failing. The token is used only
server-side and never logged or sent to the browser.

A shared cooldown (ledger row in free_tier_usage) rate-limits the button
across ALL users/sessions — pressing it again inside the window shows a
rate-limited message instead of dispatching another run.
"""
import json, os, urllib.error, urllib.request
from datetime import datetime, timezone

import streamlit as st

REPO = os.environ.get('GH_REPO', 'mustafa-sjs/capital-goods-screener')
US_WORKFLOW = 'us_intraday_refresh.yml'
DAILY_WORKFLOW = 'daily_refresh.yml'
COOLDOWN_MIN = 10
LEDGER_METRIC = 'manual_refresh'


def _token():
    if os.environ.get('GH_ACTIONS_TOKEN'):
        return os.environ['GH_ACTIONS_TOKEN']
    # same guarded st.secrets pattern as data._db_url (no red box when the
    # secrets file is absent)
    for p in (os.path.expanduser('~/.streamlit/secrets.toml'),
              os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                  os.path.abspath(__file__)))), '.streamlit', 'secrets.toml')):
        if os.path.exists(p):
            try:
                return st.secrets.get('GH_ACTIONS_TOKEN')
            except Exception:
                return None
    return None


def _dispatch(workflow_file, token, inputs=None):
    """Fire one workflow_dispatch. Returns (ok, user_message); the token
    never appears in messages or logs."""
    url = (f'https://api.github.com/repos/{REPO}/actions/workflows/'
           f'{workflow_file}/dispatches')
    body = {'ref': 'main'}
    if inputs:
        body['inputs'] = inputs
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method='POST',
        headers={'Authorization': f'Bearer {token}',
                 'Accept': 'application/vnd.github+json',
                 'User-Agent': 'capital-goods-screener'})
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass                                   # 204 No Content = accepted
        return True, f'{workflow_file} started'
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, ('GitHub rejected the refresh token — recreate '
                           'GH_ACTIONS_TOKEN with Actions read & write on '
                           'this repository.')
        if e.code == 404:
            return False, ('Workflow not found — the token may lack access '
                           'to the repository.')
        if e.code == 429:
            return False, 'GitHub is rate limiting workflow triggers — wait a minute.'
        return False, f'GitHub API error (HTTP {e.code}).'
    except Exception as e:
        return False, f'Could not reach GitHub ({type(e).__name__}).'


def _last_manual(db):
    try:
        r = db.fetchall('SELECT max(as_of) FROM free_tier_usage '
                        f'WHERE metric = {db.ph}', [LEDGER_METRIC])
        return r[0][0] if r and r[0][0] else None
    except Exception:
        return None


def _record_manual(db, detail):
    db.upsert('free_tier_usage', ['as_of', 'metric', 'value', 'detail'],
              [(datetime.now(timezone.utc).replace(tzinfo=None),
                LEDGER_METRIC, 1.0, detail)], ['as_of', 'metric'])


def cooldown_remaining_min(db, now=None):
    """Minutes left on the shared cooldown; 0 when a refresh may run."""
    last = _last_manual(db)
    if last is None:
        return 0
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    import math
    remaining = COOLDOWN_MIN - (now - last).total_seconds() / 60
    return max(0, math.ceil(remaining))


def manual_refresh_button(include_daily_option=True):
    """Render the forced-refresh control. Safe on every page: degrades to a
    caption when no token is configured."""
    from components.data import get_db
    token = _token()
    c1, c2 = st.columns([1, 3])
    if include_daily_option:
        also_daily = c2.checkbox(
            'Also refresh European/global daily prices (slower, ~5 min)',
            value=False, key='mr_daily')
    else:
        also_daily = False
    if not c1.button('🔄 Refresh data now', key='mr_btn',
                     help='Triggers the cloud refresh jobs; new data appears '
                          'here automatically in a few minutes.'):
        return
    if not token:
        st.info('Forced refresh is not configured: add a fine-grained GitHub '
                'token (Actions read & write on this repository only) as '
                '`GH_ACTIONS_TOKEN` in the Streamlit app secrets. Scheduled '
                'refreshes continue to run regardless.')
        return
    db = get_db()
    left = cooldown_remaining_min(db)
    if left > 0:
        st.warning(f'⏳ You are rate limited — a forced refresh ran in the '
                   f'last {COOLDOWN_MIN} minutes. Try again in about {left} '
                   f'minute{"s" if left != 1 else ""}. (Scheduled updates '
                   f'keep running in the background.)')
        return
    ok, msg = _dispatch(US_WORKFLOW, token, inputs={'force': True})
    msgs = [msg]
    if ok and also_daily:
        ok2, msg2 = _dispatch(DAILY_WORKFLOW, token)
        msgs.append(msg2)
        ok = ok and ok2
    if ok:
        _record_manual(db, ' + '.join(msgs))
        st.success('Refresh started — US intraday prices land in ~2–4 '
                   'minutes' + (', global daily prices in ~5–10'
                                if also_daily else '') +
                   '. The page picks them up automatically; revisit or '
                   'rerun it shortly.')
        st.caption('Note: outside US trading hours prices only move to the '
                   'last close, and the “since 16:30 UK” view needs a '
                   'benchmark captured after 16:30.')
    else:
        st.error(' '.join(msgs))
