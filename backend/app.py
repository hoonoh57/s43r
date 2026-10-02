import asyncio,json,os,secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse,Response
from fastapi.staticfiles import StaticFiles
from .config import ROOT
from .runtime import Runtime
from .extras import TradeRuntime,register
from .broker import BrokerError
from .sim import register_sim
from .desk_ops import register_ops

class SingleInstance:
    def __init__(self,path):self.path=path;self.file=None
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('a+b');self.file.write(b'0');self.file.flush();self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt;msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl;fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:self.file.close();raise RuntimeError('같은 runtime 폴더를 사용하는 앱이 이미 실행 중입니다.')
    def release(self):
        if self.file:self.file.close()

def create_app(folder=None):
    token=secrets.token_urlsafe(32);folder=Path(folder or ROOT/'runtime');lock=SingleInstance(folder/'instance.lock')
    @asynccontextmanager
    async def lifespan(app):
        lock.acquire();app.state.runtime=TradeRuntime(folder);await app.state.runtime.start()
        try:yield
        finally:await app.state.runtime.stop();lock.release()
    app=FastAPI(title='S4.3-R Trader',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    @app.middleware('http')
    async def local_only(request,call_next):
        host=request.headers.get('host','').split(':')[0]
        if host not in ('127.0.0.1','localhost','testserver'):return JSONResponse({'detail':'로컬 접속만 허용합니다.'},status_code=403)
        origin=request.headers.get('origin')
        if origin and origin!='http://'+request.headers.get('host',''):return JSONResponse({'detail':'다른 출처의 요청은 허용하지 않습니다.'},status_code=403)
        if request.method not in ('GET','HEAD'):
            if not secrets.compare_digest(request.headers.get('x-session',''),token):return JSONResponse({'detail':'화면을 새로고침하세요.'},status_code=403)
            try:size=int(request.headers.get('content-length','0'))
            except ValueError:size=17*1024*1024
            if size>16*1024*1024:return JSONResponse({'detail':'16 MB 이하 JSON을 사용하세요.'},status_code=413)
        r=await call_next(request);r.headers['Cache-Control']='no-store';r.headers['X-Content-Type-Options']='nosniff'
        r.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return r
    @app.exception_handler(ValueError)
    async def value_error(request,e):return JSONResponse({'detail':str(e)[:600]},status_code=400)
    @app.exception_handler(BrokerError)
    async def broker_error(request,e):return JSONResponse({'detail':str(e)[:600]},status_code=502)
    @app.exception_handler(Exception)
    async def generic_error(request,e):
        if hasattr(app.state,'runtime'):await app.state.runtime.fault('서버 처리 오류 ('+type(e).__name__+')')
        return JSONResponse({'detail':'처리 오류: '+type(e).__name__+' · 이벤트 기록을 확인하세요.'},status_code=500)
    async def body(request):
        raw=await request.body()
        if len(raw)>16*1024*1024:raise HTTPException(413,'16 MB 이하 JSON을 사용하세요.')
        try:return json.loads(raw)
        except (ValueError,UnicodeError):raise HTTPException(400,'올바른 JSON이 필요합니다.')
    @app.get('/api/bootstrap')
    async def bootstrap():return {'token':token,'version':'1.0.0','name':'S4.3-R Trader'}
    @app.get('/api/state')
    async def state():return app.state.runtime.state()
    @app.get('/api/chart/{code}')
    async def chart(code:str):return app.state.runtime.chart(code)
    @app.post('/api/settings')
    async def settings(request:Request):
        data=await body(request)
        async with app.state.runtime.control_lock:app.state.runtime.configure(data)
        return {'ok':True}
    @app.post('/api/connect')
    async def connect(request:Request):
        data=await body(request)
        async with app.state.runtime.control_lock:await app.state.runtime.connect(str(data.get('appkey','')),str(data.get('secretkey','')),bool(data.get('save',False)))
        return {'ok':True}
    @app.post('/api/disconnect')
    async def disconnect():
        async with app.state.runtime.control_lock:await app.state.runtime.disconnect()
        return {'ok':True}
    @app.post('/api/subscribe')
    async def subscribe(request:Request):
        data=await body(request)
        async with app.state.runtime.control_lock:await app.state.runtime.subscribe(str(data.get('sequence','')))
        return {'ok':True}
    @app.post('/api/reconcile')
    async def reconcile():
        async with app.state.runtime.control_lock:return {'problems':await app.state.runtime.reconcile()}
    @app.post('/api/control')
    async def control(request:Request):
        data=await body(request)
        async with app.state.runtime.control_lock:await app.state.runtime.control(str(data.get('action','')),str(data.get('confirmation','')))
        return {'ok':True}
    @app.post('/api/demo')
    async def demo():
        async with app.state.runtime.control_lock:await app.state.runtime.replay()
        return {'ok':True}
    @app.post('/api/replay')
    async def replay(request:Request):
        data=await body(request)
        if 'days' in data:
            days=[d for d in data['days'] if d.get('cases')]
            if len(days)!=1:raise ValueError('한 거래일의 캔들 파일을 선택하세요.')
            data=days[0]
        tf=data.get('collection',{}).get('timeframe',data.get('settings',{}).get('timeframe','T-360'))
        if tf!='T-360':raise ValueError('동결 전략은 360틱 캔들 파일을 사용합니다.')
        date=data.get('date',data.get('settings',{}).get('targetDate',data.get('collection',{}).get('date')))
        if not date:raise ValueError('date 또는 settings.targetDate가 필요합니다.')
        if not data.get('cases'):raise ValueError('cases 배열에 캔들이 없습니다.')
        async with app.state.runtime.control_lock:await app.state.runtime.replay(data['cases'],str(date).replace('-',''))
        return {'ok':True}
    @app.get('/api/export')
    async def export():
        s=app.state.runtime.state();s.pop('saved_credentials',None)
        return Response(json.dumps({'schema':'s43r-trader-report-v1',**s},ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="s43r-report-{s["date"]}.json"'})
    register(app,body)
    register_ops(app)
    register_sim(app)
    from .cybos_bridge import register_cybos; register_cybos(app); from .capture import register_capture; register_capture(app)
    @app.get('/')
    async def index():return FileResponse(ROOT/'frontend/index.html')
    app.mount('/assets',StaticFiles(directory=ROOT/'frontend'),name='assets')
    return app

app=create_app()
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('S43R_PORT','8765')),access_log=False)
