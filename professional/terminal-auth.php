#!/usr/local/hestia/php/bin/php
<?php
declare(strict_types=1);

function deny(): never {
    echo '{"ok":false,"error":"session unavailable"}', PHP_EOL;
    exit(1);
}

function controlled_config(string $path): array {
    for ($parent = dirname($path); ; $parent = dirname($parent)) {
        $st = @lstat($parent);
        if ($st === false || is_link($parent) || $st['uid'] !== 0 ||
            (($st['mode'] & 0002) !== 0 && ($st['mode'] & 01000) === 0) ||
            (($st['mode'] & 0020) !== 0 && $st['gid'] !== 0 && ($st['mode'] & 01000) === 0)) deny();
        if ($parent === '/') break;
    }
    $st = @lstat($path);
    if ($st === false || ($st['mode'] & 0170000) !== 0100000 || $st['uid'] !== 0 ||
        $st['nlink'] !== 1 || ($st['mode'] & 0002) !== 0 ||
        (($st['mode'] & 0020) !== 0 && $st['gid'] !== 0) || $st['size'] > 2097152) deny();
    $text = @file_get_contents($path);
    if (!is_string($text)) deny();
    preg_match_all("/^([A-Z_]+)='([^'\\r\\n]*)'$/m", $text, $rows, PREG_SET_ORDER);
    $result = [];
    foreach ($rows as $row) {
        if (array_key_exists($row[1], $result)) deny();
        $result[$row[1]] = $row[2];
    }
    return $result;
}

function account(string $root, string $name): array {
    if (preg_match('/\A[a-z][a-z0-9_]{1,29}\z/D', $name) !== 1) deny();
    $data = controlled_config($root . '/data/users/' . $name . '/user.conf');
    if (($data['SUSPENDED'] ?? '') !== 'no' || ($data['LOGIN_DISABLED'] ?? '') === 'yes' ||
        !in_array($data['ROLE'] ?? '', ['admin', 'user'], true) ||
        in_array(basename($data['SHELL'] ?? ''), ['', 'false', 'nologin'], true)) deny();
    return $data;
}

// Never put a bearer session ID in argv, environment or error logs.
if (PHP_SAPI !== 'cli' || $argc !== 1) deny();
$raw = stream_get_contents(STDIN, 4097);
if (!is_string($raw) || strlen($raw) > 4096) deny();
$input = json_decode($raw, true);
if (!is_array($input) || !is_string($input['session_id'] ?? null) ||
    preg_match('/\A[A-Za-z0-9,-]{1,128}\z/D', $input['session_id']) !== 1 ||
    !is_string($input['remote_ip'] ?? null) || filter_var($input['remote_ip'], FILTER_VALIDATE_IP) === false) deny();
$root = getenv('HESTIA');
if (!is_string($root) || !str_starts_with($root, '/') || str_contains($root, '/../')) deny();
$native = controlled_config($root . '/conf/hestia.conf');
if (($native['VERSION'] ?? '') !== '1.10.5' || ($native['WEB_TERMINAL'] ?? '') !== 'true' ||
    ($native['DEMO_MODE'] ?? '') === 'yes') deny();
$sessionFile = $root . '/data/sessions/sess_' . $input['session_id'];
if (!is_file($sessionFile) || is_link($sessionFile)) deny();
session_name('HESTIASID');
session_save_path($root . '/data/sessions');
session_id($input['session_id']);
if (!@session_start(['read_and_close' => true])) deny();
$user = $_SESSION['user'] ?? '';
$look = $_SESSION['look'] ?? '';
$context = $_SESSION['userContext'] ?? '';
$last = $_SESSION['LAST_ACTIVITY'] ?? 0;
$timeout = $_SESSION['INACTIVE_SESSION_TIMEOUT'] ?? 0;
if (!is_string($user) || !is_string($look) || !in_array($context, ['admin', 'user'], true) ||
    !is_numeric($last) || !is_numeric($timeout) || (int)$last <= 0 || (int)$timeout <= 0 ||
    (int)$last > time() + 60 || (int)$last + (int)$timeout * 60 < time()) deny();
if (($native['DISABLE_IP_CHECK'] ?? 'no') !== 'yes' &&
    ($_SESSION['user_combined_ip'] ?? '') !== $input['remote_ip']) deny();
$actor = account($root, $user);
if ($context !== $actor['ROLE']) deny();
if ($look !== '') {
    if ($actor['ROLE'] !== 'admin') deny();
    if (($native['POLICY_SYSTEM_PROTECTED_ADMIN'] ?? '') === 'yes' &&
        $look === ($native['ROOT_USER'] ?? '')) deny();
    account($root, $look);
}
echo json_encode(['ok' => true, 'user' => $user, 'look' => $look], JSON_THROW_ON_ERROR), PHP_EOL;

