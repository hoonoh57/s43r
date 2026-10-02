import asyncio,copy,json,os,subprocess,time
from pathlib import Path
from dataclasses import asdict
from datetime import datetime
import pytest,httpx
from fastapi.testclient import TestClient
from websockets.asyncio.server import serve
from backend.market import TickBars,match_tail,demo_cases,KST,symbol
from backend.strategy import S43REngine,StrategyConfig,evaluate
from backend.storage import Store
from backend.execution import Ledger
from backend.broker import Kiwoom,OrderUnknown,BrokerError
from backend.runtime import Runtime
from backend.app import create_app,SingleInstance
from backend.vault import crypt
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def ledger(tmp_path):
    store=Store(tmp_path);yield Ledger(store,'test');store.close()
def buy(l,qty=10):
    o=l.create('005930','buy',qty,10000,'entry','signal');l.ack(o,'0000123');return o

def test_acceptance_partial_duplicate_and_recovery(ledger):
    o=buy(ledger);assert not ledger.positions
    ledger.fill(o,4,40000,'f1');assert ledger.positions['005930']['qty']==4
    ledger.fill(o,4,40000,'f1');assert len(ledger.data['fills'])==1
    ledger.fill(o,10,100060,'f2');assert ledger.positions['005930']['avg']==10006;assert o['status']=='FILLED'
    reopened=Ledger(ledger.store,'test');assert reopened.positions['005930']['qty']==10
    with pytest.raises(ValueError):ledger.create('005930','sell',11,10000,'exit','over')

def test_crash_does_not_resend(ledger):
    o=ledger.create('005930','buy',10,10000,'entry','one')
    reopened=Ledger(ledger.store,'test');assert reopened.orders[0]['status']=='UNKNOWN'
    with pytest.raises(ValueError):reopened.create('005930','buy',10,10000,'entry','one')
    assert reopened.reconcile({'holdings':[],'open_orders':[]})

def test_cancel_race_and_cumulative_events(ledger):
    o=buy(ledger);v={'9201':'1234567890','9203':'123','9001':'A005930','913':'체결','900':'10','902':'6','903':'40000','909':'first'}
    assert ledger.execution(v,'1234567890');assert o['filled']==4
    o.update(status='CANCEL_PENDING',cancel_id='124');ledger.save()
    ledger.execution({**v,'902':'4','903':'60000','909':'second'},'1234567890');assert o['status']=='CANCEL_PENDING'
    ledger.execution({'9201':'1234567890','9203':'124','913':'확인'},'1234567890');assert o['status']=='CANCELED'
    ledger.execution({**v,'902':'4','903':'60000','909':'second'},'1234567890');assert ledger.positions['005930']['qty']==6
    assert not ledger.execution({**v,'9201':'9999999999'},'1234567890')

def test_external_holdings_not_adopted(ledger):
    assert ledger.reconcile({'holdings':[{'stk_cd':'A005930','rmnd_qty':'10'}],'open_orders':[]})
    assert not ledger.positions

def test_tick_count_not_volume_or_timestamp():
    b=TickBars();outputs=[]
    for i in range(720):
        out=b.tick('20261002','090001',10000+i,100 if i%2 else 1)
        if out:outputs.append(out)
    assert len(outputs)==2;assert outputs[0]['open']==10000;assert outputs[0]['close']==10359;assert outputs[1]['open']==10360
    b.tick('20261002','090002',11000,1);b.tick('20261005','090001',12000,1);assert b.count==1
    assert symbol('A0155E0')=='0155E0'

def test_ambiguous_tail_is_blocked():
    b=dict(date='20261002',time='0900',full_time='090001',open=100,high=100,low=100,close=100,volume=1)
    with pytest.raises(ValueError):match_tail([b,b],b)
    assert match_tail([b],b)==[b]

def test_local_api_security_and_demo(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/').status_code==200
        assert client.post('/api/demo').status_code==403
        token=client.get('/api/bootstrap').json()['token'];h={'X-Session':token}
        assert client.post('/api/demo',headers={**h,'Origin':'https://evil.example'}).status_code==403
        assert client.get('/api/state',headers={'Host':'evil.example'}).status_code==403
        assert client.post('/api/replay',headers=h,json={'date':'20261002','cases':[]}).status_code==400
        s=client.get('/api/state').json()['settings'];s['replay_speed']=500
        assert client.post('/api/settings',headers=h,json=s).status_code==200
        assert client.post('/api/demo',headers=h).status_code==200
        deadline=time.time()+15
        while time.time()<deadline:
            s=client.get('/api/state').json()
            if not s['running']:break
            time.sleep(.1)
        assert not s['running'];assert not s['error'];assert len(s['orders'])>=4
        assert any('손절' in o['reason'] for o in s['orders'])
        assert all(o['status']=='FILLED' and o['broker_id'].startswith('P') for o in s['orders'])
        assert not s['connected'];assert not s['armed']
        assert client.get('/api/export').json()['schema']=='s43r-trader-report-v1'

def test_engine_signal_does_not_create_virtual_broker_position(tmp_path):
    rt=Runtime(tmp_path);rt.date='20261002';w=rt.add_watch('005930')
    signals=[]
    for b in demo_cases(rt.date)[0]['candles']:signals.extend(rt.indicate(w,b))
    assert any(s['kind']=='entry' for s in signals)
    assert not w['engine'].entered;assert not rt.ledger.positions;rt.store.close()

def test_paper_risk_limits(tmp_path):
    async def run():
        rt=Runtime(tmp_path);rt.settings.replay_speed=500;rt.settings.max_positions=1
        await rt.replay();await rt.replay_task
        entries=[o for o in rt.ledger.orders if o['side']=='buy'];assert len(entries)==1
        assert entries[0]['qty']*entries[0]['price']<=rt.settings.allocation
        await rt.stop()
    asyncio.run(run())

def test_broker_order_timeout_is_not_retried():
    async def run():
        calls=[]
        async def handler(request):calls.append(request);raise httpx.ReadTimeout('test timeout')
        async def noop(*args):pass
        b=Kiwoom('mock',noop,noop,transport=httpx.MockTransport(handler));b.token='test';b.expires=time.time()+1000;b.interval=0
        with pytest.raises(OrderUnknown):await b.submit('buy','005930',1,10000)
        assert len(calls)==1;assert calls[0].headers['api-id']=='kt10000'
        assert json.loads(calls[0].content)['trde_tp']=='0'
        await b.close()
    asyncio.run(run())

def test_websocket_login_ping_and_conditions():
    async def run():
        got_ping=asyncio.Event();real=[];received=[]
        async def ws_handler(ws):
            async for raw in ws:
                msg=json.loads(raw);received.append(msg);tr=msg['trnm']
                if tr=='LOGIN':
                    await ws.send(json.dumps({'trnm':'LOGIN','return_code':0}));await ws.send(json.dumps({'trnm':'PING','heartbeat':1}))
                elif tr=='PING':got_ping.set()
                elif tr=='CNSRLST':await ws.send(json.dumps({'trnm':tr,'return_code':0,'data':[['7','검증조건']]}))
                elif tr=='CNSRREQ':
                    await ws.send(json.dumps({'trnm':'REAL','data':[{'type':'02','values':{'843':'I','9001':'A005930','841':'7'}}]}))
                    await ws.send(json.dumps({'trnm':tr,'return_code':0,'data':[{'jmcode':'A005930'}]}))
                else:await ws.send(json.dumps({'trnm':tr,'return_code':0}))
        async def handler(request):
            if request.url.path=='/oauth2/token':return httpx.Response(200,json={'token':'dummy','expires_dt':'20991231235959'})
            return httpx.Response(200,json={'return_code':0,'acctNo':'1234567890'})
        async def event(obj):real.append(obj)
        async def noop():pass
        async with serve(ws_handler,'127.0.0.1',0) as server:
            port=server.sockets[0].getsockname()[1]
            b=Kiwoom('mock',event,noop,transport=httpx.MockTransport(handler),ws_url=f'ws://127.0.0.1:{port}');b.interval=0
            assert await b.login('testkey','testsecret')=='1234567890'
            assert (await b.conditions())[0]['sequence']=='7'
            assert (await b.condition('7'))['data'][0]['jmcode']=='A005930'
            await asyncio.wait_for(got_ping.wait(),2);await asyncio.sleep(.03)
            assert real[0]['trnm']=='REAL';assert any(m['trnm']=='REG' and m['data'][0]['type']==['00','04'] for m in received)
            await b.close()
    asyncio.run(run())

def test_dpapi_and_single_instance(tmp_path):
    if os.name=='nt':assert crypt(crypt(b'test-only'),True)==b'test-only'
    a=SingleInstance(tmp_path/'lock');b=SingleInstance(tmp_path/'lock');a.acquire()
    try:
        with pytest.raises(RuntimeError):b.acquire()
    finally:a.release()

def test_frozen_engine_bytes_and_javascript_parity():
    if not (ROOT/'baseline/frozen/s43r_engine.py').exists():
        pytest.skip('Optional local frozen reference is not included in the public app repository')
    assert (ROOT/'backend/strategy.py').read_bytes()==(ROOT/'baseline/frozen/s43r_engine.py').read_bytes()
    cfg=StrategyConfig('20261002');bars=demo_cases(cfg.target_date)[0]['candles'];last=0
    for b in bars:
        ts=int(datetime.strptime(b['date']+b['time'],'%Y%m%d%H%M').replace(tzinfo=KST).timestamp());b['timestamp']=max(last+1,ts);last=b['timestamp']
    request=json.dumps({'candles':bars,'config':asdict(cfg)})+'\n'
    result=subprocess.run(['node',str(ROOT/'baseline/frozen/scripts/s43r_oracle.cjs')],input=request,text=True,encoding='utf8',capture_output=True,timeout=15,env={**os.environ,'TZ':'Asia/Seoul'})
    assert result.returncode==0,result.stderr
    oracle=json.loads(result.stdout);actual=evaluate(bars,cfg)
    assert len(actual['events'])==len(oracle['events'])
    for a,b in zip(actual['events'],oracle['events']):
        assert a['fraction']==pytest.approx(b['fraction'],abs=1e-14)
        assert {k:v for k,v in a.items() if k!='fraction'}=={k:v for k,v in b.items() if k!='fraction'}
    assert actual['pnl']==pytest.approx(oracle['pnl'],abs=1e-9)


def test_no_order_if_quote_expires_in_rest_queue():
    async def run():
        calls=[]
        async def handler(request):calls.append(request);return httpx.Response(200,json={'return_code':0,'ord_no':'1'})
        async def noop(*a):pass
        b=Kiwoom('mock',noop,noop,transport=httpx.MockTransport(handler));b.token='test';b.expires=time.time()+1000;b.interval=0
        with pytest.raises(BrokerError):await b.submit('buy','005930',1,10000,deadline=time.time()-1)
        assert not calls;await b.close()
    asyncio.run(run())

def test_same_trnm_timeout_cannot_consume_late_response():
    async def run():
        class FakeWS:
            async def send(self,payload):pass
            async def close(self):pass
        async def noop(*a):pass
        b=Kiwoom('mock',noop,noop);b.ws=FakeWS()
        with pytest.raises(BrokerError):await b.request({'trnm':'CNSRLST'},timeout=.001)
        with pytest.raises(BrokerError,match='재접속'):await b.request({'trnm':'CNSRLST'},timeout=.001)
        await b.close()
    asyncio.run(run())

def test_cumulative_volume_gap_isolates_symbol(tmp_path):
    async def run():
        rt=Runtime(tmp_path);w=rt.add_watch('005930');w.update(ready=True,builder=TickBars(),volume=100)
        rt.armed=rt.entries=True
        await rt.tick(w,{'20':'090501','10':'10000','15':'5','13':'111','290':'2','_received':time.time()})
        assert not w['ready'];assert w['entry_blocked']
        assert rt.armed and rt.entries
        assert not rt.ledger.orders
        await rt.stop()
    asyncio.run(run())

def test_gap_on_held_symbol_escalates_to_entries(tmp_path):
    async def run():
        rt=Runtime(tmp_path);w=rt.add_watch('005930');w.update(ready=True,builder=TickBars(),volume=100)
        rt.ledger.positions['005930']={'code':'005930','qty':10,'entry_qty':10,'entry_amount':100000.0,'avg':10000.0,'realized':0.0,'stages':{},'entered':True,'closed':False,'entry_time':None,'high':0.0}
        rt.armed=rt.entries=True
        await rt.tick(w,{'20':'090501','10':'10000','15':'5','13':'111','290':'2','_received':time.time()})
        assert rt.armed and not rt.entries
        await rt.stop()
    asyncio.run(run())

def test_snapshot_does_not_invent_early_capture(tmp_path,monkeypatch):
    from backend import runtime as module
    async def run():
        rt=Runtime(tmp_path);rt.date='20261002';rt.settings.mode='paper';rt.connected=True
        rt.conditions=[{'sequence':'7','name':'test'}]
        class Broker:
            async def condition(self,s):return {'data':[{'jmcode':'A005930'}]}
            async def register(self,*a,**k):pass
            async def close(self):pass
        rt.broker=Broker()
        async def warm(c):pass
        rt.warm=warm
        monkeypatch.setattr(module,'now',lambda:datetime(2026,10,2,9,4,tzinfo=KST))
        await rt.subscribe('7');assert rt.frozen;assert not rt.freeze_codes;assert not rt.watch['005930']['eligible']
        await rt.stop()
    asyncio.run(run())

def test_actual_capture_boundary_uses_receive_time(tmp_path):
    rt=Runtime(tmp_path);rt.date='20261002';rt.connected=rt.subscribed=rt.snapshot_received=True;rt.members={'005930'};w=rt.add_watch('005930')
    rt.freeze_due(datetime(2026,10,2,9,2,59,tzinfo=KST).timestamp());assert not rt.frozen
    rt.freeze_due(datetime(2026,10,2,9,3,0,tzinfo=KST).timestamp());assert rt.freeze_codes=={'005930'};assert w['eligible']
    rt.members.add('000660');rt.freeze_due(datetime(2026,10,2,9,3,1,tzinfo=KST).timestamp());assert '000660' not in rt.freeze_codes
    rt.store.close()

def test_real_orders_require_account_confirmation(tmp_path):
    async def run():
        rt=Runtime(tmp_path);rt.settings.mode='live';rt.settings.connection='live';rt.connected=rt.subscribed=rt.reconciled=True;rt.account='1234567890'
        async def rec():return []
        rt.reconcile=rec
        with pytest.raises(ValueError,match='확인'):await rt.control('arm','자동매매 시작')
        assert not rt.armed;await rt.control('arm','실거래 시작 7890');assert rt.armed
        await rt.control('halt');assert not rt.armed;rt.connected=False;await rt.stop()
    asyncio.run(run())

def test_config_cannot_change_under_open_order(tmp_path):
    rt=Runtime(tmp_path);rt.ledger.create('005930','buy',1,10000,'test','unique')
    with pytest.raises(ValueError):rt.configure(rt.settings.model_dump())
    rt.store.close()


def test_replay_report_survives_restart(tmp_path):
    async def run():
        rt=Runtime(tmp_path);rt.settings.replay_speed=500
        await rt.replay();await rt.replay_task
        count=len(rt.ledger.orders);date=rt.date;await rt.stop()
        rt2=Runtime(tmp_path);s=rt2.state()
        assert len(s['orders'])==count;assert len(s['watch'])==3;assert s['date']==date;assert s['progress']==1
        assert not s['armed'];assert len(rt2.chart('900001')['bars'])>0
        await rt2.stop()
    asyncio.run(run())


def test_late_fee_update_is_idempotent(ledger):
    o=buy(ledger);ledger.fill(o,10,100000,'one',0)
    ledger.fill(o,10,100000,'one',120);ledger.fill(o,10,100000,'one',120)
    assert ledger.data['realized']==-120;assert ledger.positions['005930']['qty']==10
    assert len(ledger.data['fills'])==1
