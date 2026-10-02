from backend.market import match_tail

def tk(i,p,v):return {'date':'20261002','time':'1900','full_time':f'19{i//60:02d}{i%60:02d}','open':p,'high':p,'low':p,'close':p,'volume':v}
BLOCK=[(100,3),(101,4),(100,5),(101,6),(101,7)]

def build():
    xs=[tk(i,200,1) for i in range(60)]
    for start in (10,55):
        for j,(p,v) in enumerate(BLOCK):xs[start+j]=tk(start+j,p,v)
    return xs

def test_ambiguous_resolved_by_start_time():
    xs=build();w=xs[55:60]
    target={'date':'20261002','time':'1900','full_time':xs[55]['full_time'],'open':100,'high':101,'low':100,'close':101,'volume':25}
    assert match_tail(xs,target)==w

def test_ambiguous_without_anchor_still_raises():
    import pytest
    xs=build()
    target={'date':'20261002','time':'1900','full_time':'235959','open':100,'high':101,'low':100,'close':101,'volume':25}
    with pytest.raises(ValueError):match_tail(xs,target)
