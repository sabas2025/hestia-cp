<?php
declare(strict_types=1);
require __DIR__.'/../../web/professional/model.php';
$_SESSION=['token'=>'PREVIEW_ONLY'];$identity=['owner'=>'admin','admin'=>true];
require __DIR__.'/preview-layout-fixture.php';
$tool=$argv[1]??'';
if ($tool==='editor') { define('HST_PRO_EDITOR_VIEW',true);include __DIR__.'/../../web/professional/editor-view.php'; }
elseif ($tool==='platform') { define('HST_PRO_PLATFORM_VIEW',true);include __DIR__.'/../../web/professional/platform-view.php'; }
else { exit(1); }
