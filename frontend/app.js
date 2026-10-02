const $=id=>document.getElementById(id);let token='',state=null,selected='',busy=false,settingsLoaded=false,conditionSignature='',confirmAction=null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(v,n=0)=>Number(v||0).toLocaleString('ko-KR',{maximumFractionDigits:n,minimumFractionDigits:n});
const signed=(v,n=0)=>(v>0?'+':'')+fmt(v,n);const cls=v=>v>0?'pos':v<0?'neg':'';
const time=t=>new Date(t*1000).toLocaleTimeString('ko-KR',{hour12:false});
function toast(text,error=false){$('toast').textContent=text;$('toast').hidden=false;$('toast').className=error?'toast-error':'';clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,6000);}
async function api(path,data){const res=await fetch('/api/'+path,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Session':token},body:data===undefined?undefined:JSON.stringify(data)});const body=await res.json();if(!res.ok)throw Error(typeof body.detail==='string'?body.detail:'요청 내용을 확인하세요.');return body;}
async function command(path,data={},success='완료했습니다.'){if(busy)return;busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);try{await api(path,data);toast(success);await refresh();}catch(e){toast(e.message,true);}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);}}
function view(name){document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!==name);document.querySelectorAll('.nav').forEach(e=>e.classList.toggle('active',e.dataset.view===name));if(name==='desk')setTimeout(drawSelected,30);}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>view(b.dataset.view));document.querySelectorAll('[data-goto]').forEach(b=>b.onclick=()=>view(b.dataset.goto));
function confirm(action,phrase,title,description){confirmAction=action;$('confirm-title').textContent=title;$('confirm-description').textContent=description;$('confirm-phrase').textContent=phrase;$('confirm-input').value='';$('confirm-dialog').showModal();$('confirm-input').focus();}
$('confirm-submit').onclick=()=>{if($('confirm-input').value!==$('confirm-phrase').textContent)return toast('표시된 확인 문구를 정확하게 입력하세요.',true);const text=$('confirm-input').value;$('confirm-dialog').close();command('control',{action:confirmAction,confirmation:text});};
function arm(){if(!state)return;const live=state.settings.mode==='live';confirm('arm',live?'실거래 시작 '+state.account_suffix:'자동매매 시작',live?'실계좌 자동매매 시작':'자동매매 시작',`${state.account} · ${state.settings.mode} · 종목당 ${fmt(state.settings.allocation)}원 / 최대 ${state.settings.max_positions}종목 / 총 ${fmt(state.settings.max_exposure)}원. ${live?'실제 현금 주문이 증권사로 전송됩니다.':'선택한 모드로 주문을 처리합니다.'}`);}
$('arm').onclick=arm;$('arm-settings').onclick=arm;
$('demo').onclick=()=>command('demo',{},'합성 데이터 데모를 시작했습니다.');
$('pause').onclick=()=>command('control',{action:'pause'},'신규 진입을 중지했습니다. 보유분 청산 감시는 계속합니다.');
$('halt').onclick=()=>command('control',{action:state?.running?'stop_replay':'halt'},'자동 주문을 중지했습니다. 미체결 주문은 별도로 확인하세요.');
$('upload').onclick=()=>$('replay-file').click();$('replay-file').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{if(f.size>16*1024*1024)throw Error('16 MB 이하 JSON 파일을 선택하세요.');await command('replay',JSON.parse(await f.text()),'캔들 리플레이를 시작했습니다.');}catch(e){toast(e.message,true);}e.target.value='';};
$('settings-form').onsubmit=e=>{e.preventDefault();const data={...state.settings};for(const el of e.target.elements){if(!el.name)continue;data[el.name]=el.type==='checkbox'?el.checked:el.type==='number'?Number(el.value):el.value;}command('settings',data,'설정을 저장했습니다.');};
$('connect-form').onsubmit=async e=>{e.preventDefault();const form=e.target;const data={appkey:form.appkey.value,secretkey:form.secretkey.value,save:form.save.checked};await command('connect',data,'키움 연결과 계좌 대조를 마쳤습니다.');form.appkey.value='';form.secretkey.value='';};
$('resync').onclick=()=>command('control',{action:'resync'});
$('disconnect').onclick=()=>command('disconnect');$('reconcile').onclick=()=>command('reconcile');$('subscribe').onclick=()=>command('subscribe',{sequence:$('condition').value},'조건식을 구독했습니다.');$('cancel-orders').onclick=()=>confirm('cancel','미체결 취소','앱의 미체결 주문 취소','확인된 주문번호가 있는 앱 주문의 남은 수량을 취소 요청합니다. 취소 접수 뒤에도 체결이 발생할 수 있습니다.');
const CHECKS=[['trend','추세'],['macd','MACD'],['jma','JMA'],['cum','대금'],['base','기준선'],['early','조기']];
function checks(c){if(!c||!Object.keys(c).length)return '';return '<div class="chk-row">'+CHECKS.map(([k,l])=>`<span class="chk${c[k]?' on':''}" title="${l} ${c[k]?'충족':'미충족'}">${l}</span>`).join('')+'</div>';}
function stageClass(s){s=String(s||'');return s.includes('충족')?'pos':s.includes('보유')?'cyan':/제외|오류|단절|초과/.test(s)?'neg':(s.includes('대기')||s.includes('대조'))?'gold':'muted';}
function rowEmpty(n,text){return `<tr><td colspan="${n}" class="empty-row">${esc(text)}</td></tr>`;}
function events(rows){return rows.map(e=>`<div class="event-item ${esc(e.level)}"><time>${time(e.ts)}</time><span class="level">${esc(e.kind.toUpperCase())}</span><span>${esc(e.message)}</span></div>`).join('')||'<div class="empty">이벤트가 없습니다.</div>';}
async function refresh(){
 state=await api('state');const s=state.settings;const replay=s.mode==='replay';
 $('clock').textContent=new Date().toLocaleString('ko-KR',{hour12:false});$('mode-pill').textContent=({replay:'REPLAY',record:'RECORD ONLY',paper:'PAPER',mock:'KIWOOM MOCK',live:'LIVE ACCOUNT'})[s.mode];$('mode-pill').classList.toggle('live',s.mode==='live');
 $('connection').textContent=state.connected?'● 키움 '+s.connection+' 연결':'● 연결 없음';$('connection').classList.toggle('cyan',state.connected);
 $('run-status').textContent=state.running?'리플레이 실행 중':state.armed?(state.entries?'자동매매 실행 중':'보유분 청산 감시'):'실행 대기';$('run-dot').classList.toggle('status-running',state.armed);$('source').textContent=state.source+' · '+state.date;$('progress').style.width=state.progress*100+'%';
 $('demo').hidden=!replay;$('upload').hidden=!replay;$('arm').hidden=replay||s.mode==='record';
 $('pnl').textContent=signed(state.pnl);$('pnl').className=cls(state.pnl);$('realized').textContent=signed(state.realized);$('realized').className=cls(state.realized);
 $('held').innerHTML=`${state.positions.filter(p=>p.qty>0&&!p.adopted).length} <i>/ ${s.max_positions}</i>`;$('exposure').textContent=`최대 투입 ${fmt(s.max_exposure)}원`;$('universe').innerHTML=`${state.watch.filter(w=>w.eligible).length} <i>/ ${state.watch.length}</i>`;
 $('notice').hidden=!(replay||s.mode==='paper');$('notice').textContent='리플레이 / 페이퍼 결과는 가상 체결입니다. 데모는 동작 확인용 합성 데이터이며 실제 투자 성과가 아닙니다.';
 $('error').hidden=!state.error;$('error').textContent=state.error;
 if(!state.watch.some(w=>w.code===selected))selected=state.watch[0]?.code||'';
 $('watch-body').innerHTML=state.watch.map(w=>`<tr data-code="${esc(w.code)}" class="${selected===w.code?'selected':''}"><td><b>${esc(w.name)}</b>${w.name!==w.code?`<small>${esc(w.code)}</small>`:''}</td><td>${w.price?fmt(w.price):'—'}</td><td class="${cls(w.change)}">${w.price&&w.capture?signed(w.change,2)+'%':'—'}</td><td class="${w.gap!=null&&w.gap<=0?'pos':''}">${w.gap==null?'—':w.gap<=0?'돌파':signed(w.gap,2)+'%'}</td><td><span class="${stageClass(w.stage)}">${esc(w.stage)}</span>${checks(w.checks)}</td></tr>`).join('');$('watch-empty').hidden=!!state.watch.length;
 $('watch-body').querySelectorAll('tr').forEach(r=>r.onclick=()=>{selected=r.dataset.code;drawSelected();refresh().catch(()=>{});});
 $('positions-body').innerHTML=state.positions.map(p=>`<tr><td><b>${esc(p.name||p.code)}</b>${p.name&&p.name!==p.code?`<small>${esc(p.code)}</small>`:''}</td><td>${fmt(p.qty)}주</td><td>${fmt(p.avg,1)}</td><td>${fmt(p.last)}</td><td class="${cls(p.unrealized)}">${signed(p.unrealized)}</td><td class="${cls(p.realized)}">${signed(p.realized)}</td><td>${p.adopted?(p.qty?'외부 보유':'외부 정리'):p.closed?'청산 완료':p.stages.p2?'런너':p.stages.p1?'1차 익절':'보유'}</td></tr>`).join('')||rowEmpty(7,'체결된 포지션이 없습니다.');
 $('recent-orders').innerHTML=state.orders.slice(0,4).map(o=>`<div class="order-item"><time>${time(o.created)}</time><b>${esc(o.code)}</b><span class="${o.side==='buy'?'cyan':'gold'}">${o.side==='buy'?'매수':'매도'} ${o.qty}주</span><span class="spacer">${esc(o.status)}</span></div>`).join('')||'<div class="empty">아직 주문이 없습니다.</div>';
 $('event-short').innerHTML=events(state.events.slice(0,4));$('events').innerHTML=events(state.events);
 $('orders-body').innerHTML=state.orders.map(o=>`<tr><td>${time(o.created)}</td><td>${esc(o.code)}</td><td class="${o.side==='buy'?'cyan':'gold'}">${o.side==='buy'?'매수':'매도'}</td><td>${o.qty} / ${o.filled}</td><td>${fmt(o.price)}</td><td>${esc(o.status)}</td><td>${esc(o.reason)}</td><td>${esc(o.broker_id||'—')}</td></tr>`).join('')||rowEmpty(8,'주문 내역이 없습니다.');
 $('fills-body').innerHTML=state.fills.map(f=>`<tr><td>${time(f.time)}</td><td>${esc(f.code)}</td><td>${f.side==='buy'?'매수':'매도'}</td><td>${f.qty}</td><td>${fmt(f.price,1)}</td></tr>`).join('')||rowEmpty(5,'체결 내역이 없습니다.');
 if(!settingsLoaded){for(const el of $('settings-form').elements){if(!el.name||s[el.name]===undefined)continue;if(el.type==='checkbox')el.checked=s[el.name];else el.value=s[el.name];}settingsLoaded=true;}
 $('account').textContent=state.account;$('reconcile-status').textContent=state.reconciled?'잔고 대조 정상':'잔고 대조 대기';$('saved-hint').textContent=state.saved_credentials?'이 Windows 계정에 암호화된 키가 있습니다. 빈칸으로 연결하면 저장된 키를 사용합니다.':'키는 이 PC에서 증권사 인증에만 사용합니다.';
 const sig=JSON.stringify(state.conditions);if(sig!==conditionSignature){conditionSignature=sig;$('condition').innerHTML=state.conditions.length?state.conditions.map(c=>`<option value="${esc(c.sequence)}">${esc(c.sequence)} · ${esc(c.name)}</option>`).join(''):'<option value="">접속 후 목록을 불러옵니다.</option>';if(s.condition_sequence)$('condition').value=s.condition_sequence;}
 $('problems').textContent=state.problems.join(' / ');$('problems').className='hint neg';await drawSelected();
}
async function drawSelected(){if($('desk').hidden)return;const w=state?.watch.find(w=>w.code===selected);$('chart-title').textContent=w?(w.name!==w.code?w.name+' · '+w.code:w.code):'신호 차트';$('chart-sub').textContent=w?.stage?w.stage+' · 완료 봉 · VWAP · 기준선':'완료 봉 · VWAP · +5.5% 기준선';$('capture').textContent=w?.capture?fmt(w.capture,1):'—';$('baseline').textContent=w?.baseline?fmt(w.baseline,1):'—';$('macd').textContent=w?.macd!=null?fmt(w.macd,3):'—';$('cum').textContent=w?.cum!=null?fmt(w.cum,2)+'억':'—';const osig=w?state.orders.filter(o=>o.code===w.code).map(o=>o.status+o.filled).join():'';const dsig=w?[w.code,w.ticks,w.baseline,osig].join('|'):'';if(dsig&&dsig===drawSelected.sig&&lwChart)return;const cdata=selected?await api('chart/'+selected):{bars:[],baseline:0};draw(cdata);drawSelected.sig=dsig;}
let lwChart=null,lwCandle=null,lwVwap=null,lwMarkers=null,lwBase=null,lwBaseVal=0,lwCode='';
function chartHost(){let h=$('chart');if(h&&h.tagName==='CANVAS'){const hgt=h.getBoundingClientRect().height,d=document.createElement('div');d.id='chart';d.className=h.className;d.style.width='100%';h.replaceWith(d);if(!d.getBoundingClientRect().height)d.style.height=(hgt||320)+'px';h=d;}return h;}
function ensureChart(){
 if(lwChart)return true;const L=window.LightweightCharts;
 if(!L||!L.createChart){if(!ensureChart.warned){ensureChart.warned=true;toast('차트 라이브러리를 불러오지 못했습니다. frontend/vendor 파일을 확인하세요.',true);}return false;}
 lwChart=L.createChart(chartHost(),{autoSize:true,layout:{background:{type:L.ColorType.Solid,color:'transparent'},textColor:'#728ba1',fontSize:11},grid:{vertLines:{color:'rgba(34,49,66,.45)'},horzLines:{color:'#223142'}},rightPriceScale:{borderColor:'#223142'},timeScale:{borderColor:'#223142',timeVisible:true,secondsVisible:false},localization:{locale:'ko-KR',priceFormatter:p=>fmt(p)},crosshair:{mode:L.CrosshairMode.Normal}});
 lwCandle=lwChart.addSeries(L.CandlestickSeries,{upColor:'#f0616d',downColor:'#4c8df6',borderVisible:false,wickUpColor:'#f0616d',wickDownColor:'#4c8df6',autoscaleInfoProvider:orig=>{const r=orig();if(r&&lwBaseVal){r.priceRange.minValue=Math.min(r.priceRange.minValue,lwBaseVal);r.priceRange.maxValue=Math.max(r.priceRange.maxValue,lwBaseVal);}return r;}});
 lwVwap=lwChart.addSeries(L.LineSeries,{color:'#eac57c',lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
 lwMarkers=L.createSeriesMarkers(lwCandle,[]);return true;
}
function barTime(b){const d=String(b.date),t=String(b.full_time||(b.time+'00')).padStart(6,'0');return Date.UTC(+d.slice(0,4),+d.slice(4,6)-1,+d.slice(6,8),+t.slice(0,2),+t.slice(2,4),+t.slice(4,6))/1000;}
function draw(data){
 if(!ensureChart())return;const L=window.LightweightCharts;
 const all=data.bars||[];const day=all.some(b=>String(b.date)===state?.date)?state?.date:String(all.length?all[all.length-1].date:'');const bars=all.filter(b=>String(b.date)===day);let prev=0;
 const ts=bars.map(b=>{let t=barTime(b);if(!(t>prev))t=prev+1;prev=t;return t;});
 lwCandle.setData(bars.map((b,i)=>({time:ts[i],open:b.open,high:b.high,low:b.low,close:b.close})));
 lwVwap.setData(bars.flatMap((b,i)=>b.indicator?.vwap!=null?[{time:ts[i],value:b.indicator.vwap}]:[]));
 if(lwBase){lwCandle.removePriceLine(lwBase);lwBase=null;}lwBaseVal=data.baseline||0;
 if(lwBaseVal)lwBase=lwCandle.createPriceLine({price:lwBaseVal,color:'#ba9cfa',lineWidth:1,lineStyle:L.LineStyle.Dashed,axisLabelVisible:true,title:'기준선'});
 const ms=[];for(const o of data.orders||[]){if(o.signal_time==null)continue;const i=bars.findIndex(b=>b.timestamp>=o.signal_time);if(i<0)continue;const buy=o.side==='buy';ms.push({time:ts[i],position:buy?'belowBar':'aboveBar',color:buy?'#70e6aa':'#fc9b81',shape:buy?'arrowUp':'arrowDown',text:(buy?'매수 ':'매도 ')+o.qty});}
 ms.sort((a,b)=>a.time-b.time);lwMarkers.setMarkers(ms);
 if(lwCode!==selected){lwCode=selected;lwChart.timeScale().fitContent();}
}
async function poll(){try{await refresh();}catch(e){$('error').hidden=false;$('error').textContent='앱 서버 연결을 확인하세요. '+e.message;}setTimeout(poll,1000);}
try{token=(await api('bootstrap')).token;await poll();}catch(e){toast('앱 초기화 실패: '+e.message,true);}
