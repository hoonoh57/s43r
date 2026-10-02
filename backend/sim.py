"""1틱 리플레이 시뮬레이터. 실전과 같은 TickBars + S43REngine.step으로 봉 조립과 신호 판정, 다음 틱 체결 모델(시뮬레이션 전용, 실전 원장과 분리)."""
import asyncio,dataclasses,json,math,pathlib
from datetime import datetime,timezone
from fastapi import Request
from fastapi.responses import FileResponse
from .config import ROOT
from .market import TickBars
from .strategy import S43REngine,StrategyConfig,SOURCE_SHA256
DIR=ROOT/'ticks'
SKIP=('target_date','utc_offset_minutes')
def r(x):return None if x is None or not math.isfinite(float(x)) else round(float(x),4)
def defaults():return {f.name:f.default for f in dataclasses.fields(StrategyConfig) if f.name not in SKIP}
def tick_unit(p):
    for lim,u in ((2000,1),(5000,5),(20000,10),(50000,50),(200000,100),(500000,500)):
        if p<lim:return u
    return 1000
def wall(date,ft):return int(datetime.strptime(date+ft,'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).timestamp())
def files():
    DIR.mkdir(exist_ok=True);out=[]
    for p in sorted(DIR.glob('*.json'),reverse=True):
        try:d=json.loads(p.read_text(encoding='utf-8'))
        except Exception:continue
        out.append({'file':p.name,'code':d.get('code'),'name':d.get('name',''),'date':d.get('date'),'prior':d.get('prior_dates',[]),'ticks':len(d.get('ticks',[]))})
    return out
def load(name):
    p=DIR/pathlib.Path(str(name)).name
    if not p.is_file():raise ValueError('틱 파일이 없습니다: '+p.name)
    d=json.loads(p.read_text(encoding='utf-8'))
    if not d.get('ticks') or not d.get('date'):raise ValueError('틱 데이터가 비어 있습니다.')
    return d
def config(date,params):
    base=defaults();kw={}
    for k,v in (params or {}).items():
        if k not in base:continue
        t=type(base[k])
        kw[k]=(v is True or str(v).lower() in ('true','1','on')) if t is bool else str(v).replace(':','').zfill(4) if t is str else float(v)
    return StrategyConfig(target_date=date,**kw)
def simulate(d,size=360,params=None,slip=1,cost_pct=0.25,capital=1_000_000):
    date=str(d['date']);cfg=config(date,params);e=S43REngine(cfg);tb=TickBars(int(size))
    size=int(size);slip=int(slip);cost_pct=float(cost_pct);capital=float(capital)
    if not 10<=size<=3000:raise ValueError('틱 수는 10~3000')
    bars=[];fills=[];signals=[];queue=[];eq=[];st={'qty':0,'eq':0,'avg':0.0,'real':0.0,'t':0}
    start=-1
    def fill(s,p):
        u=tick_unit(p);k=s['kind']
        if k=='entry':
            if st['qty']:return
            px=p+slip*u;n=int(capital//(px*(1+cost_pct/200)))
            if n<=0:return
            st.update(qty=n,eq=n,avg=px);fee=px*n*cost_pct/200;st['real']-=fee
        else:
            n=st['qty'] if k=='exit' else min(st['qty'],int(st['eq']*cfg.tp_fraction))
            if n<=0:return
            px=max(u,p-slip*u);fee=px*n*cost_pct/200;st['real']+=(px-st['avg'])*n-fee;st['qty']-=n
        fills.append({'t':st['t'],'side':'buy' if k=='entry' else 'sell','kind':k,'reason':s['reason'],'qty':n,'price':px,'signal':s['price'],'fee':round(fee),'realized':round(st['real'])})
    for row in d['ticks']:
        dt=str(row[0]);tm=str(row[1]);tm=tm.zfill(6) if len(tm)>4 else tm.zfill(4)+'00';p=abs(float(row[2]));v=abs(float(row[3]))
        if not p:continue
        if queue:
            for s in queue:fill(s,p)
            queue=[]
        b=tb.tick(dt,tm,p,v)
        if not b:continue
        sig=e.step(b);val=e.values[-1] if e.values else {};ind=e.indicators
        t=max(wall(b['date'],b['full_time']),st['t']+1);st['t']=t
        if b['date']==date and start<0:start=len(bars)
        bars.append({'t':t,'date':b['date'],'tm':b['full_time'],'o':b['open'],'h':b['high'],'l':b['low'],'c':b['close'],'v':b['volume'],
            'vwap':r(val.get('vwap')),'st':r(ind.up if ind.trend==1 else ind.down),'tr':ind.trend,'jma':r(val.get('jma')),'macd':r(val.get('macd')),'cum':r(val.get('cum')),'base':r(e.base_price) or None})
        for s in sig:signals.append({'t':t,'kind':s['kind'],'reason':s['reason'],'price':s['price']});queue.append(s)
        eq.append(round(st['real']+(b['close']-st['avg'])*st['qty']))
    if start<0:raise ValueError('지정일 틱이 없습니다.')
    warn=[]
    if start<40:warn.append(f'선행 봉 {start}개 · 지표 초기값 왜곡 가능 · 선행 일수를 늘려 다시 받으세요.')
    if st['qty']:warn.append(f"미청산 잔량 {st['qty']}주 · 마지막 가격으로 평가")
    day=eq[start:];peak=-1e18;mdd=0
    for x in day:peak=max(peak,x);mdd=min(mdd,x-peak)
    net=eq[-1] if eq else 0;res=e.result()
    return {'identity':{'file':d.get('file',''),'code':d.get('code'),'date':date,'size':size,'slip':slip,'cost_pct':cost_pct,'capital':capital,'engine':SOURCE_SHA256[:12],'params':dataclasses.asdict(cfg)},
        'code':d.get('code'),'name':d.get('name',''),'date':date,'start':start,'warm':start,'bars':bars,'signals':signals,'fills':fills,'equity':eq,'warnings':warn,
        'stats':{'net':net,'ret':round(net/capital*100,3),'mdd':mdd,'fills':len(fills),'entered':res['entered'],'reason':res['exitReason'],'entry':res['entryTime'],'model_pnl':round(res['pnl'],3)}}
def register_sim(app):
    async def body(request):
        try:d=await request.json()
        except Exception:raise ValueError('올바른 JSON이 필요합니다.')
        return d if isinstance(d,dict) else {}
    def args(d):return dict(size=d.get('size',360),params=d.get('params'),slip=d.get('slip',1),cost_pct=d.get('cost',0.25),capital=d.get('capital',1_000_000))
    @app.get('/sim')
    async def sim_page():return FileResponse(ROOT/'frontend/sim.html')
    @app.get('/api/sim/files')
    async def sim_files():return {'files':files(),'params':defaults(),'dir':str(DIR)}
    @app.post('/api/sim/run')
    async def sim_run(request:Request):
        d=await body(request);x=load(d.get('file',''));x['file']=d.get('file','')
        return await asyncio.to_thread(simulate,x,**args(d))
    @app.post('/api/sim/batch')
    async def sim_batch(request:Request):
        d=await body(request)
        def go():
            out=[]
            for f in files():
                try:
                    x=load(f['file']);s=simulate(x,**args(d))
                    out.append({'file':f['file'],'date':s['date'],'code':s['code'],'name':s['name'],**s['stats'],'warn':len(s['warnings'])})
                except Exception as e:out.append({'file':f['file'],'error':str(e)[:120]})
            return {'rows':out,'net':sum(r.get('net',0) for r in out)}
        return await asyncio.to_thread(go)
# END sim.py
