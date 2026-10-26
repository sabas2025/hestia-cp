<?php
declare(strict_types=1);
if (!defined('HST_PRO_TOOLS')) { http_response_code(403); exit; }
function pro_tools_call(string $tool, string $actor, string $op, array $request): array {
    $allowed = ['editor'=>['domains','list','read','save','restore','history','files','download','rename','mkdir','upload-begin','upload-part','upload-commit','upload-cancel'], 'platform'=>['summary','docker','projects','backups','jobs']];
    if (!isset($allowed[$tool]) || !in_array($op,$allowed[$tool],true) || !preg_match('/\A[a-z][a-z0-9_]{1,29}\z/D',$actor)) { throw new RuntimeException('Invalid tool'); }
    $encoded = json_encode((object)$request,JSON_THROW_ON_ERROR);
    if (strlen($encoded)>2097152) { throw new RuntimeException('Request too large'); }
    $pipes=[];
    $process=proc_open(['/usr/bin/sudo','-n',HESTIA_DIR_BIN.'v-professional-'.$tool,$actor,$op],
        [0=>['pipe','r'],1=>['pipe','w'],2=>['file','/dev/null','w']],$pipes);
    if (!is_resource($process)) { throw new RuntimeException('Unavailable tool'); }
    // Pipes are nonblocking in both directions: large editor content must not deadlock.
    stream_set_blocking($pipes[0],false);stream_set_blocking($pipes[1],false);
    $offset=0;$output='';$started=microtime(true);$exit=-1;$inputOpen=true;
    while (true) {
        if ($inputOpen && $offset<strlen($encoded)) { $n=fwrite($pipes[0],substr($encoded,$offset,8192));if ($n===false) { proc_terminate($process,9);break; }$offset+=$n; }
        if ($inputOpen && $offset===strlen($encoded)) { fclose($pipes[0]);$inputOpen=false; }
        $output.=stream_get_contents($pipes[1]);$status=proc_get_status($process);
        if (!$status['running']) { $exit=$status['exitcode'];break; }
        if (microtime(true)-$started>50 || strlen($output)>2097152) { proc_terminate($process,9);break; }
        usleep(10000);
    }
    if ($inputOpen) { fclose($pipes[0]); }
    $output.=stream_get_contents($pipes[1]);fclose($pipes[1]);proc_close($process);
    if ($exit!==0 || strlen($output)>2097152) { throw new RuntimeException('Tool refused'); }
    $result=json_decode($output,true,32,JSON_THROW_ON_ERROR);
    if (!is_array($result)) { throw new RuntimeException('Invalid response'); }
    return $result;
}
