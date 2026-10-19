<?php
declare(strict_types=1);
// HESTIA_PROFESSIONAL_PRIVATE_TOTP_V1
if (PHP_SAPI !== 'cli') { http_response_code(403); exit; }
require_once __DIR__ . '/../vendor/autoload.php';
require_once __DIR__ . '/local-provider.php';
$secret = rtrim((string)fgets(STDIN, 256), "\r\n");
$token = rtrim((string)fgets(STDIN, 64), "\r\n");
if (!preg_match('/\A[A-Z2-7]{16,128}\z/D', $secret) || !preg_match('/\A[0-9]{6}\z/D', $token)) { exit(1); }
$tfa = new \RobThree\Auth\TwoFactorAuth(new HestiaLocalQrProvider(), 'Hestia Control Panel');
if ($tfa->verifyCode($secret, $token)) { echo 'ok'; exit(0); }
exit(1);
