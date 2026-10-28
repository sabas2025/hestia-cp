<?php
declare(strict_types=1);
require __DIR__ . '/../../web/professional/model.php';
define('HST_PRO_VIEW', true);
$displayName = 'Hestia Professional';
$_SESSION['token'] = 'PREVIEW_ONLY';
$identity = ['owner' => 'admin', 'admin' => true, 'impersonating' => false];
$payload = ['overlay_version' => json_decode(file_get_contents(__DIR__ . '/../component-policy.json'), true)['overlay_version'], 'resources' => [], 'file_manager' => false, 'twofa' => false, 'disk' => '1.240', 'disk_limit' => 'unlimited', 'last_backup' => null, 'last_drill' => null, 'job' => null,
  'health' => ['status' => 'ok', 'generated_at' => 'Dados ilustrativos para revisão visual', 'checks' => [
    ['name' => 'Disco', 'state' => 'ok', 'detail' => '28% utilizado'],
    ['name' => 'Nginx', 'state' => 'ok', 'detail' => 'Ativo'],
    ['name' => 'PHP-FPM 8.4', 'state' => 'ok', 'detail' => 'Ativo'],
    ['name' => 'MariaDB', 'state' => 'ok', 'detail' => 'Ativo'],
    ['name' => 'Certificado', 'state' => 'warning', 'detail' => 'Renovação em 18 dias'],
    ['name' => 'Inodes', 'state' => 'ok', 'detail' => '9% utilizado']]]];
foreach (['web' => 6, 'mail' => 2, 'db' => 4, 'backup' => 7, 'cron' => 3, 'dns' => 6] as $key => $count) $payload['resources'][$key] = ['count' => $count, 'enabled' => true];
require __DIR__.'/preview-layout-fixture.php';
include __DIR__ . '/../../web/professional/view.php';
