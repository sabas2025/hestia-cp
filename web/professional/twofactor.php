<?php
declare(strict_types=1);
$TAB = 'PROFESSIONAL';
include $_SERVER['DOCUMENT_ROOT'] . '/inc/main.php';
require_once __DIR__ . '/model.php';
define('HST_PRO_MFA', true);
require_once __DIR__ . '/mfa-client.php';
header('Cache-Control: no-store, private'); header('Pragma: no-cache');
header('Referrer-Policy: same-origin'); header('X-Content-Type-Options: nosniff');
header("Content-Security-Policy: default-src 'self'; script-src 'none'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
try {
    $identity = pro_identity($_SESSION, $user_data ?? []);
    if ($identity['impersonating'] || ($_SESSION['VERSION'] ?? '') !== '1.10.5') { throw new RuntimeException('Acesse com a conta titular em uma versão homologada.'); }
} catch (Throwable $e) { http_response_code(403); exit('Acesso exclusivo da conta titular.'); }
$result = []; $error = '';
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if (!in_array($method, ['GET','POST'], true)) { header('Allow: GET, POST'); http_response_code(405); exit; }
if ($method === 'POST') {
    if (!isset($_POST['token']) || !is_string($_POST['token']) || !hash_equals((string)($_SESSION['token'] ?? ''), $_POST['token']) || empty($_SESSION['token'])) { http_response_code(403); exit('Sessão expirada.'); }
    if (($read_only ?? false) === true) { http_response_code(403); exit('Modo somente leitura.'); }
    try {
        $action = $_POST['action'] ?? '';
        $password = $_POST['password'] ?? ''; $code = $_POST['code'] ?? '';
        if (!is_string($action) || !is_string($password) || !is_string($code) || strlen($password)>128 || strlen($code)>40) { throw new RuntimeException('Dados inválidos.'); }
        if (!in_array($action, ['prepare','enable','disable','recovery'], true)) { throw new RuntimeException('Operação inválida.'); }
        $result = pro_mfa_call($identity['owner'], $action, ['password'=>$password, 'code'=>$code, 'binding'=>hash('sha256', $_SESSION['token'])]);
    } catch (Throwable $e) { $error = 'Operação recusada. Confira senha/código e aguarde um novo código antes de tentar novamente.'; }
    unset($_POST['password'], $_POST['code'], $password, $code);
}
$account = get_user_data($identity['owner'])[$identity['owner']] ?? [];
$enabled = !empty($account['TWOFA']);
define('HST_PRO_MFA_VIEW', true);
include __DIR__ . '/twofactor-view.php';
