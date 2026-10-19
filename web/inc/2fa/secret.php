<?php

use RobThree\Auth\TwoFactorAuth;

if (PHP_SAPI !== 'cli') { http_response_code(403); exit; }
require_once __DIR__ . "/../vendor/autoload.php";
require_once __DIR__ . '/local-provider.php';
$tfa = new TwoFactorAuth(new HestiaLocalQrProvider(), "Hestia Control Panel");

$secret = $tfa->createSecret(160); // Though the default is an 80 bits secret (for backwards compatibility reasons) we recommend creating 160+ bits secrets (see RFC 4226 - Algorithm Requirements)
$qrcode = $tfa->getQRCodeImageAsDataUri(gethostname(), $secret);

echo $secret . "-" . $qrcode;
