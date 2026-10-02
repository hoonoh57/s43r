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
