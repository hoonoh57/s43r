"""차트 데이터(키움 조회 + 실시간 틱)와 자동/반자동/수동 매매 확장. runtime.py 주문 경로를 그대로 사용한다."""
import asyncio,copy,math,time,uuid
from datetime import datetime,timezone
from fastapi import Request
from fastapi.responses import FileResponse,JSONResponse
from .config import ROOT
from .runtime import Runtime
from .broker import BrokerError
from .market import KST,now,number,symbol
from .strategy import Indicators

MODES={'auto':'자동','semi':'반자동','manual':'수동'}
APPROVAL_SEC=30
PATH='/api/dostk/chart'
PRE_BARS=150
MAX_RAW=60000
LISTS=('stk_tic_chart_qry','stk_min_pole_chart_qry','stk_dt_pole_chart_qry')
TF={'s360':{'kind':'strategy'}}
for _n in (1,3,5,10,30):TF[f't{_n}']={'kind':'tick','api':'ka10079','scope':str(_n),'k':1,'size':_n}
TF['t120']={'kind':'tick','api':'ka10079','scope':'30','k':4,'size':120}
TF['t360']={'kind':'tick','api':'ka10079','scope':'30','k':12,'size':360}
for _n in (1,3,5,10,15,30,60):TF[f'm{_n}']={'kind':'min','api':'ka10080','scope':str(_n),'k':1,'n':_n}
TF['d']={'kind':'day','api':'ka10081','k':1}

def wall(date,tm):
    # 한국 벽시계 시각을 UTC로 취급 -> 차트 축이 그대로 KST로 보인다.
    return int(datetime.strptime(date+tm,'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).timestamp())
def wall_epoch(ep):
    d=datetime.fromtimestamp(float(ep),KST);return wall(d.strftime('%Y%m%d'),d.strftime('%H%M%S'))
def rnd(x):
    return None if x is None or not math.isfinite(x) else round(float(x),4)
def parse(r):
    ts=str(r.get('cntr_tm') or r.get('dt') or '').strip()
    if len(ts)==8 and ts.isdigit():date,tm=ts,'000000'
    elif len(ts)==14 and ts.isdigit():date,tm=ts[:8],ts[8:]
    else:return None
    c=abs(number(r.get('cur_prc')))
    if not c:return None
    o=abs(number(r.get('open_pric'))) or c;h=abs(number(r.get('high_pric'))) or c;l=abs(number(r.get('low_pric'))) or c
    return {'date':date,'tm':tm,'open':o,'high':max(h,o,c),'low':min(l,o,c),'close':c,'volume':abs(number(r.get('trde_qty')))}
def rows_of(data):
    for k in LISTS:
        if isinstance(data.get(k),list):return data[k]
    for v in data.values():
        if isinstance(v,list) and v and isinstance(v[0],dict):return v
    return []
def aggregate(rows,k):
    if k==1:return rows
    out=[];cur=None;n=0;day=None
    for r in rows:
        if r['date']!=day:
            if cur:out.append(cur)
            cur=None;n=0;day=r['date']
        if cur is None:cur=dict(r)
        else:cur.update(high=max(cur['high'],r['high']),low=min(cur['low'],r['low']),close=r['close'],volume=cur['volume']+r['volume'],tm=r['tm'])
        n+=1
        if n==k:out.append(cur);cur=None;n=0
    if cur:out.append(cur)
    return out
def bucket(tm,n,label):
    m=int(tm[:2])*60+int(tm[2:4]);base=9*60
    q=base+((m-base)//n)*n if m>=base else m
    if label=='end':q+=n
    return f'{q//60:02d}{q%60:02d}00'

class ChartInd(Indicators):
    def step(self,b):
        v=super().step(b);v['st']=self.up if self.trend==1 else self.down;return v

class Calc:
    # mode='start': 틱 봉은 직전 봉의 마지막 체결 시각으로 표시해 진행 중인 봉의 시각이 바뀌지 않게 한다.
    def __init__(self,today,daily=False,mode='own'):
        self.ind=ChartInd(today);self.daily=daily;self.mode=mode;self.day=None;self.pv=self.vol=0.0;self.last=0;self.prev=None
    def step(self,b):
        v=self.ind.step(b)
        if b['date']!=self.day:self.day=b['date'];self.pv=self.vol=0.0
        self.pv+=(b['high']+b['low']+b['close'])/3*b['volume'];self.vol+=b['volume']
        if self.mode=='start':
            lab=self.prev if self.prev and self.prev[0]==b['date'] else (b['date'],'090000' if b['tm']>='090000' else b['tm'])
            self.prev=(b['date'],b['tm'])
        else:lab=(b['date'],b['tm'])
        t=max(wall(*lab),self.last+1);self.last=t
        return {'t':t,'o':b['open'],'h':b['high'],'l':b['low'],'c':b['close'],'v':b['volume'],
                'vwap':None if self.daily else rnd(self.pv/self.vol if self.vol else b['close']),
                'st':rnd(v.get('st')),'tr':v.get('trend'),'jma':rnd(v.get('jma')),'macd':rnd(v.get('macd'))}

class Series:
    def __init__(self,code,tf):
        self.code=code;self.tf=tf;self.spec=TF[tf];self.raw=[];self.bars=[];self.key='';self.more=True;self.rev=0
        self.lock=asyncio.Lock();self.loaded=self.refreshed=0.0;self.refreshing=False;self.used=time.time();self.label='start'
        self.calc=None;self.out=[];self.m=0;self.crev=-1

class ChartService:
    def __init__(self,rt):self.rt=rt;self.series={}
    def busy(self):
        t=now().strftime('%H%M')
        return '0858'<=t<='0906' and any(not w['ready'] for w in self.rt.watch.values())
    def get(self,code,tf):
        key=(code,tf);s=self.series.get(key)
        if not s:
            if len(self.series)>=12:
                old=min(self.series.values(),key=lambda x:x.used);self.series.pop((old.code,old.tf),None)
            s=self.series[key]=Series(code,tf)
        s.used=time.time();return s
    def body(self,s):
        if s.spec['kind']=='day':return {'stk_cd':s.code,'base_dt':now().strftime('%Y%m%d'),'upd_stkpc_tp':'1'}
        return {'stk_cd':s.code,'tic_scope':s.spec['scope'],'upd_stkpc_tp':'0'}
    async def page(self,s,cont='N',key=''):
        b=self.rt.broker
        if not (self.rt.connected and b):raise ValueError('키움 접속 후 조회할 수 있습니다. (전략 360틱은 접속 없이 표시)')
        data,h=await b.post(s.spec['api'],PATH,self.body(s),cont=cont,key=key)
        rows=[x for x in (parse(r) for r in rows_of(data)) if x];rows.reverse()
        nk=h.get('next-key','');return rows,nk,(h.get('cont-yn','N')=='Y' and bool(nk))
    def rebuild(self,s):
        s.bars=aggregate(s.raw,s.spec['k'])
        if len(s.raw)>MAX_RAW:s.more=False
    def detect(self,s):
        t=now();last=s.raw[-1] if s.raw else None
        if not last or last['date']!=t.strftime('%Y%m%d') or not '0900'<=t.strftime('%H%M')<'1530':return 'start'
        return 'end' if int(last['tm'][:2])*60+int(last['tm'][2:4])>t.hour*60+t.minute else 'start'
    async def initial(self,s):
        today=now().strftime('%Y%m%d');limit=2 if self.busy() else (6 if s.tf=='t1' else 10)
        raw=[];key='';cont='N';more=True;pages=0
        while more and pages<limit:
            rows,key,more=await self.page(s,cont,key);cont='Y';pages+=1;raw=rows+raw
            bars=aggregate(raw,s.spec['k'])
            if s.spec['kind']=='day':
                if len(bars)>=250:break
            elif sum(b['date']<today for b in bars)>=PRE_BARS:break
        s.raw=raw;s.key=key;s.more=more;s.loaded=s.refreshed=time.time();s.rev+=1;self.rebuild(s)
        if s.spec['kind']=='min':s.label=self.detect(s)
    def compute(self,s,full=True):
        bars=s.bars;n=len(bars)
        if s.calc is None or s.crev!=s.rev or s.m>max(n-1,0):
            s.calc=Calc(self.rt.date,s.spec['kind']=='day','start' if s.spec['kind']=='tick' else 'own');s.out=[];s.m=0;s.crev=s.rev
        while s.m<n-1:s.out.append(s.calc.step(bars[s.m]));s.m+=1
        if not n:return []
        last=copy.deepcopy(s.calc).step(bars[-1])
        return s.out+[last] if full else s.out[-2:]+[last]
    def pack(self,s):return {'rev':s.rev,'more':s.more,'bars':self.compute(s),'meta':self.meta(s.code,s)}
    def check(self,code,tf):
        if tf not in TF:raise ValueError('지원하지 않는 타임프레임')
        return symbol(code)
    async def load(self,code,tf):
        code=self.check(code,tf)
        if tf=='s360':return self.strategy(code)
        s=self.get(code,tf)
        async with s.lock:
            if not s.raw or (self.rt.connected and time.time()-s.loaded>600):await self.initial(s)
            return self.pack(s)
    async def older(self,code,tf):
        code=self.check(code,tf)
        if tf=='s360':raise ValueError('전략 360틱은 시드 범위만 표시합니다. 더 긴 과거는 "360틱 (키움 조회)"을 선택하세요.')
        s=self.get(code,tf)
        async with s.lock:
            if not s.raw:
                await self.initial(s);return self.pack(s)
            if s.more:
                rows,key,more=await self.page(s,'Y',s.key)
                s.raw=rows+s.raw;s.key=key;s.more=more;s.rev+=1;self.rebuild(s)
            return self.pack(s)
    async def refresh(self,s):
        try:
            async with s.lock:
                rows,_,_=await self.page(s)
                if rows and s.raw:
                    before=(len(s.raw),dict(s.raw[-1]))
                    k0=(rows[0]['date'],rows[0]['tm'])
                    s.raw=[r for r in s.raw if (r['date'],r['tm'])<=k0]+[r for r in rows if (r['date'],r['tm'])>k0]
                    self.rebuild(s)
                    if (len(s.raw),s.raw[-1])!=before:s.rev+=1
        except asyncio.CancelledError:raise
        except Exception:pass
        finally:s.refreshed=time.time();s.refreshing=False
    def tail(self,code,tf):
        code=self.check(code,tf)
        if tf=='s360':
            d=self.strategy(code);return {'rev':d['rev'],'bars':d['bars'][-3:],'meta':d['meta']}
        s=self.series.get((code,tf))
        if not s or not s.raw:return {'rev':-1,'bars':[],'meta':{}}
        s.used=time.time()
        if s.spec['kind']=='tick' and not s.refreshing and self.rt.connected and time.time()-s.refreshed>(20 if self.busy() else 8):
            s.refreshing=True;self.rt.task(self.refresh(s))
        return {'rev':s.rev,'bars':self.compute(s,False),'meta':self.meta(code,s)}
    def strategy(self,code):
        w=self.rt.watch.get(code)
        if not w:raise ValueError('감시 목록에 없는 종목입니다. 다른 타임프레임을 선택하면 키움 조회로 표시합니다.')
        src=list(w['bars'])
        part=w['builder'].bar if w.get('builder') is not None and w.get('ready') else None
        if part:src.append(part)
        bars=[]
        for x in src:
            ft=str(x.get('full_time') or '')
            bars.append({'date':str(x['date']),'tm':ft if len(ft)==6 else str(x['time']).zfill(4)+'00','open':float(x['open']),'high':float(x['high']),'low':float(x['low']),'close':float(x['close']),'volume':float(x['volume'])})
        calc=Calc(self.rt.date,False,'start')
        return {'rev':id(w['engine']),'more':False,'bars':[calc.step(b) for b in bars],'meta':self.meta(code)}
    def name(self,code):
        w=self.rt.watch.get(code);names=getattr(self.rt,'names',None) or {}
        n=(w or {}).get('name')
        if n and n!=code:return n
        return (names.get(code) if isinstance(names,dict) else None) or code
    def meta(self,code,s=None):
        w=self.rt.watch.get(code);e=w['engine'] if w else None;p=self.rt.ledger.positions.get(code)
        held=bool(p and p.get('qty',0)>0)
        return {'code':code,'name':self.name(code),'baseline':float(e.base_price or 0) if e else 0,'capture':float(e.capture_price or 0) if e else 0,
                'avg':float(p.get('avg',0)) if held else 0,'qty':p.get('qty',0) if held else 0,'more':s.more if s else False,'markers':self.markers(code)}
    def markers(self,code):
        out=[]
        for o in self.rt.ledger.orders:
            if o.get('code')!=code or not o.get('created'):continue
            out.append({'t':wall_epoch(o['created']),'side':o.get('side'),'text':('매수 ' if o.get('side')=='buy' else '매도 ')+str(o.get('qty','')),'status':o.get('status','')})
        for g in getattr(self.rt,'signal_log',[]):
            if g['code']==code:out.append({'t':wall_epoch(g['time']),'side':'signal','kind':g['kind'],'text':'신호'})
        return out[-200:]
    def _new(self,date,tm,price,qty):return {'date':date,'tm':tm,'open':price,'high':price,'low':price,'close':price,'volume':qty}
    def _upd(self,b,price,qty):b['high']=max(b['high'],price);b['low']=min(b['low'],price);b['close']=price;b['volume']+=qty
    def on_tick(self,code,date,tm,price,qty):
        for (c,_),s in list(self.series.items()):
            if c!=code or not s.bars:continue
            sp=s.spec;last=s.bars[-1]
            if sp['kind']=='day':
                if last['date']==date:self._upd(last,price,qty)
                elif date>last['date']:s.bars.append(self._new(date,'000000',price,qty))
            elif sp['kind']=='min':
                lab=bucket(tm,sp['n'],s.label)
                if last['date']==date and last['tm']==lab:self._upd(last,price,qty)
                elif (date,lab)>(last['date'],last['tm']):s.bars.append(self._new(date,lab,price,qty))
            elif sp['size']==1 and (date,tm)>=(last['date'],last['tm']):s.bars.append(self._new(date,tm,price,qty))
            elif last['date']==date:self._upd(last,price,qty)

class TradeRuntime(Runtime):
    def __init__(self,folder):
        super().__init__(folder)
        m=self.store.get('trade_mode');self.trade_mode=m if m in MODES else 'auto'
        self.approvals={};self.signal_log=[];self.holds=set(self.store.get('trade_holds') or []);self.charts=ChartService(self)
    def note(self,w,sig,text):
        self.signal_log.append({'code':w['code'],'kind':sig.get('kind'),'reason':str(sig.get('reason','')),'price':float(sig.get('price') or 0),'time':float(sig.get('time') or time.time()),'note':text})
        self.signal_log=self.signal_log[-300:]
    async def signals(self,w,signals):
        out=[]
        for sig in signals or []:
            code=w['code'];entry=sig.get('kind')=='entry'
            if entry and code in self.holds:
                self.note(w,sig,'대기 종목 · 자동 진입 제외');continue
            if self.trade_mode=='manual':
                self.note(w,sig,'수동 모드 · 표시만');continue
            if not self.armed:
                self.note(w,sig,'자동매매 OFF · 표시만');continue
            if self.trade_mode=='semi' and entry:
                if self.entries and w['eligible']:
                    aid=uuid.uuid4().hex[:10];t=time.time()
                    self.approvals[aid]={'id':aid,'code':code,'name':self.charts.name(code),'price':float(sig['price']),'reason':sig.get('reason',''),'created':t,'expires':t+APPROVAL_SEC,'sig':dict(sig)}
                    self.note(w,sig,'반자동 · 승인 대기');self.event('signal',f'{code} 진입 신호 · {APPROVAL_SEC}초 안에 승인하세요','warning')
                else:self.note(w,sig,'진입 제외 (중지/대상 아님)')
                continue
            ok=(not entry) or (self.entries and w['eligible'])
            self.note(w,sig,'자동 주문' if ok else '진입 제외 (중지/대상 아님)');out.append(sig)
        if out:await super().signals(w,out)
    async def tick(self,w,v,allow=True):
        before=w['volume']
        await super().tick(w,v,allow)
        if w['volume']>before and w['quote'].get('price'):
            try:self.charts.on_tick(w['code'],self.date,str(v.get('20','')).zfill(6),float(w['quote']['price']),float(w['volume']-before))
            except Exception:pass
    def set_mode(self,mode):
        if mode not in MODES:raise ValueError('auto / semi / manual 중 하나를 선택하세요.')
        self.trade_mode=mode;self.store.put('trade_mode',mode)
        if mode!='semi':self.approvals={}
        extra=' · 자동 청산 포함 모든 자동 주문 꺼짐' if mode=='manual' else ''
        self.event('control','매매 방식: '+MODES[mode]+extra,'warning' if mode=='manual' else 'info')
    def set_hold(self,code,hold):
        code=symbol(code)
        if hold:self.holds.add(code)
        else:self.holds.discard(code)
        self.store.put('trade_holds',sorted(self.holds));self.event('control',code+(' 대기 · 자동 진입 제외' if hold else ' 대기 해제'))
    async def manual(self,action,code,confirm=False):
        if not confirm:raise ValueError('주문 확인이 필요합니다.')
        code=symbol(code)
        if action=='cancel':
            pend=self.ledger.pending(code)
            if not pend:raise ValueError('이 종목의 앱 미체결 주문이 없습니다.')
            for o in pend:await self.cancel(o)
            self.event('manual',code+' 수동 미체결 취소 요청');return f'취소 요청 {len(pend)}건'
        if action not in ('buy','exit'):raise ValueError('알 수 없는 수동 주문')
        if self.settings.mode=='record':raise ValueError('기록 전용 모드에서는 주문할 수 없습니다.')
        if self.settings.broker_mode() and not self.connected:raise ValueError('키움 접속이 필요합니다.')
        p=self.ledger.positions.get(code);w=self.watch.get(code);n=len(self.ledger.orders)
        if action=='exit':
            if not p or p.get('qty',0)<=0:raise ValueError('앱 원장에 보유 수량이 없습니다.')
            if w is None:w=self.add_watch(code,self.charts.name(code))
            async with w['lock']:
                w['intents']=[]
                for o in self.ledger.pending(code):await self.cancel(o)
                if self.ledger.pending(code):raise ValueError('기존 미체결 취소 확인 중입니다. 잠시 후 다시 누르세요.')
                await self.send(w,{'kind':'exit','reason':'수동청산','price':float(w['quote'].get('price') or p['avg']),'time':int(time.time())})
        else:
            if p and (p.get('entered') or p.get('qty',0)>0):raise ValueError('이미 진입한 종목입니다. (1일 1회 진입)')
            if w is None or not w.get('quote'):raise ValueError('감시 중이고 실시간 시세가 있는 종목만 수동 매수할 수 있습니다.')
            q=w['quote']
            async with w['lock']:
                await self.send(w,{'kind':'entry','reason':'수동매수','price':float(q.get('ask') or q.get('price')),'time':int(time.time())})
        if len(self.ledger.orders)==n:raise ValueError('주문이 전송되지 않았습니다. 이벤트 기록(시세 지연/한도/계좌 대조)을 확인하세요.')
        o=self.ledger.orders[-1];label='매수' if action=='buy' else '청산'
        self.event('manual',f"{code} 수동 {label} {o['qty']}주 · {o['status']}")
        return f"{o['qty']}주 {o['status']}"
    def expire(self):
        t=time.time()
        for k in [k for k,a in self.approvals.items() if a['expires']<t]:
            a=self.approvals.pop(k);self.event('signal',a['code']+' 승인 시간 초과 · 진입하지 않음','warning')
    async def approve(self,aid,reject=False):
        self.expire();a=self.approvals.pop(aid,None)
        if not a:raise ValueError('승인 대기가 없거나 만료되었습니다.')
        if reject:
            self.event('signal',a['code']+' 진입 신호 거절');return '거절'
        if not (self.armed and self.entries):raise ValueError('자동매매 OFF 또는 신규 진입 중지 상태입니다.')
        w=self.watch.get(a['code']);n=len(self.ledger.orders)
        if w is None:raise ValueError('감시 목록에 없는 종목')
        async with w['lock']:await self.send(w,a['sig'])
        if len(self.ledger.orders)==n:raise ValueError('주문 미전송 · 이벤트 기록(추격 한도 등)을 확인하세요.')
        return '승인 주문 전송'
    def state(self):
        s=super().state();self.expire()
        s.update(trade_mode=self.trade_mode,holds=sorted(self.holds),signal_log=self.signal_log[-30:],
                 approvals=[{k:v for k,v in a.items() if k!='sig'} for a in self.approvals.values()])
        return s

def register(app,body):
    def err(e):
        m=str(e) if isinstance(e,(ValueError,BrokerError)) else '차트 처리 오류: '+type(e).__name__
        return JSONResponse({'detail':m[:400]},status_code=400)
    @app.get('/chart')
    async def chart_page():return FileResponse(ROOT/'frontend/chart.html')
    @app.get('/api/bars/{code}')
    async def bars(code:str,tf:str='s360',op:str='load'):
        c=app.state.runtime.charts
        try:
            if op=='tail':return c.tail(code,tf)
            if op=='older':return await c.older(code,tf)
            return await c.load(code,tf)
        except Exception as e:return err(e)
    @app.post('/api/trade')
    async def trade(request:Request):
        d=await body(request);rt=app.state.runtime;a=str(d.get('action',''))
        async with rt.control_lock:
            if a=='mode':
                rt.set_mode(str(d.get('mode','')));return {'ok':True}
            if a=='hold':
                rt.set_hold(str(d.get('code','')),bool(d.get('hold')));return {'ok':True}
            if a=='approve':return {'ok':True,'message':await rt.approve(str(d.get('id','')),bool(d.get('reject')))}
            return {'ok':True,'message':await rt.manual(a,str(d.get('code','')),bool(d.get('confirm')))}
# END extras.py
