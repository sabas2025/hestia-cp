'use strict';
(() => {
  const q=id=>document.getElementById(id), root=q('editor');if(!root)return;
  let opened=null,busy=false,restoreId=null;
  const scope=()=>({owner:q('editor-owner').value.trim(),domain:q('editor-domain').value});
  async function api(op,request) {
    const body=new URLSearchParams({op,token:root.dataset.token,request:JSON.stringify(request)});
    const response=await fetch('/professional/editor.php',{method:'POST',body,credentials:'same-origin',redirect:'error',cache:'no-store'});
    const data=await response.json();if(!response.ok||data.error)throw new Error(data.error||'Operação recusada.');return data;
  }
  async function task(work){if(busy)return;busy=true;root.setAttribute('aria-busy','true');q('editor-status').textContent='Consultando…';try{await work();}catch(e){q('editor-status').textContent=e.message;}finally{busy=false;root.removeAttribute('aria-busy');}}
  function reset(){opened=null;restoreId=null;q('editor-content').value='';q('editor-content').disabled=true;}
  function button(text,click){const b=document.createElement('button');b.type='button';b.className='pro-button';b.textContent=text;b.addEventListener('click',click);return b;}
  q('editor-owner').addEventListener('change',()=>{reset();q('editor-domain').replaceChildren();q('editor-files').replaceChildren();});
  q('editor-domain').addEventListener('change',reset);
  q('editor-domains').addEventListener('click',()=>task(async()=>{reset();const data=await api('domains',scope());q('editor-domain').replaceChildren(...data.domains.map(name=>{const o=document.createElement('option');o.value=name;o.textContent=name;return o;}));q('editor-status').textContent=`${data.domains.length} domínios disponíveis.`;}));
  q('editor-browse').addEventListener('submit',e=>{e.preventDefault();task(async()=>{const data=await api('list',{...scope(),path:q('editor-folder').value});q('editor-files').replaceChildren(...data.entries.map(f=>button(`${f.type==='directory'?'Pasta':'Arquivo'} · ${f.name}`,()=>{if(f.type==='directory'){q('editor-folder').value=f.path;q('editor-browse').requestSubmit();}else{q('editor-path').value=f.path;q('editor-open').click();}})));q('editor-status').textContent=`${data.entries.length} itens; limite de ${data.limit} por pasta.`;});});
  q('editor-open').addEventListener('click',()=>task(async()=>{const data=await api('read',{...scope(),path:q('editor-path').value});opened={...scope(),path:data.path,sha256:data.sha256};restoreId=null;q('editor-content').disabled=false;q('editor-content').value=data.content;q('editor-meta').textContent=`${data.bytes} bytes · versão ${data.sha256.slice(0,12)}`;q('editor-status').textContent='Arquivo aberto. Alterações serão validadas antes de salvar.';}));
  q('editor-new').addEventListener('click',()=>{opened={...scope(),path:q('editor-path').value,sha256:'absent'};restoreId=null;q('editor-content').disabled=false;q('editor-content').value='';q('editor-meta').textContent='Novo arquivo. Se o caminho já existir, a criação será recusada.';});
  q('editor-save').addEventListener('submit',e=>{e.preventDefault();task(async()=>{try{if(!opened&&!restoreId)throw new Error('Abra um arquivo ou escolha uma versão.');const credentials={password:q('editor-password').value,code:q('editor-code').value};const data=await api(restoreId?'restore':'save',restoreId?{...scope(),revision:restoreId,...credentials}:{...opened,content:q('editor-content').value,...credentials});q('editor-status').textContent=`Arquivo salvo. Revisão ${data.revision}.`;if(opened)opened.sha256=data.sha256;restoreId=null;}finally{q('editor-password').value='';q('editor-code').value='';}});});
  q('editor-history').addEventListener('click',()=>task(async()=>{const data=await api('history',scope());q('editor-revisions').replaceChildren(...data.revisions.map(r=>button(`${r.domain}/${r.path} · restaurar ${r.id.slice(0,8)}`,()=>{if(r.domain!==q('editor-domain').value){q('editor-status').textContent='Selecione o domínio dessa versão.';return;}restoreId=r.id;q('editor-path').value=r.path;q('editor-meta').textContent='Restauração selecionada. Confirme sua senha e um novo A2F no formulário de salvar.';})));q('editor-status').textContent=`${data.revisions.length} revisões. A restauração exige que o arquivo atual ainda corresponda à versão salva.`;}));
})();
