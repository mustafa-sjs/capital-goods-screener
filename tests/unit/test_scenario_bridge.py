"""The scenario return decomposition must be exactly additive:
earnings + multiple + net-debt + share-count effects == implied return."""


def bridge(e0, m0, nd0, sh0, mino, de, mt, nd, sh):
    e = e0 * (1 + de)
    eq0 = m0 * e0 - nd0 - mino
    eqN = mt * e - nd - mino
    ret = (eqN / eq0) * (sh0 / sh) - 1
    earn = m0 * (e - e0) / eq0
    mult = (mt - m0) * e / eq0
    ndef = -(nd - nd0) / eq0
    shef = (eqN / eq0) * (sh0 / sh - 1)
    return ret, earn + mult + ndef + shef


def test_bridge_additive_simple():
    ret, s = bridge(1000, 10.0, 2000, 100, 0, -0.10, 8.0, 2000, 100)
    assert abs(ret - s) < 1e-12


def test_bridge_additive_all_levers():
    ret, s = bridge(5000, 12.5, 8000, 550, 300, 0.15, 15.0, 6500, 500)
    assert abs(ret - s) < 1e-12


def test_bridge_additive_high_leverage():
    ret, s = bridge(1000, 8.0, 6000, 50, 100, -0.2, 6.0, 7000, 55)
    assert abs(ret - s) < 1e-12


def test_zero_change_is_zero_return():
    ret, s = bridge(1000, 10.0, 2000, 100, 0, 0.0, 10.0, 2000, 100)
    assert abs(ret) < 1e-12 and abs(s) < 1e-12
