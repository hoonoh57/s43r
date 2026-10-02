(()=>{'use strict';
const css=`#dWrap{position:relative;z-index:40}
#dayBar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:6px 10px;background:#0d1b2a;border-bottom:1px solid #263041;font:12px system-ui;color:#cdd6e4}
#dayBar select,#dayBar input{background:#0b0f16;color:#e6edf3;border:1px solid #2c3a50;border-radius:4px;padding:3px 6px}
#dayBar button,#dPanel button{background:#2d333b;color:#e6edf3;border:0;border-radius:4px;padding:4px 10px;cursor:pointer}
#dayBar button.pri{background:#1f6feb;color:#fff}#dayBar button:disabled,#dayBar select:disabled{opacity:.5;cursor:default}
#dPanel{position:absolute;left:8px;top:100%;width:min(1150px,calc(100vw - 16px));max-height:66vh;overflow:auto;background:#0b1220;border:1px solid #2c3a50;border-radius:6px;box-shadow:0 8px 24px #000a;font:12px system-ui;color:#cdd6e4}
#dPanel .sum{padding:8px 10px;border-bottom:1px solid #1e293b;line-height:1.7}
#dPanel table{width:100%;border-collapse:collapse}
#dPanel th,#dPanel td{padding:4px 8px;border-bottom:1px solid #131c2b;text-align:left;white-space:nowrap}
#dPanel th{position:sticky;top:0;background:#111a2b;z-index:1}
#dPanel small{color:#64748b;margin-left:4px}#dPanel tr.cur td{background:#132238}
#dPanel .pos{color:#f87171}#dPanel .neg{color:#60a5fa}#dPanel .warn{color:#f59e0b}
.st-ok{color:#3fb950}.st-short{color:#f59e0b}.st-none{color:#64748b}.st-bad{color:#f85149}
.dmsg{margin-left:6px;white-space:pre-wrap}.dmsg.ok{color:#3fb950}.dmsg.bad{color:#f85149}`;
const $=s=>document.querySelector(s);
let TOKEN=null,DAY=null,SIM={},CHECK=new Set();
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function tok(force){if(force||!TOKEN){const r=await fetch('/api/bootstrap',{cache:'no-store'});TOKEN=(await r.json()).token}return TOKEN}
async function api(url,body){const post=body!==undefined;
  for(let i=0;i<2;i++){const opt=post?{method:'POST',headers:{'Content-Type':'application/json','X-Session':await tok(i>0)},body:JSON.stringify(body)}:{cache:'no-store'};
    const r=await fetch(url,opt);let b=null;try{b=await r.json()}catch(e){}
    if(post&&r.status===403&&!i)continue;
    if(!r.ok)throw new Error((b&&typeof b.detail==='string'&&b.detail)||('HTTP '+r.status));return b}}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=(v,d=0)=>v==null||!isFinite(v)?'—':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d,minimumFractionDigits:d});
const cls=v=>v>0?'pos':v<0?'neg':'';
const say=(t,c)=>{const m=$('#dMsg');m.textContent=t;m.className='dmsg '+(c||'')};
const size=()=>+(($('#size')||{}).value||360);
const warm=t=>Object.values(t.prior||{}).reduce((a,c)=>a+Math.floor(c/size()),0);
function status(x){const t=x.tick;if(!t)return['none','미수신'];if(t.error)return['bad',t.error];if(!t.day)return['bad','지정일 틱 없음'];const w=warm(t);return w<40?['short',`선행 ${w}봉 부족`]:['ok',`✓ 선행 ${w}봉`]}
const visible=()=>(DAY?DAY.stocks:[]).filter(x=>!$('#dOnly').checked||x.eligible);
function stat(list,pnl){const ent=list.filter(x=>x&&x.entered),w=ent.filter(x=>pnl(x)>0).length;
  const gp=ent.reduce((a,x)=>a+Math.max(0,pnl(x)),0),gl=ent.reduce((a,x)=>a+Math.max(0,-pnl(x)),0);
  return{n:list.filter(Boolean).length,ent:ent.length,win:ent.length?w/ent.length*100:0,sum:ent.reduce((a,x)=>a+pnl(x),0),pf:gl?gp/gl:(gp?Infinity:null)}}
function summary(rows){const sims=rows.map(x=>SIM[x.code]).filter(s=>s&&!s.error),S=stat(sims,s=>s.model_pnl||0),R=stat(rows.map(x=>x.ref),r=>r.pnl||0);
  const net=sims.reduce((a,s)=>a+(s.net||0),0);
  const fmt=z=>`진입 ${z.ent}/${z.n} · 승률 ${n(z.win,1)}% · 손익합 <span class="${cls(z.sum)}">${n(z.sum,2)}%</span> · PF ${z.pf==null?'—':z.pf===Infinity?'∞':n(z.pf,2)}`;
  return `<b>시뮬레이션</b> ${S.n?fmt(S)+` · 순손익 <span class="${cls(net)}">${n(net)}원</span> (비용·슬리피지 포함)`:'아직 실행 안 함'}<br><b>참조 kiwoom1516 S4.3R</b> ${R.n?fmt(R):'참조 없음 (lab 파일 없음)'}`}
function row(x){const st=status(x),s=SIM[x.code],r=x.ref,cur=$('#file')&&x.tick&&$('#file').value===x.tick.file;
  const ref=r?(r.entered?`${esc(r.entry)} · <span class="${cls(r.pnl)}">${n(r.pnl,2)}%</span> · ${esc(r.reason||'')}`:'미진입'):'—';
  let sim='—';
  if(s){if(s.error)sim=`<span class="neg">${esc(s.error)}</span>`;
    else{const mis=r&&(r.entered!==!!s.entered||(r.entered&&r.entry!==s.entry));
      sim=(s.entered?`${esc(s.entry)} · <span class="${cls(s.model_pnl)}">${n(s.model_pnl,2)}%</span> · <span class="${cls(s.net)}">${n(s.net)}원</span> · ${esc(s.reason||'')}`:'미진입')
        +(mis?' <b class="warn" title="참조와 진입 여부/시각이 다릅니다">≠</b>':'')+(s.warn&&s.warn.length?` <span class="warn" title="${esc(s.warn.join(' / '))}">⚠</span>`:'')}}
  return `<tr class="${cur?'cur':''}"><td><input type="checkbox" class="dc" data-code="${x.code}" ${CHECK.has(x.code)?'checked':''}></td><td>${esc(x.name)}<small>${x.code}</small></td><td class="${x.eligible?'pos':''}">${n(x.mfe,2)}</td><td>${esc(x.label||(x.eligible?'고':''))}</td><td class="st-${st[0]}">${st[1]}${x.tick?`<small>${n(x.tick.ticks)}틱</small>`:''}</td><td>${ref}</td><td>${sim}</td><td>${x.tick&&x.tick.day?`<button class="dOpen" data-file="${esc(x.tick.file)}">차트 ▶</button>`:''}</td></tr>`}
function render(){const P=$('#dPanel');if(!DAY){P.innerHTML='';return}const rows=visible(),all=rows.length&&rows.every(x=>CHECK.has(x.code));
  $('#dInfo').textContent=`${DAY.stocks.length}종목 · 통과 ${DAY.stocks.filter(x=>x.eligible).length} · 수신완료 ${DAY.stocks.filter(x=>status(x)[0]==='ok').length}`;
  P.innerHTML=`<div class="sum">${summary(rows)}</div><table><tr><th><input type="checkbox" id="dAll" ${all?'checked':''}></th><th>종목</th><th>MFE%</th><th>등급</th><th>1틱 데이터</th><th>참조 S4.3R (kiwoom1516)</th><th>시뮬레이션 (진입 · 엔진% · 순손익 · 사유)</th><th></th></tr>${rows.map(row).join('')}</table>`}
async function reloadFiles(date){date=date||$('#dSel').value||'';const sel=$('#file');if(!sel)return;
  const r=await api('/api/sim/files'),fs=r.files.filter(x=>!date||x.date===date),cur=sel.value;
  sel.innerHTML=fs.map(x=>`<option value="${esc(x.file)}">${x.date} ${esc(x.name||'')} ${x.code} · 선행 ${(x.prior||[]).length}일 · ${Number(x.ticks).toLocaleString()}틱</option>`).join('')||'<option value="">이 날짜의 틱 파일 없음</option>';
  if(fs.some(x=>x.file===cur))sel.value=cur}
async function loadDay(keep){const date=$('#dSel').value;if(!date)return;localStorage.simDay=date;
  DAY=await api('/api/sim/capture/'+date);
  if(!keep){SIM={};CHECK=new Set(DAY.stocks.map(x=>x.code))}
  const c=$('#cybDate');if(c)c.value=date;
  await reloadFiles(date);render();if(!keep)$('#dPanel').hidden=false}
async function loadDates(){const r=await api('/api/sim/capture-dates');
  if(!r.exists){$('#dSel').innerHTML='<option value="">폴더 없음</option>';return say('포착 기록 폴더가 없습니다: '+r.dir+' (환경변수 S43R_CAPTURE_DIR로 지정 가능)','bad')}
  $('#dSel').innerHTML=r.dates.map(d=>`<option value="${d.date}">${d.date.slice(0,4)}-${d.date.slice(4,6)}-${d.date.slice(6)} · ${d.n}종목 (통과 ${d.eligible})</option>`).join('')||'<option value="">포착 파일 없음</option>';
  const saved=localStorage.simDay;if(saved&&r.dates.some(d=>d.date===saved))$('#dSel').value=saved;
  if($('#dSel').value)await loadDay()}
function lock(b){['#dGet','#dRun','#dSel'].forEach(s=>$(s).disabled=b)}
async function download(){const date=$('#dSel').value,codes=visible().filter(x=>CHECK.has(x.code)&&['none','short'].includes(status(x)[0])).map(x=>x.code);
  if(!DAY)return say('포착일 목록이 아직 없습니다.','bad');if(!codes.length)return say('받을 종목이 없습니다. (선택 종목 모두 수신 완료)','ok');
  lock(true);const fails=[];
  try{for(let i=0;i<codes.length;i+=30){const part=codes.slice(i,i+30);
      const job=await api('/api/sim/cybos/fetch',{codes:part.join(','),date,prior:+$('#dPrior').value});
      for(;;){const s=await api('/api/sim/cybos/job/'+job.id);
        if(s.state==='queued'||s.state==='running'){const sec=s.started?Math.max(0,Math.round(Date.now()/1000-s.started)):0;
          say(`다운로드 ${i+s.done}/${codes.length} · ${s.current||'대기'} · ${sec}s`);await sleep(1000);continue}
        fails.push(...s.results.filter(r=>!r.ok));break}}
    await loadDay(true);
    say(fails.length?`완료 · 실패 ${fails.length}: `+fails.map(r=>`${r.code} ${r.msg}`).join(' / '):`다운로드 완료 · ${codes.length}종목`,fails.length?'bad':'ok')}
  catch(e){say(e.message,'bad')}finally{lock(false)}}
async function runDay(){const date=$('#dSel').value,codes=visible().filter(x=>CHECK.has(x.code)&&x.tick&&x.tick.day).map(x=>x.code);
  if(!DAY)return say('포착일 목록이 아직 없습니다.','bad');if(!codes.length)return say('실행할 틱 파일이 없습니다. 먼저 다운로드하세요.','bad');
  const o=typeof window.opts==='function'?window.opts():{};lock(true);say(`${codes.length}종목 시뮬레이션 중…`);
  try{const r=await api('/api/sim/day',{date,codes,size:o.size||size(),slip:o.slip??1,cost:o.cost??0.25,capital:o.capital??1000000,params:o.params||{}});
    for(const x of r.rows)SIM[x.code]=x;$('#dPanel').hidden=false;render();
    const err=r.rows.filter(x=>x.error).length;say(`완료 · ${r.rows.length}종목`+(err?` · 오류 ${err}`:''),err?'bad':'ok')}
  catch(e){say(e.message,'bad')}finally{lock(false)}}
async function openFile(f){const sel=$('#file');if(!sel)return;if(![...sel.options].some(o=>o.value===f))await reloadFiles();
  sel.value=f;$('#dPanel').hidden=true;const b=$('#run');if(b)b.click()}
async function mount(){const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
  const w=document.createElement('div');w.id='dWrap';
  w.innerHTML=`<div id="dayBar"><b>포착일</b><select id="dSel"><option value="">불러오는 중…</option></select><span id="dInfo"></span>
  <button id="dList">종목 목록 ▾</button><label><input type="checkbox" id="dOnly"> MFE 통과만</label>
  <label>선행 <select id="dPrior">${[1,2,3,4,5].map(k=>`<option${k===2?' selected':''}>${k}</option>`).join('')}</select>일</label>
  <button id="dGet">다운로드 (미수신·부족)</button><button id="dRun" class="pri">당일 일괄 실행</button><span id="dMsg" class="dmsg"></span></div><div id="dPanel" hidden></div>`;
  document.body.prepend(w);
  $('#dSel').onchange=()=>loadDay().catch(e=>say(e.message,'bad'));
  $('#dList').onclick=()=>{$('#dPanel').hidden=!$('#dPanel').hidden;render()};
  $('#dOnly').onchange=render;$('#dGet').onclick=download;$('#dRun').onclick=runDay;
  const P=$('#dPanel');
  P.addEventListener('change',e=>{const t=e.target;
    if(t.id==='dAll'){visible().forEach(x=>t.checked?CHECK.add(x.code):CHECK.delete(x.code));render()}
    else if(t.classList.contains('dc')){t.checked?CHECK.add(t.dataset.code):CHECK.delete(t.dataset.code);render()}});
  P.addEventListener('click',e=>{const b=e.target.closest('.dOpen');if(b)openFile(b.dataset.file)});
  for(let i=0;i<50;i++){const s=$('#file');if(s&&s.options.length)break;await sleep(100)}
  window.simReloadFiles=()=>loadDay(true).catch(e=>say(e.message,'bad'));
  lock(true);say('포착 기록 읽는 중…');const t0=Date.now();try{await loadDates();if($('#dMsg').textContent.startsWith('포착 기록 읽는'))say('포착 기록 '+((Date.now()-t0)/1000).toFixed(1)+'s','ok')}catch(e){say('포착 목록 실패: '+e.message,'bad')}finally{lock(false)}}
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',mount):mount();
})();
