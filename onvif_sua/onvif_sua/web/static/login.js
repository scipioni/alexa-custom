
async function doLogin(){
  const pwd = document.getElementById('pwd').value;
  try{
    const r = await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password:pwd})});
    if(r.ok){ window.location='/'; return; }
    const j = await r.json();
    document.getElementById('msg').innerHTML='<span style="color:#f85149">'+( j.detail||'Errore')+'</span>';
    document.getElementById('pwd').value='';
    document.getElementById('pwd').focus();
  }catch(e){ document.getElementById('msg').textContent='Errore rete'; }
}
document.getElementById('pwd').addEventListener('keydown', e=>{ if(e.key==='Enter') doLogin(); });
