<?php
declare(strict_types=1);
if (!defined('HST_PRO_BUSINESS')) { http_response_code(403); exit; }
function pro_business_call(string $actor, string $op, array $request): array {
    if (!preg_match('/\A[a-z][a-z0-9_]{1,29}\z/D', $actor) || !in_array($op, ['plan','apply','rollback','history','diagnose','coverage'], true)) { throw new RuntimeException('Invalid operation'); }
    $encoded = json_encode($request, JSON_THROW_ON_ERROR);
    if (strlen($encoded)>16384) { throw new RuntimeException('Oversized request'); }
    $pipes = [];
    $process = proc_open(['/usr/bin/sudo','-n',HESTIA_DIR_BIN.'v-professional-business',$actor,$op],
        [0=>['pipe','r'],1=>['pipe','w'],2=>['file','/dev/null','w']],$pipes);
    if (!is_resource($process)) { throw new RuntimeException('Unavailable service'); }
    fwrite($pipes[0],$encoded); fclose($pipes[0]);
    stream_set_blocking($pipes[1],false); $output=''; $start=microtime(true); $exit=-1;
    while (true) {
        $output .= stream_get_contents($pipes[1]); $status=proc_get_status($process);
        if (!$status['running']) { $exit=$status['exitcode']; break; }
        if (microtime(true)-$start>55 || strlen($output)>1048576) { proc_terminate($process,9); break; }
        usleep(10000);
    }
    $output .= stream_get_contents($pipes[1]); fclose($pipes[1]); proc_close($process);
    if ($exit!==0 || strlen($output)>1048576) { throw new RuntimeException('Operation refused'); }
    $result=json_decode($output,true,24,JSON_THROW_ON_ERROR);
    if (!is_array($result)) { throw new RuntimeException('Invalid response'); }
    return $result;
}
