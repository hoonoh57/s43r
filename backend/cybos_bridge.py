"""64비트 서버 -> 32비트 파이썬(Cybos Plus) 브리지. kiwoom1516 web_server.py 방식:
인자 검증 -> 별도 32비트 프로세스 실행 -> 종료코드/결과파일 확인. Cybos 요청은 한 번에 하나."""
import json, os, re, subprocess, sys, threading, time, uuid, pathlib
from fastapi import HTTPException, Request
from pydantic import BaseModel

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY32 = os.environ.get('S43R_PY32', r'E:\Python310-32\python.exe')
WORKER = ROOT / 'tools' / 'cybos_ticks.py'
TICKS = ROOT / 'ticks'
NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
TIMEOUT = 900
CODE = re.compile(r'[0-9A-Z]{6}')
_lock = threading.Lock()
_jobs = {}

PROBE = ("import json,struct\n"
         "r={'bits':struct.calcsize('P')*8,'pywin32':False,'connect':None,'admin':None}\n"
         "try:\n import ctypes;r['admin']=bool(ctypes.windll.shell32.IsUserAnAdmin())\nexcept Exception:pass\n"
         "try:\n import win32com.client as w;r['pywin32']=True;r['connect']=int(w.Dispatch('CpUtil.CpCybos').IsConnect)\n"
         "except Exception as e:r['error']=str(e)[:200]\n"
         "print(json.dumps(r))")


def _text(b):
    if not b:
        return ''
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('cp949', errors='replace')


def child_env(base=None):
    env = dict(os.environ if base is None else base)
    for k in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'PYTHONEXECUTABLE'):
        env.pop(k, None)
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def parse_codes(s):
    out = []
    for x in re.split(r'[\s,;]+', str(s).upper().strip()):
        if not x:
            continue
        if len(x) == 7 and x[0] in 'AJQ':
            x = x[1:]
        if not CODE.fullmatch(x):
            raise ValueError(f'종목코드 형식 오류: {x}')
        if x not in out:
            out.append(x)
    if not out:
        raise ValueError('종목코드를 입력하세요.')
    if len(out) > 30:
        raise ValueError('한 번에 30종목까지 가능합니다.')
    return out


def check_date(d):
    d = str(d).strip()
    if not re.fullmatch(r'\d{8}', d):
        raise ValueError('일자는 YYYYMMDD 형식입니다.')
    time.strptime(d, '%Y%m%d')
    return d


def command(code, date, prior):
    return [PY32, str(WORKER), code, date, '--prior', str(int(prior))]


def _run(cmd, timeout):
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, timeout=timeout,
                       creationflags=NO_WINDOW, env=child_env())
    return p.returncode, _text(p.stdout), _text(p.stderr)


def _job(jid, codes, date, prior):
    j = _jobs[jid]
    with _lock:
        j['state'] = 'running'
        j['started'] = time.time()
        try:
            for i, c in enumerate(codes, 1):
                j['current'] = c
                t0 = time.time()
                try:
                    rc, out, err = _run(command(c, date, prior), TIMEOUT)
                except subprocess.TimeoutExpired:
                    rc, out, err = -1, '', f'{TIMEOUT}초 시간초과'
                except OSError as e:
                    rc, out, err = -1, '', str(e)
                f = TICKS / f'{c}_{date}.json'
                fresh = f.exists() and f.stat().st_mtime >= t0 - 1
                tail = (err.strip() or out.strip()).splitlines()[-3:]
                j['results'].append(dict(code=c, ok=rc == 0 and fresh, rc=rc,
                                         file=f.name if f.exists() else None,
                                         size=f.stat().st_size if f.exists() else 0,
                                         sec=round(time.time() - t0, 1), msg=' / '.join(tail)[:400]))
                j['done'] = i
            oks = [r['ok'] for r in j['results']]
            j['state'] = 'done' if all(oks) else ('partial' if any(oks) else 'error')
        except Exception as e:
            j['state'] = 'error'
            j['results'].append(dict(code='-', ok=False, rc=-1, file=None, size=0, sec=0, msg=str(e)[:400]))
        finally:
            j['current'] = None
            j['finished'] = time.time()


def start(codes, date, prior):
    if not os.path.isfile(PY32):
        raise ValueError(f'32비트 파이썬이 없습니다: {PY32} (환경변수 S43R_PY32로 지정 가능)')
    if not WORKER.is_file():
        raise ValueError('tools/cybos_ticks.py가 없습니다.')
    if any(j['state'] in ('queued', 'running') for j in _jobs.values()):
        raise ValueError('이미 다운로드가 진행 중입니다.')
    for k in sorted(_jobs, key=lambda k: _jobs[k].get('created', 0))[:-20]:
        _jobs.pop(k, None)
    jid = uuid.uuid4().hex[:8]
    _jobs[jid] = dict(id=jid, state='queued', codes=codes, date=date, prior=prior, done=0,
                      total=len(codes), current=None, results=[], created=time.time(), started=None)
    threading.Thread(target=_job, args=(jid, codes, date, prior), daemon=True).start()
    return _jobs[jid]


def probe():
    r = dict(py32=PY32, exists=os.path.isfile(PY32), worker=WORKER.is_file())
    if not r['exists']:
        return r
    try:
        rc, out, err = _run([PY32, '-c', PROBE], 30)
        r.update(json.loads(out.strip().splitlines()[-1]))
    except Exception as e:
        r['error'] = str(e)[:200]
    return r


def _local(req: Request):
    h = req.client.host if req.client else ''
    if h not in ('127.0.0.1', '::1', 'localhost'):
        raise HTTPException(403, '로컬 전용 기능입니다.')


class FetchReq(BaseModel):
    codes: str
    date: str
    prior: int = 2


def register_cybos(app):
    @app.get('/api/sim/cybos/probe')
    def _cyb_probe(request: Request):
        _local(request)
        return probe()

    @app.post('/api/sim/cybos/fetch')
    def _cyb_fetch(body: FetchReq, request: Request):
        _local(request)
        try:
            codes, date, prior = parse_codes(body.codes), check_date(body.date), int(body.prior)
            if not 1 <= prior <= 10:
                raise ValueError('선행일수는 1~10입니다.')
            return start(codes, date, prior)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get('/api/sim/cybos/job/{jid}')
    def _cyb_job(jid: str, request: Request):
        _local(request)
        j = _jobs.get(jid)
        if not j:
            raise HTTPException(404, '작업이 없습니다.')
        return j
