<?php
declare(strict_types=1);
$TAB='PROFESSIONAL';
include $_SERVER['DOCUMENT_ROOT'].'/inc/main.php';
require_once __DIR__.'/model.php';
define('HST_PRO_BUSINESS',true);
require_once __DIR__.'/business-client.php';
header('Cache-Control: no-store, private'); header('Pragma: no-cache');
header('Referrer-Policy: same-origin'); header('X-Content-Type-Options: nosniff');
header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
try {
    $identity=pro_identity($_SESSION,$user_data??[]);
    if ($identity['impersonating'] || ($_SESSION['VERSION']??'')!=='1.10.5' || ($user_data['LOGIN_DISABLED']??'no')==='yes') { throw new RuntimeException('Forbidden context'); }
} catch (Throwable $e) { http_response_code(403); exit('Acesse com a conta titular em uma versão homologada.'); }
$deployment=pro_snapshot(dirname(__DIR__,2).'/data/professional/deployment-status.json');
if (($deployment['state']??'')==='review-required') { http_response_code(503); exit('Implantação aguardando revisão.'); }
$method=$_SERVER['REQUEST_METHOD']??'GET';
if (!in_array($method,['GET','POST'],true)) { header('Allow: GET, POST'); http_response_code(405); exit; }
if ($method==='POST') {
    header('Content-Type: application/json; charset=utf-8');
    if (($read_only??false)===true || !is_string($_POST['token']??null) || empty($_SESSION['token']) || !hash_equals((string)$_SESSION['token'],$_POST['token'])) { http_response_code(403); exit('{"error":"Sessão expirada ou modo somente leitura."}'); }
    try {
        $raw=$_POST['request']??''; $op=$_POST['op']??'';
        if (!is_string($raw) || strlen($raw)>16384 || !is_string($op)) { throw new RuntimeException('Invalid request'); }
        if (!(json_decode($raw,false,16,JSON_THROW_ON_ERROR) instanceof stdClass)) { throw new RuntimeException('Invalid request'); }
        $request=json_decode($raw,true,16,JSON_THROW_ON_ERROR);
        $result=pro_business_call($identity['owner'],$op,$request);
        echo json_encode($result,JSON_HEX_TAG|JSON_HEX_AMP|JSON_HEX_APOS|JSON_HEX_QUOT|JSON_THROW_ON_ERROR);
    } catch (Throwable $e) { http_response_code(400); echo '{"error":"Operação recusada. Confira a delegação, a senha, um novo código A2F e o histórico. Se a configuração mudou, crie outro plano."}'; }
    unset($request,$raw,$_POST['request']); exit;
}
define('HST_PRO_BUSINESS_VIEW',true);
include __DIR__.'/business-view.php';
