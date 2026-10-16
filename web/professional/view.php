<?php if (!defined('HST_PRO_VIEW')) { http_response_code(403); exit('Acesso não autorizado.'); } ?>
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>Central · <?= pro_escape($displayName) ?></title>
  <link rel="stylesheet" href="/professional/dashboard.css">
  <script src="/professional/dashboard.js" defer></script>
</head>
<body class="pro-body">
<a class="pro-skip" href="#conteudo">Ir para o conteúdo</a>
<div class="pro-layout">
  <aside class="pro-sidebar" aria-label="Navegação">
    <a class="pro-brand" href="/professional/"><span class="pro-mark" aria-hidden="true">H</span><span><?= pro_escape($displayName) ?><small>Central de hospedagem</small></span></a>
    <span class="pro-context"><?= $identity['admin'] ? 'Administração' : 'Minha conta' ?></span>
    <nav>
      <a class="is-active" href="/professional/" aria-current="page">Visão geral</a>
      <?php foreach (['web' => ['Sites', '/list/web/'], 'mail' => ['E-mail', '/list/mail/'], 'db' => ['Bancos de dados', '/list/db/'], 'dns' => ['DNS', '/list/dns/'], 'cron' => ['Tarefas agendadas', '/list/cron/'], 'backup' => ['Backups', '/list/backup/']] as $key => [$label, $href]): ?>
      <?php if ($payload['resources'][$key]['enabled']): ?><a href="<?= $href ?>"><?= $label ?></a><?php endif; ?>
      <?php endforeach; ?>
      <?php if ($identity['admin']): ?><span class="pro-nav-label">Servidor</span><a href="/list/user/">Usuários e acessos</a><a href="/list/server/">Serviços e atualizações</a><a href="/list/firewall/">Firewall</a><?php endif; ?>
      <span class="pro-nav-label">Conta</span><a href="/edit/user/?user=<?= rawurlencode($identity['owner']) ?>">Segurança e preferências</a><a href="/list/log/">Histórico de atividades</a>
    </nav>
    <div class="pro-sidebar-note"><span class="pro-status-dot"></span>Sessão protegida<small>Informações restritas à sua conta.</small></div>
  </aside>
  <div class="pro-workspace">
    <header class="pro-topbar"><div><span class="pro-eyebrow"><?= $identity['admin'] ? 'Administração do servidor' : 'Área do cliente' ?></span><strong><?= pro_escape($identity['owner']) ?></strong></div><a class="pro-button pro-button-quiet" href="/list/web/">Abrir painel completo ↗</a></header>
    <main id="conteudo" class="pro-main">
      <section class="pro-heading"><div><span class="pro-eyebrow">Tudo em um só lugar</span><h1>Visão geral</h1><p>Acompanhe seus recursos e cuide da sua operação.</p></div><div class="pro-update"><span id="pro-refresh-status" role="status">Consulta atualizada</span><button type="button" class="pro-button" id="pro-refresh">Atualizar</button></div></section>
      <?php if ($identity['impersonating']): ?><p class="pro-banner">Visualizando a conta de <?= pro_escape($identity['owner']) ?>. Dados globais do servidor não são exibidos neste contexto.</p><?php endif; ?>
      <?php if (!$payload['twofa']): ?><div class="pro-banner pro-banner-warning"><div><strong>Proteja sua conta com autenticação em duas etapas</strong><p>Ative o autenticador e guarde o código de recuperação em um local seguro.</p></div><a href="/edit/user/?user=<?= rawurlencode($identity['owner']) ?>">Configurar segurança →</a></div><?php endif; ?>
      <section class="pro-stats" aria-label="Recursos da conta">
      <?php foreach (['web' => ['Sites', 'Domínios e aplicações', '/list/web/', '◈'], 'mail' => ['Domínios de e-mail', 'Contas e mensagens', '/list/mail/', '✉'], 'db' => ['Bancos de dados', 'Dados das suas aplicações', '/list/db/', '▤'], 'backup' => ['Backups disponíveis', 'Pontos de recuperação', '/list/backup/', '↶']] as $key => [$label, $description, $href, $icon]): ?>
        <article class="pro-stat"><div class="pro-stat-head"><span><?= $label ?></span><span class="pro-icon" aria-hidden="true"><?= $icon ?></span></div><strong data-count="<?= $key ?>"><?= $payload['resources'][$key]['count'] === null ? '—' : pro_escape($payload['resources'][$key]['count']) ?></strong><p><?= $description ?></p><?php if ($payload['resources'][$key]['enabled']): ?><a href="<?= $href ?>">Gerenciar →</a><?php else: ?><span class="pro-muted">Indisponível no plano</span><?php endif; ?></article>
      <?php endforeach; ?>
      </section>
      <section class="pro-columns">
        <article class="pro-card"><header><div><span class="pro-eyebrow">Acesso rápido</span><h2>O que você precisa fazer?</h2></div></header><label for="pro-search" class="pro-label">Buscar ferramenta</label><input type="search" id="pro-search" placeholder="Sites, banco, backup…" autocomplete="off"><div class="pro-tools" id="pro-tools">
          <?php foreach (['web' => ['Sites e certificados', 'Domínios, PHP e HTTPS', '/list/web/'], 'mail' => ['E-mail profissional', 'Contas, encaminhamento e filtros', '/list/mail/'], 'db' => ['Bancos de dados', 'Usuários e acesso aos bancos', '/list/db/'], 'dns' => ['Registros DNS', 'Zonas e configuração dos domínios', '/list/dns/'], 'cron' => ['Tarefas agendadas', 'Rotinas automáticas da aplicação', '/list/cron/'], 'backup' => ['Backup e restauração', 'Verificar e recuperar arquivos', '/list/backup/']] as $key => [$label, $description, $href]): ?>
          <?php if ($payload['resources'][$key]['enabled']): ?><a class="pro-tool" href="<?= $href ?>"><strong><?= $label ?></strong><small><?= $description ?></small><span aria-hidden="true">↗</span></a><?php endif; ?>
          <?php endforeach; ?>
        </div><p id="pro-empty" hidden>Nenhuma ferramenta encontrada.</p></article>
        <article class="pro-card"><header><div><span class="pro-eyebrow">Continuidade da operação</span><h2>Backups e tarefas</h2></div></header><dl class="pro-details"><div><dt>Cópia criptografada</dt><dd id="pro-backup-date"><?= pro_escape($payload['last_backup']['completed_at'] ?? 'Ainda sem execução registrada') ?></dd></div><div><dt>Prazo da cópia</dt><dd id="pro-backup-freshness"><?= pro_escape($payload['backup_freshness'] ?? 'Sem cópia criptografada registrada') ?></dd></div><div><dt>Ensaio de recuperação</dt><dd id="pro-drill-date"><?= pro_escape($payload['last_drill']['completed_at'] ?? 'Ainda não realizado') ?></dd></div><div><dt>Uso de disco da conta</dt><dd><?= pro_escape($payload['disk']) ?> MB</dd></div><div><dt>Autenticação em duas etapas</dt><dd><?= $payload['twofa'] ? 'Ativada' : 'Configuração pendente' ?></dd></div></dl><div class="pro-job" aria-live="polite"><span class="pro-label">Última operação</span><strong id="pro-job-state"><?= pro_escape($payload['job']['state'] ?? 'Nenhuma execução registrada') ?></strong><small id="pro-job-step"><?= pro_escape($payload['job']['step'] ?? 'Operações agendadas aparecerão aqui.') ?></small></div><p class="pro-footnote">O ensaio recupera a cópia criptografada e verifica o arquivo. A restauração completa da aplicação deve ser validada em homologação.</p></article>
      </section>
      <?php if ($identity['admin']): ?><section class="pro-card pro-health"><header><div><span class="pro-eyebrow">Monitoramento</span><h2>Saúde do servidor</h2></div><span class="pro-pill" id="pro-health-status"><?= pro_escape($payload['health']['status'] ?? 'Sem coleta') ?></span></header><p id="pro-health-age" class="pro-muted">Coleta: <?= pro_escape($payload['health']['generated_at'] ?? 'aguardando configuração do monitor') ?></p><div class="pro-checks" id="pro-checks"><?php foreach (($payload['health']['checks'] ?? []) as $check): ?><div class="pro-check"><span class="pro-indicator <?= in_array($check['state'] ?? '', ['ok','warning','critical'], true) ? $check['state'] : 'warning' ?>"></span><strong><?= pro_escape($check['name'] ?? '') ?></strong><span><?= pro_escape($check['detail'] ?? '') ?></span></div><?php endforeach; ?></div><p class="pro-footnote">Alertas ficam visíveis aqui. Nenhum serviço é reiniciado automaticamente.</p></section><?php endif; ?>
      <footer class="pro-footer"><span>Central profissional · HestiaCP</span><span>Acesso autenticado · Sem cache de informações privadas</span></footer>
    </main>
  </div>
</div>
</body>
</html>
