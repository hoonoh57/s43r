import pytest
from datetime import datetime
from backend.market import match_tail,market_quiet,KST

def tk(ft,p,v):return {'date':'20261002','time':ft[:4],'full_time':ft,'open':p,'high':p,'low':p,'close':p,'volume':v}
XS=[tk(f'1958{i:02d}',17200+i,10) for i in range(30)]+[tk('195959',17250,60)]*5
TG={'date':'20261002','time':'1959','full_time':'195959','open':17250,'high':17250,'low':17250,'close':17250,'volume':180}

def test_identical_duplicates_resolved_when_quiet():
    out=match_tail(XS,TG,quiet=True)
    assert len(out)==3 and all(x['volume']==60 for x in out)

def test_identical_duplicates_blocked_during_session():
    with pytest.raises(ValueError):match_tail(XS,TG)

def test_market_quiet_hours():
    d=lambda s:datetime.strptime(s,'%Y%m%d%H%M').replace(tzinfo=KST)
    assert market_quiet(d('202610022339')) and market_quiet(d('202610060855')) and market_quiet(d('202610030930'))
    assert not market_quiet(d('202610061000')) and not market_quiet(d('202610061930'))
