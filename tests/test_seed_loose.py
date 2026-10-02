import pytest
from backend.market import match_tail

def bar(t,p,v):return {'date':'20261002','time':t[:4],'full_time':t,'open':p,'high':p,'low':p,'close':p,'volume':v}
def ticks():
    out=[];p=1000
    for i in range(60):
        p+=(-1 if i%3==0 else 1);out.append(bar(f'0930{i:02d}',p,10+i))
    return out
def agg(xs,ft):
    return {'date':xs[0]['date'],'time':ft[:4],'full_time':ft,'open':xs[0]['open'],'high':max(x['high'] for x in xs),'low':min(x['low'] for x in xs),'close':xs[-1]['close'],'volume':sum(x['volume'] for x in xs)}

def test_strict_still_works():
    t=ticks();assert match_tail(t,agg(t[40:55],t[54]['full_time']))==t[40:55]

def test_loose_when_bar_time_is_first_tick():
    t=ticks();assert match_tail(t,agg(t[40:55],t[40]['full_time']))==t[40:55]

def test_unmatched_still_raises():
    t=ticks();g=agg(t[40:55],t[54]['full_time']);g['volume']+=1
    with pytest.raises(ValueError):match_tail(t,g)
