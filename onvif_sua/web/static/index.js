
async function apiFetch(url, opts){
  const r = await fetch(url, opts);
  if(r.status===401){ window.location='/login'; return null; }
  return r;
}

const TOPIC_MAP = [
  { k:'CellMotionDetector/Motion',   label:'Motion',       bg:'#1f4488', fg:'#79c0ff' },
  { k:'VideoSource/MotionAlarm',     label:'VideoAlarm',   bg:'#1a3a6e', fg:'#58a6ff' },
  { k:'MotionAlarm',                 label:'VideoAlarm',   bg:'#1a3a6e', fg:'#58a6ff' },
  { k:'TamperDetector/Tamper',       label:'Tamper',       bg:'#5a1e1e', fg:'#ff7b72' },
  { k:'Tamper',                      label:'Tamper',       bg:'#5a1e1e', fg:'#ff7b72' },
  { k:'LineDetector/CrossLine',      label:'Linea',        bg:'#3b1f6e', fg:'#d2a8ff' },
  { k:'LineDetector/Crossed',        label:'Linea',        bg:'#3b1f6e', fg:'#d2a8ff' },
  { k:'CrossLine',                   label:'Linea',        bg:'#3b1f6e', fg:'#d2a8ff' },
  { k:'FieldDetector/ObjectsInside', label:'Area',         bg:'#4a1f6e', fg:'#d2a8ff' },
  { k:'FieldDetector/ObjectInside',  label:'Area',         bg:'#4a1f6e', fg:'#d2a8ff' },
  { k:'CrossRegion',                 label:'Area',         bg:'#4a1f6e', fg:'#d2a8ff' },
  { k:'Intrusion',                   label:'Intrusione',   bg:'#6e1f1f', fg:'#ffa657' },
  { k:'PersonDetector',              label:'Persona',      bg:'#1a4d2e', fg:'#56d364' },
  { k:'HumanDetection',              label:'Persona',      bg:'#1a4d2e', fg:'#56d364' },
  { k:'PedestrianDetection',         label:'Persona',      bg:'#1a4d2e', fg:'#56d364' },
  { k:'VehicleDetector',             label:'Veicolo',      bg:'#4d3900', fg:'#e3b341' },
  { k:'VehicleDetection',            label:'Veicolo',      bg:'#4d3900', fg:'#e3b341' },
  { k:'FaceDetector',                label:'Viso',         bg:'#4d2900', fg:'#ffa657' },
  { k:'FaceDetection',               label:'Viso',         bg:'#4d2900', fg:'#ffa657' },
  { k:'FaceRecognition',             label:'Riconos.',     bg:'#6b3600', fg:'#ffa657' },
  { k:'ObjectDetector',              label:'Oggetto',      bg:'#1a3a4d', fg:'#79c0ff' },
  { k:'ObjectDetection',             label:'Oggetto',      bg:'#1a3a4d', fg:'#79c0ff' },
  { k:'TumbleDetection',              label:'🚨 Caduta',     bg:'#6e0000', fg:'#ff4444' },
  { k:'FallDetect',                   label:'🚨 Caduta',     bg:'#6e0000', fg:'#ff4444' },
  { k:'FallDown',                     label:'🚨 Caduta',     bg:'#6e0000', fg:'#ff4444' },
  { k:'PersonFall',                   label:'🚨 Caduta',     bg:'#6e0000', fg:'#ff4444' },
  { k:'LoiteringDetector',           label:'Attesa',       bg:'#4d2900', fg:'#f0883e' },
  { k:'RecordingConfig/JobState',    label:'Registraz.',   bg:'#21262d', fg:'#8b949e' },
  { k:'JobState',                    label:'Registraz.',   bg:'#21262d', fg:'#8b949e' },
  { k:'AudioAnalytics/Audio',        label:'Audio',        bg:'#1f4d3a', fg:'#56d364' },
  { k:'AudioDetector',               label:'Audio',        bg:'#1f4d3a', fg:'#56d364' },
  { k:'Device/Trigger/DigitalInput', label:'Ingresso I/O', bg:'#2d2d00', fg:'#e3b341' },
  { k:'Device/Trigger/Relay',        label:'Relè',         bg:'#2d1a00', fg:'#ffa657' },
  { k:'Monitoring/ProcessorUsage',   label:'CPU cam',      bg:'#1a1a2d', fg:'#8b949e' },
  { k:'Monitoring/OperatingTime',    label:'Uptime',       bg:'#1a1a2d', fg:'#8b949e' },
  { k:'Device/HardwareFailure',      label:'HW Failure',   bg:'#3d0000', fg:'#ff7b72' },
  { k:'GlobalSceneChange',           label:'ScenaChg',     bg:'#21262d', fg:'#8b949e' },
  { k:'Media/ConfigurationChanged',  label:'Cfg cambio',   bg:'#21262d', fg:'#8b949e' },
  { k:'Media/ProfileChanged',        label:'Profilo chg',  bg:'#21262d', fg:'#8b949e' },
  { k:'ImageTooBlurry',              label:'Sfocatura',    bg:'#21262d', fg:'#8b949e' },
  { k:'ImageTooDark',                label:'Buio',         bg:'#21262d', fg:'#8b949e' },
];

const SVC_HIGHLIGHT = {
  Analytics: {fg:'#56d364', title:'Supporta Analytics (AI events)'},
  Media2:    {fg:'#79c0ff', title:'Media2 — Profile T streaming'},
  DeviceIO:  {fg:'#e3b341', title:'I/O digitale e relè'},
  PTZ:       {fg:'#ffa657', title:'Pan/Tilt/Zoom'},
  Recording: {fg:'#d2a8ff', title:'Registrazione on-board'},
};

function topicInfo(fullTopic){
  const lc = fullTopic.toLowerCase();
  for(const t of TOPIC_MAP){
    if(lc.includes(t.k.toLowerCase())) return t;
  }
  const parts = fullTopic.split('/');
  return { label: parts.slice(-2).join('/'), bg:'#21262d', fg:'#8b949e' };
}

function topicPill(fullTopic, count){
  const info = topicInfo(fullTopic);
  return `<span class="ev-pill" title="${fullTopic}"
    style="background:${info.bg};color:${info.fg};border-color:${info.fg}44">
    ${info.label} <span class="cnt">${count}</span></span>`;
}

function renderServices(services){
  return (services||[]).map(s => {
    const hi = SVC_HIGHLIGHT[s];
    if(hi) return `<span class="ev-pill" title="${hi.title}"
      style="background:#161b22;color:${hi.fg};border-color:${hi.fg}66">${s}</span>`;
    return `<span style="font-size:.65rem;color:#8b949e;margin:1px">${s}</span>`;
  }).join(' ');
}

// Categorie evento: id → {label, color, keywords, defaultOn}
const CATS = [
  { id:'caduta',   label:'🚨 Caduta',   fg:'#ff4444', keys:['tumbledetection','falldetect','falldown','personfall','fall_detect'],        on:true  },
  { id:'motion',   label:'Motion',      fg:'#79c0ff', keys:['cellmotion','motionalarm','videodetect','globalscenechange'],                on:true  },
  { id:'ai',       label:'AI/Smart',    fg:'#56d364', keys:['persondetect','humandetect','pedestrian','vehicledetect','facedetect','facerecog','intrusion','loiter','linedete','fielddete','crossline','crossregion','objectdetect'], on:true  },
  { id:'io',       label:'I/O',         fg:'#e3b341', keys:['digitalinput','relay','trigger'],                                           on:true  },
  { id:'audio',    label:'Audio',       fg:'#56d364', keys:['audio'],                                                                    on:true  },
  { id:'sistema',  label:'Sistema',     fg:'#8b949e', keys:['monitoring','operatingtime','processorusage','jobstate','profilechanged','configurationchanged','imagetoo','tamper','scenechange','hardwarefailure'], on:false },
  { id:'altro',    label:'Altro',       fg:'#8b949e', keys:[],                                                                           on:true  },
];
let catState = Object.fromEntries(CATS.map(c=>[c.id, c.on]));

function catOf(topic){
  const lc = topic.toLowerCase();
  for(const c of CATS){
    if(c.keys.length && c.keys.some(k=>lc.includes(k))) return c.id;
  }
  return 'altro';
}

function initCatToggles(){
  const el = document.getElementById('cat-toggles');
  el.innerHTML = CATS.map(c=>`
    <button id="cat-${c.id}" onclick="toggleCat('${c.id}')"
      class="btn btn-sm" style="font-size:.72rem;padding:2px 8px;
        border:1px solid ${c.fg}66;
        background:${catState[c.id]?c.fg+'22':'transparent'};
        color:${catState[c.id]?c.fg:'#8b949e'};
        transition:all .15s">
      ${c.label}
    </button>`).join('');
}

function toggleCat(id){
  catState[id] = !catState[id];
  const c = CATS.find(x=>x.id===id);
  const btn = document.getElementById('cat-'+id);
  btn.style.background = catState[id] ? c.fg+'22' : 'transparent';
  btn.style.color      = catState[id] ? c.fg      : '#8b949e';
  renderLog();
}

let autoPaused=false, logLines=[], camFilter='', logIpFilter='', logTopicFilter='';

async function triggerRescan(){
  const btn=document.getElementById('btn-rescan');
  btn.disabled=true; btn.textContent='🔍 Scan in corso…';
  // Optimistically enable the stop button the instant the rescan fires — the 15s
  // status poll would otherwise lag the enable by up to a full interval; the next
  // poll reconciles the true scan_active state.
  const stopBtn=document.getElementById('btn-stop-scan');
  if(stopBtn) stopBtn.disabled=false;
  try {
    await apiFetch('/api/rescan', {method:'POST'});
    btn.textContent='🔍 Scan avviato';
  } catch(e){ btn.textContent='🔍 errore'; }
  setTimeout(()=>{ btn.disabled=false; btn.textContent='🔍 Rescan subnet'; }, 5000);
}

async function stopScan(){
  try {
    await apiFetch('/api/scan/stop', {method:'POST'});
  } catch(e){}
}
async function clearLog(){
  logLines=[];
  renderLog();
  await apiFetch('/api/events/clear', {method:'POST'});
}
function filterCams(v){ camFilter=v.toLowerCase(); renderCams(window._lastCams||[]); }
function filterLog(){
  logIpFilter    = document.getElementById('log-filter').value.toLowerCase();
  logTopicFilter = document.getElementById('log-topic-filter').value.toLowerCase();
  renderLog();
}

async function refreshAlarms(){
  if(autoPaused) return;
  try{
    const data = await fetch('/api/alarms').then(r=>r.json());
    const alarms = data.alarms || {};
    const camsOn = data.cameras_on || [];
    const entries = Object.entries(alarms);
    const card = document.getElementById('alarms-card');
    const body = document.getElementById('alarms-body');
    if(entries.length===0){ card.style.display='none'; return; }
    card.style.removeProperty('display');
    body.innerHTML = entries.map(([k,v])=>{
      const on = v==='on';
      let html = `<div class="d-flex align-items-center gap-3 py-1">
        <span style="font-size:1.1rem;font-weight:700;color:${on?'#ff4444':'#56d364'}">${k} = ${v.toUpperCase()}</span>
        <span class="badge" style="background:${on?'#6e0000':'#1a4d2e'};font-size:.9rem">${on?'🔴 ALLARME':'🟢 OK'}</span>
      </div>`;
      if(on){
        html += camsOn.length
          ? `<div class="d-flex flex-wrap align-items-center gap-1 pb-2 ps-1">
               <span class="small me-1" style="color:#ff4444">Telecamere in allarme:</span>
               ${camsOn.map(n=>`<span class="badge bg-danger">${n}</span>`).join('')}
             </div>`
          : `<div class="small text-muted pb-2 ps-1">Nessuna telecamera specifica in allarme</div>`;
      }
      return html;
    }).join('');
  }catch(e){}
}

async function refresh(force){
  // force=true bypasses the visibility auto-pause guard so an explicit user
  // action (rename/save/remove/simulate) updates the table immediately.
  if(!force && autoPaused) return;
  try{
    const [status, evts] = await Promise.all([
      apiFetch('/api/status').then(r=>r?r.json():null),
      apiFetch('/api/events?limit=500').then(r=>r?r.json():null)
    ]);
    if(!status || !evts) return;
    const cams = Object.values(status.cameras||{});
    document.getElementById('subnet-badge').textContent = status.scan_subnet||'';
    const stopBtn=document.getElementById('btn-stop-scan');
    if(stopBtn) stopBtn.disabled=!status.scan_active;
    renderConfigWarning(status.password_warning||{});
    renderAuthWarnings(status.auth_failures||[]);
    window._lastCams = cams;
    renderCams(cams);
    updateSummary(cams, evts);
    if(evts.length>0){
      const last=logLines.length>0?logLines[logLines.length-1].ts:'';
      const newEvts=evts.filter(e=>e.ts>last);
      logLines.push(...newEvts);
      if(logLines.length>1000) logLines=logLines.slice(-1000);
      renderLog();
    }
    document.getElementById('last-update').textContent='Aggiornato: '+new Date().toLocaleTimeString();
  }catch(e){}
}

function renderConfigWarning(pw){
  window._pwWarn = pw;
  const card=document.getElementById('config-warning-card');
  const body=document.getElementById('config-warning-body');
  const msgs=[];
  if(pw.cameras){
    msgs.push('La <b>password comune telecamere</b> è ancora <code>default_to_change</code>: '
      +'le telecamere <b>non vengono connesse</b> (per evitare il blocco anti-intrusione Dahua). '
      +'Modifica <code>CAMERA_PASSWORD</code> in <code>.env</code> e riavvia.');
  }
  if(pw.scan){
    msgs.push('La <b>password di scansione</b> è ancora <code>default_to_change</code>: '
      +'lo scan manuale della subnet è disabilitato finché non la cambi.');
  }
  if(msgs.length===0){ card.style.display='none'; return; }
  card.style.removeProperty('display');
  body.innerHTML=msgs.map(m=>`<div class="small mb-1" style="color:#e3b341">${m}</div>`).join('');
}

function renderAuthWarnings(fails){
  window._authFails = fails;
  const card=document.getElementById('auth-warning-card');
  const body=document.getElementById('auth-warning-body');
  if(!fails || fails.length===0){ card.style.display='none'; return; }
  card.style.removeProperty('display');
  const intro=`<div class="small mb-2" style="color:#ff7b72">`
    +`Il login è fallito su ${fails.length} telecamera${fails.length>1?'':''}. `
    +`I tentativi sono stati <b>SOSPESI</b> per non far scattare il blocco anti-intrusione `
    +`della telecamera (che la renderebbe irraggiungibile). Correggi la password in `
    +`<code>.env</code> (<code>CAMERA_PASSWORD</code> / <code>SCAN_PASSWORD</code>) e `
    +`<b>riavvia il servizio</b>.</div>`;
  const rows=fails.map(f=>{
    const nm=(f.name && f.name!==f.ip)?`${f.name} (${f.ip})`:f.ip;
    return `<div class="small mb-1" style="color:#ff4444">`
      +`⛔ <b>${nm}</b> — ${f.detail||'login fallito'} `
      +`<span class="badge bg-secondary" style="font-size:.65rem">${f.source||''}</span></div>`;
  }).join('');
  body.innerHTML=intro+rows;
}

function renderCams(cams){
  const rows=cams
    .filter(c=>!camFilter||c.ip.includes(camFilter)||(c.name||'').toLowerCase().includes(camFilter))
    .sort((a,b)=>{
      const na=a.name||'', nb=b.name||'';
      if(!na&&!nb) return a.ip.localeCompare(b.ip);
      if(!na) return 1; if(!nb) return -1;
      const ma=na.match(/^(\d+)/), mb=nb.match(/^(\d+)/);
      if(ma&&mb) return parseInt(ma[1])-parseInt(mb[1]);
      return na.localeCompare(nb,'it');
    })
    .map(c=>{
      const simOn=c.simulated===true;
      const statusLabel={connected:'connessa',connecting:'connessione…',
        error:'errore',no_onvif:'no ONVIF',sub_limit:'sub. occupata',
        auth_failed:'⛔ login fallito'}[c.status]||c.status;
      const simBadge=simOn?` <span class="badge bg-warning text-dark" title="Stato simulato — nessuna telecamera reale">SIMULATA</span>`:'';
      const statusBadge=`<span class="badge badge-${c.status}" title="${c.error||''}">${statusLabel}</span>${simBadge}`;
      const pills=Object.entries(c.topics||{}).sort((a,b)=>b[1].count-a[1].count)
        .map(([t,td])=>topicPill(t,td.count)).join('');
      const total=c.event_count||0;
      const breakdown=pills
        ?`<div class="d-flex flex-wrap">${pills}<span class="total-evt ms-1">= ${total}</span></div>`
        :`<span class="text-muted">-</span>`;
      const errHtml=c.error?`<br><small class="text-danger" style="font-size:.65rem">${c.error}</small>`:'';
      const portBadge=`<small style="color:#8b949e">${c.port||80}</small>`;
      const nameOk=c.name_verified!==false;
      const nameStyle=nameOk?'':'color:#ff4444';
      const nameTitle=nameOk?'Rinomina telecamera':'⚠️ Nome non confermato dalla cam — potrebbe richiedere riavvio';
      const nameHtml=c.name&&c.name!==c.ip
        ?`<span style="${nameStyle}">${c.name}</span> <button class="btn btn-sm p-0 ms-1" style="line-height:1;color:#adbac7" title="${nameTitle}" onclick="renameCamera('${c.ip}','${(c.name||'').replace(/'/g,"\\'")}')">✏️</button>`
        :`<span class="text-muted">-</span>`;
      const isStatic=c._static===true;
      const cfgBadge=isStatic
        ?`<span class="badge bg-success" title="Salvata in settings.yaml">in config</span>`
        :`<span class="badge bg-secondary" title="Scoperta con lo scan, non salvata">scoperta</span>`;
      const nm=(c.name||'').replace(/'/g,"\\'");
      const saveBtn=`<button class="btn btn-sm btn-outline-success py-0 px-1" title="Salva in settings.yaml" onclick="saveCamera('${c.ip}','${nm}')">💾</button>`;
      const remBtn=`<button class="btn btn-sm btn-outline-danger py-0 px-1 ms-1" title="Rimuovi da lista e config" onclick="removeCamera('${c.ip}','${nm}')">🗑</button>`;
      const simToggle=`<div class="form-check form-switch d-inline-block m-0" title="Simula presenza + caduta (test HA senza telecamera reale)">`
        +`<input class="form-check-input" type="checkbox" role="switch" style="cursor:pointer" ${simOn?'checked':''} onchange="toggleSimulate('${c.ip}','${nm}',this.checked)"></div>`;
      return `<tr class="evt-row">
        <td><code>${c.ip}</code></td>
        <td>${portBadge}</td>
        <td>${nameHtml}</td>
        <td>${statusBadge}${errHtml}</td>
        <td>${cfgBadge}</td>
        <td style="font-size:.7rem">${renderServices(c.services)}</td>
        <td class="topics-cell">${breakdown}</td>
        <td class="text-nowrap">${saveBtn}${remBtn}</td>
        <td class="text-center">${simToggle}</td>
      </tr>`;
    }).join('');
  const emptyMsg=(window._pwWarn && window._pwWarn.cameras)
    ? 'Nessuna telecamera connessa — imposta la password in <code>settings.yaml</code> (vedi avviso sopra)'
    : 'Nessuna telecamera configurata — aggiungile nel blocco <code>cameras</code> di <code>settings.yaml</code>, oppure usa 🔍 Rescan subnet';
  document.getElementById('cam-body').innerHTML=rows
    ||`<tr><td colspan="9" class="text-center text-muted py-3">${emptyMsg}</td></tr>`;
}

async function renameCamera(ip, currentName){
  const raw=prompt(`Nuovo nome per ${ip}\\n(trattini OK, underscore → trattino automatico)`, currentName||'');
  if(raw===null||raw.trim()==='') return;
  try{
    const r=await apiFetch(`/api/cameras/${encodeURIComponent(ip)}/rename`,{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:raw.trim()})
    });
    const j=await r.json();
    if(j.status==='ok'){
      const sanitized=j.name!==raw.trim()?` (sanitizzato: ${j.name})`:'';
      if(j.verified===false){
        alert(`⚠️ Comando inviato ma la cam ha risposto con "${j.actual}" invece di "${j.name}".\nIl nome è mostrato in rosso. Potrebbe servire un riavvio della telecamera.${sanitized}`);
      } else if(j.verified===null){
        alert(`Rinominato → ${j.name}${sanitized}\n(verifica non disponibile)`);
      } else {
        alert(`✅ Rinominato → ${j.name}${sanitized}`);
      }
      refresh(true);   // show the new name immediately, don't wait for the poll
    } else {
      alert('Errore: '+(j.detail||'sconosciuto'));
    }
  }catch(e){ alert('Errore rete: '+e); }
}

async function saveCamera(ip, currentName){
  let name=currentName;
  if(!name || name===ip){
    name=prompt(`Nome per la telecamera ${ip} da salvare in config`, '');
    if(name===null||name.trim()==='') return;
    name=name.trim();
  }
  if(!confirm(`Salvare ${ip} come "${name}" in settings.yaml?`)) return;
  try{
    const r=await apiFetch(`/api/cameras/${encodeURIComponent(ip)}/save`,{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:name})
    });
    const j=await r.json();
    if(j.status==='ok'){ alert(`✅ Salvata in config: ${j.name} (${j.detail})`); refresh(true); }
    else { alert('Errore: '+(j.detail||'sconosciuto')); }
  }catch(e){ alert('Errore rete: '+e); }
}

async function removeCamera(ip, name){
  if(!confirm(`Rimuovere ${ip}${name?(' ('+name+')'):''} dalla lista e da settings.yaml?`)) return;
  try{
    const r=await apiFetch(`/api/cameras/${encodeURIComponent(ip)}/remove`,{method:'POST'});
    const j=await r.json();
    if(j.status==='ok'){
      alert(`✅ Rimossa (config: ${j.removed_config?'sì':'no'}, runtime: ${j.removed_runtime?'sì':'no'})`);
      refresh(true);   // drop the row immediately, don't wait for the poll
    } else { alert('Errore: '+(j.detail||'sconosciuto')); }
  }catch(e){ alert('Errore rete: '+e); }
}

async function toggleSimulate(ip, name, on){
  try{
    const r=await apiFetch(`/api/cameras/${encodeURIComponent(ip)}/simulate`,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:on})});
    const j=await r.json();
    if(j.status!=='ok'){ alert('Errore: '+(j.detail||'sconosciuto')); }
    refresh(true);
  }catch(e){ alert('Errore rete: '+e); refresh(true); }
}

function renderLog(){
  const lines=logLines
    .filter(e=>{
      if(logIpFilter && !e.ip.includes(logIpFilter) && !(e.name||'').toLowerCase().includes(logIpFilter)) return false;
      if(logTopicFilter && !e.topic.toLowerCase().includes(logTopicFilter)) return false;
      if(!catState[catOf(e.topic)]) return false;
      return true;
    })
    .slice(-300).reverse()
    .map(e=>{
      const info=topicInfo(e.topic);
      const dataStr=Object.entries(e.data||{})
        .map(([k,v])=>`<span style="color:#adbac7">${k}=</span><span style="color:#c9d1d9">${v}</span>`)
        .join(' ');
      return `<div class="evt-row px-1 py-0">
        <span class="ts">${e.ts.replace('T',' ').substring(0,23)}</span>
        <span class="cam-name">${e.name||e.ip}</span>
        <span style="color:#58a6ff"> [${e.ip}] </span>
        <span class="ev-pill" style="background:${info.bg};color:${info.fg};border-color:${info.fg}44">${info.label}</span>
        <span class="ms-1 small">${dataStr}</span>
      </div>`;
    }).join('');
  const el=document.getElementById('event-log');
  el.innerHTML=lines||'<div class="text-muted text-center py-3">In attesa di eventi...</div>';
}

function updateSummary(cams, evts){
  const topicSet=new Set();
  cams.forEach(c=>Object.keys(c.topics||{}).forEach(t=>topicSet.add(t)));
  document.getElementById('s-total').textContent=cams.length;
  document.getElementById('s-conn').textContent=cams.filter(c=>c.status==='connected').length;
  document.getElementById('s-noonvif').textContent=cams.filter(c=>c.status==='no_onvif').length;
  document.getElementById('s-err').textContent=cams.filter(c=>c.status==='error'||c.status==='auth_failed').length;
  document.getElementById('s-evts').textContent=cams.reduce((s,c)=>s+(c.event_count||0),0);
  document.getElementById('s-topics').textContent=topicSet.size;
}

initCatToggles();
refresh();
refreshAlarms();
// Two decoupled cadences:
//  * refresh() pulls the HEAVY payloads (full camera list + event log) — kept slow
//    (15s) because that's the real kiosk-load saver and it's just a monitoring view.
//  * refreshAlarms() hits the tiny /api/alarms endpoint (alarm state + names only) —
//    kept FAST (2s) so a fallen-person alarm shows on the dashboard almost immediately.
//    The server flips the alarm state the instant a TumbleDetection 'start' arrives,
//    so end-to-end GUI latency is ≤ this interval.
setInterval(refresh, 15000);
setInterval(refreshAlarms, 2000);
// Auto-pause ALL polling while the tab/panel is hidden (a backgrounded or
// screen-off kiosk does zero polling work), and do an immediate catch-up on
// becoming visible. Tracked by its own `autoPaused` flag; there is no manual
// display-freeze pause anymore (the button now stops a running scan).
document.addEventListener('visibilitychange', () => {
  autoPaused = document.hidden;
  if (!document.hidden) {
    refresh();
    refreshAlarms();
  }
});
