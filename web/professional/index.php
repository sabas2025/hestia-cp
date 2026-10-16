<?php
declare(strict_types=1);
$TAB = 'PROFESSIONAL';
include $_SERVER['DOCUMENT_ROOT'] . '/inc/main.php';
require_once __DIR__ . '/model.php';
header('Cache-Control: no-store, private');
header('Pragma: no-cache');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: same-origin');
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
if (($_SERVER['REQUEST_METHOD'] ?? 'GET') !== 'GET') {
    header('Allow: GET'); http_response_code(405); exit('Método não permitido.');
}
try {
    // main.php rechecks role, account existence and session against live data.
    $identity = pro_identity($_SESSION, $user_data ?? []);
    if (($_SESSION['VERSION'] ?? '') !== '1.10.5') {
        http_response_code(503); exit('Central em revisão para esta versão. Acesse /list/web/ para continuar no painel.');
    }
    $account = get_user_data($identity['owner'])[$identity['owner']] ?? [];
    if (($account['SUSPENDED'] ?? 'yes') !== 'no') { throw new RuntimeException('Suspended account'); }
    $payload = pro_payload($identity, $account, dirname(__DIR__, 2));
} catch (Throwable $error) {
    http_response_code(403); exit('Acesso não autorizado.');
}
if (($_GET['format'] ?? '') === 'json') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT | JSON_INVALID_UTF8_SUBSTITUTE);
    exit;
}
$displayName = $_SESSION['APP_NAME'] ?? 'Central de hospedagem';
define('HST_PRO_VIEW', true);
include __DIR__ . '/view.php';
