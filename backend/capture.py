"""kiwoom1516 포착 기록(lab-*.json, strategy-audit-*.json) -> 일자별 종목 목록 + 당일 일괄 시뮬레이션. 기록 폴더는 읽기만 한다."""
import asyncio, json, math, os, pathlib, re
from fastapi import Request
from .config import ROOT
from . import sim as S

DIR = pathlib.Path(os.environ.get('S43R_CAPTURE_DIR') or (pathlib.Path(ROOT).parent / 'kiwoom1516' / 'data'))
_cache = {}
_tcache = {}
PATTERNS = tuple(x.strip() for x in (os.environ.get('S43R_CAPTURE_GLOB') or
    'lab-*.json,lab-*.json.txt,strategy-audit-*.json,strategy-audit-*.json.txt').split(',') if x.strip())
MAX_BYTES = 64 * 1024 * 1024


def _files():
    """틱봉 등 다른 대용량 JSON은 건드리지 않고 포착 기록 파일만 고른다."""
    seen = {}
    for pat in PATTERNS:
        for p in DIR.glob(pat):
            if p.is_file():
                seen[str(p)] = p
    return [seen[k] for k in sorted(seen)]


def _date(v):
    s = re.sub(r'\D', '', str(v or ''))
    if len(s) != 8:
        raise ValueError('일자는 YYYYMMDD 형식입니다.')
    return s


def _code(c):
    c = str(c or '').strip().upper()
    if len(c) == 7 and c[0] in 'AJQ':
        c = c[1:]
    return c if re.fullmatch(r'[0-9A-Z]{6}', c) else None


def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _put(dst, code, name='', mfe=None, label=None, eligible=False, ref=None, src=()):
    r = dst.setdefault(code, {'code': code, 'name': '', 'mfe': None, 'label': None, 'eligible': False, 'ref': None, 'src': []})
    if name and not r['name']:
        r['name'] = str(name)
    if mfe is not None and r['mfe'] is None:
        r['mfe'] = mfe
    if label and not r['label']:
        r['label'] = str(label)
    r['eligible'] = r['eligible'] or bool(eligible)
    if ref and not r['ref']:
        r['ref'] = ref
    for s in src:
        if s not in r['src']:
            r['src'].append(s)


def _parse(path):
    d = json.loads(path.read_text(encoding='utf-8-sig'))
    out = {}
    m = re.search(r'(\d{8})', path.name)
    fb = m.group(1) if m else ''

    def put(date, code, **kw):
        try:
            date = _date(date)
        except ValueError:
            return
        code = _code(code)
        if code:
            _put(out.setdefault(date, {}), code, **kw)

    def audit(day):
        s = day.get('settings') or {}
        c = day.get('collection') or {}
        date = s.get('targetDate') or c.get('date') or fb
        for x in day.get('cases') or []:
            if isinstance(x, dict):
                put(date, x.get('code'), name=x.get('name'), mfe=_num(x.get('officialMfeVal')), eligible=True, src=('audit',))

    if not isinstance(d, dict):
        return out
    if isinstance(d.get('rows'), list):
        pd = (d.get('params') or {}).get('date') or fb
        for x in d['rows']:
            if not isinstance(x, dict):
                continue
            ref = (x.get('res') or {}).get('S4.3R')
            ref = {'entered': bool(ref.get('entered')), 'entry': ref.get('entryTime'), 'exit': ref.get('exitTime'),
                   'pnl': _num(ref.get('pnl')), 'reason': ref.get('exitReason'), 'type': ref.get('entryType')} if isinstance(ref, dict) else None
            put(x.get('date') or pd, x.get('code'), name=x.get('name'), mfe=_num(x.get('mfe')), label=x.get('label'),
                eligible=x.get('label') == '고', ref=ref, src=('lab',))
    if isinstance(d.get('days'), list):
        for day in d['days']:
            if isinstance(day, dict):
                audit(day)
    if isinstance(d.get('cases'), list):
        audit(d)
    return out


def index():
    merged, files = {}, {}
    if not DIR.is_dir():
        return merged, files
    for p in _files():
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_size > MAX_BYTES:
            continue
        key = (st.st_mtime_ns, st.st_size)
        c = _cache.get(str(p))
        if not c or c[0] != key:
            try:
                parsed = _parse(p)
            except Exception:
                parsed = {}
            c = (key, parsed)
            _cache[str(p)] = c
        for date, rows in c[1].items():
            files.setdefault(date, []).append(p.name)
            dst = merged.setdefault(date, {})
            for code, r in rows.items():
                _put(dst, code, r['name'], r['mfe'], r['label'], r['eligible'], r['ref'], r['src'])
    return merged, files


def tick_info(code, date):
    p = pathlib.Path(S.DIR) / f'{code}_{date}.json'
    try:
        st = p.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    c = _tcache.get(str(p))
    if not c or c[0] != key:
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
            per = {}
            for row in d.get('ticks') or []:
                k = str(row[0])
                per[k] = per.get(k, 0) + 1
            info = {'file': p.name, 'ticks': sum(per.values()), 'day': per.get(date, 0),
                    'prior': {k: v for k, v in sorted(per.items()) if k < date}}
        except Exception:
            info = {'file': p.name, 'ticks': 0, 'day': 0, 'prior': {}, 'error': '파일 손상'}
        c = (key, info)
        _tcache[str(p)] = c
    return c[1]


def dates():
    m, f = index()
    return {'dir': str(DIR), 'exists': DIR.is_dir(),
            'dates': [{'date': d, 'n': len(m[d]), 'eligible': sum(1 for r in m[d].values() if r['eligible']),
                       'files': sorted(set(f.get(d, [])))} for d in sorted(m, reverse=True)]}


def day(date):
    date = _date(date)
    m, f = index()
    rows = [dict(r, src=list(r['src']), tick=tick_info(c, date)) for c, r in m.get(date, {}).items()]
    rows.sort(key=lambda r: (-(r['mfe'] if r['mfe'] is not None else -1e9), r['code']))
    return {'date': date, 'dir': str(DIR), 'files': sorted(set(f.get(date, []))), 'stocks': rows}


def run_day(date, codes, kw):
    date = _date(date)
    if not codes:
        codes = [s['code'] for s in day(date)['stocks']]
    rows = []
    for c in codes:
        name = f'{c}_{date}.json'
        if not (pathlib.Path(S.DIR) / name).is_file():
            rows.append({'code': c, 'error': '틱 파일 없음'})
            continue
        try:
            x = S.load(name)
            x['file'] = name
            s = S.simulate(x, **kw)
            rows.append({'code': c, 'name': s['name'], 'file': name, **s['stats'], 'warm': s['warm'], 'warn': s['warnings']})
        except Exception as e:
            rows.append({'code': c, 'error': str(e)[:160]})
    return {'date': date, 'rows': rows}


def compare_day(date, codes, kw, eligible_only=False):
    from .variants import NAMES
    date = _date(date)
    stocks = day(date)['stocks']
    names = {x['code']: x['name'] for x in stocks}
    if not codes:
        codes = [x['code'] for x in stocks if x['eligible'] or not eligible_only]
    rows = []
    for c in codes:
        f = f'{c}_{date}.json'
        if not (pathlib.Path(S.DIR) / f).is_file():
            continue
        res, nm = {}, names.get(c, '')
        for sn in NAMES:
            p = dict(kw.get('params') or {})
            p['strategy'] = sn
            try:
                x = S.load(f)
                x['file'] = f
                out = S.simulate(x, **dict(kw, params=p))
                st = out.get('stats') or {}
                nm = nm or out.get('name') or ''
                res[sn] = {'entered': bool(st.get('entered')), 'pnl': st.get('model_pnl'), 'net': st.get('net'),
                           'reason': st.get('reason') or st.get('exit_reason') or st.get('exitReason') or ''}
            except Exception as e:
                res[sn] = {'error': str(e)[:160]}
        rows.append({'code': c, 'name': nm, 'res': res})
    return {'date': date, 'strategies': NAMES, 'rows': rows}


def register_capture(app):
    @app.get('/api/sim/capture-dates')
    async def _cap_dates():
        return await asyncio.to_thread(dates)

    @app.get('/api/sim/capture/{date}')
    async def _cap_day(date: str):
        return await asyncio.to_thread(day, date)

    @app.post('/api/sim/day')
    async def _cap_run(request: Request):
        try:
            d = await request.json()
        except Exception:
            raise ValueError('올바른 JSON이 필요합니다.')
        if not isinstance(d, dict):
            raise ValueError('올바른 JSON이 필요합니다.')
        codes = [c for c in (_code(x) for x in (d.get('codes') or [])) if c]
        kw = dict(size=d.get('size', 360), params=d.get('params'), slip=d.get('slip', 1),
                  cost_pct=d.get('cost', 0.25), capital=d.get('capital', 1_000_000))
        return await asyncio.to_thread(run_day, d.get('date'), codes, kw)

    @app.get('/api/sim/strategies')
    async def _cap_strategies():
        from .variants import SPECS
        return [{'name': k, 'label': v.label} for k, v in SPECS.items()]

    @app.post('/api/sim/compare')
    async def _cap_compare(request: Request):
        try:
            d = await request.json()
        except Exception:
            raise ValueError('올바른 JSON이 필요합니다.')
        if not isinstance(d, dict):
            raise ValueError('올바른 JSON이 필요합니다.')
        g = lambda k, v: v if d.get(k) is None else d.get(k)
        codes = [c for c in (_code(x) for x in (d.get('codes') or [])) if c]
        kw = dict(size=g('size', 360), params=g('params', {}), slip=g('slip', 1),
                  cost_pct=g('cost', 0.25), capital=g('capital', 1_000_000))
        return await asyncio.to_thread(compare_day, d.get('date'), codes, kw, bool(d.get('eligible_only')))
