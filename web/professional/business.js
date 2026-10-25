'use strict';
(() => {
  const q = id => document.getElementById(id);
  const root = q('business'); if (!root) return;
  let plan = null, mode = 'apply', busy = false;
  const names = {'dns-ttl':'TTL de DNS','mail-rate':'Limite de e-mail','cache-profile':'Perfil de cache','ssh-policy':'Política SSH',resources:'Recursos da conta'};
  const states = {planned:'Planejado',applied:'Aplicado',queued:'Na fila',running:'Em execução','rolled-back':'Revertido','failed-restored':'Falhou e foi revertido','recovery-required':'Revisão manual necessária','queue-expired':'Fila expirada','interrupted-review':'Execução interrompida; revisão manual','queue-failed':'Falha ao iniciar fila','job-failed':'Execução recusada ou com falha'};
  function fields() {
    const action = q('action').value;
    q('domain-fields').hidden = !['dns-ttl','mail-rate','cache-profile'].includes(action);
    q('number-fields').hidden = !['dns-ttl','mail-rate'].includes(action);
    q('cache-fields').hidden = action !== 'cache-profile'; q('ssh-fields').hidden = action !== 'ssh-policy'; q('resource-fields').hidden = action !== 'resources';
    q('number-label').textContent = action === 'mail-rate' ? 'Mensagens por hora por caixa postal' : 'TTL em segundos';
    q('value').min = action === 'mail-rate' ? '1' : '300'; q('value').max = action === 'mail-rate' ? '10000' : '604800';
  }
  async function api(op, request) {
    const body = new URLSearchParams({token:root.dataset.token,op,request:JSON.stringify(request)});
    const response = await fetch('/professional/business.php',{method:'POST',body,credentials:'same-origin',cache:'no-store',redirect:'error'});
    const data = await response.json(); if (!response.ok || data.error) throw new Error(data.error || 'Consulta recusada.');
    return data;
  }
  async function task(work) {
    if (busy) return; busy = true; root.setAttribute('aria-busy','true'); q('business-status').textContent = 'Consultando…';
    try { await work(); } catch (error) { q('business-status').textContent = error.message; }
    finally { busy = false; root.removeAttribute('aria-busy'); }
  }
  function review(data, nextMode='apply') {
    plan = data; mode = nextMode; q('plan-review').hidden = false;
    q('plan-summary').textContent = `${names[data.action]} · ${data.owner}${data.params.domain ? ' · '+data.params.domain : ''} · ${states[data.state] || data.state}`;
    q('plan-notes').replaceChildren();
    for (const note of data.notes || []) { const li = document.createElement('li'); li.textContent = note; q('plan-notes').append(li); }
    q('plan-json').textContent = JSON.stringify(data,null,2);
    q('confirm').textContent = mode === 'rollback' ? 'Confirmar reversão e colocar na fila' : 'Confirmar e colocar na fila';
    q('password').value = ''; q('code').value = '';
  }
  async function history() {
    const data = await api('history',{}); q('history-list').replaceChildren();
    for (const entry of data.plans) {
      const row = document.createElement('div'); row.className = 'pro-operation';
      const text = document.createElement('p'); text.textContent = `${names[entry.action]} · ${entry.owner} · ${states[entry.state] || entry.state}${entry.job_state ? ' · fila: '+(states[entry.job_state] || entry.job_state) : ''}`; row.append(text);
      if (!['queued','running','interrupted-review'].includes(entry.job_state) && ['planned','applied'].includes(entry.state)) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'pro-button'; button.textContent = entry.state === 'applied' ? 'Revisar reversão' : 'Revisar plano';
        button.addEventListener('click',() => { review(entry,entry.state === 'applied' ? 'rollback' : 'apply'); q('plan-summary').scrollIntoView({block:'center'}); }); row.append(button);
      }
      q('history-list').append(row);
    }
    if (!data.plans.length) q('history-list').textContent = 'Nenhuma alteração registrada para esta conta.';
  }
  q('action').addEventListener('change',fields); fields();
  q('change-form').addEventListener('submit',event => { event.preventDefault(); task(async () => {
    const action = q('action').value; let params;
    if (action === 'resources') params = {uid:Number(q('uid').value),memory_mb:Number(q('memory').value),tasks:Number(q('tasks').value),io_weight:Number(q('io').value)};
    else if (action === 'ssh-policy') params = {value:q('ssh-policy').value};
    else params = {domain:q('domain').value.trim(),value:action === 'cache-profile' ? q('cache-profile').value : Number(q('value').value)};
    review(await api('plan',{owner:q('owner').value,action,params})); q('business-status').textContent = 'Plano preparado. Revise antes de confirmar; validade de dez minutos.';
  }); });
  q('confirm-form').addEventListener('submit',event => { event.preventDefault(); task(async () => {
    if (!plan) throw new Error('Prepare um plano.');
    try {
      const data = await api(mode,{id:plan.id,password:q('password').value,code:q('code').value});
      q('plan-json').textContent = JSON.stringify(data,null,2); plan = null; q('plan-review').hidden = true;
      await history(); q('business-status').textContent = 'Operação colocada na fila. Atualize o histórico para verificar o resultado; ainda não há confirmação de aplicação.';
    } finally { q('password').value = ''; q('code').value = ''; }
  }); });
  q('history').addEventListener('click',() => task(async () => { await history(); q('business-status').textContent = 'Histórico atualizado.'; }));
  q('diagnose').addEventListener('click',() => task(async () => {
    q('diagnostic').textContent = JSON.stringify(await api('diagnose',{owner:q('owner').value,domain:q('domain').value.trim()}),null,2);
    q('business-status').textContent = 'Consulta concluída. As limitações estão indicadas no diagnóstico.';
  }));
  q('coverage')?.addEventListener('click',() => task(async () => {
    q('diagnostic').textContent = JSON.stringify(await api('coverage',{owner:q('owner').value}),null,2); q('business-status').textContent = 'Cobertura observada; processos futuros exigem acompanhamento.';
  }));
})();
