<?php
// Professional dashboard: authorization is checked against current Hestia data.
declare(strict_types=1);

function pro_identity(array $session, array $actual): array {
    $user = $session['user'] ?? '';
    if (!is_string($user) || !preg_match('/\A[a-z][a-z0-9_]{1,29}\z/D', $user)) {
        throw new RuntimeException('Invalid session');
    }
    if (($actual['SUSPENDED'] ?? 'yes') !== 'no') {
        throw new RuntimeException('Account suspended');
    }
    $context = $session['userContext'] ?? '';
    if (!in_array($context, ['user', 'admin'], true)) {
        throw new RuntimeException('Invalid session context');
    }
    if ($context === 'admin' && ($actual['ROLE'] ?? '') !== 'admin') {
        throw new RuntimeException('Role revoked');
    }
    $look = $session['look'] ?? '';
    if (!is_string($look) || ($look !== '' && !preg_match('/\A[a-z][a-z0-9_]{1,29}\z/D', $look))) {
        throw new RuntimeException('Invalid account scope');
    }
    if ($look !== '' && ($context !== 'admin' || ($actual['ROLE'] ?? '') !== 'admin')) {
        throw new RuntimeException('Forbidden account scope');
    }
    if ($look !== '' && $look === ($session['ROOT_USER'] ?? '') && ($session['POLICY_SYSTEM_PROTECTED_ADMIN'] ?? '') === 'yes') {
        throw new RuntimeException('Protected administrator account');
    }
    return ['owner' => $look !== '' ? $look : $user,
            'admin' => $context === 'admin' && $look === '',
            'impersonating' => $look !== ''];
}

function pro_snapshot(string $file): ?array {
    if (!is_file($file) || is_link($file) || filesize($file) > 1048576) {
        return null;
    }
    $raw = file_get_contents($file);
    $value = is_string($raw) ? json_decode($raw, true) : null;
    return is_array($value) ? $value : null;
}

function pro_native(string $command, string $owner): ?array {
    $allowed = ['v-list-web-domains', 'v-list-dns-domains', 'v-list-mail-domains',
                'v-list-databases', 'v-list-cron-jobs', 'v-list-user-backups'];
    if (!in_array($command, $allowed, true) || !preg_match('/\A[a-z][a-z0-9_]{1,29}\z/D', $owner)) {
        throw new RuntimeException('Command not allowed');
    }
    $pipes = [];
    $process = proc_open(['/usr/bin/sudo', '-n', HESTIA_DIR_BIN . $command, $owner, 'json'],
        [0 => ['file', '/dev/null', 'r'], 1 => ['pipe', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
    if (!is_resource($process)) { return null; }
    stream_set_blocking($pipes[1], false);
    $output = ''; $start = microtime(true); $exit = -1;
    while (true) {
        $output .= stream_get_contents($pipes[1]);
        $status = proc_get_status($process);
        if (!$status['running']) { $exit = $status['exitcode']; break; }
        if (microtime(true) - $start > 4 || strlen($output) > 2097152) {
            proc_terminate($process, 9); break;
        }
        usleep(10000);
    }
    $output .= stream_get_contents($pipes[1]); fclose($pipes[1]); proc_close($process);
    if ($exit !== 0 || strlen($output) > 2097152) { return null; }
    $data = json_decode($output, true);
    return is_array($data) ? $data : null;
}

function pro_payload(array $identity, array $account, string $root, ?callable $runner = null): array {
    $runner ??= 'pro_native';
    $owner = $identity['owner'];
    $definitions = [
        'web' => ['v-list-web-domains', 'WEB_DOMAINS'],
        'mail' => ['v-list-mail-domains', 'MAIL_DOMAINS'],
        'dns' => ['v-list-dns-domains', 'DNS_DOMAINS'],
        'db' => ['v-list-databases', 'DATABASES'],
        'cron' => ['v-list-cron-jobs', 'CRON_JOBS'],
        'backup' => ['v-list-user-backups', 'BACKUPS'],
    ];
    $resources = [];
    foreach ($definitions as $name => [$command, $permission]) {
        $enabled = ($account[$permission] ?? '0') !== '0';
        $objects = $enabled ? $runner($command, $owner) : [];
        $resources[$name] = ['enabled' => $enabled, 'count' => is_array($objects) ? count($objects) : null];
    }
    $task = pro_snapshot($root . '/data/professional/jobs/' . $owner . '.json');
    if ($task !== null && ($task['user'] ?? '') !== $owner) { $task = null; }
    $lastBackup = pro_snapshot($root . '/data/professional/backups/' . $owner . '-run.json');
    $lastDrill = pro_snapshot($root . '/data/professional/backups/' . $owner . '-drill.json');
    foreach (['lastBackup', 'lastDrill'] as $var) {
        if ($$var !== null && ($$var['user'] ?? '') !== $owner) { $$var = null; }
    }
    $health = $identity['admin'] ? pro_snapshot($root . '/data/professional/health.json') : null;
    if ($health !== null) {
        $stamp = strtotime($health['generated_at'] ?? '');
        if ($stamp === false || time() - $stamp > 900 || $stamp > time() + 300) {
            $health['status'] = 'Coleta desatualizada';
        }
    }
    $backupState = 'Sem cópia criptografada registrada';
    if ($lastBackup !== null) {
        $completed = strtotime($lastBackup['completed_at'] ?? '');
        $rpo = (int)($lastBackup['rpo_hours'] ?? 24);
        $backupState = $completed !== false && $completed <= time() + 300 && time() - $completed <= max(1, $rpo) * 3600 ? 'Dentro do prazo configurado' : 'Cópia fora do prazo: revisar agendamento';
    }
    $catalog = pro_snapshot($root . '/data/professional/projects.json');
    $projects = [];
    foreach (($catalog['projects'] ?? []) as $project) {
        if (!is_array($project) || !preg_match('/\A[a-z][a-z0-9-]{1,31}\z/D', $project['id'] ?? '')) { continue; }
        if (!$identity['admin'] && (($project['owner'] ?? '') !== $owner || in_array($project['type'] ?? '', ['docker-ui', 'marketing'], true))) { continue; }
        $url = $project['url'] ?? '';
        $parts = is_string($url) ? parse_url($url) : false;
        if (!is_array($parts) || ($parts['scheme'] ?? '') !== 'https' || empty($parts['host']) || isset($parts['user']) || isset($parts['pass']) || isset($parts['query']) || isset($parts['fragment'])) { continue; }
        $projects[] = ['id' => $project['id'], 'type' => (string)($project['type'] ?? ''), 'url' => $url];
    }
    $cloud = [];
    foreach (glob($root . '/data/professional/backups/' . $owner . '-*-run.json') ?: [] as $file) {
        $entry = pro_snapshot($file);
        if ($entry === null || ($entry['user'] ?? '') !== $owner) { continue; }
        $id = (string)($entry['id'] ?? '');
        if (!preg_match('/\A[a-z][a-z0-9-]{1,31}\z/D', $id)) { continue; }
        $cloud[$id] = ['id' => $id, 'provider' => (string)($entry['provider'] ?? ''),
                    'state' => (string)($entry['state'] ?? ''), 'completed_at' => (string)($entry['completed_at'] ?? ''),
                    'last_success' => (string)($entry['completed_at'] ?? ''), 'last_attempt_state' => 'unknown', 'last_attempt_at' => ''];
    }
    foreach (glob($root . '/data/professional/backups/' . $owner . '-*-attempt.json') ?: [] as $file) {
        $entry = pro_snapshot($file); $id = $entry['id'] ?? '';
        if ($entry === null || ($entry['user'] ?? '') !== $owner || !is_string($id) || !preg_match('/\A[a-z][a-z0-9-]{1,31}\z/D', $id)) { continue; }
        $cloud[$id] ??= ['id'=>$id, 'provider'=>(string)($entry['provider'] ?? ''), 'state'=>'unknown', 'completed_at'=>'', 'last_success'=>''];
        $cloud[$id]['last_attempt_state'] = in_array($entry['state'] ?? '', ['succeeded','failed'], true) ? $entry['state'] : 'unknown';
        $cloud[$id]['last_attempt_at'] = (string)($entry['attempted_at'] ?? '');
    }
    $policy = pro_snapshot($root . '/professional/component-policy.json');
    return ['overlay_version' => (string)($policy['overlay_version'] ?? 'unknown'), 'identity' => $identity, 'resources' => $resources, 'projects' => $projects, 'cloud_targets' => array_values($cloud),
        'twofa' => !empty($account['TWOFA']),
        'disk' => (string)($account['U_DISK'] ?? '0'),
        'disk_limit' => (string)($account['DISK_QUOTA'] ?? 'unknown'),
        'health' => $health,
        'job' => $task, 'last_backup' => $lastBackup, 'last_drill' => $lastDrill,
        'backup_freshness' => $backupState,
        'generated_at' => gmdate('c')];
}

function pro_escape(mixed $value): string {
    return htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}
