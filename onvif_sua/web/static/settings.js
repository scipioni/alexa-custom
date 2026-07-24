
// Passwords (camera / scan / GUI login) are env-sourced (.env) — no in-GUI editing.

function updateSubnetPreview(){
  const val = document.getElementById('scan_subnet').value.trim();
  const el  = document.getElementById('subnet-preview');
  if(!val){ el.textContent=''; return; }
  // Stima host count da CIDR
  const m = val.match(/\/(\d+)$/);
  if(m){
    const bits = parseInt(m[1]);
    if(bits>=0 && bits<=32){
      const hosts = bits>=31 ? Math.pow(2,32-bits) : Math.pow(2,32-bits)-2;
      el.textContent = `→ ${hosts.toLocaleString()} host da scansionare`;
      el.style.color = hosts>10000?'#e3b341':'#8b949e';
      return;
    }
  }
  el.textContent='';
}

async function saveScan(){
  const subnet   = document.getElementById('scan_subnet').value.trim();
  if(!subnet){ showMsg2('Inserisci una subnet','danger'); return; }
  try{
    const r = await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({scan_subnet:subnet})}).then(x=>x.json());
    if(r.status==='error'){ showMsg2('❌ '+r.detail,'danger'); return; }
    showMsg2(`✅ Subnet <strong>${r.scan_subnet}</strong> impostata (per scan manuale)`,'success');
  }catch(e){ showMsg2('Errore: '+e,'danger'); }
}

function showMsg2(html,type){
  const el=document.getElementById('scan-msg');
  el.innerHTML=`<div class="alert alert-${type} py-2">${html}</div>`;
  setTimeout(()=>el.innerHTML='',5000);
}

async function loadConfig(){
  try{
    const r = await fetch('/api/config').then(x=>x.json());
    document.getElementById('scan_subnet').value   = r.scan_subnet   || '';
    document.getElementById('mqtt_host').value   = r.mqtt_host   || '';
    document.getElementById('mqtt_port').value   = r.mqtt_port   || 1883;
    document.getElementById('mqtt_user').value   = r.mqtt_user   || '';
    document.getElementById('mqtt_pass').value   = '';
    document.getElementById('mqtt_prefix').value = r.mqtt_prefix || 'onvif';
    updateSubnetPreview();
    const connected = r.mqtt_connected;
    const host      = r.mqtt_host;
    document.getElementById('status-bar').innerHTML = host
      ? `<span class="status-dot ${connected?'dot-on':'dot-off'}"></span>
         ${connected ? 'Connesso a <strong>'+host+'</strong>' : 'Non connesso ('+host+')'}`
      : '<span class="status-dot dot-off"></span>MQTT disabilitato';
    document.getElementById('preview-topic').textContent =
      (r.mqtt_prefix||'onvif') + '/NOME_CAM/alarms/fall';
  }catch(e){ showMsg('Errore caricamento: '+e,'danger'); }
}

async function saveConfig(){
  const body = {
    mqtt_host:   document.getElementById('mqtt_host').value.trim(),
    mqtt_port:   parseInt(document.getElementById('mqtt_port').value)||1883,
    mqtt_user:   document.getElementById('mqtt_user').value.trim(),
    mqtt_prefix: document.getElementById('mqtt_prefix').value.trim()||'onvif',
  };
  const pass = document.getElementById('mqtt_pass').value;
  if(pass) body.mqtt_pass = pass;  // invia solo se compilata
  try{
    const r = await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(x=>x.json());
    showMsg(body.mqtt_host ? '✅ Salvato — connessione a <strong>'+body.mqtt_host+'</strong> avviata' : '✅ Salvato — MQTT disabilitato','success');
    setTimeout(loadConfig, 2000);
  }catch(e){ showMsg('Errore: '+e,'danger'); }
}

function showMsg(html, type){
  const el = document.getElementById('msg');
  el.innerHTML = `<div class="alert alert-${type} py-2">${html}</div>`;
  setTimeout(()=>el.innerHTML='', 5000);
}

document.getElementById('scan_subnet').addEventListener('input', updateSubnetPreview);
document.getElementById('mqtt_prefix').addEventListener('input', e=>{
  document.getElementById('preview-topic').textContent = (e.target.value||'onvif')+'/NOME_CAM/alarms/fall';
});

loadConfig();
