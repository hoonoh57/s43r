import json
from backend import capture as C

def test_only_capture_files(tmp_path, monkeypatch):
    monkeypatch.setattr(C, 'DIR', tmp_path)
    (tmp_path / 'lab-20261001.json').write_text(json.dumps({'params': {'date': '20261001'},
        'rows': [{'code': '005930', 'name': '삼성전자', 'mfe': 6, 'label': '고'}]}), encoding='utf-8')
    (tmp_path / '000660_20261001_ticks.json').write_text(
        '{"rows":[{"code":"000660","date":"20261001"}]}', encoding='utf-8')
    assert [p.name for p in C._files()] == ['lab-20261001.json']
    m, _ = C.index()
    assert list(m['20261001']) == ['005930']
