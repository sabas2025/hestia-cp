<?php
declare(strict_types=1);
if (PHP_SAPI !== 'cli') { http_response_code(403); exit; }
// HESTIA_PROFESSIONAL_LOCAL_QR_V1 — no external provider, network request or secret argument.
final class HestiaLocalQrProvider implements \RobThree\Auth\Providers\Qr\IQRCodeProvider {
    public function getMimeType(): string { return 'image/svg+xml'; }
    public function getQRCodeImage(string $qrText, int $size): string {
        $pipes = [];
        $process = proc_open(['/usr/bin/python3', dirname(__DIR__, 3) . '/professional/qr.py'],
            [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes,
            null, ['PATH' => '/usr/bin:/bin', 'LANG' => 'C.UTF-8']);
        if (!is_resource($process)) { throw new RuntimeException('Offline QR renderer unavailable'); }
        fwrite($pipes[0], $qrText); fclose($pipes[0]);
        stream_set_blocking($pipes[1], false); $output = ''; $start = microtime(true); $exit = -1;
        while (true) {
            $output .= stream_get_contents($pipes[1]); $status = proc_get_status($process);
            if (!$status['running']) { $exit = $status['exitcode']; break; }
            if (microtime(true) - $start > 10 || strlen($output) > 1048576) { proc_terminate($process, 9); break; }
            usleep(10000);
        }
        $output .= stream_get_contents($pipes[1]); fclose($pipes[1]); proc_close($process);
        if ($exit !== 0 || strlen($output) > 1048576 || !str_contains($output, '<svg')) {
            throw new RuntimeException('Offline QR renderer unavailable; install python3-qrcode');
        }
        return $output;
    }
}
