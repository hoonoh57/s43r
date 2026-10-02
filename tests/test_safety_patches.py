import asyncio
import time

import pytest

from backend.execution import Ledger
from backend.runtime import Runtime


class MemStore(dict):
    def put(self, k, v):
        self[k] = v


def filled_ledger():
    lg = Ledger(MemStore(), 't')
    o = lg.create('005930', 'buy', 10, 1000, 'r', 'sid1')
    lg.ack(o, '123')
    lg.fill(o, 10, 10000, 'f1')
    return lg


def test_recent_fill_is_not_mismatch():
    lg = filled_ledger()
    snap = {'holdings': [], 'open_orders': []}
    hard, soft = lg.reconcile_detail(snap, 10)
    assert not hard and not soft

    lg.data['fills'][0]['time'] = time.time() - 60
    hard, soft = lg.reconcile_detail(snap, 10)
    assert soft and not hard
    assert lg.reconcile(snap)


def test_sell_bypasses_quote_checks(tmp_path):
    rt = Runtime(tmp_path)
    try:
        w = {'code': '005930', 'quote': {'price': 70000, 'bid': 0, 'ask': 0, 'received': 0}}
        assert rt.risk_price(w, 'sell', 69000) == 70000
        with pytest.raises(ValueError):
            rt.risk_price(w, 'buy', 69000)
    finally:
        rt.store.close()


def test_fault_scopes(tmp_path):
    rt = Runtime(tmp_path)
    try:
        rt.armed = True
        rt.entries = True
        asyncio.run(rt.fault('x'))
        assert rt.armed and not rt.entries

        asyncio.run(rt.fault('x', scope='all'))
        assert not rt.armed
    finally:
        rt.store.close()

def test_rewarm_failure_retries_then_escalates(tmp_path):
    async def run():
        import backend.runtime as R
        rt = Runtime(tmp_path)
        w = rt.add_watch('005930')
        rt.connected = True
        rt.armed = rt.entries = True
        rt.ledger.positions['005930'] = {'code': '005930', 'qty': 10, 'entry_qty': 10, 'entry_amount': 100000.0,
                                         'avg': 10000.0, 'realized': 0.0, 'stages': {}, 'entered': True,
                                         'closed': False, 'entry_time': None, 'high': 0.0}

        class Broken:
            async def pages(self, *a, **k):
                raise RuntimeError('boom')

            async def close(self):
                pass

        rt.broker = Broken()
        orig = asyncio.sleep

        async def fast(_):
            await orig(0)

        R.asyncio.sleep = fast
        try:
            await rt.fault('gap', scope='symbol', code='005930')
            for _ in range(300):
                await orig(0)
                if not rt.entries:
                    break
            assert w['rewarm'] == R.MAX_REWARM
            assert rt.armed and not rt.entries
        finally:
            R.asyncio.sleep = orig
            rt.connected = False
            await rt.stop()

    asyncio.run(run())