const $=id=>document.getElementById(id); const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function get(u,o){const r=await fetch(u,o);if(!r.ok)throw new Error(await r.text());return r.json()}
async function init(){const d=await get('/v82/lookup-types');$('kind').innerHTML=d.items.map(x=>`<option>${x}</option>`).join('')}
async function load(){if(!$('org').value)return alert('Enter organization UUID');const u=`/v82/lookups/${$('kind').value}?organization_id=${encodeURIComponent($('org').value)}&q=${encodeURIComponent($('q').value)}${$('parent').value?`&parent_id=${encodeURIComponent($('parent').value)}`:''}`;try{const d=await get(u);$('rows').innerHTML=d.items.map(x=>`<tr><td><code>${esc(x.id)}</code></td><td>${esc(x.key)}</td><td>${esc(x.label)}</td><td>${esc(x.master_type)}</td></tr>`).join('')}catch(e){alert(e.message)}}
$('load').onclick=load; init();
