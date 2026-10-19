<?php
declare(strict_types=1);
require __DIR__ . '/../../web/professional/model.php';
define('HST_PRO_MFA_VIEW', true);
$_SESSION = ['token'=>'PREVIEW_ONLY'];
$enabled = false; $result = []; $error = '';
include __DIR__ . '/../../web/professional/twofactor-view.php';
