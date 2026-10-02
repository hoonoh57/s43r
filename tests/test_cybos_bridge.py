import pytest
from backend import cybos_bridge as cb


def test_parse_codes():
    assert cb.parse_codes('005930, A042000 005930') == ['005930', '042000']
    for bad in ('12345', '   '):
        with pytest.raises(ValueError):
            cb.parse_codes(bad)


def test_check_date():
    assert cb.check_date('20261002') == '20261002'
    for bad in ('2026102', '20261332', 'abc'):
        with pytest.raises(ValueError):
            cb.check_date(bad)


def test_command_and_env():
    cmd = cb.command('005930', '20261002', 2)
    assert cmd[0] == cb.PY32 and cmd[1].endswith('cybos_ticks.py')
    assert cmd[2:] == ['005930', '20261002', '--prior', '2']
    env = cb.child_env({'PYTHONHOME': 'x', 'PYTHONPATH': 'y', 'VIRTUAL_ENV': 'z', 'PATH': 'p'})
    assert not {'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'} & set(env)
    assert env['PYTHONIOENCODING'] == 'utf-8' and env['PATH'] == 'p'


def test_job_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, 'TICKS', tmp_path)

    def fake(cmd, timeout):
        if cmd[2] == '005930':
            (tmp_path / f'{cmd[2]}_{cmd[3]}.json').write_text('{}')
            return 0, 'ok', ''
        return 1, '', 'Cybos 미연결'
    monkeypatch.setattr(cb, '_run', fake)
    cb._jobs['t1'] = dict(id='t1', state='queued', done=0, total=2, current=None, results=[])
    cb._job('t1', ['005930', '000660'], '20261002', 2)
    j = cb._jobs.pop('t1')
    assert j['state'] == 'partial' and [r['ok'] for r in j['results']] == [True, False]
    assert 'Cybos' in j['results'][1]['msg']
