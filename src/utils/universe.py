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
