# 데스크 수동 개입(포지션 선택/전체 청산, 미체결 선택/전체 취소) + 키움 잔고 동기화 보강.
# 원칙: 증권사 잔고는 증거, 앱 원장은 체결로만 변경, 취소 접수 != 취소 완료.
import asyncio,time,uuid
from fastapi import Request
from .market import number,symbol
from .execution import ACTIVE,oid
from .broker import BrokerError,OrderUnknown

HOW={'market':'시장가','bid':'최우선 매수호가 지정가','last':'현재가 지정가','bid_market':'매수호가 지정가→시장가'}
FRESH=5.0

def code_of(v):
    s=str(v or '').strip()
    if len(s)==7 and s[:1] in ('A','J','Q'):s=s[1:]
    try:return symbol(s)
    except Exception:return None

def install(rt):
    if getattr(rt,'_ops',False):return
    rt._ops=True;rt.live_bal={};rt.live_at=0.0;rt.ops_busy=set();rt._kick=None;rt._kick_at=0.0
    orig=rt.on_event
    async def on_event(obj):
        await orig(obj)
        try:feed(rt,obj)
        except Exception:pass
    rt.on_event=on_event
    if rt.broker is not None:rt.broker.on_event=on_event

def feed(rt,obj):
    hit=False
    for row in obj.get('data',[]) or []:
        typ=row.get('type');v=row.get('values') or {}
        if typ=='04':
            acct=str(v.get('9201','')).replace('-','')
            if rt.account and acct and acct!=rt.account:continue
            c=code_of(v.get('9001') or row.get('item'))
            if not c or '930' not in v:continue
            rt.live_bal[c]={'qty':int(abs(number(v.get('930')))),'orderable':int(abs(number(v.get('933',v.get('930'))))),'avg':abs(number(v.get('931'))),'price':abs(number(v.get('10'))),'name':str(v.get('302','')).strip(),'at':time.time()}
            rt.live_at=time.time();hit=True
        elif typ=='00':hit=True
    if hit:kick(rt)

def kick(rt,delay=1.5):
    if not rt.connected or (rt._kick and not rt._kick.done()):return
    async def go():
        await asyncio.sleep(max(delay,3.0-(time.time()-rt._kick_at)))
        rt._kick_at=time.time()
        try:await refresh(rt)
        except asyncio.CancelledError:raise
        except Exception as e:rt.event('account','잔고 즉시 동기화 실패: '+str(e)[:120],'warning')
    rt._kick=rt.task(go())

async def refresh(rt):
    if not (rt.connected and rt.broker):return
    async with rt.reconcile_lock:
        t=time.time();snap=await rt.broker.account_snapshot()
        rt.snapshot=snap;rt.cash=snap['cash'];rt.cash_at=t;rt.adopt(snap)

def holdings(rt):
    out={}
    for r in (rt.snapshot or {}).get('holdings',[]) or []:
        c=code_of(r.get('stk_cd'));q=int(abs(number(r.get('rmnd_qty'))))
        if not c or q<=0:continue
        tq=r.get('trde_able_qty')
        out[c]={'qty':q,'orderable':int(abs(number(tq))) if tq not in (None,'') else q,'avg':abs(number(r.get('pur_pric'))),'price':abs(number(r.get('cur_prc'))),'name':str(r.get('stk_nm','')).strip(),'at':rt.cash_at}
    for c,lv in getattr(rt,'live_bal',{}).items():
        if lv['at']<=(rt.cash_at or 0):continue
        if lv['qty']>0:out[c]={**out.get(c,{}),**{k:v for k,v in lv.items() if v or k in ('qty','orderable')}}
        else:out.pop(c,None)
    return out

def name_of(rt,c,b=None):
    p=rt.ledger.positions.get(c) or {};w=rt.watch.get(c) or {}
    for n in ((b or {}).get('name'),p.get('name'),(getattr(rt,'names',None) or {}).get(c),w.get('name')):
        if n and n!=c:return n
    return c

def last_price(rt,c,b=None):
    q=(rt.watch.get(c) or {}).get('quote') or {};p=rt.ledger.positions.get(c) or {}
    return float(q.get('price') or (b or {}).get('price') or p.get('avg') or 0)

def limit_price(rt,c,how,b=None):
    if how=='market':return 0.0
    q=(rt.watch.get(c) or {}).get('quote') or {}
    if how in ('bid','bid_market') and q.get('bid') and time.time()-q.get('received',0)<=FRESH:return float(q['bid'])
    return last_price(rt,c,b)

def positions(rt):
    H=holdings(rt);L=rt.ledger;bm=rt.settings.broker_mode();out=[]
    for c in sorted(set(H)|{c for c,p in L.positions.items() if p.get('qty',0)>0}):
        b=H.get(c);p=L.positions.get(c) or {}
        own=int(p.get('qty',0)) if p.get('qty',0)>0 else 0
        bq=b['qty'] if b else 0;qty=bq if (bm and b) else own
        price=last_price(rt,c,b);avg=float((b or {}).get('avg') or p.get('avg') or 0)
        orderable=int(b['orderable']) if (bm and b) else own
        pend=L.pending(c);warn=False;st=p.get('stages',{})
        if c in rt.ops_busy:s='청산 처리 중'
        elif pend:s='미체결 '+', '.join(('매수' if o['side']=='buy' else '매도')+f" {o['qty']-o['filled']}주" for o in pend)
        elif bm and b and own!=bq:s=f'잔고 차이 · 앱 {own} / 키움 {bq}';warn=True
        elif bm and own and not b:s='키움 잔고 없음';warn=True
        elif not own:s='원장 미반영 · 대조 대기';warn=True
        elif p.get('adopted'):s='자동매매 제외'
        else:s='런너' if st.get('p2') else '1차 익절' if st.get('p1') else '보유'
        out.append({'code':c,'name':name_of(rt,c,b),'qty':qty,'own':own,'orderable':orderable,'avg':avg,'price':price,
            'pnl':(price-avg)*qty if price and avg else 0,'rate':(price/avg-1)*100 if price and avg else 0,
            'owner':'외부' if p.get('adopted') else ('앱' if own else '—'),'status':s,'warn':warn,'sellable':own>0 and c not in rt.ops_busy})
    return out

def orders(rt):
    L=rt.ledger;out=[];mine=set()
    for o in L.pending():
        if o.get('broker_id'):mine.add(oid(o['broker_id']))
        out.append({'id':'A:'+o['id'],'time':o['created'],'code':o['code'],'name':name_of(rt,o['code']),'side':o['side'],'qty':o['qty'],'left':o['qty']-o['filled'],'price':o['price'],'status':o['status'],'source':'앱','reason':o.get('reason',''),
            'cancellable':bool(o.get('broker_id')) and o['status'] in ('ACCEPTED','PARTIAL') and rt.connected})
    if rt.settings.broker_mode():
        for r in (rt.snapshot or {}).get('open_orders',[]) or []:
            no=str(r.get('ord_no','')).strip();left=int(abs(number(r.get('oso_qty'))));c=code_of(r.get('stk_cd'))
            if left<=0 or not no or not c or oid(no) in mine:continue
            txt=' '.join(str(r.get(k,'')) for k in ('io_tp_nm','trde_tp','sell_tp','ord_tp'))
            side='sell' if '매도' in txt else 'buy' if '매수' in txt else '?'
            out.append({'id':f'X:{no}:{c}','time':str(r.get('tm','') or ''),'code':c,'name':str(r.get('stk_nm','')).strip() or name_of(rt,c),'side':side,
                'qty':int(abs(number(r.get('ord_qty')))),'left':left,'price':abs(number(r.get('ord_pric'))),'status':str(r.get('ord_stt','') or '접수'),'source':'외부','reason':'앱 밖 주문','cancellable':rt.connected})
    return out

async def submit(rt,c,qty,price,how,b=None):
    L=rt.ledger;s=rt.settings;ref=price or last_price(rt,c,b);w=rt.watch.get(c)
    sid=f'{rt.date}:{c}:{int(time.time())}:exit:manual:{uuid.uuid4().hex[:6]}'
    lock=w['lock'] if w is not None else asyncio.Lock()
    async with lock:
        o=L.create(c,'sell',qty,ref,'수동청산·'+HOW[how],sid,'',int(time.time()))
        if s.broker_mode():
            try:
                no=await rt.broker.submit('sell',c,qty,price)
                L.ack(o,no)
                for v in rt.unmatched[:]:
                    if L.execution(v,rt.account):rt.unmatched.remove(v)
            except OrderUnknown as e:L.status(o,'UNKNOWN');await rt.fault(str(e))
            except BrokerError as e:
                L.status(o,'REJECTED');rt.event('order',f'{c} 수동 청산 거부: {e}','warning');return None
        else:L.paper_fill(o,ref,s.cost_pct)
        if w is not None:rt.sync(w)
    rt.event('manual',f'{c} 수동 청산 {qty}주 · {HOW[how]}'+(f' {ref:,.0f}' if price else '')+f" · {o['status']}")
    return o

async def exit_one(rt,c,how,wait):
    L=rt.ledger;p=L.positions.get(c);w=rt.watch.get(c)
    if not p or p.get('qty',0)<=0:rt.event('manual',c+' 앱 원장 보유 없음 · 청산 건너뜀','warning');return
    if w is not None:w['intents']=[]
    for o in L.pending(c):await rt.cancel(o)
    for _ in range(24):
        if not L.pending(c):break
        await asyncio.sleep(0.5)
    if L.pending(c):rt.event('manual',c+' 기존 미체결 취소 확인 실패 · 청산 보류 (미체결 탭 확인)','error');return
    b=holdings(rt).get(c);qty=int(L.positions[c]['qty'])
    if b and rt.settings.broker_mode():qty=min(qty,int(b.get('orderable',qty)))
    if qty<=0:rt.event('manual',c+' 주문가능수량 0 · 앱 밖 매도 주문이 걸려 있는지 확인하세요.','warning');return
    price=limit_price(rt,c,how,b)
    if how!='market' and price<=0:rt.event('manual',c+' 지정가 기준 가격 없음 · 시장가를 선택하세요.','warning');return
    o=await submit(rt,c,qty,price,how,b)
    if o and how=='bid_market' and rt.settings.broker_mode():rt.task(fallback(rt,c,o,wait))

async def fallback(rt,c,o,wait):
    await asyncio.sleep(wait)
    if o['status'] not in ('ACCEPTED','PARTIAL'):return
    rt.event('manual',f'{c} {wait}초 미체결 · 취소 후 시장가 전환')
    await rt.cancel(o)
    for _ in range(24):
        if o['status'] not in ACTIVE:break
        await asyncio.sleep(0.5)
    if o['status'] in ACTIVE:rt.event('manual',c+' 지정가 취소 확인 실패 · 시장가 전환 보류','error');return
    if c in rt.ops_busy:return
    rt.ops_busy.add(c)
    try:await exit_one(rt,c,'market',0)
    finally:rt.ops_busy.discard(c)

async def run_exit(rt,codes,how,wait):
    for c in codes:
        if c in rt.ops_busy:continue
        rt.ops_busy.add(c)
        try:await exit_one(rt,c,how,wait)
        except asyncio.CancelledError:raise
        except Exception as e:rt.event('manual',f'{c} 수동 청산 오류: {e}','warning')
        finally:rt.ops_busy.discard(c)
    kick(rt,0.5)

async def run_cancel(rt,ids):
    L=rt.ledger;done=[];fail=[]
    for i in ids:
        if i.startswith('A:'):
            o=next((o for o in L.pending() if o['id']==i[2:]),None)
            if not o:fail.append('이미 종료된 주문');continue
            if not o.get('broker_id') or o['status'] not in ('ACCEPTED','PARTIAL'):fail.append(f"{o['code']} {o['status']}");continue
            await rt.cancel(o);done.append(o['code'])
        elif i.startswith('X:'):
            try:_,no,c=i.split(':',2)
            except ValueError:fail.append('잘못된 주문 id');continue
            try:
                await rt.broker.cancel(c,no);done.append(c);rt.event('manual',f'{c} 외부 미체결 {no} 취소 요청')
            except BrokerError as e:fail.append(f'{c} {e}')
    if done:rt.event('manual',f'미체결 취소 요청 {len(done)}건')
    kick(rt,1.0)
    return done,fail

def guard(rt):
    if rt.settings.mode in ('record','replay'):raise ValueError('기록/리플레이 모드에서는 주문할 수 없습니다.')
    if rt.settings.broker_mode() and not (rt.connected and rt.broker):raise ValueError('키움 접속이 필요합니다.')

async def _body(request):
    try:d=await request.json()
    except Exception:raise ValueError('올바른 JSON이 필요합니다.')
    if not isinstance(d,dict):raise ValueError('올바른 JSON이 필요합니다.')
    return d

def register_ops(app):
    def rt_():
        rt=app.state.runtime;install(rt);return rt
    @app.middleware('http')
    async def _ops_hook(request,call_next):
        rt=getattr(request.app.state,'runtime',None)
        if rt is not None and not getattr(rt,'_ops',False):install(rt)
        return await call_next(request)
    @app.get('/api/ops/state')
    async def ops_state():
        rt=rt_()
        return {'connected':rt.connected,'mode':rt.settings.mode,'armed':rt.armed,'positions':positions(rt),'orders':orders(rt),'snapshot_at':rt.cash_at,'live_at':rt.live_at}
    @app.post('/api/ops/exit')
    async def ops_exit(request:Request):
        rt=rt_();d=await _body(request)
        if d.get('confirm') is not True:raise ValueError('청산 확인이 필요합니다.')
        how=str(d.get('how','market'))
        if how not in HOW:raise ValueError('매도 조건을 선택하세요.')
        try:wait=min(max(int(d.get('wait',10)),3),120)
        except (TypeError,ValueError):wait=10
        guard(rt)
        own={c for c,p in rt.ledger.positions.items() if p.get('qty',0)>0}
        codes=[c for c in sorted({code_of(x) for x in d.get('codes',[]) or []}) if c and c in own and c not in rt.ops_busy]
        if not codes:raise ValueError('청산할 수 있는 앱 원장 보유 종목이 없습니다.')
        rt.task(run_exit(rt,codes,how,wait))
        return {'ok':True,'message':f'{len(codes)}종목 청산 요청 · {HOW[how]} · 진행은 실행 이벤트에 기록됩니다.'}
    @app.post('/api/ops/cancel')
    async def ops_cancel(request:Request):
        rt=rt_();d=await _body(request)
        if d.get('confirm') is not True:raise ValueError('취소 확인이 필요합니다.')
        guard(rt)
        ids=[str(x) for x in d.get('ids',[]) or []][:200]
        if not ids:raise ValueError('취소할 주문을 선택하세요.')
        done,fail=await run_cancel(rt,ids)
        return {'ok':True,'failed':len(fail),'message':f'취소 요청 {len(done)}건'+(f' · 실패 {len(fail)}건: '+' / '.join(fail[:3]) if fail else '')}
# END desk_ops.py
