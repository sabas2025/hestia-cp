<?php
// Synthetic account metadata for rendering only; no Hestia process is called.
$identity ??= ['owner' => 'admin', 'admin' => true, 'impersonating' => false];
$_SESSION = array_replace([
    'APP_NAME' => 'Hestia Control Panel', 'VERSION' => '1.10.5',
    'THEME' => getenv('PREVIEW_THEME') ?: 'default',
    'WEB_SYSTEM' => 'apache2', 'DNS_SYSTEM' => 'bind9', 'MAIL_SYSTEM' => 'exim4',
    'DB_SYSTEM' => 'mysql', 'CRON_SYSTEM' => 'cron', 'BACKUP_SYSTEM' => 'local',
], $_SESSION ?? []);
function get_user_data($owner): array
{
    return [$owner => [
        'U_USERS' => '2', 'USERS' => 'unlimited', 'U_WEB_DOMAINS' => '6', 'WEB_DOMAINS' => 'unlimited',
        'U_DNS_DOMAINS' => '6', 'DNS_DOMAINS' => 'unlimited', 'U_MAIL_DOMAINS' => '2', 'MAIL_DOMAINS' => 'unlimited',
        'U_DATABASES' => '4', 'DATABASES' => 'unlimited', 'U_CRON_JOBS' => '3', 'CRON_JOBS' => 'unlimited',
        'U_BACKUPS' => '7', 'BACKUPS' => '10', 'U_DISK' => '1240', 'DISK_QUOTA' => 'unlimited',
        'U_BANDWIDTH' => '680', 'BANDWIDTH' => 'unlimited',
    ]];
}
