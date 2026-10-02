import asyncio, time
import backend.runtime as R
from backend.runtime import Runtime

class FakeBroker:
    def __init__(self):self.calls=0
    async def pages(self,*a,**k):self.calls+=1;return []
    async def query(self,api_id,path,body):
        if api_id=='ka10001':return {'stk_nm':'삼성전자'}
        return {'stk_tic_chart_qry':[]}
    async def close(self):pass

def run(tmp_path, body):
    async def go():
        rt=Runtime(tmp_path)
        try:await body(rt)
        finally:
            rt.connected=False;await rt.stop()
    asyncio.run(go())

def test_seed_boundary_mismatch_is_refetched(tmp_path):
    async def body(rt):
        rt.broker=FakeBroker();n={'c':0};orig=R.build_history;sleep=R.asyncio.sleep
        def fake(thirty,one,date):
            n['c']+=1
            if n['c']==1:raise ValueError('마지막 30틱 봉의 경계를 유일하게 확인하지 못했습니다.')
            return [],None,0
        async def fast(_):await sleep(0)
        R.build_history=fake;R.asyncio.sleep=fast
        try:
            assert await rt.fetch_seed('005930')==([],None,0)
            assert n['c']==2 and rt.broker.calls==2
        finally:R.build_history=orig;R.asyncio.sleep=sleep
    run(tmp_path, body)

def test_name_fetched_for_display(tmp_path):
    async def body(rt):
        rt.broker=FakeBroker();w=rt.add_watch('005930')
        await rt.fetch_name(w)
        assert w['name']=='삼성전자'
    run(tmp_path, body)

def test_buffered_tick_shows_price_before_seed(tmp_path):
    async def body(rt):
        w=rt.add_watch('005930')
        await rt.on_event({'trnm':'REAL','_received_at':time.time(),'data':[{'type':'0B','item':'005930','values':{'10':'-10050','27':'10060','28':'10050','20':'143000'}}]})
        assert not w['ready'] and w['quote']['price']==10050 and len(w['buffer'])==1
    run(tmp_path, body)
