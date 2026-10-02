"""Kiwoom REST + WebSocket adapter. Order POSTs are NEVER retried automatically."""
import asyncio, json, time
from datetime import datetime
import httpx
from websockets.asyncio.client import connect
from .market import KST, number

class BrokerError(RuntimeError): pass
class OrderUnknown(BrokerError): pass

class Kiwoom:
    def __init__(self, environment, on_event, on_disconnect, transport=None, ws_url=None):
        self.environment=environment; self.on_event=on_event; self.on_disconnect=on_disconnect
        self.base='https://mockapi.kiwoom.com' if environment=='mock' else 'https://api.kiwoom.com'
        self.ws_url=ws_url or self.base.replace('https:','wss:')+':10000/api/dostk/websocket'
        self.http=httpx.AsyncClient(base_url=self.base,timeout=20,transport=transport)
        self.token=''; self.expires=0; self.ws=None; self.reader=None; self.consumer=None
        self.queue=asyncio.Queue(maxsize=50000); self.pending={}; self.locks={}; self.poisoned=set()
        self.rest_lock=asyncio.Lock(); self.last_request=0; self.interval=.65 if environment=='mock' else .22
        self.closed=False; self.connected=False; self.account=''

    async def login(self, appkey, secretkey):
        try:
            r=await self.http.post('/oauth2/token',json={'grant_type':'client_credentials','appkey':appkey,'secretkey':secretkey})
            r.raise_for_status(); data=r.json()
        except (httpx.HTTPError,ValueError) as e: raise BrokerError('토큰 발급 통신 실패') from e
        if not data.get('token'): raise BrokerError('토큰 발급 거절: 키와 API 환경을 확인하세요.')
        self.token=data['token']
        try:self.expires=datetime.strptime(data['expires_dt'],'%Y%m%d%H%M%S').replace(tzinfo=KST).timestamp()
        except (KeyError,ValueError):self.expires=time.time()+3600
        a=await self.query('ka00001','/api/dostk/acnt',{})
        self.account=str(a.get('acctNo','')).replace('-','').strip()
        if not self.account.isdigit() or len(self.account)!=10:raise BrokerError('토큰에 연결된 10자리 계좌를 확인하지 못했습니다.')
        self.ws=await connect(self.ws_url,open_timeout=15,ping_interval=None,max_size=8*1024*1024)
        self.reader=asyncio.create_task(self._read()); self.consumer=asyncio.create_task(self._consume())
        await self.request({'trnm':'LOGIN','token':self.token})
        self.connected=True
        await self.register([],['00','04'],'1')
        return self.account

    async def post(self,api_id,path,body,*,order=False,cont='N',key='',deadline=None):
        if not self.token or self.expires<time.time()+30:raise BrokerError('접속 토큰이 만료되었습니다. 신규 주문을 중지하고 재접속하세요.')
        attempts=1 if order else 3
        async with self.rest_lock:
            for attempt in range(attempts):
                await asyncio.sleep(max(0,self.interval-(time.monotonic()-self.last_request)))
                if deadline is not None and time.time()>deadline:raise BrokerError('주문 전 시세 유효시간 초과 · 전송하지 않았습니다.')
                self.last_request=time.monotonic()
                try:
                    r=await self.http.post(path,json=body,headers={'authorization':'Bearer '+self.token,'api-id':api_id,'cont-yn':cont,'next-key':key,'Content-Type':'application/json;charset=UTF-8'})
                    r.raise_for_status(); data=r.json()
                except (httpx.HTTPError,ValueError) as e:
                    if order:raise OrderUnknown('주문 응답 불명: 재전송하지 않고 계좌 대조가 필요합니다.') from e
                    if attempt+1==attempts:raise BrokerError(f'{api_id} 조회 통신 실패') from e
                    await asyncio.sleep(1+attempt);continue
                code=int(number(data.get('return_code',0),-1))
                if code:
                    if not order and code==1700 and attempt+1<attempts:
                        self.interval=min(3,self.interval*1.5);await asyncio.sleep(1+attempt);continue
                    raise BrokerError(f'{api_id} 요청 거절 (코드 {code})')
                return data,dict(r.headers)
        raise BrokerError('조회 재시도 소진')

    async def query(self,api_id,path,body): return (await self.post(api_id,path,body))[0]
    async def pages(self,api_id,path,body,list_key,max_pages=100,stop=None):
        rows=[];cont='N';key='';seen=set()
        for _ in range(max_pages):
            data,h=await self.post(api_id,path,body,cont=cont,key=key)
            batch=data.get(list_key,[])
            if not isinstance(batch,list):raise BrokerError(f'{api_id} 목록 형식 오류')
            rows.extend(batch)
            if stop and stop(rows):return rows
            key=h.get('next-key','');cont=h.get('cont-yn','N')
            if cont!='Y':return rows
            if not key or key in seen:raise BrokerError(f'{api_id} 연속조회 키 오류')
            seen.add(key)
        raise BrokerError(f'{api_id} 연속조회 한도: 불완전한 결과로 운용할 수 없습니다.')

    async def request(self,payload,timeout=15):
        trnm=payload['trnm'];lock=self.locks.setdefault(trnm,asyncio.Lock())
        async with lock:
            if trnm in self.poisoned:raise BrokerError(f'{trnm} 이전 요청 시간 초과: 재접속이 필요합니다.')
            fut=asyncio.get_running_loop().create_future();self.pending[trnm]=fut
            try:
                await self.ws.send(json.dumps(payload));obj=await asyncio.wait_for(fut,timeout)
                if int(number(obj.get('return_code',0),-1)):raise BrokerError(f'{trnm} 요청 거절 (코드 {obj.get("return_code")})')
                return obj
            except asyncio.TimeoutError as e:
                self.poisoned.add(trnm);raise BrokerError(f'{trnm} 응답 시간 초과') from e
            finally:self.pending.pop(trnm,None)

    async def _read(self):
        try:
            async for raw in self.ws:
                obj=json.loads(raw);trnm=obj.get('trnm')
                if trnm=='PING':await self.ws.send(raw);continue
                if trnm in self.pending and ('return_code' in obj or trnm in ('CNSRLST','REG','REMOVE','CNSRCLR')):
                    f=self.pending[trnm]
                    if not f.done():f.set_result(obj)
                else:
                    obj['_received_at']=time.time();self.queue.put_nowait(obj)
        except asyncio.CancelledError:raise
        except Exception:pass
        finally:
            self.connected=False
            for f in self.pending.values():
                if not f.done():f.set_exception(BrokerError('실시간 연결이 끊어졌습니다.'))
            if not self.closed:await self.on_disconnect()

    async def _consume(self):
        try:
            while True:await self.on_event(await self.queue.get())
        except asyncio.CancelledError:raise
        except Exception:
            self.connected=False;await self.on_disconnect()
            if self.ws:await self.ws.close()

    async def conditions(self):
        obj=await self.request({'trnm':'CNSRLST'})
        return [{'sequence':str(r[0]),'name':str(r[1])} for r in obj.get('data',[]) if isinstance(r,list) and len(r)>1]
    async def condition(self,sequence):return await self.request({'trnm':'CNSRREQ','seq':str(sequence),'search_type':'1','stex_tp':'K'})
    async def register(self,codes,types=('0B',),group='ticks'):
        return await self.request({'trnm':'REG','grp_no':str(group),'refresh':'1','data':[{'item':list(codes),'type':list(types)}]})
    async def submit(self,side,code,qty,price,deadline=None):
        body={'dmst_stex_tp':'KRX','stk_cd':code,'ord_qty':str(qty),'ord_uv':str(int(price)) if price else '', 'trde_tp':'0' if price else '3','cond_uv':''}
        data,_=await self.post('kt10000' if side=='buy' else 'kt10001','/api/dostk/ordr',body,order=True,deadline=deadline)
        if not data.get('ord_no'):raise OrderUnknown('주문번호 없는 응답: 계좌 대조가 필요합니다.')
        return str(data['ord_no'])
    async def cancel(self,code,order_id):
        data,_=await self.post('kt10003','/api/dostk/ordr',{'dmst_stex_tp':'KRX','orig_ord_no':order_id,'stk_cd':code,'cncl_qty':'0'},order=True)
        if not data.get('ord_no'):raise OrderUnknown('취소 주문번호 없는 응답')
        return str(data['ord_no'])
    async def account_snapshot(self):
        cash=await self.query('kt00001','/api/dostk/acnt',{'qry_tp':'2'})
        holdings=await self.pages('kt00018','/api/dostk/acnt',{'qry_tp':'1','dmst_stex_tp':'KRX'},'acnt_evlt_remn_indv_tot')
        open_orders=await self.pages('ka10075','/api/dostk/acnt',{'all_stk_tp':'0','trde_tp':'0','stk_cd':'','stex_tp':'1'},'oso')
        return {'cash':max(0,number(cash.get('100stk_ord_alow_amt',0))), 'holdings':holdings,'open_orders':open_orders}
    async def close(self):
        self.closed=True;self.connected=False
        if self.ws:await self.ws.close()
        for task in (self.reader,self.consumer):
            if task and task is not asyncio.current_task():task.cancel()
        await asyncio.gather(*(t for t in (self.reader,self.consumer) if t and t is not asyncio.current_task()),return_exceptions=True)
        await self.http.aclose();self.token=''
