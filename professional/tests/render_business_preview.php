<?php
declare(strict_types=1);
require __DIR__.'/../../web/professional/model.php';
define('HST_PRO_BUSINESS_VIEW',true);
$_SESSION=['token'=>'PREVIEW_ONLY'];
$identity=['owner'=>'admin','admin'=>true];
include __DIR__.'/../../web/professional/business-view.php';
