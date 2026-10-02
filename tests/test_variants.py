import random
import pytest
from backend.strategy import S43REngine, StrategyConfig
from backend.variants import VariantEngine, ORIG, engine_for

CFG = StrategyConfig(target_date='20261001')


def bars(seed):
    rng = random.Random(seed)
    out, p = [], 10000.0
    def add(date, hh, mm, drift, vol):
        nonlocal p
        o = p
        p = max(100.0, p * (1 + rng.gauss(drift, 0.008)))
        hi = max(o, p) * (1 + abs(rng.gauss(0, 0.003)))
        lo = min(o, p) * (1 - abs(rng.gauss(0, 0.003)))
        out.append(dict(date=date, time=f'{hh:02d}{mm:02d}', open=round(o), high=round(hi),
                        low=round(lo), close=round(p), volume=vol))
    for i in range(90):
        add('20260930', 14 + i // 60, i % 60, 0.0, 20000)
    drift = rng.uniform(-0.002, 0.007)
    for i in range(101):
        add('20261001', 9 + i // 60, i % 60, drift, 30000)
    return out


def run(factory, b):
    e = factory(CFG)
    for x in b:
        e.step(x)
    return e.result()


def key(r):
    return (r['entered'], round(r['pnl'], 9), r['entryTime'], r['entryTimestamp'], r['exitTimestamp'],
            [(e['kind'], e['time'], e['price'], round(e['fraction'], 12)) for e in r['events']])


def test_clone_reproduces_original_exactly():
    ent = part = 0
    for s in range(400):
        b = bars(s)
        a = run(S43REngine, b)
        c = run(lambda cfg: VariantEngine(cfg, spec=ORIG), b)
        assert key(a) == key(c), f'seed {s}'
        ent += a['entered']
        part += any(e['kind'] == 'partial' for e in a['events'])
    assert ent > 20 and part > 3


def test_r3_same_entry_and_tiers():
    part = 0
    for s in range(400):
        b = bars(s)
        a, r = run(S43REngine, b), run(engine_for('S4.3-R3'), b)
        assert (a['entered'], a['entryTimestamp']) == (r['entered'], r['entryTimestamp'])
        ps = [e for e in r['events'] if e['kind'] == 'partial']
        assert [round(e['fraction'], 6) for e in ps] == [0.4, 0.3][:len(ps)]
        if len(ps) == 2:
            assert ps[0]['time'] < ps[1]['time']
        ex = [e for e in r['events'] if e['kind'] == 'exit']
        if ex:
            assert abs(sum(e['fraction'] for e in ps) + ex[0]['fraction'] - 1) < 1e-9
        part += bool(ps)
    assert part > 3


def test_registry():
    assert engine_for(None) is S43REngine and engine_for('S4.3-R') is S43REngine
    with pytest.raises(ValueError):
        engine_for('없는버전')
