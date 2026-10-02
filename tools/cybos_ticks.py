"""Cybos Plus 1틱 다운로더 (32비트 Python + Cybos Plus 관리자 로그인).
지정일 전체와 이전 거래일을 하루 단위로 받는다. 선행분은 --prior 일 이상이면서
--size 틱 봉 기준 --min-bars 개 이상이 될 때까지 더 과거로 내려간다(최대 --max-days 일).
사용: py -3-32 tools\\cybos_ticks.py 005930 20261002 --prior 2"""
import argparse, json, pathlib, struct, sys, time
if struct.calcsize('P') * 8 != 32:
    sys.exit('[중단] 32비트 Python으로 실행하세요. (예: py -3-32)')
import win32com.client as w

R = pathlib.Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument('code')
ap.add_argument('date')
ap.add_argument('--prior', type=int, default=2)
ap.add_argument('--min-bars', type=int, default=40)
ap.add_argument('--size', type=int, default=360)
ap.add_argument('--max-days', type=int, default=10)
a = ap.parse_args()
code = a.code.strip().upper()
code = code[1:] if len(code) == 7 and code[0] in 'AJQ' else code
date = a.date.replace('-', '')
max_days = max(a.prior, a.max_days)

cy = w.Dispatch('CpUtil.CpCybos')
if cy.IsConnect != 1:
    sys.exit('[중단] CYBOS Plus에 로그인하세요. (관리자 권한 실행)')
name = w.Dispatch('CpUtil.CpStockCode').CodeToName('A' + code) or code
ch = w.Dispatch('CpSysDib.StockChart')
ch.SetInputValue(0, 'A' + code)
ch.SetInputValue(1, ord('2'))
ch.SetInputValue(2, int(date))
ch.SetInputValue(4, 10000)
ch.SetInputValue(5, [0, 1, 5, 8])
ch.SetInputValue(6, ord('T'))
ch.SetInputValue(7, 1)
ch.SetInputValue(9, ord('1'))

rows, order, count = [], [], {}


def bars(days):
    return sum(count[d] // a.size for d in days)


def enough():
    done = [d for d in order if d < date]
    if len(done) >= max_days:
        return True
    return len(done) >= a.prior and bars(done) >= a.min_bars


stop = False
while not stop:
    while cy.GetLimitRemainCount(1) <= 0:
        time.sleep(0.25)
    ch.BlockRequest()
    if ch.GetDibStatus() != 0:
        sys.exit('[중단] 조회 오류: ' + str(ch.GetDibMsg1()))
    n = ch.GetHeaderValue(3)
    for i in range(n):
        d = str(ch.GetDataValue(0, i))
        if d > date:
            continue
        if not order or order[-1] != d:
            if order and enough():
                stop = True
                break
            order.append(d)
            count[d] = 0
        count[d] += 1
        rows.append([d, str(ch.GetDataValue(1, i)).zfill(4), float(ch.GetDataValue(2, i)), float(ch.GetDataValue(3, i))])
    print(f'\r수신 {len(rows):,}틱 · {len(order)}일 · 선행 {bars([d for d in order if d < date])}봉', end='', flush=True)
    if n == 0 or not ch.Continue:
        break

rows.reverse()
if date not in count:
    sys.exit('\n[중단] 지정일 틱이 없습니다. (휴장일/종목코드 확인)')
prior = sorted(d for d in order if d < date)
b = bars(prior)
out = R / 'ticks'
out.mkdir(exist_ok=True)
p = out / f'{code}_{date}.json'
p.write_text(json.dumps({'source': 'cybos', 'code': code, 'name': name, 'date': date, 'prior_dates': prior, 'ticks': rows},
                        ensure_ascii=False), encoding='utf-8')
print(f'\n[완료] {p.name} · {name} · {len(rows):,}틱 · 선행 {len(prior)}일 {b}봉'
      + ('' if b >= a.min_bars else f' · 선행 부족(최대 {max_days}일까지 조회)'))
