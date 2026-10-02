import asyncio
from backend.runtime import Runtime

def snap(*rows):
    return {'cash':10_000_000,'holdings':[{'stk_cd':c,'stk_nm':'T','rmnd_qty':str(q),'pur_pric':str(p),'cur_prc':str(p)} for c,q,p in rows],'open_orders':[]}

def run(tmp_path, body):
    async def go():
        rt=Runtime(tmp_path);rt.settings.mode='mock'
        try:await body(rt)
        finally:await rt.stop()
    asyncio.run(go())

def test_startup_adopts_external_holdings(tmp_path):
    async def body(rt):
        rt.adopt(snap(('005930',10,70000)),startup=True)
        p=rt.ledger.positions['005930']
        assert p['adopted'] and p['qty']==10 and p['avg']==70000
        hard,soft=rt.ledger.reconcile_detail(snap(('005930',10,70000)),0)
        assert not hard and not soft
    run(tmp_path, body)

def test_adopted_mirrors_manual_sell(tmp_path):
    async def body(rt):
        rt.adopt(snap(('005930',10,70000)))
        rt.adopt(snap(('005930',4,70000)))
        assert rt.ledger.positions['005930']['qty']==4
        rt.adopt(snap())
        p=rt.ledger.positions['005930']
        assert p['qty']==0 and p['closed']
    run(tmp_path, body)

def test_app_owned_mismatch_still_reported(tmp_path):
    async def body(rt):
        rt.ledger.positions['000660']={'code':'000660','qty':5,'entry_qty':5,'entry_amount':500000.0,'avg':100000.0,'realized':0.0,'stages':{},'entered':True,'closed':False,'entry_time':None,'high':0.0}
        rt.adopt(snap(('000660',7,100000)))
        assert rt.ledger.positions['000660']['qty']==5
        hard,soft=rt.ledger.reconcile_detail(snap(('000660',7,100000)),0)
        assert soft
    run(tmp_path, body)

def test_adopted_never_bought_and_excluded_from_pnl(tmp_path):
    async def body(rt):
        rt.adopt(snap(('005930',10,70000)))
        w=rt.add_watch('005930');w['quote']={'price':60000,'ask':60000,'bid':59900,'received':0}
        await rt.send(w,{'kind':'entry','price':60000,'time':'0905','reason':'test'})
        assert not rt.ledger.orders
        assert rt.pnl_total()==0
        assert rt.diagnose(w)['stage'].startswith('외부 보유')
    run(tmp_path, body)
