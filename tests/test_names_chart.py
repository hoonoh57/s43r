import asyncio
from backend.runtime import Runtime

class FakeBroker:
    def __init__(self, fail=False):self.calls=[];self.fail=fail
    async def pages(self,api_id,path,body,list_key,max_pages=100,stop=None):
        self.calls.append((api_id,body.get('mrkt_tp'),list_key))
        if self.fail:raise RuntimeError('boom')
        return [{'code':'005930','name':'삼성전자'}] if body.get('mrkt_tp')=='0' else [{'code':'0011A0','name':'테스트우'}]
    async def close(self):pass

def run(tmp_path, body):
    async def go():
        rt=Runtime(tmp_path)
        try:await body(rt)
        finally:await rt.stop()
    asyncio.run(go())

def test_names_loaded_and_cached(tmp_path):
    async def body(rt):
        rt.broker=FakeBroker();w=rt.add_watch('005930')
        await rt.load_names()
        assert w['name']=='삼성전자' and rt.add_watch('0011A0')['name']=='테스트우'
        assert {c[1] for c in rt.broker.calls}=={'0','10'} and all(c[0]=='ka10099' for c in rt.broker.calls)
        rt.names={};rt.broker.calls.clear()
        await rt.load_names()
        assert not rt.broker.calls and rt.names['005930']=='삼성전자'
    run(tmp_path, body)

def test_names_failure_is_harmless(tmp_path):
    async def body(rt):
        rt.broker=FakeBroker(fail=True);w=rt.add_watch('005930')
        await rt.load_names()
        assert w['name']=='005930' and not rt.names
    run(tmp_path, body)

def test_state_shows_names_and_bar_count(tmp_path):
    async def body(rt):
        rt.names={'005930':'삼성전자'};rt.watch={};rt.add_watch('005930','005930')
        rt.ledger.positions['005930']={'code':'005930','qty':1,'entry_qty':1,'entry_amount':70000.0,'avg':70000.0,'realized':0.0,'stages':{},'entered':True,'closed':False,'entry_time':None,'high':0.0}
        s=rt.state();row=[x for x in s['watch'] if x['code']=='005930'][0]
        assert row['name']=='삼성전자' and row['bars_n']==0
        assert s['positions'][0]['name']=='삼성전자'
    run(tmp_path, body)
