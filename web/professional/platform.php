<?php
declare(strict_types=1);
$TAB='PROFESSIONAL';include $_SERVER['DOCUMENT_ROOT'].'/inc/main.php';require_once __DIR__.'/model.php';
define('HST_PRO_TOOLS',true);require_once __DIR__.'/tools-client.php';
define('HST_PRO_BUSINESS',true);require_once __DIR__.'/business-client.php';
header('Cache-Control: no-store, private');header('Referrer-Policy: no-referrer');header('X-Content-Type-Options: nosniff');
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
try {
    $identity=pro_identity($_SESSION,$user_data??[]);
    if (!$identity['admin'] || $identity['impersonating'] || ($_SESSION['VERSION']??'')!=='1.10.5' || ($user_data['LOGIN_DISABLED']??'no')==='yes') { throw new RuntimeException(); }
} catch (Throwable $e) { http_response_code(403);exit('Acesse com sua própria conta administrativa.'); }
$method=$_SERVER['REQUEST_METHOD']??'GET';
if (!in_array($method,['GET','POST'],true)) { header('Allow: GET, POST');http_response_code(405);exit; }
if ($method==='POST') {
    header('Content-Type: application/json; charset=utf-8');
    if (($read_only??false)===true || !is_string($_POST['token']??null) || empty($_SESSION['token']) || !hash_equals((string)$_SESSION['token'],$_POST['token'])) { http_response_code(403);exit('{"error":"Sessão expirada ou modo somente leitura."}'); }
    try {
        $raw=$_POST['request']??'';$op=$_POST['op']??'';
        if (!is_string($raw) || strlen($raw)>16384 || !is_string($op) || !(json_decode($raw,false,24,JSON_THROW_ON_ERROR) instanceof stdClass)) { throw new RuntimeException(); }
        $request=json_decode($raw,true,24,JSON_THROW_ON_ERROR);
        if (in_array($op,['plan','apply','history'],true)) {
            if ($op==='plan' && !in_array($request['action']??'', ['protection-profile','docker-operation','project-operation','cloud-operation','native-backup'],true)) { throw new RuntimeException(); }
            $result=pro_business_call($identity['owner'],$op,$request);
        } else { $result=pro_tools_call('platform',$identity['owner'],$op,$request); }
        echo json_encode($result,JSON_HEX_TAG|JSON_HEX_AMP|JSON_HEX_APOS|JSON_HEX_QUOT|JSON_THROW_ON_ERROR);
    } catch (Throwable $e) { http_response_code(400);echo '{"error":"Operação recusada. Confira dependências, projeto/destino cadastrado, propriedade, integridade e A2F. Nenhuma credencial é incluída no histórico."}'; }
    unset($raw,$request,$_POST['request']);exit;
}
define('HST_PRO_PLATFORM_VIEW',true);include __DIR__.'/platform-view.php';
