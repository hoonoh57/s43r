(()=>{'use strict';
const g=id=>document.getElementById(id);
const css=`#stSel{background:#0b0f16;color:#e6edf3;border:1px solid #2c3a50;border-radius:4px;padding:3px 6px;margin-right:4px}
#stCmp{background:#2d333b;color:#e6edf3;border:0;border-radius:4px;padding:4px 10px;cursor:pointer;margin-right:6px}
#stPanel{position:fixed;left:50%;top:90px;transform:translateX(-50%);width:min(1150px,calc(100vw - 20px));max-height:75vh;overflow:auto;background:#0b1220;border:1px solid #2c3a50;border-radius:6px;box-shadow:0 8px 24px #000a;font:12px system-ui;color:#cdd6e4;z-index:60}
#stPanel .hd{display:flex;justify-content:space-between;align-items:center;padding:8px 10px;border-bottom:1px solid #1e293b}
#stPanel table{width:100%;border-collapse:collapse}
#stPanel th,#stPanel td{padding:4px 8px;border-bottom:1px solid #131c2b;text-align:right;white-space:nowrap}
#stPanel th:first-child,#stPanel td:first-child{text-align:left}
#stPanel th{position:sticky;top:0;background:#111a2b}#stPanel tfoot td{font-weight:600;background:#0f1a2c}
#stPanel .pos{color:#f87171}#stPanel .neg{color:#60a5fa}#stPanel small{color:#64748b;font-weight:400}
#stPanel button{background:#2d333b;color:#e6edf3;border:0;border-radius:4px;padding:3px 10px;cursor:pointer}`;
let TOKEN=null,LIST=[];
async function tok(f){if(f||!TOKEN){const r=await fetch('/api/bootstrap',{cache:'no-store'});TOKEN=(await r.json()).token}return TOKEN}
async function post(url,body){for(let i=0;i<2;i++){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Session':await tok(i>0)},body:JSON.stringify(body)});
  let b=null;try{b=await r.json()}catch(e){}if(r.status===403&&!i)continue;
  if(!r.ok)throw new Error((b&&typeof b.detail==='string'&&b.detail)||('HTTP '+r.status));return b}}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=v=>v==null||!isFinite(v)?'—':(v>0?'+':'')+Number(v).toFixed(2)+'%';
const cls=v=>v>0?'pos':v<0?'neg':'';
const cur=()=>(g('stSel')||{}).value||'S4.3-R';
function wrap(){const o=window.opts;if(typeof o!=='function')return false;if(o.__st)return true;
  const w=function(){const x=o.apply(this,arguments)||{};x.params=Object.assign({},x.params||{},{strategy:cur()});return x};
  w.__st=1;window.opts=w;return true}
function stat(rows,s){let ent=0,win=0,sum=0,gp=0,gl=0;
  for(const r of rows){const x=r.res&&r.res[s];if(!x||x.error||!x.entered)continue;const p=+x.pnl||0;ent++;if(p>0){win++;gp+=p}else gl-=p;sum+=p}
  return{ent,win:ent?win/ent*100:0,sum,pf:gl?gp/gl:(gp?Infinity:null)}}
function show(d){let P=g('stPanel');
  if(!P){P=document.createElement('div');P.id='stPanel';document.body.appendChild(P);P.addEventListener('click',e=>{if(e.target.id==='stClose')P.remove()})}
  const N=d.strategies,rows=d.rows,O=N[0];
  const val=(r,s)=>{const x=r.res[s];return x&&!x.error&&x.entered?(+x.pnl||0):null};
  const cell=(r,s)=>{const x=r.res[s];if(!x)return'<td>—</td>';if(x.error)return`<td title="${esc(x.error)}" style="color:#f85149">오류</td>`;
    if(!x.entered)return'<td><small>미진입</small></td>';return`<td class="${cls(x.pnl)}">${pct(x.pnl)}<br><small>${esc(x.reason)}</small></td>`};
  const diff=(r,s)=>{const a=val(r,O),b=val(r,s);if(a==null&&b==null)return'<td>—</td>';const z=(b||0)-(a||0);return`<td class="${cls(z)}">${(z>0?'+':'')+z.toFixed(2)}%p</td>`};
  const S=N.map(s=>stat(rows,s));
  P.innerHTML=`<div class="hd"><b>버전 비교 · ${esc(d.date)} · ${rows.length}종목</b><span><small>모델 손익(비용 전) · 차이는 원본 대비</small> <button id="stClose">닫기</button></span></div>
  <table><thead><tr><th>종목</th>${N.map(s=>`<th>${esc(s)}</th>`).join('')}${N.slice(1).map(s=>`<th>${esc(s.replace('S4.3-',''))}−원본</th>`).join('')}</tr></thead>
  <tbody>${rows.map(r=>`<tr><td>${esc(r.name)} <small>${esc(r.code)}</small></td>${N.map(s=>cell(r,s)).join('')}${N.slice(1).map(s=>diff(r,s)).join('')}</tr>`).join('')}</tbody>
  <tfoot><tr><td>합계</td>${S.map(z=>`<td class="${cls(z.sum)}">${pct(z.sum)}<br><small>진입 ${z.ent} · 승률 ${z.win.toFixed(1)}% · PF ${z.pf==null?'—':z.pf===Infinity?'∞':z.pf.toFixed(2)}</small></td>`).join('')}${S.slice(1).map(z=>{const q=z.sum-S[0].sum;return`<td class="${cls(q)}">${(q>0?'+':'')+q.toFixed(2)}%p</td>`}).join('')}</tr></tfoot></table>`}
async function compare(){const b=g('stCmp'),date=(g('dSel')||{}).value;if(!date){alert('포착일을 먼저 선택하세요.');return}
  const o=typeof window.opts==='function'?window.opts():{};b.disabled=true;const t0=Date.now();
  const iv=setInterval(()=>b.textContent=`비교 중… ${Math.round((Date.now()-t0)/1000)}s`,500);
  try{show(await post('/api/sim/compare',{date,eligible_only:!!(g('dOnly')&&g('dOnly').checked),size:o.size,slip:o.slip,cost:o.cost,capital:o.capital,params:o.params||{}}))}
  catch(e){alert('버전 비교 실패: '+e.message)}finally{clearInterval(iv);b.disabled=false;b.textContent='버전 비교'}}
async function mount(){const st=document.createElement('style');st.textContent=css;document.head.appendChild(st);
  for(let i=0;i<100&&!g('run');i++)await new Promise(r=>setTimeout(r,100));
  const run=g('run');if(!run)return;
  try{LIST=await(await fetch('/api/sim/strategies',{cache:'no-store'})).json()}catch(e){LIST=[{name:'S4.3-R',label:'원본'}]}
  const sel=document.createElement('select');sel.id='stSel';
  sel.innerHTML=LIST.map(s=>`<option value="${esc(s.name)}">${esc(s.name)}</option>`).join('');
  const sv=localStorage.getItem('simStrategy');if(sv&&LIST.some(s=>s.name===sv))sel.value=sv;
  const tip=()=>sel.title=(LIST.find(s=>s.name===sel.value)||{}).label||'';tip();
  sel.onchange=()=>{localStorage.setItem('simStrategy',sel.value);tip();run.click()};
  const cmp=document.createElement('button');cmp.id='stCmp';cmp.textContent='버전 비교';cmp.onclick=compare;
  run.parentNode.insertBefore(sel,run);run.parentNode.insertBefore(cmp,run);
  if(!wrap()){sel.disabled=true;sel.title='sim.js opts() 를 찾지 못해 버전 선택 불가'}}
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',mount):mount();
})();
