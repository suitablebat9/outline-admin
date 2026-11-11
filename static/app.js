'use strict';
const $ = selector => document.querySelector(selector);
let csrf = $('meta[name="csrf-token"]').content;
let latest, currentDevice, loading = false, signature = '', byUser = false;
const bytes = number => {
  if (!number) return '0 B';
  const units = ['B','KiB','MiB','GiB','TiB','PiB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(number) / Math.log(1024)));
  return (number / 1024 ** index).toFixed(index ? 1 : 0) + ' ' + units[index];
};
function element(tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}
function signedIn(value) {
  $('#login').hidden = value;
  $('#dashboard').hidden = $('#logout').hidden = !value;
  if (!value) document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
}
async function api(url, method='GET', body) {
  const response = await fetch(url, {method, headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},
    body:body ? JSON.stringify(body) : undefined, signal:AbortSignal.timeout(55000)});
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) signedIn(false);
    throw Error(result.error || 'Request failed.');
  }
  return result;
}
function openProfile(name) {
  currentDevice = name;
  $('#owner-form').elements.owner.value = latest?.rows?.find(d=>d.name===name)?.owner || name;
  const url = '/api/wireguard/' + encodeURIComponent(name);
  $('#profile-title').textContent = name;
  $('#conf').href = url + '/conf'; $('#json').href = url + '/json';
  $('#qr-status').textContent = 'Loading QR code…'; $('#qr').hidden = true;
  $('#qr').src = url + '/sing-box-qr'; $('#profile').showModal();
}
function render() {
  if (!latest) return;
  const now = Date.now()/1000;
  const live = latest.sampled && now-latest.sampled < 8;
  $('#status').classList.toggle('live', Boolean(live));
  $('#status').textContent = live ? 'Gateway online · updates every 2 seconds' : 'Live stats unavailable · showing recorded totals';
  $('#name-column').textContent = byUser ? 'User' : 'Device';
  $('#down').textContent = bytes(latest.down); $('#up').textContent = bytes(latest.up);
  let entries = latest.rows || [];
  if (byUser) {
    const people = new Map();
    for (const device of entries) {
      const id = device.owner.toLowerCase();
      const person = people.get(id) || {name:device.owner, up:0, down:0, today:0, seen:0, devices:[]};
      for (const field of ['up','down','today']) person[field] += device[field];
      person.seen = Math.max(person.seen, device.seen || 0);
      person.devices.push(device.name);
      people.set(id,person);
    }
    entries = [...people.values()].sort((a,b)=>a.name.localeCompare(b.name));
  }
  const term = $('#search').value.trim().toLowerCase();
  const rows = entries.filter(d => [d.name,d.owner,...(d.devices||[])].some(v=>v?.toLowerCase().includes(term)));
  const view = rows.map(d => ({...d, recent:live && d.seen && now-d.seen<30}));
  const next = JSON.stringify([byUser,view,live,latest.days,Math.floor(now/86400)]);
  if (next === signature) return;
  signature = next;
  $('#rows').replaceChildren(...view.map(d => {
    const row=document.createElement('tr'), person=element('td','');
    const last = d.seen ? 'Last traffic ' + new Date(d.seen*1000).toLocaleString() : 'No traffic recorded';
    const activity=element('small', d.recent ? 'Active recently' : last);
    activity.className='activity' + (d.recent ? ' active' : '');
    person.append(element('strong',d.name),activity);
    if (!byUser && d.owner!==d.name) person.append(element('small', d.owner));

    const action=element('td',''), button=element('button','Profile');
    button.setAttribute('aria-label','Profile for ' + d.name); button.onclick=()=>openProfile(d.name);
    if (byUser) action.textContent = d.devices.join(', ');
    else action.append(button);
    row.append(person,element('td',bytes(d.down)),element('td',bytes(d.up)),element('td',bytes(d.today)),action);
    return row;
  }));
  $('#empty').hidden = rows.length > 0;
  $('#empty').textContent = latest.devices.length ? 'No devices match your search.' : 'Add a device to create its first profile.';
  const days = new Map((latest.days||[]).map(d=>[d.day,d]));
  const peak = Math.max(1,...Array.from(days.values(),d=>d.up+d.down));
  const ns='http://www.w3.org/2000/svg';
  $('#chart').replaceChildren(...Array.from({length:7},(_,i)=>{
    const date=new Date((Math.floor(now/86400)-6+i)*86400000);
    const key=date.toISOString().slice(0,10), daily=days.get(key)||{up:0,down:0};
    const day=element('div','');day.className='day';day.setAttribute('role','listitem');
    day.title=key+' · Download '+bytes(daily.down)+' · Upload '+bytes(daily.up);
    day.setAttribute('aria-label',day.title);
    const svg=document.createElementNS(ns,'svg'); svg.setAttribute('viewBox','0 0 40 80');
    let y=80;
    for(const [value,color] of [[daily.down,'#82e6c3'],[daily.up,'#799eed']]){
      const height=value/peak*78; y-=height;
      const rect=document.createElementNS(ns,'rect');
      for(const [attr,v] of Object.entries({x:7,y,width:26,height,fill:color})) rect.setAttribute(attr,v);
      svg.append(rect);
    }
    day.append(svg,document.createTextNode(date.toLocaleDateString(undefined,{weekday:'short',timeZone:'UTC'})));return day;
  }));
}
async function refresh() {
  if ($('#dashboard').hidden || document.hidden || loading) return;
  loading=true;
  try {latest=await api('/api/wireguard'); render(); $('#notice').textContent='';}
  catch(e){ $('#status').classList.remove('live'); $('#status').textContent='Dashboard unavailable'; $('#notice').textContent=e.message; }
  finally {loading=false;}
}
$('#search').oninput=render;
for (const [id, grouped] of [['#by-device',false],['#by-user',true]]) {
  $(id).onclick=()=>{byUser=grouped;$('#by-user').setAttribute('aria-pressed',String(grouped));
    $('#by-device').setAttribute('aria-pressed',String(!grouped));render();};
}
$('#owner-form').onsubmit=async event=>{
  event.preventDefault();
  try {await api('/api/wireguard/'+encodeURIComponent(currentDevice),'PATCH',{owner:event.currentTarget.elements.owner.value});
    await refresh(); $('#qr-status').textContent='User saved.';}
  catch(error){$('#qr-status').textContent=error.message;}
};
$('#new').onclick=()=>{ $('#add-form').reset(); $('.err').textContent=''; $('#add').showModal(); };
document.querySelectorAll('.close').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('#qr').onload=()=>{$('#qr').hidden=false;$('#qr-status').textContent='';};
$('#qr').onerror=()=>{$('#qr-status').textContent='QR unavailable. Download the sing-box profile below.';};
$('#profile').onclose=()=>{$('#qr').removeAttribute('src');currentDevice=null;};
$('#add-form').onsubmit=async e=>{
  e.preventDefault();const form=e.currentTarget,button=form.querySelector('.primary');button.disabled=true;
  try {const name=form.elements.name.value.trim();await api('/api/wireguard','POST',{name, owner:form.elements.owner.value});$('#add').close();await refresh();openProfile(name);}
  catch(error){$('.err').textContent=error.message;}finally{button.disabled=false;}
};
$('#remove').onclick=async()=>{
  if (!currentDevice || !confirm('Revoke both profiles for '+currentDevice+'? Other devices will briefly reconnect.')) return;
  $('#remove').disabled=true;
  try{await api('/api/wireguard/'+encodeURIComponent(currentDevice),'DELETE');$('#profile').close();await refresh();}
  catch(error){$('#qr-status').textContent=error.message;}finally{$('#remove').disabled=false;}
};
$('#login-form').onsubmit=async e=>{
  e.preventDefault();const form=e.currentTarget;
  try {const data=await api('/api/login','POST',Object.fromEntries(new FormData(form)));csrf=data.csrf;form.password.value='';$('#login-error').textContent='';signedIn(true);await refresh();}
  catch(error){$('#login-error').textContent=error.message;}
};
$('#logout').onclick=async()=>{try{await api('/api/logout','POST');location.reload();}catch(error){$('#notice').textContent=error.message;}};
api('/api/session').then(s=>{csrf=s.csrf;signedIn(s.authenticated);refresh();}).catch(e=>{signedIn(false);$('#login-error').textContent=e.message;});
setInterval(refresh,2000);
document.addEventListener('visibilitychange',refresh);
