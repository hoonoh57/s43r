const $=id=>document.getElementById(id);let tok='',R=null,k=0,timer=null,chart,cs,vw,st,jm,vs,mh,mk,bl=null,DEF={};
const f=(v,n=0)=>v==null?'—':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:n,minimumFractionDigits:n});
const c=v=>v>0?'pos':v<0?'neg':'';const hm=s=>s.slice(0,2)+':'+s.slice(2,4)+':'+s.slice(4,6);
const tt=t=>{const d=new Date(t*1000);return d.toISOString().slice(11,19);};
const LBL={capture_time:'포착 시각',entry_start:'진입 시작',entry_cutoff:'진입 마감',exit_soft:'소프트 종료',exit_hard:'하드 종료',base_rate_pct:'기준 상승률%',apply_mfe_gate:'MFE 게이트',macd_threshold:'MACD 임계',early_enabled:'조기 진입',early_until:'조기 마감',early_cum_eok:'조기 누적(억)',early_macd:'조기 MACD',apply_cum_gate:'누적 게이트',min_cum_eok:'최소 누적(억)',hard_stop_pct:'손절%',tp1_pct:'1차 익절%',tp2_pct:'2차 익절%',tp_fraction:'익절 비중',bep_pct:'본전컷%',atr_trail_mult:'ATR 배수',vwap_runner_cut:'VWAP 런너컷',vwap_extend:'VWAP 연장'};
async function api(p,d){const r=await fetch('/api/'+p,{method:d===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Session':tok},body:d===undefined?undefined:JSON.stringify(d)});const b=await r.json().catch(()=>({}));if(!r.ok)throw Error(typeof b.detail==='string'?b.detail:'요청 실패 '+r.status);return b;}
const msg=t=>$('msg').textContent=t;
function renderParams(v){$('params').innerHTML=Object.entries(v).map(([k,x])=>`<label>${LBL[k]||k}${typeof x==='boolean'?`<input type="checkbox" data-k="${k}" ${x?'checked':''}>`:`<input data-k="${k}" value="${x}">`}</label>`).join('');}
function params(){const o={};document.querySelectorAll('#params [data-k]').forEach(i=>o[i.dataset.k]=i.type==='checkbox'?i.checked:i.value);return o;}
function opts(){return {file:$('file').value,size:+$('size').value,slip:+$('slip').value,cost:+$('cost').value,capital:+$('cap').value,params:params()};}
function mkChart(){const L=LightweightCharts;chart=L.createChart($('chart'),{autoSize:true,layout:{background:{color:'#070d17'},textColor:'#94a3b8'},grid:{vertLines:{color:'#0f1a2b'},horzLines:{color:'#0f1a2b'}},timeScale:{timeVisible:true,secondsVisible:true},rightPriceScale:{borderColor:'#1e293b'}});
 cs=chart.addSeries(L.CandlestickSeries,{upColor:'#ef4444',downColor:'#3b82f6',borderVisible:false,wickUpColor:'#ef4444',wickDownColor:'#3b82f6'});
 const ln=(color,w=1)=>chart.addSeries(L.LineSeries,{color,lineWidth:w,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
 vw=ln('#facc15');st=ln('#22c55e',2);jm=ln('#e879f9');
 vs=chart.addSeries(L.HistogramSeries,{priceFormat:{type:'volume'},priceLineVisible:false},1);mh=chart.addSeries(L.HistogramSeries,{priceLineVisible:false},2);
 try{const p=chart.panes();p[1].setHeight(70);p[2].setHeight(90);}catch(e){}
 mk=L.createSeriesMarkers(cs,[]);}
function show(i){if(!R)return;const n=R.bars.length;k=Math.max(0,Math.min(n-1,i));const B=R.bars.slice(0,k+1),b=B[k],T=b.t;
 cs.setData(B.map(x=>({time:x.t,open:x.o,high:x.h,low:x.l,close:x.c})));
 vw.setData(B.filter(x=>x.vwap!=null).map(x=>({time:x.t,value:x.vwap})));jm.setData(B.filter(x=>x.jma!=null).map(x=>({time:x.t,value:x.jma})));
 st.setData(B.filter(x=>x.st!=null).map(x=>({time:x.t,value:x.st,color:x.tr===1?'#22c55e':'#f43f5e'})));
 vs.setData(B.map(x=>({time:x.t,value:x.v,color:x.c>=x.o?'#7f1d1d':'#1e3a8a'})));mh.setData(B.map(x=>({time:x.t,value:x.macd??0,color:(x.macd??0)>=0?'#ef4444':'#3b82f6'})));
 const S=R.signals.filter(s=>s.t<=T);mk.setMarkers(S.map(s=>({time:s.t,position:s.kind==='entry'?'belowBar':'aboveBar',color:s.kind==='entry'?'#22c55e':s.kind==='partial'?'#f59e0b':'#f43f5e',shape:s.kind==='entry'?'arrowUp':'arrowDown',text:s.reason})));
 if(bl){cs.removePriceLine(bl);bl=null;}if(b.base)bl=cs.createPriceLine({price:b.base,color:'#94a3b8',lineStyle:2,title:'기준가'});
 const F=R.fills.filter(x=>x.t<=T);
 $('fills').innerHTML='<tr><th>시각</th><th>구분</th><th>수량</th><th>체결가</th><th>신호가</th><th>누적손익</th></tr>'+F.map(x=>`<tr><td>${tt(x.t)}</td><td class="${x.side==='buy'?'pos':'neg'}">${x.reason}</td><td>${f(x.qty)}</td><td>${f(x.price)}</td><td>${f(x.signal)}</td><td class="${c(x.realized)}">${f(x.realized)}</td></tr>`).join('');
 $('sigs').innerHTML='<tr><th>시각</th><th>신호</th><th>가격</th></tr>'+S.map(s=>`<tr><td>${tt(s.t)}</td><td>${s.reason}</td><td>${f(s.price)}</td></tr>`).join('');
 const e=R.equity[k],z=R.stats;
 $('stats').innerHTML=`<div><span>현재 평가손익</span><b class="${c(e)}">${f(e)}</b></div><div><span>최종 손익 / 수익률</span><b class="${c(z.net)}">${f(z.net)} / ${f(z.ret,2)}%</b></div><div><span>당일 최대낙폭</span><b>${f(z.mdd)}</b></div><div><span>진입 / 사유</span><b>${z.entered?z.entry:'미진입'} · ${z.reason}</b></div><div><span>엔진 손익(비용 제외)</span><b>${f(z.model_pnl,2)}%</b></div><div><span>선행 봉</span><b>${R.warm}</b></div>`;
 $('pos').max=n-1;$('pos').value=k;$('cur').textContent=`${b.date} ${hm(b.tm)} · ${k+1}/${n}${k<R.start?' · 선행':''}`;}
function stop(){clearInterval(timer);timer=null;$('play').textContent='▶';}
function play(){if(timer)return stop();if(!R)return;if(k>=R.bars.length-1)show(R.start);$('play').textContent='⏸';timer=setInterval(()=>{if(k>=R.bars.length-1)stop();else show(k+1);},1000/+$('speed').value);}
async function run(){stop();const o=opts();if(!o.file)return msg('ticks 폴더에 파일이 없습니다.');msg('계산 중…');localStorage.setItem('simParams',JSON.stringify(o.params));
 try{R=await api('sim/run',o);msg(`${R.name||R.code} ${R.date} · ${R.bars.length}봉 · 신호 ${R.signals.length} · 체결 ${R.fills.length}`);$('warn').textContent=R.warnings.join(' / ');show(Math.max(0,R.start-1));chart.timeScale().fitContent();}catch(e){msg(e.message);}}
async function batch(){const o=opts();msg('일괄 계산 중…');try{const r=await api('sim/batch',o);msg('일괄 합계 '+f(r.net));
 $('batchT').innerHTML='<tr><th>일자·종목</th><th>진입</th><th>사유</th><th>손익</th><th>%</th></tr>'+r.rows.map(x=>x.error?`<tr><td>${x.file}</td><td colspan="4" class="neg">${x.error}</td></tr>`:`<tr><td>${x.date} ${x.name||x.code}</td><td>${x.entered?x.entry:'—'}</td><td>${x.reason}</td><td class="${c(x.net)}">${f(x.net)}</td><td>${f(x.ret,2)}</td></tr>`).join('');}catch(e){msg(e.message);}}
(async()=>{try{tok=(await api('bootstrap')).token;const d=await api('sim/files');DEF=d.params;
 $('file').innerHTML=d.files.map(x=>`<option value="${x.file}">${x.date} ${x.name||''} ${x.code} · 선행 ${x.prior.length}일 · ${Number(x.ticks).toLocaleString()}틱</option>`).join('')||'<option value="">ticks 폴더에 파일 없음</option>';
 let saved={};try{saved=JSON.parse(localStorage.getItem('simParams')||'{}');}catch(e){}renderParams({...DEF,...saved});mkChart();
 $('run').onclick=run;$('batch').onclick=batch;$('reset').onclick=()=>{localStorage.removeItem('simParams');renderParams(DEF);};
 $('first').onclick=()=>{stop();show(R?R.start:0);};$('last').onclick=()=>{stop();show(1e9);};$('prev').onclick=()=>{stop();show(k-1);};$('next').onclick=()=>{stop();show(k+1);};$('play').onclick=play;
 $('pos').oninput=e=>{stop();show(+e.target.value);};$('speed').onchange=()=>{if(timer){stop();play();}};
 document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;if(e.key==='ArrowRight')$('next').click();else if(e.key==='ArrowLeft')$('prev').click();else if(e.key===' '){e.preventDefault();play();}});
}catch(e){msg('초기화 실패: '+e.message);}})();
// END sim.js
