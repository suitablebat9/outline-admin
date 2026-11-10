const $=s=>document.querySelector(s);
let csrf=$('meta[name="csrf-token"]').content, users=[], removing=null, busy=false, refreshing=false, historySignature=null, eventSignature=null, sharingName=null, sharingId=null, sendRequestId=null;
const bytes=n=>{if(!n)return '0 B';const u=['B','KiB','MiB','GiB','TiB'];const i=Math.min(4,Math.floor(Math.log(n)/Math.log(1024)));return `${(n/1024**i).toFixed(i?1:0)} ${u[i]}`};
const when=t=>t?new Date(t*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'Not observed';
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;setTimeout(()=>$('#toast').hidden=true,3500)}
async function api(url,options={}){const response=await fetch(url,{signal:AbortSignal.timeout(options.method ? 60000 : 15000),...options,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,...options.headers}});let data;try{data=await response.json()}catch{throw Error('Unexpected server response. Check the admin tunnel route.')}if(!response.ok){if(response.status===401&&!url.endsWith('/login'))showLogin();throw Error(data.error||'Request failed.')}return data}
function showLogin(){$('#dashboard').hidden=true;$('#login').hidden=false;document.querySelectorAll('dialog[open]').forEach(d=>d.close());$('#key-value').value=''}
function showKey(name,key,id){
  sharingName=name;sharingId=id;sendRequestId=crypto.randomUUID();
  $('#email-form').reset();$('#share-email').disabled=false;
  $('#send-email').disabled=true;$('#send-email').textContent='Send email with attachment';
  $('#share-status').textContent='Checking email configuration…';
  $('#key-title').textContent=`Access for ${name}`;$('#key-value').value=key;$('#copy-key').textContent='Copy access code';$('#key-dialog').showModal();
  api('/api/email/status').then(status=>{if(sharingId!==id)return;$('#send-email').disabled=!status.ready;$('#share-status').textContent=status.ready?`Sends from ${status.sender}. The access code and actual DNS profile file will be emailed to the address you enter.`:'Email setup required: run outline-admin-email-setup inside your LXC, then reopen this panel.'}).catch(()=>{if(sharingId===id)$('#share-status').textContent='Could not check email setup. Close and reopen this panel.'});
}
function renderUsers(){
  const term=$('#search').value.toLowerCase();
  const filtered=users.filter(u=>u.name.toLowerCase().includes(term));
  const body=$('#users'), wanted=new Set(filtered.map(u=>u.id));
  for(const row of [...body.children])if(!wanted.has(row.dataset.id))row.remove();
  $('#empty').hidden=filtered.length>0;
  $('#empty strong').textContent=users.length?'No matching people.':'Your network starts here.';
  $('#empty p').textContent=users.length?'Try a different search.':'Create an access key to invite your first person.';
  for(const u of filtered){
    let tr=[...body.children].find(row=>row.dataset.id===u.id);
    if(!tr){
      tr=el('tr');tr.dataset.id=u.id;
      const person=el('div',undefined,'person');
      person.append(el('div',u.name.slice(0,2),'avatar'));
      const identity=el('div');const personButton=el('button',u.name,'person-name');personButton.setAttribute('aria-label',`Share access for ${u.name}`);identity.append(personButton,el('small',u.legacy?'Existing server key':'Personal access'));person.append(identity);
      const td=el('td');td.append(person);tr.append(td);
      const activity=el('td');activity.append(el('span','','activity-pill'));tr.append(activity);
      for(let i=0;i<4;i++)tr.append(el('td',''));
      const actions=el('td',undefined,'right');
      const view=el('button','Share','text-button');
      const openShare=async()=>{view.disabled=true;personButton.disabled=true;try{showKey(u.name,(await api(`/api/users/${encodeURIComponent(u.id)}/key`)).key,u.id)}catch(e){toast(e.message)}finally{view.disabled=false;personButton.disabled=false}};view.addEventListener('click',openShare);personButton.addEventListener('click',openShare);
      const remove=el('button','Revoke','revoke');
      remove.addEventListener('click',()=>{removing=u;$('#remove-title').textContent=`Revoke ${u.name}'s access?`;$('#remove-dialog .dialog-error').textContent='';$('#remove-dialog').showModal()});
      actions.append(view,remove);tr.append(actions);body.append(tr);
    }
    const pill=tr.children[1].firstChild;
    pill.textContent=u.activity;
    pill.className='activity-pill '+(u.activity==='Active recently'?'on':u.activity==='Unknown'?'unknown':'');
    [bytes(u.download),bytes(u.upload),bytes(u.today),when(u.last_active)].forEach((value,i)=>{if(tr.children[i+2].textContent!==value)tr.children[i+2].textContent=value});
  }
}
function chart(history){const map=new Map(history.map(d=>[d.day,d]));const days=[];for(let i=13;i>=0;i--){const d=new Date();d.setUTCDate(d.getUTCDate()-i);const day=d.toISOString().slice(0,10);days.push(map.get(day)||{day,download:0,upload:0})}const max=Math.max(1,...days.map(d=>d.upload+d.download));const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 980 150');svg.setAttribute('preserveAspectRatio','none');for(let i=0;i<days.length;i++){const d=days[i],download=140*d.download/max,upload=140*d.upload/max;for(const [height,y,color]of [[download,150-download,'#59dfb4'],[upload,150-download-upload,'#6678f4']]){const rect=document.createElementNS(ns,'rect');Object.entries({x:i*70+12,y,width:42,height,rx:2,fill:color}).forEach(([k,v])=>rect.setAttribute(k,v));const title=document.createElementNS(ns,'title');title.textContent=`${d.day}: ${bytes(d.download)} downloaded, ${bytes(d.upload)} uploaded`;rect.append(title);svg.append(rect)}}$('#chart').replaceChildren(svg);if(max===1){const title=document.createElementNS(ns,'text');title.setAttribute('x','490');title.setAttribute('y','80');title.setAttribute('text-anchor','middle');title.setAttribute('fill','#819397');title.setAttribute('font-size','12');title.textContent='Recorded traffic will appear here';svg.append(title)}$('#chart-start').textContent=days[0].day}
async function refresh(){if($('#dashboard').hidden||busy||refreshing||document.hidden)return;refreshing=true;$('#refresh-now').disabled=true;try{const d=await api('/api/dashboard');users=d.users;$('#count').textContent=users.length;$('#table-count').textContent=users.length;$('#active').textContent=d.healthy?users.filter(u=>u.activity==='Active recently').length:'—';$('#download').textContent=bytes(d.total_download);$('#upload').textContent=bytes(d.total_upload);$('#health').textContent=d.healthy?'● Live · 2s':'○ Metrics unavailable';$('#health').className='pill'+(d.healthy?'':' warn');$('#notice').hidden=d.healthy;$('#notice').textContent='Metrics are unavailable. Activity is unknown; recorded totals are retained. Check the Outline metrics listener and service.';$('#monitoring-since').textContent='Monitoring installed '+when(d.started);$('#updated').textContent='Last successful sample '+when(d.last_ok);renderUsers();const nextHistory=JSON.stringify(d.history);if(nextHistory!==historySignature){chart(d.history);historySignature=nextHistory}const nextEvents=JSON.stringify(d.events);if(nextEvents!==eventSignature){eventSignature=nextEvents;$('#events').replaceChildren();for(const event of d.events){const row=el('div',undefined,'event');const detail=el('div',event.action);detail.append(el('small',event.username));row.append(detail,el('time',when(event.at)));$('#events').append(row)}if(!d.events.length)$('#events').append(el('p','No admin actions yet.','muted'))}}catch(e){$('#notice').hidden=false;$('#notice').textContent=e.name==='TimeoutError'?'Refresh timed out. Retrying automatically.':e.message;$('#health').textContent='○ Connection interrupted';$('#health').className='pill warn';$('#active').textContent='—'}finally{refreshing=false;$('#refresh-now').disabled=false}}
$('#login-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.target.querySelector('button');button.disabled=true;$('#login-error').textContent='';try{const f=new FormData(e.target);const d=await api('/api/login',{method:'POST',body:JSON.stringify(Object.fromEntries(f))});csrf=d.csrf;e.target.password.value='';$('#login').hidden=true;$('#dashboard').hidden=false;await refresh()}catch(error){$('#login-error').textContent=error.message}finally{button.disabled=false}});
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout',{method:'POST'});location.reload()}catch(e){toast(e.message)}});
$('#open-add').addEventListener('click',()=>{$('#add-form').reset();$('#add-dialog .dialog-error').textContent='';$('#add-dialog').showModal()});
document.querySelectorAll('.close').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
$('#key-dialog').addEventListener('close',()=>{$('#key-value').value='';$('#email-form').reset();sharingName=null;sharingId=null;sendRequestId=null});
$('#search').addEventListener('input',renderUsers);
$('#copy-key').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#key-value').value);$('#copy-key').textContent='Copied ✓'}catch{$('#key-value').select();toast('Select and copy the access link.')}});
$('#add-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.target.querySelector('[type=submit]');button.disabled=true;busy=true;try{const name=new FormData(e.target).get('name');const result=await api('/api/users',{method:'POST',body:JSON.stringify({name})});$('#add-dialog').close();showKey(result.name,result.key,result.id);toast('Access created')}catch(error){$('#add-dialog .dialog-error').textContent=error.message}finally{button.disabled=false;busy=false;await refresh()}});
$('#remove-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.target.querySelector('[type=submit]');button.disabled=true;busy=true;try{await api(`/api/users/${encodeURIComponent(removing.id)}`,{method:'DELETE'});$('#remove-dialog').close();toast('Access revoked')}catch(error){$('#remove-dialog .dialog-error').textContent=error.message}finally{button.disabled=false;busy=false;await refresh()}});
async function init(){try{const state=await api('/api/session');csrf=state.csrf;$('#domain').textContent=state.domain;if(state.authenticated){$('#dashboard').hidden=false;await refresh()}else showLogin()}catch(e){showLogin();$('#login-error').textContent=e.message}}
$('#refresh-now').addEventListener('click',refresh);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
window.addEventListener('online',refresh);
init();setInterval(refresh,2000);

$('#copy-setup').addEventListener('click',async()=>{try{const message=OutlineShare.buildShareMessage(sharingName,$('#key-value').value);await navigator.clipboard.writeText(message.body);toast('Setup message copied')}catch(e){$('#share-status').textContent='Unable to copy automatically. Use Copy access code instead.'}});
$('#email-form').addEventListener('submit',async e=>{
  e.preventDefault();const id=sharingId,requestId=sendRequestId;
  if(!id||!requestId||$('#send-email').disabled)return;
  $('#send-email').disabled=true;$('#share-email').disabled=true;
  $('#send-email').textContent='Sending…';$('#share-status').textContent='Sending the access code and profile attachment…';
  try{
    const result=await api(`/api/users/${encodeURIComponent(id)}/email`,{method:'POST',body:JSON.stringify({email:$('#share-email').value.trim(),request_id:requestId})});
    if(sharingId===id&&sendRequestId===requestId){$('#send-email').textContent='Email accepted ✓';$('#share-status').textContent=result.message}
    toast('Email accepted by the mail provider');
  }catch(error){
    if(sharingId===id&&sendRequestId===requestId){$('#send-email').textContent='Send not confirmed';$('#share-status').textContent=(error.name==='TimeoutError'?'The request timed out. Delivery may have completed; check the recipient inbox.':error.message)+' Close and reopen Share before making a new send attempt.'}
  }
});
