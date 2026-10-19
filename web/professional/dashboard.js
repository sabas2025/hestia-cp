'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const search = $('pro-search');
  const normalize = (value) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('pt-BR');
  search?.addEventListener('input', () => {
    let count = 0;
    for (const card of document.querySelectorAll('.pro-tool')) {
      card.hidden = !normalize(card.textContent).includes(normalize(search.value));
      if (!card.hidden) count++;
    }
    $('pro-empty').hidden = count !== 0;
  });
  const stateLabel = {running: 'Em andamento', succeeded: 'Concluída', failed: 'Falhou'};
  const date = (value) => {
    if (!value) return 'Ainda sem registro';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? 'Data indisponível' : parsed.toLocaleString('pt-BR');
  };
  const updateHealth = (health) => {
    if (!$('pro-checks')) return;
    const timestamp = Date.parse(health?.generated_at ?? '');
    const stale = !Number.isFinite(timestamp) || Date.now() - timestamp > 15 * 60 * 1000;
    $('pro-health-status').textContent = stale ? 'Coleta desatualizada' : ({ok: 'Operacional', warning: 'Atenção', critical: 'Requer ação'}[health?.status] ?? 'Sem coleta');
    $('pro-health-age').textContent = `Coleta: ${date(health?.generated_at)}`;
    const rows = [];
    for (const check of health?.checks ?? []) {
      const row = document.createElement('div'); row.className = 'pro-check';
      const light = document.createElement('span');
      light.className = `pro-indicator ${['ok', 'warning', 'critical'].includes(check.state) ? check.state : 'warning'}`;
      const name = document.createElement('strong'); name.textContent = check.name;
      const detail = document.createElement('span'); detail.textContent = check.detail;
      row.append(light, name, detail); rows.push(row);
    }
    $('pro-checks').replaceChildren(...rows);
  };
  let pending = false;
  async function refresh() {
    if (pending || document.hidden) return;
    pending = true; $('pro-refresh').disabled = true;
    const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 70000);
    try {
      const response = await fetch('/professional/?format=json', {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Sessão indisponível');
      const data = await response.json();
      for (const element of document.querySelectorAll('[data-count]')) element.textContent = data.resources[element.dataset.count]?.count ?? '—';
      $('pro-backup-date').textContent = date(data.last_backup?.completed_at);
      $('pro-drill-date').textContent = date(data.last_drill?.completed_at);
      if ($('pro-backup-freshness')) $('pro-backup-freshness').textContent = data.backup_freshness;
      $('pro-job-state').textContent = stateLabel[data.job?.state] ?? 'Nenhuma execução registrada';
      $('pro-job-step').textContent = data.job?.step ?? 'Operações agendadas aparecerão aqui.';
      updateHealth(data.health);
      $('pro-refresh-status').textContent = `Atualizado às ${new Date().toLocaleTimeString('pt-BR')}`;
    } catch {
      $('pro-refresh-status').textContent = 'Falha na atualização. Verifique a sessão e tente novamente.';
    } finally {
      clearTimeout(timer); pending = false; $('pro-refresh').disabled = false;
    }
  }
  $('pro-refresh')?.addEventListener('click', refresh);
  let assistantPlan = null;
  $('pro-assistant-form')?.addEventListener('submit', (event) => {
    event.preventDefault();
    const topic = $('pro-assistant-topic').value;
    const name = $('pro-assistant-domain').value.trim().toLowerCase().replace(/\.$/, '');
    const address = $('pro-assistant-ip').value.trim();
    const octets = address.split('.');
    const validIP = octets.length === 4 && octets.every(x => /^(0|[1-9][0-9]{0,2})$/.test(x) && +x <= 255) &&
      ![0, 10, 127].includes(+octets[0]) && +octets[0] < 224 &&
      !(+octets[0] === 192 && +octets[1] === 168) && !(+octets[0] === 172 && +octets[1] >= 16 && +octets[1] <= 31) &&
      !(+octets[0] === 169 && +octets[1] === 254) && !(+octets[0] === 100 && +octets[1] >= 64 && +octets[1] <= 127);
    if (name.length > 253 || !name.includes('.') || !name.split('.').every(s => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(s)) || !/[a-z]/.test(name) || !validIP) {
      $('pro-assistant-message').textContent = 'Informe um domínio válido e o IPv4 público da VPS.';
      $('pro-assistant-result').hidden = true; assistantPlan = null; return;
    }
    const steps = ['Confirme o IP e o provedor que hospeda a zona DNS.', 'Revise os registros existentes antes de publicar alterações.'];
    const records = [{type: 'A', name, value: address}];
    if (topic === 'email') {
      records.push({type: 'A', name: `mail.${name}`, value: address}, {type: 'MX', name, value: `10 mail.${name}`},
        {type: 'TXT', name, value: `v=spf1 ip4:${address} ~all`}, {type: 'TXT', name: `_dmarc.${name}`, value: 'v=DMARC1; p=none'});
      steps.push('O SPF sugerido autoriza apenas este IP. Mescle seus remetentes em um único SPF; preserve as integrações existentes.',
        'Ative DKIM no Hestia e copie a chave pública real do domínio.', `Peça ao provedor da VPS o PTR do IP para mail.${name}.`,
        'Valide TLS, SMTP autenticado, envio e recebimento. DMARC começa em observação; avance após conferir os remetentes.');
    } else if (topic === 'backup') steps.push('Ative o backup nativo local para cobrir sites e dumps dos bancos.',
      'Configure os destinos em cloud-backup.json e credenciais root/0600 pelo terminal administrativo.',
      'Execute plan, init, run, check e drill; guarde a senha de criptografia fora da VPS.',
      'Ensaie importação SQL e restauração da aplicação em homologação.');
    else if (topic === 'server') steps.push('Confirme hostname, certificado, atualizações, usuário de aplicação e 2FA.',
      'Use uma VPS limpa para instalar o Hestia; migre aplicações e bancos antes de alterar o DNS.');
    else if (topic === 'security') steps.push('Comece o WAF em observação e valide login, APIs, OAuth e uploads.',
      'Avance PL1 → PL2 → PL3 com revisão de falsos positivos por regra e rota.',
      'Cadastre seu IP no Fail2Ban e mantenha console e rollback disponíveis.',
      'Rotas de proxy direto para Node.js/Docker precisam de WAF próprio.');
    assistantPlan = {schema: 1, assistant: 'local-guided-rules', mode: 'plan', topic, domain: name,
      records: ['dns', 'email'].includes(topic) ? records : [], steps, changes_applied: false, dkim_generated: false};
    $('pro-assistant-steps').replaceChildren(...steps.map(text => { const li = document.createElement('li'); li.textContent = text; return li; }));
    $('pro-assistant-records').textContent = assistantPlan.records.map(r => `${r.type}  ${r.name}  ${r.value}`).join('\n');
    $('pro-assistant-records').hidden = assistantPlan.records.length === 0;
    $('pro-assistant-result').hidden = false;
    $('pro-assistant-message').textContent = 'Roteiro gerado localmente. Nenhuma alteração foi aplicada.';
  });
  $('pro-assistant-download')?.addEventListener('click', () => {
    if (!assistantPlan) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(assistantPlan, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'plano-configuracao.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  // No automatic repeated expensive CLI queries; refresh only on explicit request.
})();
