import asyncio
from backend.runtime import Runtime

KEYS={'trend','macd','jma','cum','base','early'}
JOIN={'data':[{'type':'02','values':{'841':'7','843':'I','9001':'A005930'}}]}

class StubBroker:
    def __init__(self):self.registered=[]
    async def register(self,codes,*a,**k):self.registered.append(list(codes))
    async def pages(self,*a,**k):raise RuntimeError('no network in test')
    async def query(self,*a,**k):raise RuntimeError('no network in test')
    async def close(self):pass

def live_like(tmp_path,frozen):
    rt=Runtime(tmp_path);rt.settings.mode='paper';rt.settings.condition_sequence='7';rt.frozen=frozen;rt.broker=StubBroker();return rt

def test_state_exposes_stage_and_checks(tmp_path):
    async def run():
        rt=Runtime(tmp_path);rt.settings.replay_speed=500
        await rt.replay();await rt.replay_task
        s=rt.state();assert s['watch']
        for x in s['watch']:assert x['stage'] and KEYS<=set(x['checks'])
        assert any(x['stage'] in ('보유 중','청산 완료') for x in s['watch'])
        await rt.stop()
    asyncio.run(run())

def test_join_after_freeze_is_record_only(tmp_path):
    async def run():
        rt=live_like(tmp_path,True)
        await rt.on_event(dict(JOIN))
        assert '005930' in rt.members and '005930' not in rt.watch and not rt.broker.registered
        await rt.stop()
    asyncio.run(run())

def test_join_before_freeze_is_seeded(tmp_path):
    async def run():
        rt=live_like(tmp_path,False)
        await rt.on_event(dict(JOIN))
        assert '005930' in rt.watch and rt.broker.registered
        await asyncio.sleep(0);await rt.stop()
    asyncio.run(run())
