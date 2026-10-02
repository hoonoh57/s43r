from datetime import datetime,timedelta,timezone
import math,re
KST=timezone(timedelta(hours=9))
def now():return datetime.now(KST)
def number(v,default=0):
    try:
        x=float(str(v).strip().replace(',',''));return x if math.isfinite(x) else default
    except (ValueError,TypeError):return default

def symbol(v):
    s=str(v).strip().upper()
    if len(s)==7 and s[0] in 'AJQ':s=s[1:]
    if len(s)!=6 or not re.fullmatch(r'[0-9A-Z]{6}',s):raise ValueError('KRX 6자리 종목코드가 필요합니다.')
    return s

def chart_bar(row):
    ts=str(row['cntr_tm'])
    if len(ts)!=14:raise ValueError('차트 체결시각 누락')
    return {'date':ts[:8],'time':ts[8:12],'full_time':ts[8:],'open':abs(number(row['open_pric'])),'high':abs(number(row['high_pric'])),'low':abs(number(row['low_pric'])),'close':abs(number(row['cur_prc'])),'volume':abs(number(row['trde_qty']))}

class TickBars:
    """Fixed session boundaries; count trades, never volume or repeated timestamp groups."""
    def __init__(self,size=360):self.size=size;self.count=0;self.bar=None;self.date=None
    def add(self,b,count=1):
        if b['date']!=self.date:self.count=0;self.bar=None;self.date=b['date']
        if count<=0 or self.count+count>self.size:raise ValueError('틱 경계 불일치')
        if self.bar is None:self.bar=dict(b)
        else:self.bar.update(high=max(self.bar['high'],b['high']),low=min(self.bar['low'],b['low']),close=b['close'],volume=self.bar['volume']+b['volume'],time=b['time'],full_time=b.get('full_time',b['time']+'00'))
        self.count+=count
        if self.count==self.size:out=self.bar;self.count=0;self.bar=None;return out
        return None
    def tick(self,date,tm,price,volume):return self.add(dict(date=date,time=tm[:4],full_time=tm,open=price,high=price,low=price,close=price,volume=volume))

def _loose_tail(one_ticks,target,max_count=30):
    """체결시각 비교만 뺀 대조. 후보가 정확히 1개일 때만 채택한다."""
    found=[]
    for end in range(len(one_ticks),0,-1):
        z=one_ticks[end-1]
        if abs(z['close']-target['close'])>1e-8:continue
        hi=-float('inf');lo=float('inf');vol=0
        for start in range(end-1,max(-1,end-max_count-1),-1):
            a=one_ticks[start];hi=max(hi,a['high']);lo=min(lo,a['low']);vol+=a['volume']
            if vol>target['volume']+1e-8:break
            if a['date']==target['date'] and abs(a['open']-target['open'])<1e-8 and abs(hi-target['high'])<1e-8 and abs(lo-target['low'])<1e-8 and abs(vol-target['volume'])<1e-8:found.append((start,end))
    if len(found)!=1:return None
    a,b=found[0];return one_ticks[a:b]

def _dump_tail(one_ticks,target,strict):
    try:
        import json,time as _t,pathlib as _p
        d=_p.Path(__file__).resolve().parent.parent/'seed_debug';d.mkdir(exist_ok=True)
        for f in sorted(d.glob('*.json'))[:-40]:f.unlink()
        name=f"{target.get('date','')}_{target.get('full_time','')}_{_t.time_ns()}.json"
        (d/name).write_text(json.dumps({'strict':strict,'target':target,'one_tail':one_ticks[-150:]},ensure_ascii=False,indent=1),encoding='utf-8')
    except Exception:pass

def match_tail(one_ticks,target,max_count=30):
    found=[]
    for end in range(len(one_ticks),0,-1):
        hi=-float('inf');lo=float('inf');vol=0
        for start in range(end-1,max(-1,end-max_count-1),-1):
            b=one_ticks[start];hi=max(hi,b['high']);lo=min(lo,b['low']);vol+=b['volume'];a=one_ticks[start];z=one_ticks[end-1]
            if a['date']==target['date'] and z.get('full_time')==target.get('full_time') and all(abs(x-y)<1e-8 for x,y in [(a['open'],target['open']),(z['close'],target['close']),(hi,target['high']),(lo,target['low']),(vol,target['volume'])]):found.append((start,end))
    if len(found)==1:
        a,b=found[0];return one_ticks[a:b]
    loose=_loose_tail(one_ticks,target,max_count) if not found else None
    if loose is not None:return loose
    _dump_tail(one_ticks,target,len(found))
    raise ValueError(f'마지막 30틱 봉의 경계를 유일하게 확인하지 못했습니다. (엄격 {len(found)}건 · seed_debug 저장)')

def build_history(thirties,ones,date):
    if not thirties or not ones:raise ValueError('워밍업 시세가 비어 있습니다.')
    if thirties[0]['date']>=date:raise ValueError('당일 시작 경계가 없어 추가 연속조회가 필요합니다.')
    tail=match_tail(ones,thirties[-1]);builder=TickBars();bars=[]
    for b in thirties[:-1]:
        out=builder.add(b,30)
        if out:bars.append(out)
    for b in tail:
        out=builder.add(b)
        if out:bars.append(out)
    previous=[b for b in bars if b['date']<date][-80:]
    if len(previous)<20:raise ValueError('전일 시드가 부족합니다.')
    return previous+[b for b in bars if b['date']==date],builder,sum(b['volume'] for b in thirties if b['date']==date)

def demo_cases(date='20261002'):
    out=[]
    for n,kind in enumerate(('trend','stop','flat')):
        bars=[];base=10000+n*4000
        for i in range(80):
            p=round(base*(1+.002*math.sin(i/4)));bars.append(dict(date=(datetime.strptime(date,'%Y%m%d')-timedelta(days=1)).strftime('%Y%m%d'),time=f'{13+i//60:02d}{i%60:02d}',open=p,high=p+20,low=p-20,close=p,volume=30000))
        prior=base
        for i in range(110):
            if i<4:change=0
            elif kind=='trend':change=min((i-3)*.012,.24) if i<26 else .24-(i-26)*.004
            elif kind=='stop':change=(i-3)*.009 if i<6 else .018-(i-5)*.028
            else:change=.003*math.sin(i/2)
            p=max(base*.8,round(base*(1+change)));bars.append(dict(date=date,time=f'{9+i//60:02d}{i%60:02d}',open=prior,high=max(p,prior)+20,low=min(p,prior)-20,close=p,volume=50000));prior=p
        out.append({'code':f'90000{n+1}','name':['데모 추세','데모 손절','데모 횡보'][n],'candles':bars})
    return out
