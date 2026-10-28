'use strict';
(() => {
  const q=id=>document.getElementById(id),root=q('editor');if(!root)return;
  const MAX=64*1024*1024;
  let opened=null,busy=false,restoreId=null,listing=null,pending=null;
  const scope=()=>({owner:q('editor-owner').value.trim(),domain:q('editor-domain').value});
  const join=(folder,name)=>folder?`${folder}/${name}`:name;
  const size=n=>n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KiB`:`${(n/1048576).toFixed(1)} MiB`;
  async function api(op,request){
    const body=new URLSearchParams({op,token:root.dataset.token,request:JSON.stringify(request)});
    const response=await fetch('/professional/editor.php',{method:'POST',body,credentials:'same-origin',redirect:'error',cache:'no-store'});
    let data;try{data=await response.json();}catch(_){throw new Error('Resposta inválida. Confira a sessão e os limites do servidor.');}
    if(!response.ok||data.error)throw new Error(data.error||'Operação recusada.');return data;
  }
  async function task(work){
    if(busy)return;busy=true;root.setAttribute('aria-busy','true');q('editor-status').textContent='Processando…';
    const controls=[...root.querySelectorAll('button'),q('editor-owner'),q('editor-domain'),q('editor-folder'),q('editor-path')].map(el=>[el,el.disabled]);
    controls.forEach(([el])=>el.disabled=true);
    try{await work();}catch(e){q('editor-status').textContent=e.message;if(q('fm-dialog').open)q('fm-error').textContent=e.message;}
    finally{busy=false;root.removeAttribute('aria-busy');controls.forEach(([el,disabled])=>{if(el.isConnected)el.disabled=disabled;});if(listing){q('fm-previous').disabled=!listing.offset;q('fm-next').disabled=listing.next===null;}q('fm-progress').hidden=true;}
  }
  function reset(){opened=null;restoreId=null;q('editor-content').value='';q('editor-content').disabled=true;q('editor-meta').textContent='Selecione um arquivo de texto para editar.';}
  function button(text,action,cls=''){const b=document.createElement('button');b.type='button';b.className=cls;b.textContent=text;b.addEventListener('click',action);return b;}
  function empty(text){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.className='fm-empty';td.textContent=text;tr.append(td);return tr;}
  function breadcrumbs(folder){
    let current='';const nodes=[button('public_html',()=>task(()=>load('')))];
    for(const part of folder.split('/').filter(Boolean)){current=join(current,part);const target=current;nodes.push(document.createTextNode('/'),button(part,()=>task(()=>load(target))));}
    q('fm-breadcrumbs').replaceChildren(...nodes);
  }
  function render(){
    if(!listing)return;const filter=q('fm-search').value.toLocaleLowerCase();
    const rows=listing.entries.filter(f=>f.name.toLocaleLowerCase().includes(filter)).map(f=>{
      const tr=document.createElement('tr');const name=document.createElement('td'),bytes=document.createElement('td'),modified=document.createElement('td'),actions=document.createElement('td');
      name.append(button(`${f.type==='directory'?'📁':'▤'} ${f.name}`,()=>f.type==='directory'?task(()=>load(f.path)):f.editable?open(f.path):task(()=>download(f)),'fm-name'));
      bytes.textContent=f.type==='directory'?'—':size(f.bytes);modified.textContent=new Date(f.modified*1000).toLocaleDateString('pt-BR');
      const group=document.createElement('div');group.className='fm-actions';
      if(f.type==='directory')group.append(button('Abrir',()=>task(()=>load(f.path))));
      else{if(f.editable)group.append(button('Editar',()=>open(f.path)));if(f.downloadable)group.append(button('Baixar',()=>task(()=>download(f))));group.append(button('Renomear',()=>dialog('rename',f)));}
      actions.append(group);tr.append(name,bytes,modified,actions);return tr;
    });q('editor-files').replaceChildren(...(rows.length?rows:[empty('Nenhum item nesta página.')]));
  }
  async function load(folder='',offset=0){
    const data=await api('files',{...scope(),path:folder,offset});listing=data;q('editor-folder').value=data.path;q('fm-search').value='';breadcrumbs(data.path);render();
    q('fm-previous').disabled=!data.offset;q('fm-next').disabled=data.next===null;
    q('fm-count').textContent=`${data.total?data.offset+1:0}–${data.offset+data.entries.length} de ${data.total}`;
    q('editor-status').textContent=`${data.total} itens em ${data.path||'public_html'}.`;
  }
  function open(path){return task(async()=>{const data=await api('read',{...scope(),path});opened={...scope(),path:data.path,sha256:data.sha256};restoreId=null;q('editor-path').value=data.path;q('editor-content').disabled=false;q('editor-content').value=data.content;q('editor-meta').textContent=`${size(data.bytes)} · versão ${data.sha256.slice(0,12)}`;q('editor-status').textContent='Arquivo aberto. Alterações serão validadas antes de salvar.';});}
  function progress(value){q('fm-progress').hidden=false;q('fm-progress').value=value;}
  function encode(bytes){let text='';for(let offset=0;offset<bytes.length;offset+=8192)text+=String.fromCharCode(...bytes.subarray(offset,offset+8192));return btoa(text);}
  async function download(file){
    const fixed=scope(),chunks=[];let offset=0;
    do{const data=await api('download',{...fixed,path:file.path,etag:file.etag,offset});const raw=Uint8Array.from(atob(data.data),c=>c.charCodeAt(0));if(data.offset!==offset||data.total!==file.bytes||data.etag!==file.etag||(!raw.length&&!data.eof))throw new Error('Transferência inconsistente; recarregue a pasta.');chunks.push(raw);offset+=raw.length;progress(file.bytes?offset/file.bytes*100:100);if(data.eof)break;}while(offset<file.bytes);
    if(offset!==file.bytes)throw new Error('Download incompleto.');
    const url=URL.createObjectURL(new Blob(chunks,{type:'application/octet-stream'})),a=document.createElement('a');a.href=url;a.download=file.name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
    q('editor-status').textContent=`Download concluído: ${file.name} (${size(file.bytes)}).`;
  }
  function dialog(action,file=null){
    if(busy)return;if(!scope().domain){q('editor-status').textContent='Selecione um domínio primeiro.';return;}
    pending={action,file,scope:scope(),folder:q('editor-folder').value};q('fm-dialog-title').textContent={rename:'Renomear arquivo',mkdir:'Nova pasta','upload':'Enviar arquivo'}[action];
    q('fm-dialog-path').textContent=`${pending.scope.domain}/public_html/${file?file.path:pending.folder}`;
    q('fm-name').value=file?file.name:'';q('fm-name-field').hidden=action==='upload';q('fm-name').required=action!=='upload';q('fm-file-field').hidden=action!=='upload';q('fm-file').required=action==='upload';q('fm-file').value='';q('fm-password').value='';q('fm-code').value='';q('fm-error').textContent='';q('fm-dialog').showModal();
  }
  q('fm-action').addEventListener('submit',e=>{e.preventDefault();task(async()=>{
    const job=pending,credentials={password:q('fm-password').value,code:q('fm-code').value};let upload=null;
    try{
      if(!job)throw new Error('Selecione uma operação.');
      if(job.action==='rename'){await api('rename',{...job.scope,path:job.file.path,name:q('fm-name').value,etag:job.file.etag,...credentials});reset();}
      else if(job.action==='mkdir')await api('mkdir',{...job.scope,path:join(job.folder,q('fm-name').value),...credentials});
      else{
        const file=q('fm-file').files[0];if(!file||file.size>MAX)throw new Error('Escolha um arquivo de até 64 MiB.');
        q('editor-status').textContent='Conferindo arquivo…';const bytes=new Uint8Array(await file.arrayBuffer());
        const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('');
        const begin=await api('upload-begin',{...job.scope,path:join(job.folder,file.name),total:file.size,sha256:hash,...credentials});upload=begin.upload;
        for(let offset=0;offset<bytes.length;offset+=begin.chunk_bytes){const chunk=bytes.subarray(offset,offset+begin.chunk_bytes);const result=await api('upload-part',{...job.scope,upload,offset,data:encode(chunk)});if(result.received!==offset+chunk.length)throw new Error('Upload interrompido.');progress(result.received/bytes.length*100);}
        await api('upload-commit',{...job.scope,upload});upload=null;
      }
      q('fm-dialog').close();pending=null;await load(job.folder);q('editor-status').textContent={rename:'Arquivo renomeado.',mkdir:'Pasta criada.',upload:'Upload concluído e SHA-256 conferido.'}[job.action];
    }finally{q('fm-password').value='';q('fm-code').value='';if(upload){try{await api('upload-cancel',{upload});}catch(_){/* Private staging expires and is cleaned on the next upload. */}}}
  });});
  q('fm-close').addEventListener('click',()=>{q('fm-dialog').close();pending=null;q('fm-password').value='';q('fm-code').value='';});
  q('fm-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();else{pending=null;q('fm-password').value='';q('fm-code').value='';}});
  q('fm-upload').addEventListener('click',()=>dialog('upload'));q('fm-mkdir').addEventListener('click',()=>dialog('mkdir'));
  q('fm-search').addEventListener('input',render);q('fm-up').addEventListener('click',()=>task(()=>load(q('editor-folder').value.split('/').filter(Boolean).slice(0,-1).join('/'))));
  q('fm-previous').addEventListener('click',()=>task(()=>load(listing.path,Math.max(0,listing.offset-100))));q('fm-next').addEventListener('click',()=>task(()=>load(listing.path,listing.next)));
  q('editor-owner').addEventListener('change',()=>{reset();listing=null;q('editor-domain').replaceChildren();q('editor-files').replaceChildren(empty('Carregue os domínios da conta.'));q('editor-folder').value='';});
  q('editor-domain').addEventListener('change',()=>{reset();task(()=>load(''));});
  async function domains(){reset();const data=await api('domains',scope());q('editor-domain').replaceChildren(...data.domains.map(name=>{const o=document.createElement('option');o.value=name;o.textContent=name;return o;}));if(data.domains.includes(root.dataset.domain))q('editor-domain').value=root.dataset.domain;if(data.domains.length)await load('');else{listing=null;q('editor-files').replaceChildren(empty('Esta conta não possui domínios disponíveis.'));q('editor-status').textContent='Nenhum domínio disponível.';}}
  q('editor-domains').addEventListener('click',()=>task(domains));q('editor-browse').addEventListener('submit',e=>{e.preventDefault();task(()=>load(q('editor-folder').value));});
  q('editor-open').addEventListener('click',()=>open(q('editor-path').value));
  q('editor-new').addEventListener('click',()=>{opened={...scope(),path:q('editor-path').value,sha256:'absent'};restoreId=null;q('editor-content').disabled=false;q('editor-content').value='';q('editor-meta').textContent='Novo arquivo. Um caminho existente será recusado.';});
  q('editor-content').addEventListener('keydown',e=>{if(e.key==='Tab'){e.preventDefault();const start=e.target.selectionStart,end=e.target.selectionEnd;e.target.setRangeText('  ',start,end,'end');}});
  q('editor-save').addEventListener('submit',e=>{e.preventDefault();task(async()=>{try{if(!opened&&!restoreId)throw new Error('Abra um arquivo ou escolha uma versão.');const credentials={password:q('editor-password').value,code:q('editor-code').value};const data=await api(restoreId?'restore':'save',restoreId?{...scope(),revision:restoreId,...credentials}:{...opened,content:q('editor-content').value,...credentials});q('editor-status').textContent=`Arquivo salvo. Revisão ${data.revision}.`;if(opened)opened.sha256=data.sha256;restoreId=null;}finally{q('editor-password').value='';q('editor-code').value='';}});});
  q('editor-history').addEventListener('click',()=>task(async()=>{const data=await api('history',scope());q('editor-revisions').replaceChildren(...data.revisions.map(r=>button(`${r.domain}/${r.path} · restaurar ${r.id.slice(0,8)}`,()=>{if(r.domain!==q('editor-domain').value){q('editor-status').textContent='Selecione o domínio dessa versão.';return;}restoreId=r.id;opened=null;q('editor-path').value=r.path;q('editor-content').value='';q('editor-content').disabled=true;q('editor-meta').textContent='Restauração selecionada. Confirme a senha e um novo A2F no formulário de salvar.';},'button button-secondary pro-button pro-button-quiet')));q('editor-status').textContent=`${data.revisions.length} revisões. A restauração verifica a versão atual antes de gravar.`;}));
  if(root.dataset.domain)task(domains);
})();
