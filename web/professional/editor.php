<?php
declare(strict_types=1);
$TAB='PROFESSIONAL';include $_SERVER['DOCUMENT_ROOT'].'/inc/main.php';require_once __DIR__.'/model.php';
define('HST_PRO_TOOLS',true);require_once __DIR__.'/tools-client.php';
header('Cache-Control: no-store, private');header('Referrer-Policy: same-origin');header('X-Content-Type-Options: nosniff');
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
try {
    $identity=pro_identity($_SESSION,$user_data??[]);
    if ($identity['impersonating'] || ($_SESSION['VERSION']??'')!=='1.10.5' || ($user_data['LOGIN_DISABLED']??'no')==='yes') { throw new RuntimeException(); }
} catch (Throwable $e) { http_response_code(403);exit('Acesse com sua própria conta.'); }
$method=$_SERVER['REQUEST_METHOD']??'GET';
if (!in_array($method,['GET','POST'],true)) { header('Allow: GET, POST');http_response_code(405);exit; }
if ($method==='POST') {
    header('Content-Type: application/json; charset=utf-8');
    if (($read_only??false)===true || !is_string($_POST['token']??null) || empty($_SESSION['token']) || !hash_equals((string)$_SESSION['token'],$_POST['token'])) { http_response_code(403);exit('{"error":"Sessão expirada ou modo somente leitura."}'); }
    try {
        $raw=$_POST['request']??'';$op=$_POST['op']??'';
        if (!is_string($raw) || strlen($raw)>2097152 || !is_string($op) || !(json_decode($raw,false,32,JSON_THROW_ON_ERROR) instanceof stdClass)) { throw new RuntimeException(); }
        $request=json_decode($raw,true,32,JSON_THROW_ON_ERROR);
        if (!$identity['admin'] && isset($request['owner']) && $request['owner']!==$identity['owner']) { throw new RuntimeException(); }
        echo json_encode(pro_tools_call('editor',$identity['owner'],$op,$request),JSON_HEX_TAG|JSON_HEX_AMP|JSON_HEX_APOS|JSON_HEX_QUOT|JSON_THROW_ON_ERROR);
    } catch (Throwable $e) { http_response_code(400);echo '{"error":"Operação recusada. Confira proprietário, caminho, alteração concorrente, sintaxe e A2F. Recarregue o arquivo antes de tentar novamente."}'; }
    unset($raw,$request,$_POST['request']);exit;
}
define('HST_PRO_EDITOR_VIEW',true);include __DIR__.'/editor-view.php';
