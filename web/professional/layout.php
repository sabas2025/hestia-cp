<?php
declare(strict_types=1);

// Views are reached only after main.php and their own authorization checks.
if (!defined('HST_PRO_VIEW') && !defined('HST_PRO_BUSINESS_VIEW') &&
    !defined('HST_PRO_EDITOR_VIEW') && !defined('HST_PRO_PLATFORM_VIEW') &&
    !defined('HST_PRO_MFA_VIEW')) {
    http_response_code(403);
    exit;
}

function pro_layout_theme(): string
{
    $theme = ($_SESSION['POLICY_USER_CHANGE_THEME'] ?? '') === 'no'
        ? ($_SESSION['THEME'] ?? 'default')
        : ($_SESSION['userTheme'] ?? $_SESSION['THEME'] ?? 'default');
    if (!is_string($theme) || !preg_match('/\A[a-zA-Z0-9_-]{1,64}\z/D', $theme)) {
        return '';
    }
    if ($theme === 'default') { return ''; }
    $web = dirname(__DIR__);
    foreach (['/css/themes/' . $theme . '.min.css', '/css/themes/custom/' . $theme . '.min.css',
              '/css/themes/custom/' . $theme . '.css'] as $path) {
        if (is_file($web . $path)) { return $path; }
    }
    return '';
}

function pro_layout_usage(array $account, string $used, string $limit): string
{
    $usage = (string)($account[$used] ?? '0');
    $quota = (string)($account[$limit] ?? '—');
    if (function_exists('humanize_usage_size') && function_exists('humanize_usage_measure')) {
        return humanize_usage_size($usage) . ' ' . humanize_usage_measure($usage) . ' / ' .
            ($quota === 'unlimited' ? '∞' : humanize_usage_size($quota) . ' ' . humanize_usage_measure($quota));
    }
    return $usage . ' MB / ' . ($quota === 'unlimited' ? '∞' : $quota);
}

function pro_layout_open(string $title, string $section, array $identity,
                         array $scripts = [], array $styles = [], string $bodyClass = ''): void
{
    $owner = (string)($identity['owner'] ?? '');
    $admin = ($identity['admin'] ?? false) === true && empty($identity['impersonating']);
    $account = function_exists('get_user_data') ? (get_user_data($owner)[$owner] ?? []) : [];
    // Use the same selected theme as the native pages. Do not load the native
    // Alpine bootstrap: these pages keep their strict CSP, and A2F needs no JS.
    $theme = pro_layout_theme();
    $appName = (string)($_SESSION['APP_NAME'] ?? 'Hestia Control Panel');
    $token = rawurlencode((string)($_SESSION['token'] ?? ''));
    $settings = '/edit/user/?user=' . rawurlencode($owner) . '&token=' . $token;
    $tabs = [];
    if ($admin && ($_SESSION['POLICY_SYSTEM_HIDE_ADMIN'] ?? '') === 'yes' &&
        ($_SESSION['user'] ?? '') !== ($_SESSION['ROOT_USER'] ?? '')) {
        $account['U_USERS'] = max(0, (int)($account['U_USERS'] ?? 0) - 1);
    }
    if ($admin) { $tabs[] = ['USUÁRIO', '/list/user/', 'fa-users', 'U_USERS', '']; }
    foreach ([['WEB', 'web', 'fa-earth-americas', 'U_WEB_DOMAINS', 'WEB_DOMAINS', 'WEB_SYSTEM'],
              ['DNS', 'dns', 'fa-book-atlas', 'U_DNS_DOMAINS', 'DNS_DOMAINS', 'DNS_SYSTEM'],
              ['E-MAIL', 'mail', 'fa-envelope', 'U_MAIL_DOMAINS', 'MAIL_DOMAINS', 'MAIL_SYSTEM'],
              ['DATABASE', 'db', 'fa-database', 'U_DATABASES', 'DATABASES', 'DB_SYSTEM'],
              ['TAREFA', 'cron', 'fa-clock', 'U_CRON_JOBS', 'CRON_JOBS', 'CRON_SYSTEM'],
              ['BACKUP', 'backup', 'fa-file-zipper', 'U_BACKUPS', 'BACKUPS', 'BACKUP_SYSTEM']] as $tab) {
        [$label, $path, $icon, $count, $quota, $system] = $tab;
        if (!empty($_SESSION[$system]) && ((string)($account[$quota] ?? '0') !== '0' ||
            ($path === 'backup' && ((int)($account[$count] ?? 0) > 0 || ($account['BACKUPS_INCREMENTAL'] ?? '') === 'yes')))) {
            $tabs[] = [$label, '/list/' . $path . '/', $icon, $count, $quota];
        }
    }
    $sections = ['overview' => ['Visão geral', '/professional/'],
                 'editor' => ['Arquivos por domínio', '/professional/editor.php'],
                 'business' => ['Operações e diagnóstico', '/professional/business.php'],
                 'twofactor' => ['Segurança A2F', '/professional/twofactor.php']];
    if ($admin) { $sections['platform'] = ['Ferramentas do servidor', '/professional/platform.php']; }
    ?>
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title><?= pro_escape($title . ' · ' . $appName) ?></title>
  <link rel="icon" href="/images/logo.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/css/themes/default.min.css">
  <?php if ($theme !== ''): ?><link rel="stylesheet" href="<?= pro_escape($theme) ?>"><?php endif; ?>
  <link rel="stylesheet" href="/professional/dashboard.css">
  <?php foreach ($styles as $style): ?><link rel="stylesheet" href="/professional/<?= pro_escape($style) ?>"><?php endforeach; ?>
  <?php foreach ($scripts as $script): ?><script src="/professional/<?= pro_escape($script) ?>" defer></script><?php endforeach; ?>
</head>
<body class="pro-body page-professional <?= pro_escape($bodyClass) ?>">
<a class="pro-skip" href="#pro-content">Ir para o conteúdo</a>
<div class="app">
  <header class="app-header">
    <div class="top-bar"><div class="container top-bar-inner">
      <div class="top-bar-left">
        <a href="/professional/" class="top-bar-logo" title="<?= pro_escape($appName) ?>"><img src="/images/logo-header.svg" alt="<?= pro_escape($appName) ?>" width="54" height="29"></a>
        <div class="top-bar-usage"><div class="top-bar-usage-inner">
          <span class="top-bar-usage-item"><i class="fas <?= $admin ? 'fa-user-tie' : 'fa-user' ?>" aria-hidden="true"></i> <strong><?= pro_escape($owner) ?></strong></span>
          <span class="top-bar-usage-item pro-native-usage" title="Disco"><i class="fas fa-hard-drive" aria-hidden="true"></i> <?= pro_escape(pro_layout_usage($account, 'U_DISK', 'DISK_QUOTA')) ?></span>
          <span class="top-bar-usage-item pro-native-usage" title="Tráfego"><i class="fas fa-right-left" aria-hidden="true"></i> <?= pro_escape(pro_layout_usage($account, 'U_BANDWIDTH', 'BANDWIDTH')) ?></span>
        </div></div>
      </div>
      <nav class="pro-native-actions" aria-label="Conta e servidor">
        <?php if ($admin): ?><a class="top-bar-menu-link" href="/list/server/" title="Configurar servidor" aria-label="Configurar servidor"><i class="fas fa-gear" aria-hidden="true"></i></a><?php endif; ?>
        <a class="top-bar-menu-link" href="<?= pro_escape($settings) ?>" title="Minha conta" aria-label="Minha conta"><i class="fas fa-circle-user" aria-hidden="true"></i></a>
        <a class="top-bar-menu-link" href="/list/log/" title="Histórico" aria-label="Histórico"><i class="fas fa-clock-rotate-left" aria-hidden="true"></i></a>
        <a class="top-bar-menu-link top-bar-menu-link-logout" href="/logout/?token=<?= pro_escape($token) ?>" title="Sair" aria-label="Sair"><i class="fas fa-right-from-bracket" aria-hidden="true"></i></a>
      </nav>
    </div></div>
    <nav class="main-menu" aria-label="Painel HestiaCP"><div class="container"><ul class="main-menu-list">
      <?php foreach ($tabs as [$label, $href, $icon, $count, $quota]): ?>
      <li class="main-menu-item"><a class="main-menu-item-link" href="<?= $href ?>"><p class="main-menu-item-label"><?= $label ?><i class="fas <?= $icon ?>" aria-hidden="true"></i></p><ul class="main-menu-stats"><li><?= $quota === '' ? 'Usuários: ' : '' ?><?= pro_escape($account[$count] ?? '0') ?><?php if ($quota !== ''): ?> / <?= pro_escape(($account[$quota] ?? '') === 'unlimited' ? '∞' : ($account[$quota] ?? '—')) ?><?php endif; ?></li></ul></a></li>
      <?php endforeach; ?>
      <li class="main-menu-item"><a class="main-menu-item-link active" href="/professional/" aria-current="true"><p class="main-menu-item-label">PROFESSIONAL<i class="fas fa-layer-group" aria-hidden="true"></i></p><ul class="main-menu-stats"><li>Central de hospedagem</li></ul></a></li>
    </ul></div></nav>
  </header>
  <div class="app-content">
    <div class="toolbar pro-native-toolbar"><nav class="container pro-page-nav" aria-label="Páginas Professional">
      <?php foreach ($sections as $key => [$label, $href]): ?><a class="toolbar-link<?= $section === $key ? ' selected' : '' ?>" href="<?= $href ?>"<?= $section === $key ? ' aria-current="page"' : '' ?>><?= $label ?></a><?php endforeach; ?>
    </nav></div>
    <div id="pro-content" tabindex="-1">
<?php
}

function pro_layout_close(): void
{
    ?>
    </div>
  </div>
  <footer class="app-footer"><div class="container"><p>Hestia Control Panel v<?= pro_escape($_SESSION['VERSION'] ?? '1.10.5') ?> · Professional</p></div></footer>
</div>
</body>
</html>
<?php
}
