"""Durable order ledger: acceptance != fill. One atomic SQLite value per ledger."""
import time,uuid,copy
from .market import number,symbol
ACTIVE={'SENDING','ACCEPTED','PARTIAL','CANCEL_PENDING','UNKNOWN'}
FINAL={'FILLED','CANCELED','REJECTED'}
def oid(value):return str(value).lstrip('0') or '0'

class Ledger:
    def __init__(self,store,key):
        self.store=store;self.key=key;self.data=store.get(key,{'orders':[],'positions':{},'fills':[],'realized':0.0})
        for o in self.orders:
            if o['status']=='SENDING':o['status']='UNKNOWN'
        self.save()
    @property
    def orders(self):return self.data['orders']
    @property
    def positions(self):return self.data['positions']
    def save(self):self.store.put(self.key,self.data)
    def pending(self,code=None):return [o for o in self.orders if o['status'] in ACTIVE and (code is None or o['code']==code)]
    def create(self,code,side,qty,price,reason,signal_id,stage='',stamp=None):
        if any(o['signal_id']==signal_id for o in self.orders):raise ValueError('이미 처리한 신호입니다.')
        if self.pending(code):raise ValueError('같은 종목의 미완료 주문이 있습니다.')
        if qty<=0 or int(qty)!=qty:raise ValueError('주문 수량 오류')
        p=self.positions.get(code,{'qty':0})
        if side=='sell' and qty>p['qty']:raise ValueError('실제 보유 수량 초과')
        o={'id':uuid.uuid4().hex,'broker_id':'','code':code,'side':side,'qty':int(qty),'price':float(price),'filled':0,'amount':0.0,'status':'SENDING','reason':reason,'signal_id':signal_id,'stage':stage,'created':time.time(),'signal_time':stamp,'cancel_id':'','fee':0.0}
        self.orders.append(o);self.save();return o
    def ack(self,o,broker_id):o.update(broker_id=str(broker_id),status='ACCEPTED' if not o['filled'] else o['status']);self.save()
    def status(self,o,status):o['status']=status;self.save()
    def fill(self,o,cumulative_qty,cumulative_amount,fill_id,fee=None):
        q=int(cumulative_qty);amount=float(cumulative_amount)
        if q<o['filled']:return False
        if q>o['qty'] or amount<o['amount']-1e-8:raise ValueError('체결 누계 불일치')
        delta=q-o['filled'];gross=amount-o['amount']
        if delta and gross<=0:raise ValueError('체결 가격 확인 불가')
        # A duplicated execution number must not be applied twice.
        if not delta:
            if abs(amount-o['amount'])>1e-8:raise ValueError('동일 수량의 체결 금액 불일치')
            if fee is not None and o['code'] in self.positions:
                increment=max(0,float(fee)-o['fee']);o['fee']+=increment;self.positions[o['code']]['realized']-=increment;self.data['realized']-=increment;self.save()
            return False
        if fill_id and any(f['key']==o['id']+':'+fill_id for f in self.data['fills']):raise ValueError('동일 체결번호의 누계 변경')
        p=self.positions.setdefault(o['code'],{'code':o['code'],'qty':0,'entry_qty':0,'entry_amount':0.0,'avg':0.0,'realized':0.0,'stages':{},'entered':False,'closed':False,'entry_time':o.get('signal_time'),'high':0.0})
        if o['side']=='buy':
            p['qty']+=delta;p['entry_qty']+=delta;p['entry_amount']+=gross;p['avg']=p['entry_amount']/p['entry_qty'];p['entered']=True;p['closed']=False
        else:
            if delta>p['qty']:raise ValueError('체결 수량이 앱 소유 보유량을 초과합니다.')
            pnl=gross-delta*p['avg'];p['qty']-=delta;p['realized']+=pnl;self.data['realized']+=pnl
            if not p['qty']:p['closed']=True
        o['filled']=q;o['amount']=amount
        if q==o['qty']:o['status']='FILLED'
        elif o['status'] not in ('CANCEL_PENDING','CANCELED'):o['status']='PARTIAL'
        if o['stage'] and o['side']=='sell':
            s=p['stages'].setdefault(o['stage'],{'qty':0,'amount':0.0});s['qty']+=delta;s['amount']+=gross
        f={'key':o['id']+':'+(fill_id or str(q)),'order':o['id'],'code':o['code'],'side':o['side'],'qty':delta,'price':gross/delta,'time':time.time()}
        self.data['fills'].append(f)
        if fee is not None:
            increment=max(0,float(fee)-o['fee']);o['fee']+=increment;p['realized']-=increment;self.data['realized']-=increment
        self.save();return True
    def paper_fill(self,o,price,cost_pct):
        self.ack(o,'P'+o['id'][:10])
        # Half the configured round-trip estimate on each side.
        self.fill(o,o['qty'],o['qty']*price,'paper',o['qty']*price*cost_pct/200)
    def execution(self,values,account):
        if str(values.get('9201','')).replace('-','')!=account:return False
        order_id=oid(values.get('9203',''));original=oid(values.get('904',''))
        cancel=next((o for o in self.orders if o['cancel_id'] and oid(o['cancel_id'])==order_id),None)
        if cancel:
            if str(values.get('913',''))=='확인':self.status(cancel,'CANCELED' if cancel['filled']<cancel['qty'] else 'FILLED')
            return True
        o=next((o for o in self.orders if o['broker_id'] and oid(o['broker_id'])==order_id),None)
        if not o:return False
        if symbol(values.get('9001',o['code']))!=o['code']:raise ValueError('체결 종목 불일치')
        status=str(values.get('913',''));reject=str(values.get('919','')).strip()
        if reject and reject not in ('0','000000'):self.status(o,'REJECTED');return True
        if status=='체결':
            # 902 gives remaining shares, 903 cumulative consideration; no OHLC fill assumptions.
            if '902' not in values or '903' not in values:raise ValueError('체결 누계 필드 누락')
            qty=int(number(values.get('900',o['qty'])))-int(number(values['902']))
            self.fill(o,qty,abs(number(values['903'])),str(values.get('909','')),number(values.get('938'))+number(values.get('939')))
        if status=='거부':self.status(o,'REJECTED')
        return True
    def reconcile_detail(self,snapshot,settle_sec=10.0):
        """(hard, soft) 반환. soft는 체결 통지와 잔고 조회의 도착 시차로 잠시 생길 수 있는 불일치."""
        now_ts=time.time()
        unsettled={o['code'] for o in self.pending()}|{f['code'] for f in self.data['fills'] if now_ts-f['time']<settle_sec}
        actual={symbol(r['stk_cd']):int(number(r.get('rmnd_qty'))) for r in snapshot['holdings'] if number(r.get('rmnd_qty'))>0}
        own={c:p['qty'] for c,p in self.positions.items() if p['qty']>0}
        hard=[];soft=[]
        diff=sorted(c for c in set(actual)|set(own) if actual.get(c,0)!=own.get(c,0) and c not in unsettled)
        if diff:soft.append('증권사 잔고와 앱 소유 잔고가 다릅니다 ('+', '.join(diff)+')')
        external=[];broker_open={}
        for r in snapshot['open_orders']:
            if number(r.get('oso_qty'))<=0:continue
            broker_open[oid(r['ord_no'])]=r
            o=next((o for o in self.orders if o['broker_id'] and oid(o['broker_id'])==oid(r['ord_no'])),None)
            if not o:external.append(r['ord_no']);continue
            cum=int(number(r['ord_qty']))-int(number(r['oso_qty']))
            if cum!=o['filled']:soft.append('누락 체결 의심 ('+o['code']+')')
        if external:hard.append('앱 외부 미체결 주문이 있습니다.')
        for o in self.pending():
            if o['status']=='UNKNOWN':hard.append('결과가 불명확한 주문이 있습니다.')
            elif o['broker_id'] and oid(o['broker_id']) not in broker_open and now_ts-o['created']>max(10,settle_sec):soft.append('주문 종료 상태를 확인하지 못했습니다.')
        return list(dict.fromkeys(hard)),list(dict.fromkeys(soft))
    def reconcile(self,snapshot):
        """기존 호환: 시차 유예 없이 모든 문제를 반환(자동매매 시작 전 엄격 검사용)."""
        hard,soft=self.reconcile_detail(snapshot,settle_sec=0)
        return hard+soft
