<?php
declare(strict_types=1);
if (!defined('HST_PRO_MFA')) { http_response_code(403); exit; }
function pro_mfa_call(string $user, string $action, array $request): array {
    if (!preg_match('/\A[a-z][a-z0-9_]{1,29}\z/D', $user) || !in_array($action, ['prepare','enable','disable','recovery','verify','reauth'], true)) { throw new RuntimeException('Operação inválida.'); }
    if (array_diff(array_keys($request), ['password','code','binding'])) { throw new RuntimeException('Dados inválidos.'); }
    foreach ($request as $key=>$value) {
        if (!is_string($value) || strlen($value) > ['password'=>128,'code'=>40,'binding'=>64][$key]) { throw new RuntimeException('Dados inválidos.'); }
    }
    $encoded = json_encode($request, JSON_THROW_ON_ERROR);
    if (strlen($encoded) > 4096) { throw new RuntimeException('Dados inválidos.'); }
    $pipes = [];
    $process = proc_open(['/usr/bin/sudo', '-n', HESTIA_DIR_BIN . 'v-professional-mfa', $user, $action],
        [0=>['pipe','r'],1=>['pipe','w'],2=>['file','/dev/null','w']], $pipes);
    if (!is_resource($process)) { throw new RuntimeException('Serviço A2F indisponível.'); }
    fwrite($pipes[0], $encoded); fclose($pipes[0]);
    stream_set_blocking($pipes[1], false); $output = ''; $start = microtime(true); $exit = -1;
    while (true) {
        $output .= stream_get_contents($pipes[1]); $status = proc_get_status($process);
        if (!$status['running']) { $exit = $status['exitcode']; break; }
        if (microtime(true)-$start > 15 || strlen($output)>1048576) { proc_terminate($process,9); break; }
        usleep(10000);
    }
    $output .= stream_get_contents($pipes[1]); fclose($pipes[1]); proc_close($process);
    if ($exit !== 0 || strlen($output)>1048576) { throw new RuntimeException('Operação recusada. Confira senha, código, horário e aguarde antes de tentar novamente. Um código já usado não é aceito novamente.'); }
    if ($action === 'verify' && trim($output) === 'ok') { return ['state'=>'verified']; }
    $value = json_decode($output, true, 8, JSON_THROW_ON_ERROR);
    if (!is_array($value)) { throw new RuntimeException('Resposta inválida.'); }
    return $value;
}
