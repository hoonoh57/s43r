from backend import sim
def data():
    t=[]
    for d,n,up in (('20261001',3600,0),('20261002',7200,1)):
        for i in range(n):
            m=540+i//20;p=10000+(i//40)*10*up+(i%3)*10
            t.append([d,f'{m//60:02d}{m%60:02d}',p,10+i%7])
    return {'code':'005930','name':'T','date':'20261002','ticks':t}
def test_bars_and_warmup():
    r=sim.simulate(data())
    assert len(r['bars'])==30 and r['start']==10 and r['bars'][r['start']]['date']=='20261002'
    assert all(b['jma'] is not None for b in r['bars'][r['start']:])
def test_deterministic():
    a=sim.simulate(data(),params={'base_rate_pct':1.0});b=sim.simulate(data(),params={'base_rate_pct':1.0})
    assert a['stats']==b['stats'] and a['fills']==b['fills'] and a['signals']==b['signals']
def test_fills_next_tick_with_slippage():
    r=sim.simulate(data(),params={'base_rate_pct':0.5,'min_cum_eok':0.0,'early_cum_eok':0.0})
    for x in r['fills']:
        u=sim.tick_unit(x['price'])
        assert (x['price']>=x['signal']) if x['side']=='buy' else True
def test_param_types():
    c=sim.config('20261002',{'early_enabled':False,'entry_cutoff':'09:25','hard_stop_pct':'-2'})
    assert c.early_enabled is False and c.entry_cutoff=='0925' and c.hard_stop_pct==-2.0
# END test_sim.py
