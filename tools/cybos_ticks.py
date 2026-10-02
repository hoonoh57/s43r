"""Cybos Plus 1틱 다운로드. 32비트 Python + CYBOS Plus 로그인(관리자 권한) 상태에서 실행.
사용: py -3-32 tools\cybos_ticks.py 005930 20261002 --prior 2   (지정일 + 이전 2거래일)"""
import argparse,json,pathlib,struct,sys,time
if struct.calcsize('P')*8!=32:sys.exit('[중단] 32비트 Python으로 실행하세요. (예: py -3-32)')
import win32com.client as w
R=pathlib.Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('code');ap.add_argument('date');ap.add_argument('--prior',type=int,default=2);a=ap.parse_args()
code=a.code.strip().lstrip('A').zfill(6);date=a.date.replace('-','')
cy=w.Dispatch('CpUtil.CpCybos')
if cy.IsConnect!=1:sys.exit('[중단] CYBOS Plus에 로그인하세요. (관리자 권한 실행)')
name=w.Dispatch('CpUtil.CpStockCode').CodeToName('A'+code) or code
ch=w.Dispatch('CpSysDib.StockChart')
ch.SetInputValue(0,'A'+code);ch.SetInputValue(1,ord('2'));ch.SetInputValue(2,int(date));ch.SetInputValue(4,10000)
ch.SetInputValue(5,[0,1,5,8]);ch.SetInputValue(6,ord('T'));ch.SetInputValue(7,1);ch.SetInputValue(9,ord('1'))
rows=[];days=set();first=True
while True:
    while cy.GetLimitRemainCount(1)<=0:time.sleep(0.25)
    if first:ch.BlockRequest();first=False
    else:ch.BlockRequest()
    if ch.GetDibStatus()!=0:sys.exit('[중단] 조회 오류: '+str(ch.GetDibMsg1()))
    n=ch.GetHeaderValue(3);done=False
    for i in range(n):
        d=str(ch.GetDataValue(0,i))
        if d>date:continue
        days.add(d)
        if len(days)>a.prior+1:done=True;break
        rows.append([d,str(ch.GetDataValue(1,i)).zfill(4),float(ch.GetDataValue(2,i)),float(ch.GetDataValue(3,i))])
    print(f'\r수신 {len(rows):,}틱 · {len(days)}일',end='',flush=True)
    if done or n==0 or not ch.Continue:break
rows.reverse()
keep=sorted({r[0] for r in rows})
if date not in keep:sys.exit('\n[중단] 지정일 틱이 없습니다. (휴장일/종목코드 확인)')
out=R/'ticks';out.mkdir(exist_ok=True);p=out/f'{code}_{date}.json'
p.write_text(json.dumps({'source':'cybos','code':code,'name':name,'date':date,'prior_dates':[d for d in keep if d<date],'ticks':rows},ensure_ascii=False),encoding='utf-8')
print(f'\n[완료] {p.name} · {name} · {len(rows):,}틱 · 일자 {keep}')
