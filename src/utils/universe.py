"""Load the coverage-pack universe from config/coverage_packs/*.yaml.

The YAML is the single source of truth for securities and peer baskets.
Returns the exact shapes the engine and refresh scripts consume:
  SEC       {key: dict(name, qccy, rccy, exch, sym)}
  SUBGROUPS [(subgroup_name, [(display, [coverage_keys], [peer_keys]), ...])]
  YAHOO     {key: yahoo_symbol}

Falls back to None if PyYAML is unavailable so callers can keep their
embedded literals as a last resort (documented fallback, not the norm).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PACK = os.path.join(ROOT, 'config', 'coverage_packs', 'capital_goods.yaml')


def load_universe(path=DEFAULT_PACK):
    try:
        import yaml
    except ImportError:
        return None
    if not os.path.exists(path):
        return None
    cfg = yaml.safe_load(open(path))
    sec = {k: dict(name=v['name'], qccy=v['quote_ccy'], rccy=v['report_ccy'],
                   exch=v['exchange'], sym=v['ticker'])
           for k, v in cfg['securities'].items()}
    subgroups = [(sg['name'],
                  [(g['display'], list(g['coverage']), list(g['peers']))
                   for g in sg['groups']])
                 for sg in cfg['subgroups']]
    yahoo = {k: v['yahoo_symbol'] for k, v in cfg['securities'].items()
             if v.get('yahoo_symbol')}
    # referential integrity: every key referenced by a group must exist
    for sg, groups in subgroups:
        for disp, cov, peers in groups:
            for k in cov + peers:
                if k not in sec:
                    raise ValueError(f'{path}: group "{disp}" references unknown key {k}')
    return dict(sec=sec, subgroups=subgroups, yahoo=yahoo, pack=cfg.get('pack'))


# ===== shared universe service ==============================================
# ONE place that answers "which companies, which subgroup, which peers?" so
# no page reconstructs the lists itself. Everything derives from the pack
# YAML above; the service adds the derived shapes the app needs plus hard
# validation of the invariants every page relies on.

EXPECTED_CORE_COUNT = 30

_svc_cache = {}


class UniverseError(ValueError):
    """The coverage pack violates a hard invariant — do not serve pages."""


def universe_service(path=DEFAULT_PACK, validate=True):
    """Cached derived view of the coverage pack.

    Returns dict with:
      core       : list of core coverage keys (one primary listing each,
                   first-appearance order of the pack config)
      peers      : sorted list of direct-peer keys that are NOT core
      all        : sorted list of every key (core + peers)
      sub_of     : {key: subgroup display name} (core key -> its subgroup;
                   peer key -> subgroup of the first basket using it)
      group_of   : {core key: coverage-group display name}
      peers_of   : {key: [peer keys of its basket]} (peers map to the first
                   basket that uses them)
      role_of    : {key: 'coverage' | 'peer'}
      names, tickers, qccy, rccy, exch : {key: value}
      sec, subgroups, yahoo, pack      : the load_universe() shapes
    """
    ck = (os.path.abspath(path),)
    if ck in _svc_cache:
        return _svc_cache[ck]
    u = load_universe(path)
    if u is None:
        raise UniverseError(f'coverage pack not loadable: {path}')
    core, seen = [], set()
    sub_of, group_of, peers_of, role_of = {}, {}, {}, {}
    for sg_name, groups in u['subgroups']:
        for disp, cov, peers in groups:
            for k in cov:
                if k not in seen:
                    core.append(k)
                    seen.add(k)
                    sub_of[k] = sg_name
                    group_of[k] = disp
                    peers_of[k] = list(peers)
                    role_of[k] = 'coverage'
            for p in peers:
                sub_of.setdefault(p, sg_name)
                peers_of.setdefault(p, list(peers))
                role_of.setdefault(p, 'peer')
    peer_only = sorted(k for k in role_of if role_of[k] == 'peer')
    svc = dict(
        core=core, peers=peer_only, all=sorted(set(core) | set(peer_only)),
        sub_of=sub_of, group_of=group_of, peers_of=peers_of, role_of=role_of,
        names={k: v['name'] for k, v in u['sec'].items()},
        tickers={k: v['sym'] for k, v in u['sec'].items()},
        qccy={k: v['qccy'] for k, v in u['sec'].items()},
        rccy={k: v['rccy'] for k, v in u['sec'].items()},
        exch={k: v['exch'] for k, v in u['sec'].items()},
        sec=u['sec'], subgroups=u['subgroups'], yahoo=u['yahoo'],
        pack=u['pack'])
    if validate:
        problems = validate_universe(svc)
        if problems:
            raise UniverseError('; '.join(problems))
    _svc_cache[ck] = svc
    return svc


def universe_keys(selection, svc=None):
    """Resolve a user-facing universe selection to the keys BOTH displayed
    and used for rankings/percentiles (never rank on more than you show)."""
    svc = svc or universe_service()
    return {
        'Core coverage': list(svc['core']),
        'Core coverage + direct peers': sorted(set(svc['core'])
                                               | set(svc['peers'])),
        'Full universe': list(svc['all']),
    }[selection]


UNIVERSE_OPTIONS = ['Core coverage', 'Core coverage + direct peers',
                    'Full universe']
DEFAULT_UNIVERSE = 'Core coverage'


def validate_universe(svc):
    """Hard rules from the product spec. Returns a list of problems
    (empty = valid)."""
    problems = []
    core = svc['core']
    if len(core) != len(set(core)):
        problems.append('duplicate keys in core coverage')
    if len(set(core)) != EXPECTED_CORE_COUNT:
        problems.append(f'core coverage has {len(set(core))} companies, '
                        f'expected {EXPECTED_CORE_COUNT}')
    for must in ('SIE', 'SU', 'ABBN', 'LR'):
        if must not in core:
            problems.append(f'{must} missing from core coverage')
    # one subgroup + one display name per core company
    for k in core:
        if k not in svc['sub_of']:
            problems.append(f'{k} has no subgroup')
        if k not in svc['names'] or not svc['names'][k]:
            problems.append(f'{k} has no display name')
    # no duplicate primary listings: two core keys must not share a name
    names = [svc['names'].get(k, k) for k in core]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        problems.append(f'duplicate primary listings in core: {sorted(dupes)}')
    return problems
