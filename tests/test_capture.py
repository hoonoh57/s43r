import json
from backend import capture as cp, sim as S


def _w(p, o):
    p.write_text(json.dumps(o, ensure_ascii=False), encoding='utf-8')


def test_index_day_and_ticks(tmp_path, monkeypatch):
    data = tmp_path / 'data'; data.mkdir(); ticks = tmp_path / 'ticks'; ticks.mkdir()
    monkeypatch.setattr(cp, 'DIR', data); monkeypatch.setattr(S, 'DIR', ticks)
    cp._cache.clear(); cp._tcache.clear()
    _w(data / 'lab-20261001.json', {'params': {'date': '20261001'}, 'rows': [
        {'date': '20261001', 'code': 'A439960', 'name': '코스모로보틱스', 'mfe': 35.4, 'label': '고',
         'res': {'S4.3R': {'entered': True, 'pnl': 14.4, 'entryTime': '09:04', 'exitReason': 'ATR'}}},
        {'date': '20261001', 'code': 'A025560', 'name': '미래산업', 'mfe': 0, 'label': '저', 'res': {}}]})
    _w(data / 'strategy-audit-20261001-20261001-T-360-mfe-gt-5p5.json', {'schema': 's44-audit-batch-v1', 'days': [
        {'settings': {'targetDate': '20261001'}, 'cases': [{'code': 'A439960', 'name': '코스모로보틱스', 'officialMfeVal': 35.4, 'candles': []}]}]})
    _w(data / 'strategy-audit-20260930-T-360.json', {'settings': {'targetDate': '20260930'},
        'cases': [{'code': 'A000660', 'name': 'SK하이닉스', 'officialMfeVal': 7}]})
    (data / 'broken.json').write_text('{', encoding='utf-8')
    ds = cp.dates()
    assert ds['exists'] and [d['date'] for d in ds['dates']] == ['20261001', '20260930']
    assert ds['dates'][0]['n'] == 2 and ds['dates'][0]['eligible'] == 1
    _w(ticks / '439960_20261001.json', {'code': '439960', 'date': '20261001', 'prior_dates': ['20260930'],
        'ticks': [['20260930', '0901', 1, 1]] * 5 + [['20261001', '0901', 1, 1]] * 3})
    d = cp.day('20261001'); s = {x['code']: x for x in d['stocks']}
    a = s['439960']
    assert a['eligible'] and a['ref']['entry'] == '09:04' and set(a['src']) == {'lab', 'audit'}
    assert a['tick']['day'] == 3 and a['tick']['prior'] == {'20260930': 5}
    assert s['025560']['tick'] is None and not s['025560']['eligible']
    assert d['stocks'][0]['code'] == '439960'
    r = cp.run_day('20261001', ['025560'], {})
    assert r['rows'][0]['error']
