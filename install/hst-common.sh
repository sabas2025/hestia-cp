#!/bin/bash
# Local professional overlay, GPL-3.0. No code in this file runs when sourced.

hst_fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

hst_usage() {
    cat <<'HELP'
HestiaCP Professional — local bundle, PHP 8.4 default
  bash install/hst-install.sh --preflight       # read-only, default
  bash install/hst-install.sh --apply [options] # fresh OS only
  --interactive yes|no --hostname FQDN --email EMAIL --username USER
  --password-file ABSOLUTE_PATH | --password-fd DESCRIPTOR
  --apache --phpfpm --vsftpd --proftpd --named --mysql --mysql8
  --postgresql --exim --dovecot --sieve --clamav --spamassassin
  --iptables --fail2ban --quota --resourcelimit --webterminal --api (yes|no)
  --multiphp no|yes|8.2,8.3,8.4,8.5 --port PORT --lang LANGUAGE
  --with-debs DIRECTORY --allow-missing-netplan
--force and plaintext --password are deliberately rejected.
No install script is fetched or executed remotely by the launcher.
HELP
}

hst_parse() {
    HST_APPLY=no; HST_HELP=no; HST_NETPLAN=no; HST_PASS_FILE=''; HST_PASS_FD=''
    interactive=yes; port=8083; lang=pt-br
    while (($#)); do
        case "$1" in
            --apply) HST_APPLY=yes; shift; continue ;;
            --preflight|--dry-run) HST_APPLY=no; shift; continue ;;
            --help|-h) HST_HELP=yes; shift; continue ;;
            --allow-missing-netplan) HST_NETPLAN=yes; shift; continue ;;
            --force|-f) hst_fail 'Force cannot bypass fresh-OS checks. Use a separate migration.' ;;
            --password|-p) hst_fail 'Plaintext argv password rejected; use --password-file or --password-fd.' ;;
        esac
        (($# >= 2)) || hst_fail "Missing value for $1"
        [[ $2 != --* ]] || hst_fail "Missing value for $1"
        local key
        case "$1" in
            --apache|-a) key=apache ;; --phpfpm|-w) key=phpfpm ;;
            --multiphp|-o) key=multiphp ;; --vsftpd|-v) key=vsftpd ;;
            --proftpd|-j) key=proftpd ;; --named|-k) key=named ;;
            --mysql|--mariadb|-m) key=mysql ;; --mysql8|--mysql-classic|-M) key=mysql8 ;;
            --postgresql|-g) key=postgresql ;; --exim|-x) key=exim ;;
            --dovecot|-z) key=dovecot ;; --sieve|-Z) key=sieve ;;
            --clamav|-c) key=clamd ;; --spamassassin|-t) key=spamd ;;
            --iptables|-i) key=iptables ;; --fail2ban|-b) key=fail2ban ;;
            --quota|-q) key=quota ;; --resourcelimit|-L) key=resourcelimit ;;
            --webterminal|-W) key=webterminal ;; --api|-d) key=api ;;
            --interactive|-y) key=interactive ;; --port|-r) key=port ;;
            --lang|-l) key=lang ;; --hostname|-s) key=servername ;;
            --email|-e) key=email ;; --username|-u) key=username ;;
            --with-debs|-D) key=withdebs ;;
            --password-file) key=HST_PASS_FILE ;; --password-fd) key=HST_PASS_FD ;;
            *) hst_fail "Unknown option or positional argument: $1" ;;
        esac
        printf -v "$key" '%s' "$2"
        shift 2
    done
    [[ $HST_HELP == no ]] || { hst_usage; exit 0; }
    local key value
    for key in apache phpfpm vsftpd proftpd named mysql mysql8 postgresql exim dovecot sieve clamd spamd iptables fail2ban quota resourcelimit webterminal api interactive; do
        value=${!key-}
        [[ -z $value || $value == yes || $value == no ]] || hst_fail "$key must be yes or no"
    done
    if [[ ! $port =~ ^[0-9]{1,5}$ ]] || ((10#$port < 1 || 10#$port > 65535)); then hst_fail 'Port must be between 1 and 65535'; fi
    port=$((10#$port))
    [[ $lang =~ ^[a-z]{2}(-[a-z]{2})?$ ]] || hst_fail 'Invalid language code'
    [[ -z $HST_PASS_FILE || -z $HST_PASS_FD ]] || hst_fail 'Choose one password source'
    [[ -z $HST_PASS_FD || $HST_PASS_FD =~ ^[0-9]{1,3}$ ]] || hst_fail 'Invalid password descriptor'
    [[ -z ${servername-} ]] || hst_hostname_valid "$servername" || hst_fail 'Invalid hostname'
    [[ -z ${username-} ]] || hst_username_valid "$username" || hst_fail 'Invalid or reserved username'
    [[ -z ${email-} ]] || hst_email_valid "$email" || hst_fail 'Invalid email'
    if [[ -n ${multiphp-} && $multiphp != no && $multiphp != yes ]]; then
        [[ $multiphp =~ ^8\.[2345](,8\.[2345])*$ ]] || hst_fail 'Only PHP 8.2, 8.3, 8.4 and 8.5 are allowed'
    fi
    [[ -z ${withdebs-} || $withdebs == /* && -d $withdebs && ! -L $withdebs ]] || hst_fail 'Local deb directory must be an absolute, real directory'
}

hst_hostname_valid() {
    local name=$1 label
    [[ ${#name} -le 253 && $name == *.* && $name != *..* && $name != .* && $name != *. && ! $name =~ ^[0-9.]+$ ]] || return 1
    local -a labels
    IFS=. read -r -a labels <<< "$name"
    for label in "${labels[@]}"; do
        [[ ${#label} -le 63 && $label =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$ ]] || return 1
    done
}
hst_username_valid() {
    [[ $1 =~ ^[a-z][a-z0-9_]{1,29}$ ]] || return 1
    case "$1" in root|sudo|mysql|hestiaweb|hestiamail|hestia-users|aria|aria_log|mysql_upgrade|ib|ib_buffer|ddl|ddl_recovery|performance) return 1 ;; esac
}
hst_email_valid() { [[ $1 =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$ ]]; }
hst_password_valid() {
    [[ ${#1} -ge 14 && ${#1} -le 128 && $1 != *$'\n'* && $1 != *$'\r'* && $1 != /tmp/* && $1 != *:* && $1 =~ [A-Z] && $1 =~ [a-z] && $1 =~ [0-9] ]]
}

# Parse without sourcing arbitrary shell content from os-release.
hst_os_detect() {
    local file=${1:-/etc/os-release} key value
    HST_OS=; HST_RELEASE=; HST_CODENAME=
    [[ -r $file ]] || return 1
    while IFS='=' read -r key value; do
        value=${value%\"}; value=${value#\"}; value=${value%\'}; value=${value#\'}
        case "$key" in ID) HST_OS=$value ;; VERSION_ID) HST_RELEASE=$value ;; VERSION_CODENAME) HST_CODENAME=$value ;; esac
    done < "$file"
    case "$HST_OS:$HST_RELEASE" in debian:12|debian:13|ubuntu:22.04|ubuntu:24.04|ubuntu:26.04) return 0 ;; *) return 1 ;; esac
}

hst_preflight() {
    local root=${1:-/} failed=0 p state
    printf 'HestiaCP Professional 1.0 — inspection only\n'
    if hst_os_detect "${root%/}/etc/os-release"; then
        printf 'OS: %s %s\n' "$HST_OS" "$HST_RELEASE"
    else printf 'BLOCK: unsupported OS\n'; failed=1; fi
    case "$(uname -m)" in x86_64|aarch64) ;; *) printf 'BLOCK: unsupported CPU architecture\n'; failed=1 ;; esac
    for p in usr/local/hestia usr/local/CyberCP usr/local/lsws www/server/panel usr/local/cpanel usr/local/psa; do
        if [[ -e ${root%/}/$p ]]; then printf 'BLOCK: existing panel or stack: /%s\n' "$p"; failed=1; fi
    done
    if [[ -d ${root%/}/var/lib/mysql ]] && [[ -n $(find "${root%/}/var/lib/mysql" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null) ]]; then
        printf 'BLOCK: existing MySQL data\n'; failed=1
    fi
    if [[ $root == / ]] && command -v dpkg-query >/dev/null; then
        for p in nginx apache2 mariadb-server mysql-server postfix exim4 dovecot-core; do
            state=$(dpkg-query -W -f='${db:Status-Status}' "$p" 2>/dev/null)
            if [[ $state == installed ]]; then printf 'BLOCK: conflicting package: %s\n' "$p"; failed=1; fi
        done
        if command -v ss >/dev/null && ss -H -ltn | awk '{print $4}' | grep -Eq ':(80|443|8083)$'; then
            printf 'BLOCK: web/panel port already listening\n'; failed=1
        fi
        local available memory
        available=$(df -Pk / | awk 'NR==2 {print $4}')
        memory=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
        printf 'Available root KiB: %s; RAM KiB: %s\n' "$available" "$memory"
        [[ $available =~ ^[0-9]+$ && $available -ge 10485760 ]] || { printf 'BLOCK: at least 10 GiB free required\n'; failed=1; }
        [[ $memory =~ ^[0-9]+$ && $memory -ge 1000000 ]] || { printf 'BLOCK: at least 1 GB RAM required\n'; failed=1; }
    fi
    printf 'PHP default: 8.4; destination panel port: %s\n' "${port:-8083}"
    printf 'Inspection result: %s\n' "$([[ $failed == 0 ]] && printf PASS || printf BLOCKED)"
    return "$failed"
}

hst_credentials() {
    if [[ $interactive == no ]]; then
        [[ -n ${username-} && -n ${servername-} && -n ${email-} ]] || hst_fail 'Non-interactive mode requires username, hostname and email'
        [[ -n $HST_PASS_FILE || -n $HST_PASS_FD ]] || hst_fail 'Non-interactive mode requires password-file or password-fd'
    else
        if [[ -z ${username-} ]]; then IFS= read -r -p 'Administrator username: ' username || hst_fail 'Input closed'; fi
        if [[ -z ${servername-} ]]; then IFS= read -r -p 'FQDN hostname: ' servername || hst_fail 'Input closed'; fi
        if [[ -z ${email-} ]]; then IFS= read -r -p 'Administrator email: ' email || hst_fail 'Input closed'; fi
    fi
    hst_username_valid "$username" || hst_fail 'Invalid username'
    hst_hostname_valid "$servername" || hst_fail 'Invalid hostname'
    hst_email_valid "$email" || hst_fail 'Invalid email'
    getent passwd "$username" >/dev/null && hst_fail 'Username already exists'
    getent group "$username" >/dev/null && hst_fail 'Group already exists'
    if [[ -n $HST_PASS_FILE ]]; then
        [[ $HST_PASS_FILE == /* && -f $HST_PASS_FILE && ! -L $HST_PASS_FILE ]] || hst_fail 'Password file must be an absolute regular non-symlink file'
        [[ $(stat -c %u "$HST_PASS_FILE") == 0 ]] || hst_fail 'Password file must be root owned'
        local mode; mode=$(stat -c %a "$HST_PASS_FILE")
        (( (8#$mode & 077) == 0 )) || hst_fail 'Password file must not allow group/other access'
        (( $(stat -c %s "$HST_PASS_FILE") <= 130 )) || hst_fail 'Password file too large'
        vpass=$(< "$HST_PASS_FILE")
    elif [[ -n $HST_PASS_FD ]]; then
        IFS= read -r -u "$HST_PASS_FD" vpass || [[ -n $vpass ]] || hst_fail 'Empty or unreadable password descriptor'
    else
        local confirm
        IFS= read -r -s -p 'Administrator password (14+ characters): ' vpass || hst_fail 'Input closed'
        printf '\n'
        IFS= read -r -s -p 'Confirm password: ' confirm || hst_fail 'Input closed'
        printf '\n'
        [[ $vpass == "$confirm" ]] || hst_fail 'Passwords do not match'
        unset confirm
    fi
    hst_password_valid "$vpass" || hst_fail 'Password: 14–128 chars, upper/lowercase and digit; no colon, newline or /tmp/ prefix'
}

hst_cleanup() {
    local status=$? keep_stage=no
    trap - EXIT INT TERM HUP
    if [[ ${HST_POLICY_ACTIVE:-no} == yes ]]; then
        if ! hst_restore_policy; then status=1; keep_stage=yes; printf 'Policy recovery failed; original retained in %s\n' "$HST_STAGE_DIR" >&2; fi
    fi
    if [[ -n ${HST_STAGE_DIR:-} && -d $HST_STAGE_DIR && -O $HST_STAGE_DIR ]]; then
        rm -f -- "$HST_STAGE_DIR/admin-password" "$HST_STAGE_DIR/mysql-password" "$HST_STAGE_DIR/pgsql-password"
        [[ $keep_stage == yes ]] || rm -rf -- "$HST_STAGE_DIR"
    fi
    unset vpass
    if [[ $status != 0 ]]; then printf 'Installation stopped (status %s). Check the restricted log; no automatic rollback was attempted.\n' "$status" >&2; fi
    exit "$status"
}
hst_begin() {
    [[ $(id -u) == 0 ]] || hst_fail 'Run installation as root'
    umask 077
    command -v flock >/dev/null || hst_fail 'flock is required'
    [[ ! -L /run/hestia-professional ]] || hst_fail 'Install lock directory is a symlink'
    mkdir -p /run/hestia-professional || hst_fail 'Cannot create install lock directory'
    [[ $(stat -c %u /run/hestia-professional) == 0 ]] || hst_fail 'Unexpected lock directory owner'
    chmod 700 /run/hestia-professional || hst_fail 'Cannot protect lock directory'
    [[ ! -L /run/hestia-professional/install.lock ]] || hst_fail 'Install lock is a symlink'
    exec 9>/run/hestia-professional/install.lock || hst_fail 'Cannot open install lock'
    flock -n 9 || hst_fail 'Another installation is running'
    HST_STAGE_DIR=$(mktemp -d /tmp/hestia-install.XXXXXXXX) || hst_fail 'Cannot create private workspace'
    chmod 700 "$HST_STAGE_DIR" || hst_fail 'Cannot protect workspace'
    trap hst_cleanup EXIT
    trap 'exit 130' INT; trap 'exit 143' TERM; trap 'exit 129' HUP
    mkdir -p /root/hst_install_backups || hst_fail 'Cannot create log folder'
    HST_RUN_ID=$(date -u +%Y%m%dT%H%M%SZ)-$$
    LOG=/root/hst_install_backups/hst_install-"$HST_RUN_ID".log
    : > "$LOG" || hst_fail 'Cannot create log'; chmod 600 "$LOG"
    printf '%s installation started, source c14350f40c71b71f36e3945e42607d7d9c4980eb\n' "$HST_RUN_ID" >> "$LOG"
    # Services need readable non-secret configuration files; secrets stay inside
    # the private workspace and are explicitly created with mode 0600.
    umask 022
}
hst_run() {
    local label=$1 status; shift
    printf '[ * ] %s\n' "$label"
    printf '%s START %s\n' "$(date -u +%FT%TZ)" "$label" >> "$LOG"
    "$@" >> "$LOG" 2>&1; status=$?
    printf '%s END %s status=%s\n' "$(date -u +%FT%TZ)" "$label" "$status" >> "$LOG"
    [[ $status == 0 ]] || { printf 'ERROR: %s failed (status %s); see %s\n' "$label" "$status" "$LOG" >&2; exit "$status"; }
}
hst_policy_block() {
    local policy=${1:-/usr/sbin/policy-rc.d}
    HST_POLICY_PATH=$policy; HST_POLICY_PREVIOUS=no
    [[ ! -L $policy ]] || hst_fail 'policy-rc.d is a symlink'
    if [[ -e $policy ]]; then cp -p -- "$policy" "$HST_STAGE_DIR/policy-rc.d.original" || hst_fail 'Cannot preserve policy'; HST_POLICY_PREVIOUS=yes; fi
    HST_POLICY_ACTIVE=yes
    printf '#!/bin/sh\nexit 101\n' > "$policy" || hst_fail 'Cannot write policy'
    chmod 755 "$policy" || hst_fail 'Cannot protect policy'
}
hst_restore_policy() {
    if [[ ${HST_POLICY_PREVIOUS:-no} == yes ]]; then
        cp -p -- "$HST_STAGE_DIR/policy-rc.d.original" "$HST_POLICY_PATH" || return 1
    else rm -f -- "$HST_POLICY_PATH" || return 1; fi
    HST_POLICY_ACTIVE=no
}

hst_download() {
    local url=$1 destination=$2
    [[ $url == https://* ]] || hst_fail 'Only HTTPS downloads are allowed'
    if command -v curl >/dev/null; then
        curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 300 --retry 2 --output "$destination" "$url" || return 1
    elif command -v wget >/dev/null; then
        wget --https-only --timeout=30 --tries=3 -q -O "$destination" "$url" || return 1
    else printf 'No curl or wget available\n' >&2; return 1; fi
    [[ -s $destination ]]
}
hst_asset() {
    local name=$1 destination=$2 line hash url extra
    line=$(awk -F '\t' -v id="$name" '$1==id {print; n++} END {if(n!=1) exit 1}' "$HST_BUNDLE_ROOT/install/assets.lock.tsv") || hst_fail "Missing unique asset lock: $name"
    IFS=$'\t' read -r extra hash url <<< "$line"
    [[ $hash =~ ^[a-f0-9]{64}$ ]] || hst_fail 'Invalid locked hash'
    hst_download "$url" "$destination" || hst_fail "Download failed: $name"
    printf '%s  %s\n' "$hash" "$destination" | sha256sum -c --status || hst_fail "Integrity mismatch: $name"
}
hst_keyring() {
    local name=$1 destination=$2 source="$HST_STAGE_DIR/key-$1" output
    hst_asset "key-$name" "$source"
    output=$(mktemp "${destination}.XXXXXXXX") || hst_fail 'Cannot create keyring temp'
    if ! gpg --batch --yes --dearmor --output "$output" "$source"; then rm -f "$output"; hst_fail "Invalid GPG key: $name"; fi
    gpg --batch --show-keys "$output" > /dev/null 2>&1 || { rm -f "$output"; hst_fail 'Keyring has no public key'; }
    if ! { chmod 644 "$output" && chown root:root "$output" && mv -f "$output" "$destination"; }; then rm -f "$output"; hst_fail 'Cannot install keyring'; fi
}
hst_publish_config() {
    local destination=$1 temporary
    temporary=$(mktemp "${destination}.XXXXXXXX") || hst_fail 'Cannot create config temp'
    if ! sort "$destination" > "$temporary"; then rm -f "$temporary"; hst_fail 'Cannot sort config'; fi
    if ! { chmod --reference="$destination" "$temporary" && chown --reference="$destination" "$temporary" && mv -f "$temporary" "$destination"; }; then rm -f "$temporary"; hst_fail 'Cannot publish config'; fi
}

hst_prepare() {
    HST_BUNDLE_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P) || hst_fail 'Cannot resolve bundle'
    hst_parse "$@"
    local result=0
    hst_preflight / || result=$?
    [[ $HST_APPLY == yes ]] || exit "$result"
    [[ $result == 0 ]] || hst_fail 'Fresh OS checks failed; migrate to a new server'
    [[ $interactive != yes ]] || { local answer; IFS= read -r -p 'Install on this fresh server? Type INSTALL: ' answer || hst_fail 'Input closed'; [[ $answer == INSTALL ]] || hst_fail 'Installation cancelled'; }
    hst_credentials
    if [[ -d /etc/netplan && -z $(find /etc/netplan -maxdepth 1 -type f -print -quit) && $HST_NETPLAN != yes ]]; then hst_fail 'Netplan is empty; review networking or explicitly use --allow-missing-netplan'; fi
    hst_begin
}
