<?php
// Recovery codes are consumed only after password verification in the regular login.
header('Cache-Control: no-store');
header('Location: /login/');
exit;
