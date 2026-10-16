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
  // No automatic repeated expensive CLI queries; refresh only on explicit request.
})();
