const $=id=>document.getElementById(id),L=LightweightCharts;
let TOKEN='',S=null,cur={code:'',tf:'s360',rev:null,more:false,busy:false},data=[],lines=[],lineKey='';
const chart=L.createChart($('chart'),{autoSize:true,layout:{background:{color:'#0b1220'},textColor:'#cbd5e1'},
 grid:{vertLines:{color:'#1e293b'},horzLines:{color:'#1e293b'}},timeScale:{timeVisible:true,secondsVisible:true,rightOffset:5},crosshair:{mode:0}});
const nl={priceLineVisible:false,lastValueVisible:false};
const candle=chart.addSeries(L.CandlestickSeries,{upColor:'#ef4444',downColor:'#3b82f6',borderVisible:false,wickUpColor:'#ef4444',wickDownColor:'#3b82f6'});
const SER={vwap:chart.addSeries(L.LineSeries,{color:'#facc15',lineWidth:1,...nl}),st:chart.addSeries(L.LineSeries,{lineWidth:2,...nl}),
 jma:chart.addSeries(L.LineSeries,{color:'#a78bfa',lineWidth:1,...nl}),vol:chart.addSeries(L.HistogramSeries,{priceFormat:{type:'volume'},...nl},1),
 macd:chart.addSeries(L.HistogramSeries,nl,2)};
try{chart.panes()[1].setHeight(80);chart.panes()[2].setHeight(90)}catch(e){}
const marks=L.createSeriesMarkers(candle,[]);
const P={c:x=>({time:x.t,open:x.o,high:x.h,low:x.l,close:x.c}),vwap:x=>x.vwap==null?null:{time:x.t,value:x.vwap},
 st:x=>x.st==null?null:{time:x.t,value:x.st,color:x.tr==1?'#22c55e':'#ef4444'},jma:x=>x.jma==null?null:{time:x.t,value:x.jma},
 vol:x=>({time:x.t,value:x.v,color:x.c>=x.o?'#ef444480':'#3b82f680'}),macd:x=>x.macd==null?null:{time:x.t,value:x.macd,color:x.macd>=0?'#ef4444':'#3b82f6'}};
function msg(t,e){$('info').textContent=t;$('info').className=e?'err':''}
async function api(p,o){const r=await fetch(p,o),j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||r.status);return j}
const post=b=>api('/api/trade',{method:'POST',headers:{'Content-Type':'application/json','x-session':TOKEN},body:JSON.stringify(b)});
function setAll(b,meta){data=b.slice();candle.setData(b.map(P.c));for(const k in SER)SER[k].setData(b.map(P[k]).filter(Boolean));if(meta)applyMeta(meta,true)}
function tail(b){for(const x of b){const n=data.length,last=n?data[n-1].t:-1;
 if(x.t<last){const i=data.findIndex(y=>y.t===x.t);if(i>=0)data[i]=x;continue}
 if(x.t===last)data[n-1]=x;else data.push(x);candle.update(P.c(x));for(const k in SER){const p=P[k](x);if(p)SER[k].update(p)}}}
function snap(t){for(let i=data.length-1;i>=0;i--)if(data[i].t<=t)return data[i].t;return null}
function applyMeta(m,force){
 if(!m||!m.code)return;
 document.title=`${m.name} (${m.code}) · S4.3-R`;
 const key=[m.baseline,m.capture,m.avg].join();if(force||key!==lineKey){lineKey=key;lines.forEach(l=>candle.removePriceLine(l));lines=[];
  if(m.baseline)lines.push(candle.createPriceLine({price:m.baseline,color:'#c084fc',lineStyle:2,title:'기준선'}));
  if(m.capture)lines.push(candle.createPriceLine({price:m.capture,color:'#64748b',lineStyle:2,title:'09:03'}));
  if(m.avg)lines.push(candle.createPriceLine({price:m.avg,color:'#f97316',title:`평단 ${m.qty}주`}))}
 const mk=[];for(const x of m.markers||[]){const t=snap(x.t);if(t==null)continue;
  mk.push({time:t,position:x.side=='sell'?'aboveBar':'belowBar',shape:x.side=='buy'?'arrowUp':x.side=='sell'?'arrowDown':'circle',
   color:x.side=='buy'?'#ef4444':x.side=='sell'?'#3b82f6':'#f59e0b',text:x.text})}
 marks.setMarkers(mk.sort((a,b)=>a.time-b.time));$('older').disabled=!cur.more}
async function load(keep){if(!cur.code)return;cur.busy=true;msg('불러오는 중…');
 try{const r=chart.timeScale().getVisibleLogicalRange(),d=await api(`/api/bars/${cur.code}?tf=${cur.tf}`);cur.rev=d.rev;cur.more=d.more;setAll(d.bars,d.meta);
  if(keep&&r)chart.timeScale().setVisibleLogicalRange(r);else chart.timeScale().scrollToRealTime();msg(`${d.bars.length}봉${d.more?' · 왼쪽 끝으로 끌면 이전 캔들 추가':''}`)}
 catch(e){cur.rev=null;msg(e.message,true)}finally{cur.busy=false}}
async function older(){if(cur.busy||!cur.more||!cur.code)return;cur.busy=true;
 try{const n0=data.length,r=chart.timeScale().getVisibleLogicalRange(),d=await api(`/api/bars/${cur.code}?tf=${cur.tf}&op=older`);
  cur.rev=d.rev;cur.more=d.more;setAll(d.bars,d.meta);const add=d.bars.length-n0;if(r)chart.timeScale().setVisibleLogicalRange({from:r.from+add,to:r.to+add});
  msg(`${d.bars.length}봉 (+${add})${d.more?'':' · 더 이상 이전 데이터 없음'}`)}catch(e){msg(e.message,true)}finally{cur.busy=false}}
chart.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(r&&r.from<3)older()});
$('older').onclick=older;
$('tf').onchange=e=>{cur.tf=e.target.value;cur.rev=null;load()};
$('code').onchange=e=>{cur.code=e.target.value;cur.rev=null;load()};
$('mode').onchange=async e=>{const m=e.target.value;if(m=='manual'&&!confirm('수동 모드: 자동 손절/청산을 포함한 모든 자동 주문이 꺼집니다. 계속할까요?')){e.target.value=S.trade_mode;return}
 try{await post({action:'mode',mode:m});msg('매매 방식 변경')}catch(x){msg(x.message,true)}};
document.querySelectorAll('#ind input').forEach(c=>c.onchange=()=>SER[c.dataset.k].applyOptions({visible:c.checked}));
async function act(a,label){if(!cur.code||!confirm(`${label}: ${cur.code}\n진행할까요?`))return;
 try{const r=await post({action:a,code:cur.code,confirm:true});msg(label+' · '+(r.message||'완료'))}catch(e){msg(e.message,true)}}
$('buy').onclick=()=>act('buy','매수 (최우선 매도호가)');$('exit').onclick=()=>act('exit','즉시 청산 (시장가)');$('cancel').onclick=()=>act('cancel','미체결 취소');
$('hold').onclick=async()=>{try{await post({action:'hold',code:cur.code,hold:!(S.holds||[]).includes(cur.code)})}catch(e){msg(e.message,true)}};
async function poll(){try{S=await api('/api/state');
 const list=S.watch.map(w=>[w.code,w.name]);for(const p of S.positions)if(p.qty>0&&!list.some(x=>x[0]==p.code))list.push([p.code,p.name||p.code]);
 const sel=$('code'),key=list.map(x=>x.join(':')).join();if(sel.dataset.k!==key){sel.dataset.k=key;sel.innerHTML='';
  for(const[c,n]of list){const o=document.createElement('option');o.value=c;o.textContent=n&&n!=c?`${n} (${c})`:c;sel.append(o)}}
 if(!cur.code&&list.length){const q=new URLSearchParams(location.search).get('code');cur.code=list.some(x=>x[0]==q)?q:list[0][0];load()}
 sel.value=cur.code;$('mode').value=S.trade_mode;$('hold').textContent=(S.holds||[]).includes(cur.code)?'대기 해제':'대기';
 $('warn').textContent=S.trade_mode=='manual'?'수동 모드: 자동 손절·청산 포함 모든 자동 주문이 꺼져 있습니다.':!S.armed?'자동매매 OFF: 신호는 표시만 합니다 (데스크에서 시작).':!S.entries?'신규 진입 중지 상태':'';
 const ap=$('appr');ap.innerHTML='';for(const a of S.approvals||[]){const d=document.createElement('div'),left=Math.max(0,Math.round(a.expires-Date.now()/1000));
  d.textContent=`진입 승인 대기: ${a.name} (${a.code}) ${a.price} · ${a.reason} · ${left}초 `;
  for(const[t,rj]of[['승인',false],['거절',true]]){const b=document.createElement('button');b.textContent=t;
   b.onclick=async()=>{try{const r=await post({action:'approve',id:a.id,reject:rj});msg(r.message)}catch(e){msg(e.message,true)}};d.append(b)}ap.append(d)}
}catch(e){}}
setInterval(async()=>{if(!cur.code||cur.busy||document.hidden)return;
 try{const d=await api(`/api/bars/${cur.code}?tf=${cur.tf}&op=tail`);if(d.rev!==cur.rev)return load(true);tail(d.bars);applyMeta(d.meta)}catch(e){}},1000);
(async()=>{try{TOKEN=(await api('/api/bootstrap')).token}catch(e){msg('서버 연결 실패',true)}poll();setInterval(poll,2000)})();
// END chart.js
