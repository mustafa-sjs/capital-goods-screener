"""Forced-refresh button component: cooldown ledger + GitHub dispatch, all
mocked — no network, no real token."""
import io, os, sys, tempfile, urllib.error
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'app'))

from src.database import db as dbmod
from src.database.db import DB
from components import manual_refresh as mr


def tmp_db(monkeypatch):
    monkeypatch.setattr(dbmod, 'DUCKDB_PATH', tempfile.mktemp(suffix='.duckdb'))
    monkeypatch.delenv('DATABASE_URL', raising=False)
    d = DB()
    d.init_schema()
    return d


def test_cooldown_empty_then_recent_then_expired(monkeypatch):
    db = tmp_db(monkeypatch)
    assert mr.cooldown_remaining_min(db) == 0            # never pressed
    mr._record_manual(db, 'test dispatch')
    left = mr.cooldown_remaining_min(db)
    assert 0 < left <= mr.COOLDOWN_MIN                   # rate limited now
    future = datetime.now(timezone.utc).replace(tzinfo=None) \
        + timedelta(minutes=mr.COOLDOWN_MIN + 1)
    assert mr.cooldown_remaining_min(db, now=future) == 0
    # second press writes a second ledger row (PK as_of+metric) — idempotent
    mr._record_manual(db, 'again')
    assert db.fetchall('SELECT count(*) FROM free_tier_usage')[0][0] >= 1


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_dispatch_success(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen['url'] = req.full_url
        seen['auth'] = req.headers.get('Authorization')
        return _Resp()

    monkeypatch.setattr(mr.urllib.request, 'urlopen', fake_urlopen)
    ok, msg = mr._dispatch(mr.US_WORKFLOW, 'tok-abc', inputs={'force': True})
    assert ok and mr.US_WORKFLOW in msg
    assert seen['url'].endswith(f'{mr.US_WORKFLOW}/dispatches')
    assert 'tok-abc' in seen['auth']                     # sent in header only


def test_dispatch_auth_and_missing_errors(monkeypatch):
    def raise_code(code):
        def f(req, timeout=None):
            raise urllib.error.HTTPError('u', code, 'm', {}, io.BytesIO(b''))
        return f

    monkeypatch.setattr(mr.urllib.request, 'urlopen', raise_code(401))
    ok, msg = mr._dispatch(mr.US_WORKFLOW, 'tok-secret')
    assert not ok and 'token' in msg and 'tok-secret' not in msg
    monkeypatch.setattr(mr.urllib.request, 'urlopen', raise_code(404))
    ok, msg = mr._dispatch(mr.US_WORKFLOW, 'tok-secret')
    assert not ok and 'not found' in msg.lower()
    monkeypatch.setattr(mr.urllib.request, 'urlopen', raise_code(429))
    ok, msg = mr._dispatch(mr.US_WORKFLOW, 'tok-secret')
    assert not ok and 'rate limit' in msg.lower()


def test_dispatch_network_failure(monkeypatch):
    def boom(req, timeout=None):
        raise TimeoutError('t')
    monkeypatch.setattr(mr.urllib.request, 'urlopen', boom)
    ok, msg = mr._dispatch(mr.US_WORKFLOW, 'tok')
    assert not ok and 'TimeoutError' in msg


def test_token_from_env(monkeypatch):
    monkeypatch.setenv('GH_ACTIONS_TOKEN', 'env-tok')
    assert mr._token() == 'env-tok'
    monkeypatch.delenv('GH_ACTIONS_TOKEN')
