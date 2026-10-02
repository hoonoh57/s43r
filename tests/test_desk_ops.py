import asyncio,time
from backend.runtime import Runtime
from backend import desk_ops as ops

def run(tmp_path,body,mode='paper'):
    async def go():
        rt=Runtime(tmp_path);rt.settings.mode=mode;ops.install(rt)
        try:await body(rt)
        finally:
            rt.connected=False;await rt.stop()
    asyncio.run(go())

def pos(rt,c,q,avg,adopted=False):
    rt.ledger.positions[c]={'code':c,'qty':q,'entry_qty':q,'entry_amount':q*avg,'avg':float(avg),'realized':0.0,'stages':{},'entered':not adopted,'closed':False,'entry_time':None,'high':0.0,**({'adopted':True} if adopted else {})}

def test_paper_bulk_exit_app_and_external(tmp_path):
    async def body(rt):
        pos(rt,'005930',10,70000);pos(rt,'000660',3,100000,True)
        w=rt.add_watch('005930');w['quote']={'price':71000,'bid':70900,'ask':71100,'received':time.time()}
        await ops.run_exit(rt,['005930','000660'],'last',0)
        assert rt.ledger.positions['005930']['qty']==0 and rt.ledger.positions['000660']['qty']==0
        assert all(o['side']=='sell' and o['status']=='FILLED' for o in rt.ledger.orders)
        assert rt.ledger.orders[0]['price']==71000
    run(tmp_path,body)

def test_state_merges_broker_and_external_orders(tmp_path):
    async def body(rt):
        pos(rt,'005930',10,70000)
        rt.snapshot={'cash':0,'holdings':[{'stk_cd':'A005930','stk_nm':'삼성전자','rmnd_qty':'10','trde_able_qty':'4','pur_pric':'70000','cur_prc':'72000'},
            {'stk_cd':'A035720','stk_nm':'카카오','rmnd_qty':'5','trde_able_qty':'5','pur_pric':'40000','cur_prc':'41000'}],
            'open_orders':[{'ord_no':'0012345','stk_cd':'A035720','stk_nm':'카카오','io_tp_nm':'-매도','ord_qty':'1','oso_qty':'1','ord_pric':'42000','tm':'101500'}]}
        rt.cash_at=time.time()
        P={r['code']:r for r in ops.positions(rt)}
        assert P['005930']['orderable']==4 and P['005930']['sellable'] and not P['035720']['sellable']
        O=ops.orders(rt)
        assert O[0]['source']=='외부' and O[0]['side']=='sell' and O[0]['id']=='X:0012345:035720'
    run(tmp_path,body,'mock')

def test_live_04_overrides_snapshot(tmp_path):
    async def body(rt):
        rt.snapshot={'cash':0,'holdings':[{'stk_cd':'005930','rmnd_qty':'10','trde_able_qty':'10','pur_pric':'70000','cur_prc':'70000'}],'open_orders':[]};rt.cash_at=time.time()-5
        ops.feed(rt,{'data':[{'type':'04','item':'005930','values':{'9001':'005930','930':'6','933':'6','931':'70000','10':'71000'}}]})
        assert ops.holdings(rt)['005930']['qty']==6
        ops.feed(rt,{'data':[{'type':'04','item':'005930','values':{'9001':'005930','302':'x'}}]})
        assert ops.holdings(rt)['005930']['qty']==6
        ops.feed(rt,{'data':[{'type':'04','item':'005930','values':{'9001':'005930','930':'0','933':'0'}}]})
        assert '005930' not in ops.holdings(rt)
    run(tmp_path,body,'mock')

class FakeBroker:
    def __init__(s):s.calls=[]
    async def cancel(s,c,no):s.calls.append((c,no));return '999'
    async def close(s):pass

def test_cancel_external_order(tmp_path):
    async def body(rt):
        rt.broker=FakeBroker();rt.connected=True
        done,fail=await ops.run_cancel(rt,['X:0012345:035720'])
        assert rt.broker.calls==[('035720','0012345')] and done==['035720'] and not fail
    run(tmp_path,body,'mock')
# END test_desk_ops.py
