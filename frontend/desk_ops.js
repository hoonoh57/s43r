const q=id=>document.getElementById(id);let tok='',S=null,tab='pos';const selP=new Set(),selO=new Set();
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const f=(v,n=0)=>Number(v||0).toLocaleString('ko-KR',{maximumFractionDigits:n,minimumFractionDigits:n});
const sg=(v,n=0)=>(v>0?'+':'')+f(v,n),cl=v=>v>0?'pos':v<0?'neg':'';
function tm(t){if(!t)return '—';if(typeof t==='number')return new Date(t*1000).toLocaleTimeString('ko-KR',{hour12:false});const s=String(t).replace(/\D/g,'').slice(-6).padStart(6,'0');return s.slice(0,2)+':'+s.slice(2,4)+':'+s.slice(4);}
async function api(p,d){const r=await fetch('/api/'+p,{method:d===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Session':tok},body:d===undefined?undefined:JSON.stringify(d)});const b=await r.json().catch(()=>({}));if(!r.ok)throw Error(typeof b.detail==='string'?b.detail:'요청 실패 ('+r.status+')');return b;}
function msg(t,e){const m=q('ops-msg');if(!m)return;m.textContent=t;m.className=e?'neg':'cyan';clearTimeout(msg.t);msg.t=setTimeout(()=>{m.textContent='';},9000);}
function setTab(t){tab=t;document.querySelectorAll('#ops-panel [data-tab]').forEach(b=>b.classList.toggle('on',b.dataset.tab===t));q('ops-pos').hidden=t!=='pos';q('ops-bar-pos').hidden=t!=='pos';q('ops-ord').hidden=t!=='ord';q('ops-bar-ord').hidden=t!=='ord';}
function mount(){const el=q('ops-panel');if(!el)return false;
 el.innerHTML=`<div class="panel-head"><div class="ops-tabs"><button type="button" data-tab="pos" class="on">포지션 <i id="ops-npos">0</i></button><button type="button" data-tab="ord">미체결 <i id="ops-nord">0</i></button></div><span class="muted" id="ops-sync"></span></div>
 <div class="ops-bar" id="ops-bar-pos"><select id="ops-how"><option value="market">시장가</option><option value="bid">최우선 매수호가 지정가</option><option value="last">현재가 지정가</option><option value="bid_market">매수호가 지정가 → N초 후 시장가</option></select><label id="ops-wait-l">N초 <input id="ops-wait" type="number" min="3" max="120" value="10"></label><button type="button" id="ops-exit-sel" class="danger">선택 청산</button><button type="button" id="ops-exit-all" class="danger">전체 청산</button><span id="ops-msg"></span></div>
 <div class="ops-bar" id="ops-bar-ord" hidden><button type="button" id="ops-cancel-sel">선택 취소</button><button type="button" id="ops-cancel-all" class="danger">전체 취소</button><span class="muted">외부 = 키움 HTS·0309 등 앱 밖에서 낸 주문</span></div>
 <div class="table-wrap"><table id="ops-pos"><thead><tr><th><input type="checkbox" id="ops-allp" title="전체 선택"></th><th>종목</th><th>보유</th><th>주문가능</th><th>매입가</th><th>현재가</th><th>평가손익</th><th>수익률</th><th>구분</th><th>상태</th></tr></thead><tbody></tbody></table>
 <table id="ops-ord" hidden><thead><tr><th><input type="checkbox" id="ops-allo" title="전체 선택"></th><th>시각</th><th>종목</th><th>구분</th><th>주문</th><th>미체결</th><th>주문가</th><th>상태</th><th>출처</th></tr></thead><tbody></tbody></table></div>`;
 el.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>setTab(b.dataset.tab));
 const how=q('ops-how');how.onchange=()=>{q('ops-wait-l').hidden=how.value!=='bid_market';};q('ops-wait-l').hidden=true;
 q('ops-pos').addEventListener('change',e=>{const k=e.target.dataset.p;if(k===undefined)return;e.target.checked?selP.add(k):selP.delete(k);render();});
 q('ops-ord').addEventListener('change',e=>{const k=e.target.dataset.o;if(k===undefined)return;e.target.checked?selO.add(k):selO.delete(k);render();});
 q('ops-allp').onchange=e=>{selP.clear();if(e.target.checked&&S)S.positions.filter(r=>r.sellable).forEach(r=>selP.add(r.code));render();};
 q('ops-allo').onchange=e=>{selO.clear();if(e.target.checked&&S)S.orders.filter(r=>r.cancellable).forEach(r=>selO.add(r.id));render();};
 q('ops-exit-sel').onclick=()=>exitPos(false);q('ops-exit-all').onclick=()=>exitPos(true);
 q('ops-cancel-sel').onclick=()=>cancelOrd(false);q('ops-cancel-all').onclick=()=>cancelOrd(true);return true;}
function render(){if(!S)return;const P=S.positions,O=S.orders;
 const pk=new Set(P.filter(r=>r.sellable).map(r=>r.code));for(const k of [...selP])if(!pk.has(k))selP.delete(k);
 const ok=new Set(O.filter(r=>r.cancellable).map(r=>r.id));for(const k of [...selO])if(!ok.has(k))selO.delete(k);
 q('ops-npos').textContent=P.length;q('ops-nord').textContent=O.length;
 q('ops-pos').querySelector('tbody').innerHTML=P.map(r=>`<tr class="${selP.has(r.code)?'sel':''}"><td><input type="checkbox" data-p="${esc(r.code)}" ${selP.has(r.code)?'checked':''} ${r.sellable?'':'disabled'}></td><td><b>${esc(r.name)}</b><small>${esc(r.code)}</small></td><td>${f(r.qty)}</td><td>${f(r.orderable)}</td><td>${f(r.avg)}</td><td>${f(r.price)}</td><td class="${cl(r.pnl)}">${sg(r.pnl)}</td><td class="${cl(r.rate)}">${sg(r.rate,2)}%</td><td>${esc(r.owner)}</td><td class="${r.warn?'neg':'muted'}">${esc(r.status)}</td></tr>`).join('')||'<tr><td colspan="10" class="empty-row">보유 종목이 없습니다.</td></tr>';
 q('ops-ord').querySelector('tbody').innerHTML=O.map(r=>`<tr class="${selO.has(r.id)?'sel':''}"><td><input type="checkbox" data-o="${esc(r.id)}" ${selO.has(r.id)?'checked':''} ${r.cancellable?'':'disabled'}></td><td>${tm(r.time)}</td><td><b>${esc(r.name)}</b><small>${esc(r.code)}</small></td><td class="${r.side==='buy'?'cyan':'gold'}">${r.side==='buy'?'매수':r.side==='sell'?'매도':'?'}</td><td>${f(r.qty)}</td><td>${f(r.left)}</td><td>${r.price?f(r.price):'시장가'}</td><td>${esc(r.status)}</td><td class="${r.source==='외부'?'gold':'muted'}">${esc(r.source)}</td></tr>`).join('')||'<tr><td colspan="9" class="empty-row">미체결 주문이 없습니다.</td></tr>';
 q('ops-allp').checked=pk.size>0&&selP.size===pk.size;q('ops-allo').checked=ok.size>0&&selO.size===ok.size;
 q('ops-exit-sel').textContent=`선택 청산 (${selP.size})`;q('ops-cancel-sel').textContent=`선택 취소 (${selO.size})`;
 q('ops-sync').textContent=`키움 잔고 ${S.snapshot_at?tm(S.snapshot_at):'—'} · 실시간 04 ${S.live_at?tm(S.live_at):'수신 없음'}`;}
async function exitPos(all){if(!S)return;const P=S.positions.filter(r=>r.sellable&&(all||selP.has(r.code)));if(!P.length)return msg(all?'청산할 보유 종목이 없습니다.':'청산할 종목을 체크하세요.',true);
 const how=q('ops-how'),label=how.options[how.selectedIndex].text,wait=+q('ops-wait').value||10,ext=P.filter(r=>r.owner==='외부').length;
 const text=`${all?'전체':'선택'} 청산 ${P.length}종목 · ${label}${how.value==='bid_market'?' ('+wait+'초)':''}\n\n`+P.map(r=>`${r.name} ${f(Math.min(r.own,r.orderable||r.own))}주`).join('\n')+(ext?`\n\n외부 보유 ${ext}종목 포함`:'')+'\n\n기존 미체결은 먼저 취소합니다. 진행할까요?';
 if(!window.confirm(text))return;try{const r=await api('ops/exit',{codes:P.map(r=>r.code),how:how.value,wait,confirm:true});msg(r.message);selP.clear();}catch(e){msg(e.message,true);}}
async function cancelOrd(all){if(!S)return;const O=S.orders.filter(r=>r.cancellable&&(all||selO.has(r.id)));if(!O.length)return msg(all?'취소할 수 있는 미체결이 없습니다.':'취소할 주문을 체크하세요.',true);
 const text=`${all?'전체':'선택'} 미체결 취소 ${O.length}건\n\n`+O.map(r=>`${r.name} ${r.side==='sell'?'매도':'매수'} ${f(r.left)}주 @${r.price?f(r.price):'시장가'} (${r.source})`).join('\n')+'\n\n취소 접수 뒤에도 그 사이 체결될 수 있습니다. 진행할까요?';
 if(!window.confirm(text))return;try{const r=await api('ops/cancel',{ids:O.map(r=>r.id),confirm:true});msg(r.message,!!r.failed);selO.clear();}catch(e){msg(e.message,true);}}
async function poll(){try{S=await api('ops/state');render();}catch(e){}setTimeout(poll,1000);}
(async()=>{try{tok=(await api('bootstrap')).token;}catch(e){}if(mount())poll();})();
// END desk_ops.js
