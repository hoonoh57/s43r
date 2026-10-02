import json,sqlite3,time
from pathlib import Path
class Store:
    def __init__(self, folder):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.folder/'trader.sqlite',timeout=10)
        self.db.execute('pragma journal_mode=WAL');self.db.execute('pragma synchronous=FULL')
        self.db.executescript('create table if not exists kv(key text primary key,value text not null);create table if not exists events(seq integer primary key autoincrement,ts real,level text,kind text,message text,data text);')
        self.db.commit();self.raw=None;self.raw_day=''
    def get(self,key,default=None):
        r=self.db.execute('select value from kv where key=?',(key,)).fetchone();return json.loads(r[0]) if r else default
    def put(self,key,value):
        self.db.execute('insert or replace into kv values (?,?)',(key,json.dumps(value,ensure_ascii=False)));self.db.commit()
    def event(self,kind,message,data=None,level='info'):
        self.db.execute('insert into events(ts,level,kind,message,data) values(?,?,?,?,?)',(time.time(),level,kind,message,json.dumps(data or {},ensure_ascii=False)));self.db.commit()
    def events(self,limit=100):
        rows=self.db.execute('select seq,ts,level,kind,message from events order by seq desc limit ?',(limit,)).fetchall()
        return [dict(zip(('id','ts','level','kind','message'),r)) for r in rows]
    def record(self,kind,data):
        day=time.strftime('%Y%m%d')
        if day!=self.raw_day:
            if self.raw:self.raw.close()
            p=self.folder/'market';p.mkdir(exist_ok=True);self.raw=(p/f'{day}.jsonl').open('a',encoding='utf-8',buffering=1024*1024);self.raw_day=day
        self.raw.write(json.dumps({'received_at':time.time(),'kind':kind,'data':data},ensure_ascii=False)+'\n')
    def flush(self):
        if self.raw:self.raw.flush()
    def close(self):
        if self.raw:self.raw.close()
        self.db.close()
