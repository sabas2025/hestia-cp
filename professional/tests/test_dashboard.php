<?php
declare(strict_types=1);
require __DIR__ . '/../../web/professional/model.php';
$checks = 0;
function expect(bool $condition, string $label): void {
    global $checks;
    $checks++;
    if (!$condition) { throw new RuntimeException($label); }
}
function denied(array $session, array $actual, string $label): void {
    $blocked = false;
    try { pro_identity($session, $actual); }
    catch (RuntimeException $error) { $blocked = true; }
    expect($blocked, $label);
}
$user = ['user' => 'clientone', 'userContext' => 'user', 'look' => '', 'ROOT_USER' => 'admin'];
$actual = ['ROLE' => 'user', 'SUSPENDED' => 'no'];
$identity = pro_identity($user, $actual);
expect($identity['owner'] === 'clientone' && !$identity['admin'], 'Own scope');
denied([], $actual, 'Anonymous');
denied(array_replace($user, ['look' => 'clienttwo']), $actual, 'Cross-account scope');
denied(array_replace($user, ['userContext' => 'admin']), $actual, 'Forged admin role');
denied($user, ['ROLE' => 'user', 'SUSPENDED' => 'yes'], 'Suspended account');
denied(array_replace($user, ['user' => '../admin']), $actual, 'Path traversal');
denied(array_replace($user, ['userContext' => 'unknown']), $actual, 'Unknown context');
$admin = array_replace($user, ['user' => 'admin', 'userContext' => 'admin']);
$adminActual = ['ROLE' => 'admin', 'SUSPENDED' => 'no'];
expect(pro_identity($admin, $adminActual)['admin'], 'Current administrator');
$impersonated = pro_identity(array_replace($admin, ['look' => 'clienttwo']), $adminActual);
expect($impersonated['owner'] === 'clienttwo' && !$impersonated['admin'], 'Impersonation uses client scope');
denied(array_replace($admin, ['look' => 'admin', 'POLICY_SYSTEM_PROTECTED_ADMIN' => 'yes']), $adminActual, 'Protected administrator');
denied($admin, ['ROLE' => 'user', 'SUSPENDED' => 'no'], 'Admin demoted while session active');
$blocked = false;
try { pro_native('v-delete-user', 'clientone'); } catch (RuntimeException $error) { $blocked = true; }
expect($blocked, 'No arbitrary commands');
$blocked = false;
try { pro_native('v-list-web-domains', '../admin'); } catch (RuntimeException $error) { $blocked = true; }
expect($blocked, 'No traversal in native command');

$root = sys_get_temp_dir() . '/pro-dashboard-test-' . bin2hex(random_bytes(5));
mkdir($root . '/data/professional/jobs', 0700, true);
mkdir($root . '/data/professional/backups', 0700, true);
file_put_contents($root . '/data/professional/health.json', json_encode(['status' => 'ok', 'generated_at' => gmdate('c'), 'private' => 'ADMIN_ONLY']));
file_put_contents($root . '/data/professional/jobs/clientone.json', json_encode(['user' => 'clienttwo', 'state' => 'running', 'private' => 'OTHER_USER']));
$account = ['WEB_DOMAINS' => '10', 'MAIL_DOMAINS' => '0', 'DNS_DOMAINS' => '0', 'DATABASES' => '2', 'CRON_JOBS' => '1', 'BACKUPS' => '1', 'TWOFA' => 'RECOVERY_SECRET', 'PASSWORD' => 'HASH_SECRET', 'U_DISK' => '340'];
$calls = [];
$runner = function (string $command, string $owner) use (&$calls): array {
    $calls[] = [$command, $owner]; return ['one' => []];
};
$payload = pro_payload($identity, $account, $root, $runner);
expect($payload['health'] === null, 'Client receives no global server data');
expect($payload['job'] === null, 'Wrong-owner task rejected');
expect($payload['resources']['web']['count'] === 1, 'Resource count');
expect($payload['resources']['mail']['enabled'] === false, 'Unavailable resource');
expect(count($calls) === 4, 'Disabled resources never queried');
expect(count(array_filter($calls, fn($call) => $call[1] !== 'clientone')) === 0, 'All commands scoped to owner');
expect($payload['twofa'] === true, 'Boolean 2FA status');
expect(!str_contains(json_encode($payload), 'RECOVERY_SECRET'), 'No 2FA recovery code');
expect(!str_contains(json_encode($payload), 'HASH_SECRET'), 'No password hashes');
expect(!str_contains(json_encode($payload), 'ADMIN_ONLY'), 'No global data leaks');
$adminPayload = pro_payload(pro_identity($admin, $adminActual), $account, $root, $runner);
expect($adminPayload['health']['private'] === 'ADMIN_ONLY', 'Admin sees snapshot');
file_put_contents($root . '/data/professional/health.json', json_encode(['status' => 'ok', 'generated_at' => '2000-01-01T00:00:00Z']));
$adminPayload = pro_payload(pro_identity($admin, $adminActual), $account, $root, $runner);
expect($adminPayload['health']['status'] === 'Coleta desatualizada', 'Stale health is not presented as current');
expect(pro_snapshot($root . '/absent.json') === null, 'Missing snapshot');
file_put_contents($root . '/malformed.json', '{broken');
expect(pro_snapshot($root . '/malformed.json') === null, 'Corrupt snapshot');
symlink($root . '/malformed.json', $root . '/symlink.json');
expect(pro_snapshot($root . '/symlink.json') === null, 'Symlink snapshot rejected');
expect(pro_escape('<script>"&') === '&lt;script&gt;&quot;&amp;', 'HTML escaped');
file_put_contents($root . '/data/professional/projects.json', json_encode(['projects' => [
    ['id' => 'my-node', 'type' => 'node', 'owner' => 'clientone', 'url' => 'https://node.example.org'],
    ['id' => 'other-node', 'type' => 'node', 'owner' => 'clienttwo', 'url' => 'https://private.example.org'],
    ['id' => 'docker-admin', 'type' => 'docker-ui', 'owner' => 'clientone', 'url' => 'https://docker.example.org'],
    ['id' => 'bad-script', 'type' => 'editor', 'owner' => 'clientone', 'url' => 'javascript:alert(1)'],
    ['id' => 'token-link', 'type' => 'editor', 'owner' => 'clientone', 'url' => 'https://editor.example.org/?token=SECRET'],
]]));
$clientProjects = pro_payload($identity, $account, $root, $runner)['projects'];
expect(count($clientProjects) === 1 && $clientProjects[0]['id'] === 'my-node', 'Client project isolation and unsafe URLs blocked');
$lookProjects = pro_payload($impersonated, $account, $root, $runner)['projects'];
expect(count($lookProjects) === 1 && $lookProjects[0]['id'] === 'other-node', 'Impersonation has no global Docker access');
file_put_contents($root . '/data/professional/backups/clientone-forged-run.json', json_encode(['user' => 'clienttwo', 'id' => 'other', 'provider' => 'private']));
expect(pro_payload($identity, $account, $root, $runner)['cloud_targets'] === [], 'Wrong-owner cloud snapshot rejected');
file_put_contents($root . '/data/professional/backups/clientone-main-copy-run.json', json_encode(['user'=>'clientone','id'=>'main-copy','provider'=>'google-drive','state'=>'succeeded','completed_at'=>'2026-10-18T10:00:00Z']));
file_put_contents($root . '/data/professional/backups/clientone-main-copy-attempt.json', json_encode(['user'=>'clientone','id'=>'main-copy','provider'=>'google-drive','state'=>'failed','attempted_at'=>'2026-10-19T10:00:00Z']));
$targets = pro_payload($identity, $account, $root, $runner)['cloud_targets'];
expect($targets[0]['last_success'] === '2026-10-18T10:00:00Z', 'Previous successful copy is retained');
expect($targets[0]['last_attempt_state'] === 'failed', 'Most recent failed attempt is visible');
$iterator = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST);
foreach ($iterator as $file) { $file->isDir() && !$file->isLink() ? rmdir($file->getPathname()) : unlink($file->getPathname()); }
rmdir($root);
echo json_encode(['checks' => $checks, 'status' => 'passed'], JSON_PRETTY_PRINT) . PHP_EOL;
