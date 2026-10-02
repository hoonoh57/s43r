import asyncio
from backend.extras import aggregate,bucket,Calc,TradeRuntime

def r(d,tm,p,v=10):return {'date':d,'tm':tm,'open':p,'high':p,'low':p,'close':p,'volume':v}

def test_aggregate_resets_each_day():
    rows=[r('20261001',f'1500{i:02d}',100+i) for i in range(5)]+[r('20261002',f'0900{i:02d}',200+i) for i in range(4)]
    out=aggregate(rows,2)
    assert [b['volume'] for b in out]==[20,20,10,20,20] and out[3]['open']==200

def test_minute_bucket():
    assert bucket('090412',3,'start')=='090300' and bucket('090412',3,'end')=='090600'

def test_calc_monotonic_time_and_vwap():
    c=Calc('20261002',False,'start');rows=[r('20261002','090001',100)]*3
    out=[c.step(x) for x in rows]
    assert out[0]['t']<out[1]['t']<out[2]['t'] and out[-1]['vwap']==100

def test_manual_mode_blocks_orders(tmp_path):
    rt=TradeRuntime(tmp_path)
    try:
        rt.set_mode('manual');rt.armed=rt.entries=True;w=rt.add_watch('005930');w['eligible']=True
        asyncio.run(rt.signals(w,[{'kind':'entry','price':1000,'time':1,'reason':'S4.3'}]))
        assert not rt.ledger.orders and rt.signal_log[-1]['note'].startswith('수동')
    finally:rt.store.close()

def test_semi_mode_queues_approval(tmp_path):
    rt=TradeRuntime(tmp_path)
    try:
        rt.set_mode('semi');rt.armed=rt.entries=True;w=rt.add_watch('005930');w['eligible']=True
        asyncio.run(rt.signals(w,[{'kind':'entry','price':1000,'time':1,'reason':'S4.3'}]))
        assert len(rt.approvals)==1 and not rt.ledger.orders
    finally:rt.store.close()
# END test_extras.py
