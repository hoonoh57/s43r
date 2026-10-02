(()=>{'use strict';
const css=`#cyb{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:6px 10px;background:#11161f;border-bottom:1px solid #263041;font:12px system-ui;color:#cdd6e4}
#cyb input,#cyb select{background:#0b0f16;color:#e6edf3;border:1px solid #2c3a50;border-radius:4px;padding:3px 6px}
#cyb button{background:#1f6feb;color:#fff;border:0;border-radius:4px;padding:4px 10px;cursor:pointer}
#cyb button.g{background:#2d333b}#cyb button:disabled{opacity:.5;cursor:default}
#cyb .msg{margin-left:6px;white-space:pre-wrap}#cyb .ok{color:#3fb950}#cyb .bad{color:#f85149}`;
const $=s=>document.querySelector(s);
const ymd=d=>d.getFullYear()+String(d.getMonth()+1).padStart(2,'0')+String(d.getDate()).padStart(2,'0');
function lastBiz(){const d=new Date();if(d.getHours()<20)d.setDate(d.getDate()-1);while(d.getDay()===0||d.getDay()===6)d.setDate(d.getDate()-1);return ymd(d)}
function say(t,c){const m=$('#cybMsg');m.textContent=t;m.className='msg '+(c||'')}
let TOKEN=null;
async function tok(force){if(force||!TOKEN){const r=await fetch('/api/bootstrap',{cache:'no-store'});TOKEN=(await r.json()).token}return TOKEN}
async function send(url,opt){opt=Object.assign({},opt||{});const m=(opt.method||'GET').toUpperCase();
  if(m==='GET'||m==='HEAD')return fetch(url,opt);
  for(let i=0;i<2;i++){opt.headers=Object.assign({},opt.headers||{},{'x-session':await tok(i>0)});
    const r=await fetch(url,opt);if(r.status!==403||i)return r}}
async function j(url,opt){const r=await send(url,opt);let b=null;try{b=await r.json()}catch(e){}
  if(!r.ok)throw new Error((b&&b.detail)||('HTTP '+r.status));return b}
async function probe(){say('점검 중…');try{const r=await j('/api/sim/cybos/probe');const bad=[];
  if(!r.exists)bad.push('32비트 파이썬 없음: '+r.py32);
  else{if(r.bits!==32)bad.push('비트수 '+r.bits+' (32 필요)');if(!r.pywin32)bad.push('pywin32 없음');
    if(r.connect!==1)bad.push('Cybos 미로그인/미연결');if(r.admin===false)bad.push('관리자 권한 아님');if(r.error)bad.push(r.error)}
  if(!r.worker)bad.push('tools/cybos_ticks.py 없음');
  say(bad.length?'✗ '+bad.join(' · '):'✓ 32비트 · pywin32 · Cybos 연결 · 관리자',bad.length?'bad':'ok')}catch(e){say('✗ '+e.message,'bad')}}
function refresh(){if(typeof window.simReloadFiles==='function'){window.simReloadFiles();return}
  window.dispatchEvent(new CustomEvent('sim-ticks-ready'));
  if(!$('#cybReload')){const b=document.createElement('button');b.id='cybReload';b.className='g';b.textContent='파일 목록 새로고침';b.onclick=()=>location.reload();$('#cyb').appendChild(b)}}
async function poll(id){for(;;){const s=await j('/api/sim/cybos/job/'+id);
  if(s.state==='queued'||s.state==='running'){const sec=s.started?Math.max(0,Math.round(Date.now()/1000-s.started)):0;
    say(`다운로드 ${s.done}/${s.total} · ${s.current||'대기'} · ${sec}s`);await new Promise(r=>setTimeout(r,1000));continue}
  say(s.results.map(r=>`${r.ok?'✓':'✗'} ${r.code} `+(r.ok?`${r.file} ${(r.size/1048576).toFixed(1)}MB ${r.sec}s`:`rc=${r.rc} ${r.msg}`)).join('\n'),s.state==='done'?'ok':'bad');
  if(s.results.some(r=>r.ok))refresh();return}}
async function go(){const codes=$('#cybCodes').value.trim(),date=$('#cybDate').value.trim(),prior=+$('#cybPrior').value;
  localStorage.cybCodes=codes;localStorage.cybDate=date;$('#cybGo').disabled=true;say('요청 중…');
  try{const job=await j('/api/sim/cybos/fetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({codes,date,prior})});await poll(job.id)}
  catch(e){say('✗ '+e.message,'bad')}finally{$('#cybGo').disabled=false}}
function mount(){const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
  const box=document.createElement('div');box.id='cyb';
  box.innerHTML=`<b>Cybos 1틱</b><input id="cybCodes" size="24" placeholder="종목코드 (쉼표로 여러 개)">
  <input id="cybDate" size="9" placeholder="YYYYMMDD"><label>선행 <select id="cybPrior">${[1,2,3,4,5].map(n=>`<option${n===2?' selected':''}>${n}</option>`).join('')}</select>일</label>
  <button id="cybGo">다운로드</button><button id="cybProbe" class="g">연결 점검</button><span class="msg" id="cybMsg"></span>`;
  document.body.prepend(box);$('#cybDate').value=localStorage.cybDate||lastBiz();$('#cybCodes').value=localStorage.cybCodes||'';
  $('#cybGo').onclick=go;$('#cybProbe').onclick=probe}
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',mount):mount();
})();
