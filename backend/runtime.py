import asyncio,copy,json,math,time,uuid
from datetime import datetime
from dataclasses import asdict
from pathlib import Path
from .config import Settings,SettingsFile
from .storage import Store
from .vault import Vault
from .market import now,number,symbol,chart_bar,build_history,demo_cases,KST
from .strategy import S43REngine,StrategyConfig
from .broker import Kiwoom,BrokerError,OrderUnknown
from .execution import Ledger,ACTIVE,oid

POSITION_FIELDS=('entered','closed','entry_price','runner_high','entry_timestamp','exit_timestamp','entry_time','reason','pnl','p1','p2')
MAX_REWARM=3
MAX_EXIT_RETRIES=3
SETTLE_SEC=10.0
class Runtime:
    def __init__(self,folder):
        self.folder=Path(folder);self.store=Store(folder);self.settings_file=SettingsFile(folder);self.settings=self.settings_file.load();self.vault=Vault(folder)
        self.date=now().strftime('%Y%m%d');self.ledger=Ledger(self.store,'replay:last' if self.settings.mode=='replay' else 'disconnected:'+self.settings.mode);self.broker=None;self.account='';self.connected=False
        self.armed=False;self.entries=False;self.reconciled=False;self.problems=[];self.cash=0;self.cash_at=0.0;self.soft_streak=0;self.conditions=[];self.subscribed=False
        self.watch={};self.members=set();self.frozen=False;self.freeze_codes=set();self.subscription_time=None;self.snapshot_received=False
        self.tasks=set();self.replay_task=None;self.monitor_task=None;self.running=False;self.source='대기';self.progress=0;self.last_error='';self.unmatched=[]
        self.names={};self.warm_semaphore=asyncio.Semaphore(2);self.control_lock=asyncio.Lock();self.reconcile_lock=asyncio.Lock();self.feed_lock=asyncio.Lock();self.snapshot=None
        if self.settings.mode=='replay':self.restore_replay_view()
    def save_replay_view(self):
        view={'date':self.date,'source':self.source,'progress':self.progress,'watch':[]}
        for w in self.watch.values():
            view['watch'].append({k:w[k] for k in ('code','name','bars','quote','eligible','ready','status') } | {'capture':w['engine'].capture_price,'baseline':w['engine'].base_price})
        self.store.put('replay:last',self.ledger.data);self.store.put('replay:view',view)
    def restore_replay_view(self):
        view=self.store.get('replay:view')
        if not view:return
        self.date=view['date'];self.source=view['source'];self.progress=view['progress']
        for saved in view['watch']:
            w=self.add_watch(saved['code'],saved['name'])
            for key in ('bars','quote','eligible','ready','status'):w[key]=saved[key]
            w['engine'].capture_price=saved['capture'];w['engine'].base_price=saved['baseline'];w['engine'].values=[b.get('indicator',{}) for b in w['bars']]
    def event(self,kind,message,level='info'):self.store.event(kind,message,level=level)
    def task(self,coro):
        t=asyncio.create_task(coro);self.tasks.add(t);t.add_done_callback(self.tasks.discard);return t
    async def start(self):self.monitor_task=asyncio.create_task(self.monitor());self.event('system','S4.3-R 독립 앱 시작 · 자동 주문 OFF')
    async def stop(self):
        self.armed=self.entries=False
        if self.replay_task:self.replay_task.cancel()
        if self.monitor_task:self.monitor_task.cancel()
        for t in list(self.tasks):t.cancel()
        await asyncio.gather(*(list(self.tasks)+[t for t in (self.monitor_task,self.replay_task) if t]),return_exceptions=True)
        if self.broker:await self.broker.close()
        self.store.close()
    def cfg(self):
        s=self.settings
        return StrategyConfig(target_date=self.date,base_rate_pct=s.base_rate,hard_stop_pct=s.hard_stop,early_enabled=s.early_enabled,early_macd=s.early_macd)
    def add_watch(self,code,name=''):
        code=symbol(code)
        if code not in self.watch:self.watch[code]={'code':code,'name':name or self.names.get(code,code),'engine':S43REngine(self.cfg()),'bars':[],'builder':None,'volume':0,'buffer':[],'ready':False,'eligible':False,'status':'시드 대기','quote':{},'lock':asyncio.Lock(),'intents':[],'last_received':0,'entry_blocked':False,'rewarm':0}
        return self.watch[code]
    def configure(self,data):
        if self.connected or self.running or self.armed or self.ledger.pending():raise ValueError('실행/접속/미완료 주문 중에는 설정을 바꿀 수 없습니다.')
        s=Settings.model_validate(data)
        if s.mode in ('mock','live'):s.connection=s.mode
        self.settings=s;self.settings_file.save(s);self.watch={};self.ledger=Ledger(self.store,'empty:'+uuid.uuid4().hex);self.date=now().strftime('%Y%m%d');self.source='대기';self.progress=0;self.store.put('replay:view',None);self.event('settings','설정 저장 · '+s.mode)
    async def connect(self,key='',secret='',save=False):
        if self.settings.mode=='replay':raise ValueError('설정에서 기록/페이퍼/키움 모의/실계좌 모드를 선택하세요.')
        if self.connected:raise ValueError('이미 접속되어 있습니다.')
        if self.running:raise ValueError('리플레이를 먼저 중지하세요.')
        env=self.settings.connection
        if not key or not secret:
            saved=self.vault.load(env)
            if not saved:raise ValueError('App Key와 Secret Key가 필요합니다.')
            key,secret=saved['appkey'],saved['secretkey']
        if self.broker:await self.broker.close()
        broker=Kiwoom(env,self.on_event,self.disconnected);self.broker=broker
        try:
            acct=await broker.login(key,secret)
            self.account=acct;self.connected=True;self.date=now().strftime('%Y%m%d')
            self.ledger=Ledger(self.store,f'ledger:{self.settings.mode}:{env}:{acct}:{self.date}')
            self.watch={};self.members=set();self.freeze_codes=set();self.frozen=False;self.subscribed=False;self.snapshot_received=False;self.conditions=[];self.unmatched=[]
            if save:self.vault.save(env,key,secret)
            self.conditions=await broker.conditions();await self.reconcile(adopt=True);self.task(self.load_names())
            self.source='키움 '+('모의' if env=='mock' else '실서버');self.event('connect',self.source+' 접속 · 계좌 '+self.masked_account())
        except Exception:
            self.connected=False;await broker.close();raise
    def masked_account(self):return self.account[:4]+'••••'+self.account[-2:] if self.account else '미접속'
    async def disconnect(self):
        self.armed=self.entries=False;self.connected=False;self.reconciled=False;self.subscribed=False
        if self.broker:await self.broker.close()
        for t in list(self.tasks):t.cancel()
        self.event('connect','연결 종료 · 미체결 주문은 증권사에 남을 수 있습니다.')
    async def disconnected(self):
        self.armed=self.entries=False;self.connected=False;self.reconciled=False
        self.last_error='실시간 연결 중단 · 주문 중지. 재접속 후 잔고 대조와 재승인이 필요합니다.';self.event('error',self.last_error,'error')
    async def subscribe(self,seq):
        if not self.connected:raise ValueError('키움 접속이 필요합니다.')
        match=next((c for c in self.conditions if c['sequence']==str(seq)),None)
        if not match:raise ValueError('조회된 조건식 중에서 선택하세요.')
        if self.subscribed:raise ValueError('조건식 변경은 연결 종료 후 다시 접속하세요.')
        self.settings.condition_sequence=match['sequence'];self.settings.condition_name=match['name'];self.settings_file.save(self.settings)
        self.subscription_time=now();self.subscribed=True;self.snapshot_received=False
        try:obj=await self.broker.condition(seq)
        except Exception:self.subscribed=False;raise
        self.members={symbol(r.get('jmcode',r.get('9001',''))) for r in obj.get('data',[]) if r.get('jmcode') or r.get('9001')}
        self.snapshot_received=True
        self.store.record('condition_snapshot',{'sequence':str(seq),'codes':sorted(self.members),'entry_time_unknown':True})
        if now().strftime('%H%M%S')>='090300':
            self.frozen=True;self.freeze_codes=set();self.event('universe','09:03 이후 접속: 과거 편입을 추정하지 않으므로 오늘 신규 진입 대상 0개','warning')
        codes=self.members|{c for c,p in self.ledger.positions.items() if p['qty']>0 and not p.get('adopted')}|{o['code'] for o in self.ledger.pending()}
        for c in sorted(codes):self.add_watch(c)
        await self.register_ticks()
        for c in sorted(codes):self.task(self.warm(c))
        self.event('condition',match['name']+' 감시 시작 · '+str(len(self.members))+'종목')
    async def register_ticks(self):
        codes=list(self.watch)
        # Distinct groups avoid dropping subscription to existing position symbols.
        for i in range(0,len(codes),50):await self.broker.register(codes[i:i+50],group=str(100+i//50))
    async def warm(self,code):
        w=self.watch[code];failed=False;started=time.monotonic()
        async with self.warm_semaphore, w['lock']:
            try:
                w['status']='30틱 / 1틱 경계 대조 중'
                bars,builder,vol=await self.fetch_seed(code)
                w['engine']=S43REngine(self.cfg());w['bars']=[]
                for b in bars:self.indicate(w,b)
                w['builder']=builder;w['volume']=vol;w['ready']=True;w['status']='감시';self.sync(w)
                queued=w['buffer'];w['buffer']=[]
                # Warmup is read-only. Buffered old signals must never become orders.
                for v in queued:await self.tick(w,v,allow=False)
                took=time.monotonic()-started
                self.event('warm',code+' 360틱 시드 준비 완료 · '+str(len(bars))+'봉 · '+f'{took:.1f}초')
                if w['eligible'] and now().strftime('%H%M')>=w['engine'].config.entry_start:
                    self.event('warm',code+' 09:04 진입 구간 시작 후 시드 완료 · 그 전 신호는 주문하지 않았습니다.','warning')
            except asyncio.CancelledError:raise
            except Exception as e:
                failed=True;w['ready']=False;w['status']='시드 오류: '+str(e);self.event('warm',code+' '+w['status'],'warning')
        await self.fetch_name(w)
        # Auto-rewarm path: after releasing the lock, back off, then re-isolate -> retry or escalate.
        if failed and w['rewarm']>0 and self.connected:
            await asyncio.sleep(min(5*w['rewarm'],15))
            if self.connected and not w['ready']:await self.fault(code+' 재시드 실패',scope='symbol',code=code)
    async def fetch_seed(self,code):
        """30틱/1틱 경계 대조. 장중에는 조회 사이 새 체결로 마지막 30틱 봉이 바뀔 수 있어 경계 불일치만 재조회한다."""
        for attempt in range(3):
            try:
                rows=await self.broker.pages('ka10079','/api/dostk/chart',{'stk_cd':code,'tic_scope':'30','upd_stkpc_tp':'0'},'stk_tic_chart_qry',self.settings.history_pages,stop=lambda rs:sum(str(r.get('cntr_tm',''))[:8]<self.date for r in rs)>=960)
                ones=await self.broker.query('ka10079','/api/dostk/chart',{'stk_cd':code,'tic_scope':'1','upd_stkpc_tp':'0'})
                thirty=[chart_bar(r) for r in reversed(rows)];one=[chart_bar(r) for r in reversed(ones.get('stk_tic_chart_qry',[]))]
                bars,builder,vol=build_history(thirty,one,self.date)
                return bars,builder,vol
            except ValueError as e:
                if '마지막 30틱' not in str(e) or attempt==2:raise
                self.event('warm',f'{code} 30틱 경계 재조회 {attempt+1}/2')
                await asyncio.sleep(1.0+attempt)

    async def fetch_name(self,w):
        """화면 표시용 종목명(ka10001). 실패해도 운용에 영향 없음."""
        if w['name']!=w['code'] or not self.broker:return
        try:
            d=await self.broker.query('ka10001','/api/dostk/stkinfo',{'stk_cd':w['code']})
            n=str(d.get('stk_nm','')).strip()
            if n:w['name']=n
        except asyncio.CancelledError:raise
        except Exception:pass

    async def load_names(self):
        """화면 표시용 종목명 일괄 조회(ka10099 코스피/코스닥, 거래일별 캐시). 실패해도 운용에 영향 없음."""
        key='names:'+self.date;cache=dict(self.store.get(key) or {})
        if not cache and self.broker:
            for mk in ('0','10'):
                try:rows=await self.broker.pages('ka10099','/api/dostk/stkinfo',{'mrkt_tp':mk},'list',max_pages=50)
                except asyncio.CancelledError:raise
                except Exception as e:self.event('system',f'종목명 목록 조회 실패(시장 {mk}): {e}','warning');continue
                for r in rows:
                    try:c=symbol(r.get('code',''))
                    except ValueError:continue
                    n=str(r.get('name','')).strip()
                    if n:cache[c]=n
            if cache:self.store.put(key,cache)
        self.names.update(cache)
        for c,w in self.watch.items():
            if w['name']==c and c in self.names:w['name']=self.names[c]
        if cache:self.event('system',f'종목명 {len(cache)}개 로드')

    def sync(self,w):
        e=w['engine'];p=self.ledger.positions.get(w['code'])
        if not p:
            e.entered=e.closed=False;e.entry_price=e.runner_high=0;e.entry_timestamp=e.exit_timestamp=None;e.p1=e.p2=None;e.entry_time='-';return
        e.entered=p['entered'];e.closed=p['closed'];e.entry_price=p['avg'];e.entry_timestamp=p.get('entry_time') or 0
        e.runner_high=max(e.runner_high,p.get('high',0),p['avg'])
        for attr,stage in [('p1','p1'),('p2','p2')]:
            s=p['stages'].get(stage);setattr(e,attr,s['amount']/s['qty'] if s and s['qty'] else None)
    def indicate(self,w,bar):
        # Keep only indicator/time/capture changes from the reference engine.
        self.sync(w);e=w['engine'];before={k:copy.deepcopy(getattr(e,k)) for k in POSITION_FIELDS};n=len(e.events)
        signals=e.step(bar);high=e.runner_high
        for k,v in before.items():setattr(e,k,v)
        del e.events[n:]
        p=self.ledger.positions.get(w['code'])
        if p and p['qty']>0:p['high']=max(p['high'],high);e.runner_high=p['high']
        w['bars'].append({**bar,'indicator':e.values[-1] if e.values else {},'timestamp':e.last_timestamp})
        if len(w['bars'])>1200:w['bars']=w['bars'][-1200:]
        # Indicators are incremental; retain only chart history to bound memory.
        if len(e.values)>1200:e.values=e.values[-1200:]
        return signals
    def freeze_due(self,observed_at=None):
        if observed_at is None and self.broker and not self.broker.queue.empty():return
        observed=datetime.fromtimestamp(observed_at,KST) if observed_at is not None else now()
        if not (self.connected and self.subscribed and self.snapshot_received) or self.frozen or observed.strftime('%H%M%S')<'090300':return
        self.frozen=True;self.freeze_codes=set(self.members)
        for c,w in self.watch.items():w['eligible']=c in self.freeze_codes
        self.store.put('universe:'+self.date,{'codes':sorted(self.freeze_codes),'at':now().isoformat(),'condition':self.settings.condition_sequence})
        self.event('universe','09:03 실제 감시 목록 동결 · '+str(len(self.freeze_codes))+'종목')
    async def on_event(self,obj):
        self.freeze_due(obj.get('_received_at',time.time()))
        self.store.record('websocket',obj)
        for row in obj.get('data',[]):
            typ=row.get('type');v=row.get('values',{})
            if typ=='00':
                try:
                    handled=self.ledger.execution(v,self.account)
                    if not handled:self.unmatched.append(v);self.unmatched=self.unmatched[-500:]
                    for w in self.watch.values():self.sync(w)
                except Exception as e:await self.fault('체결 대조 오류: '+str(e))
            elif typ=='02':
                if str(v.get('841'))!=self.settings.condition_sequence:continue
                try:c=symbol(v.get('9001',row.get('item','')))
                except ValueError:continue
                if str(v.get('843'))=='I':
                    new=c not in self.members;self.members.add(c)
                    if self.frozen and self.settings.mode!='replay':
                        # 09:03 이후 편입은 진입 대상이 아니므로 시드/틱 등록 없이 기록만 한다(장 초반 REST 부하 절감).
                        if new and c not in self.watch:self.event('universe',c+' 09:03 이후 편입 · 진입 대상 아님(기록만)')
                    elif c not in self.watch and len(self.watch)<100:
                        self.add_watch(c);await self.register_ticks();self.task(self.warm(c))
                elif str(v.get('843'))=='D':self.members.discard(c)
            elif typ=='0B':
                try:c=symbol(row.get('item',v.get('9001','')))
                except ValueError:continue
                w=self.watch.get(c)
                if not w:continue
                v={**v,'_received':obj.get('_received_at',time.time())}
                if not w['ready']:
                    if abs(number(v.get('10'))):w['quote']={'price':abs(number(v.get('10'))),'ask':abs(number(v.get('27'))),'bid':abs(number(v.get('28'))),'received':v['_received']}
                    w['buffer'].append(v)
                    if len(w['buffer'])>100000:
                        w['buffer']=[];w['status']='수신 버퍼 초과';await self.fault(c+' 시드 중 틱 버퍼 초과',scope='symbol',code=c)
                else:
                    async with w['lock']:await self.tick(w,v)
    async def tick(self,w,v,allow=True):
        if str(v.get('290','2'))!='2':return
        tm=str(v.get('20','')).zfill(6);price=abs(number(v.get('10')));qty=abs(number(v.get('15')));cum=number(v.get('13'))
        if len(tm)!=6 or not tm.isdigit() or not price or not qty:return
        if cum<=w['volume']:return
        if abs(cum-w['volume']-qty)>1e-6:
            w['ready']=False;w['status']='틱 누락 감지 · 재시드 필요';await self.fault(w['code']+' 누적 거래량 단절',scope='symbol',code=w['code']);return
        w['volume']=cum;w['last_received']=v['_received'];w['quote']={'price':price,'ask':abs(number(v.get('27'))),'bid':abs(number(v.get('28'))),'received':v['_received']}
        bar=w['builder'].tick(self.date,tm,price,qty)
        if bar:
            sig=self.indicate(w,bar)
            if allow:await self.signals(w,sig)
            self.ledger.save()
    async def signals(self,w,signals):
        if not self.armed:return
        for sig in signals:
            if sig['kind']=='entry':
                if self.entries and w['eligible']:await self.send(w,sig)
            else:
                # Serialize exits. Full exit supersedes queued partials.
                if sig['kind']=='exit':
                    w['intents']=[sig]
                    for o in self.ledger.pending(w['code']):await self.cancel(o)
                elif not any(x['kind']=='exit' or x['reason']==sig['reason'] for x in w['intents']):w['intents'].append(sig)
        await self.drain(w)
    async def drain(self,w):
        while self.armed and w['intents'] and not self.ledger.pending(w['code']):
            if w['intents'][0].get('not_before',0)>time.time():break
            sig=w['intents'].pop(0)
            try:await self.send(w,sig)
            except ValueError as e:self.event('risk',w['code']+' '+str(e),'warning');break
    def risk_price(self,w,side,signal_price,replay=False):
        q=w['quote'];s=self.settings
        if replay:return float(signal_price)
        if side=='sell':
            if not q or time.time()-q.get('received',0)>s.quote_age_ms/1000:
                self.event('risk',w['code']+' 시세 지연 상태에서 청산 시장가 전송','warning')
                return float(q.get('bid') or q.get('price') or signal_price)
            return float(q.get('bid') or q.get('price') or signal_price)
        if not q or time.time()-q.get('received',0)>s.quote_age_ms/1000:raise ValueError('시세 지연으로 주문 보류')
        ask,bid=q.get('ask',0),q.get('bid',0)
        if not ask or not bid or ask<bid:raise ValueError('유효한 매수/매도 호가가 없습니다.')
        if (ask-bid)/bid*10000>s.max_spread_bps:raise ValueError('호가 스프레드 한도 초과')
        if ask>signal_price*(1+s.max_chase_bps/10000):raise ValueError('신호가 대비 추격 한도 초과')
        return ask
    async def send(self,w,sig):
        s=self.settings;replay=s.mode=='replay';code=w['code'];side='buy' if sig['kind']=='entry' else 'sell'
        if self.ledger.pending(code):return
        p=self.ledger.positions.get(code)
        if side=='buy' and (w.get('entry_blocked') or (p and (p['entered'] or p.get('adopted')))):return
        if side=='sell' and (not p or p['qty']<=0):return
        try:price=self.risk_price(w,side,sig['price'],replay)
        except ValueError as e:self.event('risk',code+' '+str(e),'warning');return
        stage=''
        if side=='buy':
            if not replay and (not self.reconciled or not self.connected):return
            if self.pnl_total()<=-s.daily_loss:self.entries=False;self.event('risk','일 손실 한도 · 신규 진입 중지','warning');return
            pending=self.ledger.pending();held=[p for p in self.ledger.positions.values() if p['qty']>0 and not p.get('adopted')]
            if len(held)+sum(o['side']=='buy' for o in pending)>=s.max_positions:return
            exposure=sum(p['qty']*p['avg'] for p in held)+sum((o['qty']-o['filled'])*o['price'] for o in pending if o['side']=='buy')
            budget=min(s.allocation,s.max_exposure-exposure)
            if s.broker_mode():budget=min(budget,max(0,self.available_cash())*.99)
            qty=int(budget//(price*(1+s.cost_pct/200)))
        else:
            if sig['kind']=='partial':
                stage='p1' if sig['reason'].startswith('1') else 'p2';done=p['stages'].get(stage,{}).get('qty',0)
                qty=min(p['qty'],max(0,int(p['entry_qty']*.3)-done))
            else:qty=p['qty']
        if qty<=0:return
        sid=f'{self.date}:{code}:{sig["time"]}:{sig["kind"]}:{sig["reason"]}' + (f'#r{sig["retries"]}' if sig.get('retries') else '')
        if any(o['signal_id']==sid for o in self.ledger.orders):return
        o=self.ledger.create(code,side,qty,price,sig['reason'],sid,stage,sig['time'])
        if s.broker_mode():
            deadline=w['quote'].get('received',0)+s.quote_age_ms/1000 if side=='buy' else None
            try:
                broker_id=await self.broker.submit(side,code,qty,price if side=='buy' else 0,deadline=deadline)
                self.ledger.ack(o,broker_id)
                for v in self.unmatched[:]:
                    if self.ledger.execution(v,self.account):self.unmatched.remove(v)
            except OrderUnknown as e:self.ledger.status(o,'UNKNOWN');await self.fault(str(e))
            except BrokerError as e:
                self.ledger.status(o,'REJECTED');self.event('order',code+' '+str(e),'warning')
                if side=='sell':self.retry_exit(w,sig)
            except Exception:self.ledger.status(o,'UNKNOWN');await self.fault('주문 처리 중 예외 · 결과 확인 필요')
        else:self.ledger.paper_fill(o,price,s.cost_pct)
        self.sync(w);self.event('order',f'{code} {"매수" if side=="buy" else "매도"} {qty}주 · {sig["reason"]} · {o["status"]}')
    def pnl_total(self):
        return self.ledger.data['realized']+sum((self.watch.get(c,{}).get('quote',{}).get('price',p['avg'])-p['avg'])*p['qty'] for c,p in self.ledger.positions.items() if not p.get('adopted'))
    async def fault(self,message,scope='entries',code=None):
        """scope
        - 'symbol' : 해당 종목만 격리(그 종목 신규 진입 금지 + 자동 재시드). 다른 종목은 정상 운용.
        - 'entries': 전체 신규 진입 중지. armed는 유지하여 보유분 전략 청산은 계속.
        - 'all'    : 모든 자동 주문 중지(거래일 변경 등 진짜 치명적 상황만).
        """
        self.last_error=message;self.event('error',f'[{scope}] {message}','error')
        if scope=='symbol':
            w=self.watch.get(code)
            if w is None:scope='entries'
            else:
                w['entry_blocked']=True
                if self.connected and w['rewarm']<MAX_REWARM:
                    w['rewarm']+=1;w['status']=f'시세 단절 · 자동 재시드 {w["rewarm"]}/{MAX_REWARM}'
                    self.task(self.warm(code));return
                p=self.ledger.positions.get(code)
                if not (p and p['qty']>0):w['status']='시세 단절 · 당일 제외';return
                scope='entries';self.last_error=code+' 보유 종목 시세 복구 실패 · 이 종목은 청산 감시 불가, 수동 확인 필요';self.event('error',self.last_error,'error')
        self.entries=False;self.reconciled=False
        if scope=='all':self.armed=False
    async def reconcile(self,adopt=False):
        if not self.connected:raise ValueError('키움 접속이 필요합니다.')
        async with self.reconcile_lock:
            started=time.time()
            snap=await self.broker.account_snapshot();self.snapshot=snap;self.cash=snap['cash'];self.cash_at=started;self.adopt(snap,adopt)
            hard,soft=self.ledger.reconcile_detail(snap,SETTLE_SEC) if self.settings.broker_mode() else ([],[])
            self.problems=hard+soft
            self.soft_streak=self.soft_streak+1 if soft else 0
            self.reconciled=not self.problems
            if self.armed and (hard or self.soft_streak>=2):
                await self.fault(' / '.join(self.problems),scope='entries')
            return self.problems
    def adopt(self,snap,startup=False):
        """증권사 잔고 -> 원장 동기화. 앱이 오늘 주문하지 않은 종목만 '외부 보유'로 인수(자동매매 제외)."""
        if not self.settings.broker_mode():return
        L=self.ledger;now_ts=time.time()
        busy={o['code'] for o in L.pending()}|{f['code'] for f in L.data['fills'] if now_ts-f['time']<SETTLE_SEC}
        traded={o['code'] for o in L.orders}
        actual={}
        for r in snap['holdings']:
            q=int(number(r.get('rmnd_qty')))
            if q>0:actual[symbol(r['stk_cd'])]=(q,abs(number(r.get('pur_pric'))) or abs(number(r.get('cur_prc'))),str(r.get('stk_nm','')).strip())
        changed=[]
        for c in sorted(set(actual)|{c for c,p in L.positions.items() if p.get('adopted')}):
            if c in busy:continue
            p=L.positions.get(c)
            if p is not None and not p.get('adopted'):continue
            if p is None and c in traded:continue
            q,avg,name=actual.get(c,(0,0.0,''))
            if p is None:
                if not q:continue
                L.positions[c]={'code':c,'qty':q,'entry_qty':q,'entry_amount':q*avg,'avg':avg,'realized':0.0,'stages':{},'entered':False,'closed':False,'entry_time':None,'high':0.0,'adopted':True,'name':name}
                changed.append(f'{c} {q}주 인수')
            elif p['qty']!=q:
                changed.append(f"{c} {p['qty']}->{q}주");p.update(qty=q,entry_qty=max(p['entry_qty'],q),closed=not q)
                if q and avg:p.update(avg=avg,entry_amount=q*avg)
        if changed:
            L.save();self.event('account',('기동 시 ' if startup else '')+'외부 보유 동기화 · '+', '.join(changed)+' · 자동매매 제외')
    def available_cash(self):
        """스냅샷 현금 - 미체결 매수 - 스냅샷 전후 매수 체결. 이중 차감을 허용하는 보수적 계산."""
        pend=sum((o['qty']-o['filled'])*o['price'] for o in self.ledger.pending() if o['side']=='buy')
        spent=sum(f['qty']*f['price'] for f in self.ledger.data['fills'] if f['side']=='buy' and f['time']>=self.cash_at-SETTLE_SEC)
        return self.cash-pend-spent
    def retry_exit(self,w,sig):
        n=sig.get('retries',0)+1
        if n>MAX_EXIT_RETRIES:
            self.last_error=f"{w['code']} 청산 {n-1}회 재시도 실패 · 수동 청산 필요";self.event('risk',self.last_error,'error');return
        retry={**sig,'retries':n,'not_before':time.time()+min(2**n,10)}
        if sig['kind']=='exit':w['intents']=[retry]
        else:w['intents'].insert(0,retry)
    async def control(self,action,confirmation=''):
        if action=='arm':
            if not self.connected or not self.subscribed:raise ValueError('접속 후 조건식을 구독하세요.')
            if self.settings.mode=='record':raise ValueError('기록 전용 모드입니다.')
            if any(p['qty'] and not p.get('adopted') and not self.watch.get(c,{}).get('ready') for c,p in self.ledger.positions.items()):raise ValueError('보유 종목의 시드 준비를 먼저 완료하세요.')
            await self.reconcile()
            if not self.reconciled:raise ValueError('계좌 대조 오류: '+' / '.join(self.problems))
            expected=('실거래 시작 '+self.account[-4:]) if self.settings.mode=='live' else '자동매매 시작'
            if confirmation!=expected:raise ValueError('확인 문구가 일치하지 않습니다.')
            if self.settings.mode=='live' and self.settings.connection!='live':raise ValueError('실계좌 환경 불일치')
            if self.frozen and not self.freeze_codes and not any(p['qty'] for p in self.ledger.positions.values()):raise ValueError('09:03 실제 동결 목록이 없습니다. 다음 거래일 09:03 이전부터 접속하세요.')
            if self.ledger.pending():raise ValueError('미완료 주문을 먼저 확인하세요.')
            self.armed=self.entries=True;self.last_error='';self.event('control','자동매매 시작 · '+self.settings.mode)
        elif action=='resync':
            if not self.connected:raise ValueError('접속이 필요합니다.')
            self.armed=self.entries=False
            for w in self.watch.values():w['ready']=False;w['buffer']=[];w['intents']=[];self.task(self.warm(w['code']))
            self.event('control','시세 재동기화 · 완료 후 자동매매를 다시 시작하세요.')
        elif action=='pause':self.entries=False;self.event('control','신규 진입 중지 · 보유분 전략 청산은 계속')
        elif action=='halt':self.armed=self.entries=False;self.event('control','모든 자동 주문 중지 · 증권사 미체결은 별도 취소 필요','warning')
        elif action=='stop_replay':
            if self.replay_task:self.replay_task.cancel();await asyncio.gather(self.replay_task,return_exceptions=True)
            self.running=self.armed=self.entries=False
        elif action=='cancel':
            if confirmation!='미체결 취소':raise ValueError('미체결 취소 확인이 필요합니다.')
            self.entries=False
            for o in self.ledger.pending():await self.cancel(o)
        else:raise ValueError('알 수 없는 명령')
    async def cancel(self,o):
        if not self.settings.broker_mode() or not self.connected:return
        if not o['broker_id'] or o['status'] in ('UNKNOWN','CANCEL_PENDING'):return
        self.ledger.status(o,'CANCEL_PENDING')
        try:
            o['cancel_id']=await self.broker.cancel(o['code'],o['broker_id']);self.ledger.save()
            for v in self.unmatched[:]:
                if self.ledger.execution(v,self.account):self.unmatched.remove(v)
        except Exception:await self.fault('취소 결과 확인 필요 · 자동 재취소하지 않습니다.')
    async def replay(self,cases=None,date=None):
        if self.settings.mode!='replay' or self.connected:raise ValueError('연결 종료 후 리플레이 모드를 선택하세요.')
        if self.running:raise ValueError('이미 실행 중입니다.')
        date=date or now().strftime('%Y%m%d');cases=demo_cases(date) if cases is None else cases
        if not isinstance(cases,list) or not cases or len(cases)>100:raise ValueError('cases 배열은 1~100종목이어야 합니다.')
        cleaned=[]
        for c in cases:
            code=symbol(c['code']);bars=c.get('candles',[])
            if not bars or len(bars)>100000:raise ValueError('종목별 candles는 1~100,000개여야 합니다.')
            previous=''
            if not any(str(b['date'])==date for b in bars):raise ValueError('대상 거래일 캔들이 없습니다.')
            for b in bars:
                from datetime import datetime
                datetime.strptime(str(b['date'])+str(b['time']), '%Y%m%d%H%M')
                if len(str(b['time']))!=4 or str(b['date'])>date:raise ValueError('날짜/시각 범위 오류')
                key=str(b['date'])+str(b['time'])
                if key<previous:raise ValueError('캔들은 시간 순서여야 합니다.')
                previous=key
                if any(not math.isfinite(float(b[k])) for k in ('open','high','low','close','volume')) or min(float(b[k]) for k in ('open','high','low','close'))<=0 or float(b['volume'])<0:raise ValueError('잘못된 OHLCV 값')
                if float(b['high'])<max(float(b[k]) for k in ('open','low','close')) or float(b['low'])>min(float(b[k]) for k in ('open','close')):raise ValueError('OHLC 범위 오류')
            normalized=[{**b,'date':str(b['date']),'time':str(b['time']),**{k:float(b[k]) for k in ('open','high','low','close','volume')}} for b in bars]
            cleaned.append((code,str(c.get('name',code)),normalized))
        self.date=date;self.cfg();self.watch={};self.progress=0;self.ledger=Ledger(self.store,'replay:'+uuid.uuid4().hex)
        if len({c[0] for c in cleaned})!=len(cleaned):raise ValueError('중복 종목코드')
        self.source='합성 데모' if cases[0].get('name','').startswith('데모') else '사용자 캔들 리플레이'
        for code,name,bars in cleaned:
            w=self.add_watch(code,name);w.update(ready=True,eligible=True,status='리플레이')
        self.armed=self.entries=self.running=True;self.last_error='';self.event('replay',self.source+' 시작 · 실제 주문 없음')
        self.replay_task=asyncio.create_task(self._replay(cleaned))
    async def _replay(self,cases):
        try:
            timeline=sorted((b['date'],b['time'],i,code,b) for code,name,bars in cases for i,b in enumerate(bars))
            for index,(_,_,_,code,b) in enumerate(timeline):
                w=self.watch[code];w['quote']={'price':b['close'],'bid':b['close'],'ask':b['close'],'received':time.time()}
                await self.signals(w,self.indicate(w,b));self.progress=(index+1)/len(timeline)
                if b['date']==self.date:await asyncio.sleep(1/self.settings.replay_speed)
            self.event('replay','리플레이 완료 · 잔여 포지션은 임의 종가청산하지 않습니다.');self.store.put('replay:last',self.ledger.data)
        except asyncio.CancelledError:self.event('replay','리플레이 중지');raise
        except Exception as e:self.last_error=str(e);self.event('error','리플레이 오류: '+str(e),'error')
        finally:
            self.running=self.armed=self.entries=False;self.save_replay_view()
    async def monitor(self):
        last_reconcile=0
        while True:
            try:
                await asyncio.sleep(1);self.store.flush()
                if self.connected:
                    if now().strftime('%Y%m%d')!=self.date:
                        await self.fault('거래일 변경 · 재접속 후 새로운 거래일을 시작하세요.',scope='all');await self.disconnect();continue
                    self.freeze_due()
                    if time.time()-last_reconcile>15:
                        last_reconcile=time.time();await self.reconcile()
                    if self.armed and self.pnl_total()<=-self.settings.daily_loss:self.entries=False
                    for o in self.ledger.pending():
                        if self.armed and o['status'] in ('ACCEPTED','PARTIAL') and time.time()-o['created']>self.settings.order_timeout_sec:await self.cancel(o)
                    if self.armed:
                        for w in self.watch.values():await self.drain(w)
                self.ledger.save()
            except asyncio.CancelledError:raise
            except Exception as e:await self.fault('감시 오류: '+str(e))
    def diagnose(self,w):
        """화면 표시 전용: 현재 단계와 마지막 완료 봉 기준 진입 조건 충족 여부. 주문 판단에는 사용하지 않는다."""
        e=w['engine'];cfg=e.config;v=e.values[-1] if e.values else {};bar=w['bars'][-1] if w['bars'] else None
        today=bar if bar and str(bar.get('date'))==self.date else None;tm=str(today['time']) if today else ''
        close=float(today['close']) if today else 0.0;price=w['quote'].get('price') or close
        checks={}
        if v:
            macd=v.get('macd') or 0;cum=v.get('cum') or 0
            checks={'trend':v.get('trend')==1,'macd':macd>=cfg.macd_threshold,'jma':bool(e.prev_jma>e.prev_prev_jma),'cum':cum>=cfg.min_cum_eok,'base':bool(e.base_price) and close>=e.base_price}
            checks['early']=bool(cfg.early_enabled and checks['trend'] and checks['macd'] and checks['jma'] and tm and tm<=cfg.early_until and cum>=cfg.early_cum_eok and macd>=cfg.early_macd)
        gap=(e.base_price/price-1)*100 if e.base_price and price else None
        ok=bool(checks) and checks['trend'] and checks['macd'] and checks['jma'] and checks['cum'] and (checks['base'] or checks['early'])
        p=self.ledger.positions.get(w['code'])
        if p and p['qty']>0:stage='외부 보유 · 자동매매 제외' if p.get('adopted') else '보유 중'
        elif p and p.get('closed'):stage='청산 완료'
        elif w.get('entry_blocked'):stage='진입 제외 · 시세 단절'
        elif not w['ready']:stage=w['status']
        elif self.settings.mode!='replay' and not self.frozen:stage='포착 · 09:03 동결 대기'
        elif not w['eligible']:stage='관찰 · 진입 대상 아님'
        elif not tm or tm<cfg.entry_start:stage='진입 대기 · 09:04부터'
        elif tm>cfg.entry_cutoff:stage='진입 시간 종료'
        elif ok:stage='진입 조건 충족'
        else:stage='조건 대기'
        return {'stage':stage,'checks':checks,'gap':gap,'bar_time':tm}
    def state(self):
        positions=[]
        for code,p in self.ledger.positions.items():
            last=self.watch.get(code,{}).get('quote',{}).get('price',p['avg']);positions.append({**p,'name':p.get('name') or self.names.get(code,code),'last':last,'unrealized':(last-p['avg'])*p['qty']})
        watch=[]
        for code,w in self.watch.items():
            e=w['engine'];v=e.values[-1] if e.values else {};q=w['quote'];price=q.get('price',0)
            watch.append({'code':code,'name':w['name'] if w['name']!=code else self.names.get(code,code),'bars_n':len(w['bars']),'price':price,'baseline':e.base_price,'capture':e.capture_price,'change':(price/e.capture_price-1)*100 if e.capture_price and price else 0,'macd':v.get('macd'),'cum':v.get('cum'),'eligible':w['eligible'],'ready':w['ready'],'status':w['status'],'ticks':w['builder'].count if w['builder'] else None,**self.diagnose(w)})
        return {'settings':self.settings.model_dump(),'date':self.date,'connected':self.connected,'account':self.masked_account(),'account_suffix':self.account[-4:] if self.account else '', 'conditions':self.conditions,'subscribed':self.subscribed,'frozen':self.frozen,'universe_count':len(self.freeze_codes),'armed':self.armed,'entries':self.entries,'reconciled':self.reconciled,'problems':self.problems,'source':self.source,'running':self.running,'progress':self.progress,'cash':self.cash,'realized':self.ledger.data['realized'],'pnl':self.pnl_total(),'positions':positions,'orders':self.ledger.orders[-100:][::-1],'fills':self.ledger.data['fills'][-100:][::-1],'watch':watch,'events':self.store.events(),'error':self.last_error,'saved_credentials':self.vault.exists(self.settings.connection),'strategy':asdict(self.cfg())}
    def chart(self,code):
        w=self.watch.get(code)
        if not w:return {'bars':[],'baseline':0,'orders':[]}
        return {'bars':w['bars'][-240:],'baseline':w['engine'].base_price,'orders':[o for o in self.ledger.orders if o['code']==code]}
