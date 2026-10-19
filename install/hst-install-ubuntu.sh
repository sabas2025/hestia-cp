#!/bin/bash
# Professional overlay, modified 2026-10-15; upstream GPL-3.0 retained.
# shellcheck source=install/hst-common.sh
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/hst-common.sh" || exit 1
hst_prepare "$@"

# ======================================================== #
#
# Hestia Control Panel Installer for Ubuntu
# https://www.hestiacp.com/
#
# Currently Supported Versions:
# Ubuntu 22.04, 24.04, 26.04 LTS
#
# ======================================================== #

#----------------------------------------------------------#
#                  Variables&Functions                     #
#----------------------------------------------------------#
export PATH=$PATH:/sbin
export DEBIAN_FRONTEND=noninteractive
RHOST='apt.hestiacp.com'
VERSION='ubuntu'
HESTIA='/usr/local/hestia'
# LOG was created securely by hst_prepare.
memory=$(grep 'MemTotal' /proc/meminfo | tr ' ' '\n' | grep [0-9])
hst_backups="/root/hst_install_backups/$HST_RUN_ID"
spinner="/-\|"
os='ubuntu'
release="$HST_RELEASE"
codename="$HST_CODENAME"
architecture="$(arch)"
HESTIA_INSTALL_DIR="$HESTIA/install/deb"
HESTIA_COMMON_DIR="$HESTIA/install/common"
VERBOSE='no'

# Define software versions
HESTIA_INSTALL_VER='1.10.5'

# Build the full Hestia version
# Split base version (1.10.0) from channel suffix (~alpha / ~beta), if present
HESTIA_BASE_VER="${HESTIA_INSTALL_VER%%~*}"
if [[ "$HESTIA_INSTALL_VER" == *"~"* ]]; then
	HESTIA_CHANNEL="~${HESTIA_INSTALL_VER#*~}"
else
	HESTIA_CHANNEL=""
fi
# Build the distro identifier
case "$os" in
	ubuntu)
		os_id="ubuntu${release}"
		;;
	debian)
		os_id="debian${release}"
		;;
	*)
		echo "Error: unsupported distribution for determining Hestia version ($os)"
		exit 1
		;;
esac
# Final version string, e.g.: 1.10.0-1+deb13~alpha / 1.10.0-1+ubuntu26.04
HESTIA_INSTALL_BUILD="${HESTIA_BASE_VER}-1+${os_id}${HESTIA_CHANNEL}"

# Supported PHP versions
multiphp_v=("8.2" "8.3" "8.4" "8.5")
# One of the following PHP versions is required for Roundcube / phpmyadmin
multiphp_required=("8.2" "8.3" "8.4" "8.5")
# Default PHP version if none supplied
fpm_v="8.4"
# MariaDB version
mariadb_v="11.8"
# Node.js version
node_v="24"

# Defining software pack for all distros
software="acl apache2 apache2.2-common apache2-suexec-custom apache2-utils apparmor-utils at awstats bc bind9 bsdmainutils bsdutils
  clamav-daemon cron curl dnsutils dovecot-imapd dovecot-managesieved dovecot-pop3d dovecot-sieve e2fslibs e2fsprogs
  exim4 exim4-daemon-heavy expect fail2ban flex ftp git python3-qrcode hestia=${HESTIA_INSTALL_BUILD} hestia-nginx hestia-php hestia-web-terminal
  idn2 imagemagick ipset jq libapache2-mod-fcgid libapache2-mod-php$fpm_v libapache2-mod-rpaf libonig5 libzip4 lsb-release
  lsof mariadb-client mariadb-common mariadb-server mc mysql-client mysql-common mysql-server nginx nodejs openssh-server
  php$fpm_v php$fpm_v-apcu php$fpm_v-bz2 php$fpm_v-cgi php$fpm_v-cli php$fpm_v-common php$fpm_v-curl php$fpm_v-gd
  php$fpm_v-imagick php$fpm_v-imap php$fpm_v-intl php$fpm_v-ldap php$fpm_v-mbstring php$fpm_v-mysql
  php$fpm_v-pgsql php$fpm_v-pspell php$fpm_v-readline php$fpm_v-xml php$fpm_v-zip postgresql postgresql-contrib
  proftpd-core proftpd-mod-crypto quota rrdtool rsyslog util-linux spamassassin
  sysstat unzip vim-common vsftpd whois zip zstd bubblewrap restic rclone"

installer_dependencies="python3 apt-transport-https ca-certificates curl dirmngr gnupg openssl software-properties-common wget sudo"

# Defining help function
help() {
	echo "Usage: $0 [OPTIONS]
  -a, --apache            Install Apache        [yes|no]  default: yes
  -w, --phpfpm            Install PHP-FPM       [yes|no]  default: yes
  -o, --multiphp          Install MultiPHP      [yes|no]  default: no
  -v, --vsftpd            Install VSFTPD        [yes|no]  default: yes
  -j, --proftpd           Install ProFTPD       [yes|no]  default: no
  -k, --named             Install BIND          [yes|no]  default: yes
  -m, --mysql             Install MariaDB       [yes|no]  default: yes
  -M, --mysql8            Install MySQL 8       [yes|no]  default: no
  -g, --postgresql        Install PostgreSQL    [yes|no]  default: no
  -x, --exim              Install Exim          [yes|no]  default: yes
  -z, --dovecot           Install Dovecot       [yes|no]  default: yes
  -Z, --sieve             Install Sieve         [yes|no]  default: no
  -c, --clamav            Install ClamAV        [yes|no]  default: yes
  -t, --spamassassin      Install SpamAssassin  [yes|no]  default: yes
  -i, --iptables          Install iptables      [yes|no]  default: yes
  -b, --fail2ban          Install Fail2Ban      [yes|no]  default: yes
  -q, --quota             Filesystem Quota      [yes|no]  default: no
  -L, --resourcelimit     Resource Limitation   [yes|no]  default: no
  -W, --webterminal       Web Terminal          [yes|no]  default: no
  -d, --api               Activate API          [yes|no]  default: yes
  -r, --port              Change Backend Port             default: 8083
  -l, --lang              Default language                default: en
  -y, --interactive       Interactive install   [yes|no]  default: yes
  -s, --hostname          Set hostname
  -e, --email             Set admin email
  -u, --username          Set admin user
  -p, --password          Set admin password
  -D, --with-debs         Path to Hestia debs
  -f, --force             Force installation
  -h, --help              Print this help

  Example: bash $0 -e demo@hestiacp.com -p p4ssw0rd --multiphp yes"
	exit 1
}

# Defining file download function
download_file() {
	wget $1 -q --show-progress --progress=bar:force
}

# Defining password-gen function
gen_pass() {
	matrix=$1
	length=$2
	if [ -z "$matrix" ]; then
		matrix="A-Za-z0-9"
	fi
	if [ -z "$length" ]; then
		length=16
	fi
	head /dev/urandom | tr -dc $matrix | head -c$length
}

# Defining return code check function
check_result() {
	if [ $1 -ne 0 ]; then
		echo "Error: $2"
		exit $1
	fi
}

# Source conf in installer
source_conf() {
	while IFS='= ' read -r lhs rhs; do
		if [[ ! $lhs =~ ^\ *# && -n $lhs ]]; then
			rhs="${rhs%%^\#*}" # Del in line right comments
			rhs="${rhs%%*( )}" # Del trailing spaces
			rhs="${rhs%\'*}"   # Del opening string quotes
			rhs="${rhs#\'*}"   # Del closing string quotes
			declare -g $lhs="$rhs"
		fi
	done < $1
}

# Fixed variable names only; no eval or command re-interpretation.
set_default_value() {
 local key=$1 value=${!1-}
 if [[ -z $value ]]; then printf -v "$key" '%s' "$2";
 elif [[ $value != yes && $value != no ]]; then hst_fail "Invalid boolean: $key"; fi
}
set_default_lang() { [[ -n $lang ]] || lang=$1; }
set_default_port() { [[ -n $port ]] || port=$1; }

# Write configuration KEY/VALUE pair to $HESTIA/conf/hestia.conf
write_config_value() {
	local key="$1"
	local value="$2"
	echo "$key='$value'" >> $HESTIA/conf/hestia.conf
}

# Sort configuration file values
# Write final copy to $HESTIA/conf/hestia.conf for active usage
# Duplicate file to $HESTIA/conf/defaults/hestia.conf to restore known good installation values
sort_config_file() {
 hst_publish_config "$HESTIA/conf/hestia.conf"
 mkdir -p "$HESTIA/conf/defaults/" || hst_fail 'Cannot create defaults directory'
 cp -p "$HESTIA/conf/hestia.conf" "$HESTIA/conf/defaults/hestia.conf" || hst_fail 'Cannot preserve defaults'
}

# todo add check for usernames that are blocked
validate_username() {
	if [[ "$username" =~ ^[[:alnum:]][-|\.|_[:alnum:]]{0,28}[[:alnum:]]$ ]]; then
		if [ -n "$(grep ^$username: /etc/passwd /etc/group)" ]; then
			echo -e "\nUsername or Group allready exists please select a new user name or delete the user and / or group."
		else
			return 1
		fi
	else
		echo -e "\nPlease use a valid username (ex. user)."
		return 0
	fi
}

validate_password() {
	if [ -z "$vpass" ]; then
		return 0
	else
		return 1
	fi
}

# Validate hostname according to RFC1178
validate_hostname() {
	# remove extra .
	servername=$(echo "$servername" | sed -e "s/[.]*$//g")
	servername=$(echo "$servername" | sed -e "s/^[.]*//")
	if [[ $(echo "$servername" | grep -o "\." | wc -l) -gt 1 ]] && [[ ! $servername =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
		# Hostname valid
		return 1
	else
		# Hostname invalid
		return 0
	fi
}

validate_email() {
	if [[ ! "$email" =~ ^[A-Za-z0-9._%+-]+@[[:alnum:].-]+\.[A-Za-z]{2,63}$ ]]; then
		# Email invalid
		return 0
	else
		# Email valid
		return 1
	fi
}

version_ge() { test "$(printf '%s\n' "$@" | sort -V | head -n 1)" != "$1" -o -n "$1" -a "$1" = "$2"; }

#----------------------------------------------------------#
#                    Verifications                         #
#----------------------------------------------------------#

# Options and credentials were parsed and validated before any mutation.
tmpfile=$(mktemp "$HST_STAGE_DIR/metadata.XXXXXXXX") || hst_fail 'Cannot create metadata file'

if [ -n "$multiphp" ]; then
	if [ "$multiphp" != 'no' ] && [ "$multiphp" != 'yes' ]; then
		IFS=',' read -r -a php_versions <<< "$multiphp"
		multiphp_version=()
		for php_version in "${php_versions[@]}"; do
			if [[ $(echo "${multiphp_v[@]}" | fgrep -w "$php_version") ]]; then
				multiphp_version=(${multiphp_version[@]} "$php_version")
			else
				echo "$php_version is not supported"
				exit 1
			fi
		done
		multiphp_v=()
		for version in "${multiphp_version[@]}"; do
			multiphp_v=(${multiphp_v[@]} $version)
		done
		fpm_old=$fpm_v
		multiphp="yes"
		fpm_v=$(printf "%s\n" "${multiphp_version[@]}" | sort -V | tail -n1)
		fpm_last=$(printf "%s\n" "${multiphp_required[@]}" | sort -V | tail -n1)
		# Allow Maintainer to set minimum fpm version to make sure phpmyadmin and roundcube keep working
		if [[ -z $(echo "${multiphp_required[@]}" | fgrep -w $fpm_v) ]]; then
			if version_ge $fpm_v $fpm_last; then
				multiphp_version=(${multiphp_version[@]} $fpm_last)
				fpm_v=$fpm_last
			else
				# Roundcube and PHPmyadmin doesn't support the version selected.
				echo "Selected PHP versions are not supported any more by Dependencies..."
				exit 1
			fi
		fi

		software=$(echo "$software" | sed -e "s/php$fpm_old/php$fpm_v/g")

	fi
fi

# Defining default software stack
set_default_value 'nginx' 'yes'
set_default_value 'apache' 'yes'
set_default_value 'phpfpm' 'yes'
set_default_value 'multiphp' 'no'
set_default_value 'vsftpd' 'yes'
set_default_value 'proftpd' 'no'
set_default_value 'named' 'yes'
set_default_value 'mysql' 'yes'
set_default_value 'mysql8' 'no'
set_default_value 'postgresql' 'no'
set_default_value 'exim' 'yes'
set_default_value 'dovecot' 'yes'
set_default_value 'sieve' 'no'
if [ $memory -lt 1500000 ]; then
	set_default_value 'clamd' 'no'
	set_default_value 'spamd' 'no'
elif [ $memory -lt 3000000 ]; then
	set_default_value 'clamd' 'no'
	set_default_value 'spamd' 'yes'
else
	set_default_value 'clamd' 'yes'
	set_default_value 'spamd' 'yes'
fi
set_default_value 'iptables' 'yes'
set_default_value 'fail2ban' 'yes'
set_default_value 'quota' 'no'
set_default_value 'resourcelimit' 'no'
set_default_value 'webterminal' 'no'
set_default_value 'interactive' 'yes'
set_default_value 'api' 'yes'
set_default_port '8083'
set_default_lang 'en'

# Checking software conflicts
if [ "$proftpd" = 'yes' ]; then
	vsftpd='no'
fi
if [ "$exim" = 'no' ]; then
	clamd='no'
	spamd='no'
	dovecot='no'
fi
if [ "$dovecot" = 'no' ]; then
	sieve='no'
fi
if [ "$iptables" = 'no' ]; then
	fail2ban='no'
fi
if [ "$apache" = 'no' ]; then
	phpfpm='yes'
fi
if [ "$mysql" = 'yes' ] && [ "$mysql8" = 'yes' ]; then
	mysql='no'
fi

# Checking root permissions
if [ "x$(id -u)" != 'x0' ]; then
	check_result 1 "Script can be run executed only by root"
fi

if [ -d "/usr/local/hestia" ]; then
	check_result 1 "Hestia install detected. Unable to continue"
fi

type="$HST_OS"
if [ "$type" = "debian" ]; then
	check_result 1 "You are running the wrong installer for Debian. Please run hst-install.sh or hst-install-debian.sh instead."
elif [ "$type" != "ubuntu" ]; then
	check_result 1 "You are running an unsupported OS."
fi

# Clear the screen once launch permissions have been verified
clear

# Configure apt to retry downloading on error
if [ ! -f /etc/apt/apt.conf.d/80-retries ]; then
	echo "APT::Acquire::Retries \"3\";" > /etc/apt/apt.conf.d/80-retries
fi

# Welcome message
echo "Welcome to the Hestia Control Panel installer!"
echo
echo "Please wait, the installer is now checking for missing dependencies..."
echo

# Update apt repository
hst_run "Refresh package indexes" apt-get -qq update

# Creating backup directory
mkdir -p "$hst_backups"

# Pre-install packages
echo "[ * ] Installing dependencies..."
hst_run "Install bootstrap dependencies" apt-get -y install $installer_dependencies

# Check repository availability
hst_download "https://$RHOST" "$HST_STAGE_DIR/repository-probe" || hst_fail "Unable to connect to Hestia repository"

# Fresh-OS and network checks were already completed before modifying APT.
# Compare against this reviewed source snapshot, never against a mutable branch.
release_branch_ver=$(awk '/^Version:/ {print $2}' "$HST_BUNDLE_ROOT/src/deb/hestia/control")
[[ "$HESTIA_INSTALL_VER" == "$release_branch_ver" ]] || hst_fail 'Bundle/package version mismatch'

case $architecture in
	x86_64)
		ARCH="amd64"
		;;
	aarch64)
		ARCH="arm64"
		;;
	*)
		echo
		echo -e "\e[91mInstallation aborted\e[0m"
		echo "===================================================================="
		echo -e "\e[33mERROR: $architecture is currently not supported!\e[0m"
		echo -e "\e[33mPlease verify the achitecture used is currenlty supported\e[0m"
		echo ""
		echo -e "\e[33mhttps://github.com/hestiacp/hestiacp/blob/main/README.md\e[0m"
		echo ""
		check_result 1 "Installation aborted"
		;;
esac

#----------------------------------------------------------#
#                       Brief Info                         #
#----------------------------------------------------------#

install_welcome_message() {
	DISPLAY_VER=$(echo $HESTIA_INSTALL_VER | sed "s|~alpha||g" | sed "s|~beta||g" | sed "s|~rc[0-9]*||g")
	echo
	echo '                _   _           _   _        ____ ____                  '
	echo '               | | | | ___  ___| |_(_) __ _ / ___|  _ \                 '
	echo '               | |_| |/ _ \/ __| __| |/ _` | |   | |_) |                '
	echo '               |  _  |  __/\__ \ |_| | (_| | |___|  __/                 '
	echo '               |_| |_|\___||___/\__|_|\__,_|\____|_|                    '
	echo "                                                                        "
	echo "                          Hestia Control Panel                          "
	if [[ "$HESTIA_INSTALL_VER" =~ "rc" ]]; then
		echo "                             RELEASE CANDIDATE                      "
	fi
	if [[ "$HESTIA_INSTALL_VER" =~ "beta" ]]; then
		echo "                              BETA RELEASE                          "
	fi
	if [[ "$HESTIA_INSTALL_VER" =~ "alpha" ]]; then
		echo "                          DEVELOPMENT SNAPSHOT                      "
		echo "                    NOT INTENDED FOR PRODUCTION USE                 "
		echo "                          USE AT YOUR OWN RISK                      "
	fi
	echo "                                  ${DISPLAY_VER}                        "
	echo "                            www.hestiacp.com                            "
	echo
	echo "========================================================================"
	echo
	echo "Thank you for downloading Hestia Control Panel! In a few moments,"
	echo "we will begin installing the following components on your server:"
	echo
}

# Printing nice ASCII logo
clear
install_welcome_message

# Web stack
echo '   - NGINX Web / Proxy Server'
if [ "$apache" = 'yes' ]; then
	echo '   - Apache Web Server (as backend)'
fi
if [ "$phpfpm" = 'yes' ] && [ "$multiphp" = 'no' ]; then
	echo '   - PHP-FPM Application Server'
fi
if [ "$multiphp" = 'yes' ]; then
	phpfpm='yes'
	echo -n '   - Multi-PHP Environment: Version'
	for version in "${multiphp_v[@]}"; do
		echo -n " php$version"
	done
	echo ''
fi

# DNS stack
if [ "$named" = 'yes' ]; then
	echo '   - Bind DNS Server'
fi

# Mail stack
if [ "$exim" = 'yes' ]; then
	echo -n '   - Exim Mail Server'
	if [ "$clamd" = 'yes' ] || [ "$spamd" = 'yes' ]; then
		echo -n ' + '
		if [ "$clamd" = 'yes' ]; then
			echo -n 'ClamAV '
		fi
		if [ "$spamd" = 'yes' ]; then
			if [ "$clamd" = 'yes' ]; then
				echo -n '+ '
			fi
			echo -n 'SpamAssassin'
		fi
	fi
	echo
	if [ "$dovecot" = 'yes' ]; then
		echo -n '   - Dovecot POP3/IMAP Server'
		if [ "$sieve" = 'yes' ]; then
			echo -n '+ Sieve'
		fi
	fi
fi

echo

# Database stack
if [ "$mysql" = 'yes' ]; then
	echo '   - MariaDB Database Server'
fi
if [ "$mysql8" = 'yes' ]; then
	echo '   - MySQL8 Database Server'
fi
if [ "$postgresql" = 'yes' ]; then
	echo '   - PostgreSQL Database Server'
fi

# FTP stack
if [ "$vsftpd" = 'yes' ]; then
	echo '   - Vsftpd FTP Server'
fi
if [ "$proftpd" = 'yes' ]; then
	echo '   - ProFTPD FTP Server'
fi

if [ "$webterminal" = 'yes' ]; then
	echo '   - Web terminal'
fi

# Firewall stack
if [ "$iptables" = 'yes' ]; then
	echo -n '   - Firewall (iptables)'
fi
if [ "$iptables" = 'yes' ] && [ "$fail2ban" = 'yes' ]; then
	echo -n ' + Fail2Ban Access Monitor'
fi
echo -e "\n"
echo "========================================================================"
echo -e "\n"

# Asking for confirmation to proceed
# Installation was confirmed before package and locale changes.

# All credentials were validated before APT was touched.
displaypass="The password supplied through the protected input."
# Set FQDN if it wasn't set
mask1='(([[:alnum:]](-?[[:alnum:]])*)\.)'
mask2='*[[:alnum:]](-?[[:alnum:]])+\.[[:alnum:]]{2,}'
if ! [[ "$servername" =~ ^${mask1}${mask2}$ ]]; then
	if [[ -n "$servername" ]]; then
		servername="$servername.example.com"
	else
		servername="example.com"
	fi
	echo "127.0.0.1 $servername" >> /etc/hosts
fi

if [[ -z $(grep -i "$servername" /etc/hosts) ]]; then
	echo "127.0.0.1 $servername" >> /etc/hosts
fi

# Set email if it wasn't set
if [[ -z "$email" ]]; then
	email="admin@$servername"
fi

# Defining backup directory
echo -e "Installation backup directory: $hst_backups"

# Print Log File Path
echo "Installation log file: $LOG"

# Print new line
echo

#----------------------------------------------------------#
#                      Checking swap                       #
#----------------------------------------------------------#

# Add swap for low memory servers
if [ -z "$(swapon -s)" ] && [ "$memory" -lt 1000000 ]; then
	fallocate -l 1G /swapfile
	chmod 600 /swapfile
	mkswap /swapfile
	swapon /swapfile
	echo "/swapfile	none	swap	sw	0	0" >> /etc/fstab
fi

#----------------------------------------------------------#
#                   Install repository                     #
#----------------------------------------------------------#

# Define apt conf location
apt=/etc/apt/sources.list.d

# Create new folder if it doesn't exist
mkdir -p /root/.gnupg/ && chmod 700 /root/.gnupg/

# Updating system
echo "Adding required repositories to proceed with installation:"
echo

# Installing Nginx repo
echo "[ * ] NGINX"
echo "deb [arch=$ARCH signed-by=/usr/share/keyrings/nginx-keyring.gpg] https://nginx.org/packages/mainline/$VERSION/ $codename nginx" > $apt/nginx.list
hst_keyring nginx /usr/share/keyrings/nginx-keyring.gpg

# Installing sury PHP repo
# add-apt-repository does not yet support signed-by see: https://bugs.launchpad.net/ubuntu/+source/software-properties/+bug/1862764
echo "[ * ] PHP"
if [[ "$release" = "22.04" ]] || [[ "$release" = "24.04" ]]; then
	# Keep the APT signature algorithm policy intact.
	hst_run "Enable PHP repository" env LC_ALL=C.UTF-8 add-apt-repository -y ppa:ondrej/php
else
	# Ubuntu 26.04 and later use the Sury repository instead of a PPA
	echo "deb [arch=$ARCH signed-by=/usr/share/keyrings/sury-keyring.gpg] https://packages.sury.org/php/ $codename main" > $apt/php.list
	hst_keyring sury /usr/share/keyrings/sury-keyring.gpg
fi

# Installing sury Apache2 repo
if [ "$apache" = 'yes' ] && [ "$release" = '22.04' ]; then
	echo "[ * ] Apache2"
	echo "deb https://ppa.launchpadcontent.net/ondrej/apache2/ubuntu $codename main" > $apt/apache2.list
fi

# Installing MariaDB repo
if [ "$mysql" = 'yes' ]; then
	echo "[ * ] MariaDB $mariadb_v"
	echo "deb [arch=$ARCH signed-by=/usr/share/keyrings/mariadb-keyring.gpg] https://dlm.mariadb.com/repo/mariadb-server/$mariadb_v/repo/$VERSION $codename main" > $apt/mariadb.list
	hst_keyring mariadb /usr/share/keyrings/mariadb-keyring.gpg
fi

# Installing HestiaCP repo
echo "[ * ] Hestia Control Panel"
echo "deb [arch=$ARCH signed-by=/usr/share/keyrings/hestia-keyring.gpg] https://$RHOST/ $codename main" > $apt/hestia.list
hst_keyring hestia /usr/share/keyrings/hestia-keyring.gpg

# Installing Node.js repo
if [ "$webterminal" = 'yes' ]; then
	echo "[ * ] Node.js $node_v"
	echo "deb [arch=$ARCH signed-by=/usr/share/keyrings/nodejs.gpg] https://deb.nodesource.com/node_$node_v.x nodistro main" > $apt/nodejs.list
	hst_keyring nodejs /usr/share/keyrings/nodejs.gpg
	hst_run "Install Node.js" apt-get -y install nodejs
fi

# Installing PostgreSQL repo
if [ "$postgresql" = 'yes' ]; then
	echo "[ * ] PostgreSQL"
	echo "deb [arch=$ARCH signed-by=/usr/share/keyrings/postgresql-keyring.gpg] https://apt.postgresql.org/pub/repos/apt/ $codename-pgdg main" > $apt/postgresql.list
	hst_keyring postgresql /usr/share/keyrings/postgresql-keyring.gpg
fi

# Echo for a new line
echo

# Updating system
echo -ne "Updating currently installed packages, please wait... "
hst_run "Refresh package indexes" apt-get -qq update
hst_run "Upgrade installed packages" apt-get -y upgrade

#----------------------------------------------------------#
#                         Backup                           #
#----------------------------------------------------------#

# Creating backup directory tree
mkdir -p $hst_backups
cd $hst_backups
mkdir nginx apache2 php vsftpd proftpd bind exim4 dovecot clamd
mkdir spamassassin mysql postgresql openssl hestia

# Backup OpenSSL configuration
cp /etc/ssl/openssl.cnf $hst_backups/openssl > /dev/null 2>&1

# Backup nginx configuration
systemctl stop nginx > /dev/null 2>&1
cp -r /etc/nginx/* $hst_backups/nginx > /dev/null 2>&1

# Backup Apache configuration
systemctl stop apache2 > /dev/null 2>&1
cp -r /etc/apache2/* $hst_backups/apache2 > /dev/null 2>&1
rm -f /etc/apache2/conf.d/* > /dev/null 2>&1

# Backup PHP-FPM configuration
systemctl stop php*-fpm > /dev/null 2>&1
cp -r /etc/php/* $hst_backups/php > /dev/null 2>&1

# Backup Bind configuration
systemctl stop bind9 > /dev/null 2>&1
cp -r /etc/bind/* $hst_backups/bind > /dev/null 2>&1

# Backup Vsftpd configuration
systemctl stop vsftpd > /dev/null 2>&1
cp /etc/vsftpd.conf $hst_backups/vsftpd > /dev/null 2>&1

# Backup ProFTPD configuration
systemctl stop proftpd > /dev/null 2>&1
cp /etc/proftpd/* $hst_backups/proftpd > /dev/null 2>&1

# Backup Exim configuration
systemctl stop exim4 > /dev/null 2>&1
cp -r /etc/exim4/* $hst_backups/exim4 > /dev/null 2>&1

# Backup ClamAV configuration
systemctl stop clamav-daemon > /dev/null 2>&1
cp -r /etc/clamav/* $hst_backups/clamav > /dev/null 2>&1

# Backup SpamAssassin configuration
systemctl stop spamassassin > /dev/null 2>&1
cp -r /etc/spamassassin/* $hst_backups/spamassassin > /dev/null 2>&1

# Backup Dovecot configuration
systemctl stop dovecot > /dev/null 2>&1
cp /etc/dovecot.conf $hst_backups/dovecot > /dev/null 2>&1
cp -r /etc/dovecot/* $hst_backups/dovecot > /dev/null 2>&1

# Backup MySQL/MariaDB configuration and data
systemctl stop mysql > /dev/null 2>&1

# Existing database data is blocked by preflight; no datadir move.
cp -r /etc/mysql/* $hst_backups/mysql > /dev/null 2>&1
mv -f /root/.my.cnf $hst_backups/mysql > /dev/null 2>&1

# Backup Hestia
systemctl stop hestia > /dev/null 2>&1
cp -r $HESTIA/* $hst_backups/hestia > /dev/null 2>&1
apt-get -y purge hestia hestia-nginx hestia-php > /dev/null 2>&1
rm -rf $HESTIA > /dev/null 2>&1

#----------------------------------------------------------#
#                     Package Includes                     #
#----------------------------------------------------------#

if [ "$phpfpm" = 'yes' ]; then
	fpm="php$fpm_v php$fpm_v-common php$fpm_v-bcmath php$fpm_v-cli
         php$fpm_v-curl php$fpm_v-fpm php$fpm_v-gd php$fpm_v-intl
         php$fpm_v-mysql php$fpm_v-soap php$fpm_v-xml php$fpm_v-zip
         php$fpm_v-mbstring php$fpm_v-bz2 php$fpm_v-pspell
         php$fpm_v-imagick"
	software="$software $fpm"
fi

#----------------------------------------------------------#
#                     Package Excludes                     #
#----------------------------------------------------------#

# Excluding packages
software=$(echo "$software" | sed -e "s/apache2.2-common//")

if [ "$apache" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/apache2 //")
	software=$(echo "$software" | sed -e "s/apache2-bin//")
	software=$(echo "$software" | sed -e "s/apache2-utils//")
	software=$(echo "$software" | sed -e "s/apache2-suexec-custom//")
	software=$(echo "$software" | sed -e "s/apache2.2-common//")
	software=$(echo "$software" | sed -e "s/libapache2-mod-rpaf//")
	software=$(echo "$software" | sed -e "s/libapache2-mod-fcgid//")
	software=$(echo "$software" | sed -e "s/libapache2-mod-php$fpm_v//")
fi
if [ "$vsftpd" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/vsftpd//")
fi
if [ "$proftpd" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/proftpd-core//")
	software=$(echo "$software" | sed -e "s/proftpd-mod-crypto//")
fi
if [ "$named" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/bind9//")
fi
if [ "$exim" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/exim4 //")
	software=$(echo "$software" | sed -e "s/exim4-daemon-heavy//")
	software=$(echo "$software" | sed -e "s/dovecot-imapd//")
	software=$(echo "$software" | sed -e "s/dovecot-pop3d//")
	software=$(echo "$software" | sed -e "s/clamav-daemon//")
	software=$(echo "$software" | sed -e "s/spamassassin//")
	software=$(echo "$software" | sed -e "s/dovecot-sieve//")
	software=$(echo "$software" | sed -e "s/dovecot-managesieved//")
fi
if [ "$clamd" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/clamav-daemon//")
fi
if [ "$spamd" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/spamassassin//")
fi
if [ "$dovecot" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/dovecot-imapd//")
	software=$(echo "$software" | sed -e "s/dovecot-pop3d//")
fi
if [ "$sieve" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/dovecot-sieve//")
	software=$(echo "$software" | sed -e "s/dovecot-managesieved//")
fi
if [ "$mysql" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/mariadb-server//")
	software=$(echo "$software" | sed -e "s/mariadb-client//")
	software=$(echo "$software" | sed -e "s/mariadb-common//")
fi
if [ "$mysql8" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/mysql-server//")
	software=$(echo "$software" | sed -e "s/mysql-client//")
	software=$(echo "$software" | sed -e "s/mysql-common//")
fi
if [ "$mysql" = 'no' ] && [ "$mysql8" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/php$fpm_v-mysql//")
	if [ "$multiphp" = 'yes' ]; then
		for v in "${multiphp_v[@]}"; do
			software=$(echo "$software" | sed -e "s/php$v-mysql//")
			software=$(echo "$software" | sed -e "s/php$v-bz2//")
		done
	fi
fi
if [ "$postgresql" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/postgresql-contrib//")
	software=$(echo "$software" | sed -e "s/postgresql//")
	software=$(echo "$software" | sed -e "s/php$fpm_v-pgsql//")
fi
if [ "$fail2ban" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/fail2ban//")
fi
if [ "$iptables" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/ipset//")
	software=$(echo "$software" | sed -e "s/fail2ban//")
fi
if [ "$webterminal" = 'no' ]; then
	software=$(echo "$software" | sed -e "s/nodejs//")
	software=$(echo "$software" | sed -e "s/hestia-web-terminal//")
fi
if [ "$phpfpm" = 'yes' ]; then
	software=$(echo "$software" | sed -e "s/php$fpm_v-cgi//")
	software=$(echo "$software" | sed -e "s/libapache2-mod-ruid2//")
	software=$(echo "$software" | sed -e "s/libapache2-mod-php$fpm_v//")
fi
if [ -d "$withdebs" ]; then
	software=$(echo "$software" | sed -e "s/hestia-nginx//")
	software=$(echo "$software" | sed -e "s/hestia-php//")
	software=$(echo "$software" | sed -e "s/hestia-web-terminal//")
	software=$(echo "$software" | sed -e "s/hestia=${HESTIA_INSTALL_BUILD}//")
fi
if [ "$release" = '24.04' ]; then
	software=$(echo "$software" | sed -e "s/libzip4/libzip4t64/")
fi
if [ "$release" = '26.04' ]; then
	software=$(echo "$software" | sed -e "s/libzip4/libzip5/")
fi

#----------------------------------------------------------#
#                 Disable Apparmor on LXC                  #
#----------------------------------------------------------#

if grep --quiet lxc /proc/1/environ; then
	if [ -f /etc/init.d/apparmor ]; then
		systemctl stop apparmor > /dev/null 2>&1
		systemctl disable apparmor > /dev/null 2>&1
	fi
fi

#----------------------------------------------------------#
#                     Install packages                     #
#----------------------------------------------------------#

# Enable en_US.UTF-8
if [ -f /etc/locale.gen ]; then
	sed -i "s/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/g" /etc/locale.gen
	locale-gen > /dev/null 2>&1
elif [ -f /usr/bin/localectl ]; then
	apt-get -y install locales-all >> $LOG
	localectl set-locale LANG=en_US.UTF-8 > /dev/null 2>&1
fi

# Disabling daemon autostart on apt-get install
hst_policy_block

# Installing apt packages
echo "The installer is now downloading and installing all required packages."
echo -ne "NOTE: This process may take 10 to 15 minutes to complete, please wait... "
echo
hst_run "Install selected packages" apt-get -y install $software

echo
echo "========================================================================"
echo

# Install Hestia packages from local folder
if [ -n "$withdebs" ] && [ -d "$withdebs" ]; then
	echo "[ * ] Installing local package files..."
	echo "    - hestia core package"
	hst_run "Install local Hestia component" dpkg -i "$withdebs"/hestia_*.deb

	if ! (shopt -s nullglob; candidates=("$withdebs"/hestia-php_*.deb); ((${#candidates[@]}))); then
		echo "    - hestia-php backend package (from apt)"
		hst_run "Install local Hestia component" apt-get -y install hestia-php
	else
		echo "    - hestia-php backend package"
		hst_run "Install local Hestia component" dpkg -i "$withdebs"/hestia-php_*.deb
	fi

	if ! (shopt -s nullglob; candidates=("$withdebs"/hestia-nginx_*.deb); ((${#candidates[@]}))); then
		echo "    - hestia-nginx backend package (from apt)"
		hst_run "Install local Hestia component" apt-get -y install hestia-nginx
	else
		echo "    - hestia-nginx backend package"
		hst_run "Install local Hestia component" dpkg -i "$withdebs"/hestia-nginx_*.deb
	fi

	if [ "$webterminal" = "yes" ]; then
		if ! (shopt -s nullglob; candidates=("$withdebs"/hestia-web-terminal_*.deb); ((${#candidates[@]}))); then
			echo "    - hestia-web-terminal package (from apt)"
			hst_run "Install local Hestia component" apt-get -y install hestia-web-terminal
		else
			echo "    - hestia-web-terminal"
			hst_run "Install local Hestia component" dpkg -i "$withdebs"/hestia-web-terminal_*.deb
		fi
	fi
fi

# Apply version-aware runtime and interface additions.
hst_run "Install professional overlay" python3 "$HST_BUNDLE_ROOT/professional/apply.py" --root "$HESTIA" --source "$HST_BUNDLE_ROOT"

# Restoring autostart policy
hst_restore_policy || hst_fail "Cannot restore service startup policy"

#----------------------------------------------------------#
#                     Configure system                     #
#----------------------------------------------------------#

echo "[ * ] Configuring system settings..."

# Generate a random password
# No interactive password is generated for the service account.
# Create the new hestiaweb user
/usr/sbin/useradd "hestiaweb" -c "$email" --no-create-home
# do not allow login into hestiaweb user
hst_run "Lock service account login" /usr/sbin/usermod --lock hestiaweb

# Add a general group for normal users created by Hestia
if [ -z "$(grep ^hestia-users: /etc/group)" ]; then
	groupadd --system "hestia-users"
fi

# Create user for php-fpm configs
/usr/sbin/useradd "hestiamail" -c "$email" --no-create-home
# Ensures proper permissions for Hestia service interactions.
/usr/sbin/adduser hestiamail hestia-users

# Enable SFTP subsystem for SSH
sftp_subsys_enabled=$(grep -iE "^#?.*subsystem.+(sftp )?sftp-server" /etc/ssh/sshd_config)
if [ -n "$sftp_subsys_enabled" ]; then
	sed -i -E "s/^#?.*Subsystem.+(sftp )?sftp-server/Subsystem sftp internal-sftp/g" /etc/ssh/sshd_config
fi

# Reduce SSH login grace time
sed -i "s/[#]LoginGraceTime [[:digit:]]m/LoginGraceTime 1m/g" /etc/ssh/sshd_config

# Disable SSH suffix broadcast
if [ -z "$(grep "^DebianBanner no" /etc/ssh/sshd_config)" ]; then
	sed -i '/^[#]Banner .*/a DebianBanner no' /etc/ssh/sshd_config
	if [ -z "$(grep "^DebianBanner no" /etc/ssh/sshd_config)" ]; then
		# If first attempt fails just add it
		echo '' >> /etc/ssh/sshd_config
		echo 'DebianBanner no' >> /etc/ssh/sshd_config
	fi
fi

# Restart SSH daemon
systemctl restart ssh

# Disable AWStats cron
rm -f /etc/cron.d/awstats
# Replace AWStats function
cp -f $HESTIA_INSTALL_DIR/logrotate/httpd-prerotate/* /etc/logrotate.d/httpd-prerotate/

# Set directory color
if [ -z "$(grep 'LS_COLORS="$LS_COLORS:di=00;33"' /etc/profile)" ]; then
	echo 'LS_COLORS="$LS_COLORS:di=00;33"' >> /etc/profile
fi

# Register /usr/sbin/nologin
if [ -z "$(grep nologin /etc/shells)" ]; then
	echo "/usr/sbin/nologin" >> /etc/shells
fi

# Configuring NTP
# Ubuntu 26.04 doesn't install systemd-timesyncd, by default it uses Chrony
if [[ "$release" = "22.04" ]] || [[ "$release" = "24.04" ]]; then
	sed -i 's/#NTP=/NTP=pool.ntp.org/' /etc/systemd/timesyncd.conf
	systemctl enable systemd-timesyncd
	systemctl start systemd-timesyncd
fi

# Check iptables paths and add symlinks when necessary
if [ ! -e "/sbin/iptables" ]; then
	if which iptables > /dev/null; then
		ln -s "$(which iptables)" /sbin/iptables
	elif [ -e "/usr/sbin/iptables" ]; then
		ln -s /usr/sbin/iptables /sbin/iptables
	elif whereis -B /bin /sbin /usr/bin /usr/sbin -f -b iptables; then
		autoiptables=$(whereis -B /bin /sbin /usr/bin /usr/sbin -f -b iptables | cut -d '' -f 2)
		if [ -x "$autoiptables" ]; then
			ln -s "$autoiptables" /sbin/iptables
		fi
	fi
fi

if [ ! -e "/sbin/iptables-save" ]; then
	if which iptables-save > /dev/null; then
		ln -s "$(which iptables-save)" /sbin/iptables-save
	elif [ -e "/usr/sbin/iptables-save" ]; then
		ln -s /usr/sbin/iptables-save /sbin/iptables-save
	elif whereis -B /bin /sbin /usr/bin /usr/sbin -f -b iptables-save; then
		autoiptables_save=$(whereis -B /bin /sbin /usr/bin /usr/sbin -f -b iptables-save | cut -d '' -f 2)
		if [ -x "$autoiptables_save" ]; then
			ln -s "$autoiptables_save" /sbin/iptables-save
		fi
	fi
fi

if [ ! -e "/sbin/iptables-restore" ]; then
	if which iptables-restore > /dev/null; then
		ln -s "$(which iptables-restore)" /sbin/iptables-restore
	elif [ -e "/usr/sbin/iptables-restore" ]; then
		ln -s /usr/sbin/iptables-restore /sbin/iptables-restore
	elif whereis -B /bin /sbin /usr/bin /usr/sbin -f -b iptables-restore; then
		autoiptables_restore=$(whereis -B /bin /sbin /usr/bin /usr/sbin -f -b iptables-restore | cut -d '' -f 2)
		if [ -x "$autoiptables_restore" ]; then
			ln -s "$autoiptables_restore" /sbin/iptables-restore
		fi
	fi
fi

# Restrict access to /proc fs
# Prevent unpriv users from seeing each other running processes
mount -o remount,defaults,hidepid=2 /proc > /dev/null 2>&1
if [ $? -ne 0 ]; then
	echo "Info: Cannot remount /proc (LXC containers require additional perm added to host apparmor profile)"
else
	echo "@reboot root sleep 5 && mount -o remount,defaults,hidepid=2 /proc" > /etc/cron.d/hestia-proc
fi

#----------------------------------------------------------#
#                     Configure Hestia                     #
#----------------------------------------------------------#

echo "[ * ] Configuring Hestia Control Panel..."
# Installing sudo configuration
mkdir -p /etc/sudoers.d
cp -f $HESTIA_COMMON_DIR/sudo/hestiaweb /etc/sudoers.d/
# Ubuntu 26.04 and the new rust implementation of sudo doesn't support !requiretty
if [[ "$release" != "22.04" ]] && [[ "$release" != "24.04" ]]; then
	sed -i '/^Defaults:root !requiretty$/d' /etc/sudoers.d/hestiaweb
fi
chmod 440 /etc/sudoers.d/hestiaweb

# Add Hestia global config
if [[ ! -e /etc/hestiacp/hestia.conf ]]; then
	mkdir -p /etc/hestiacp
	echo -e "# Do not edit this file, will get overwritten on next upgrade, use /etc/hestiacp/local.conf instead\n\nexport HESTIA='/usr/local/hestia'\n\n[[ -f /etc/hestiacp/local.conf ]] && source /etc/hestiacp/local.conf" > /etc/hestiacp/hestia.conf
fi

# Configuring system env
echo "export HESTIA='$HESTIA'" > /etc/profile.d/hestia.sh
echo 'PATH=$PATH:'$HESTIA'/bin' >> /etc/profile.d/hestia.sh
echo 'export PATH' >> /etc/profile.d/hestia.sh
chmod 755 /etc/profile.d/hestia.sh
source /etc/profile.d/hestia.sh

# Configuring logrotate for Hestia logs
cp -f $HESTIA_INSTALL_DIR/logrotate/hestia /etc/logrotate.d/hestia

# Create log path and symbolic link
rm -f /var/log/hestia
mkdir -p /var/log/hestia
ln -s /var/log/hestia $HESTIA/log

# Building directory tree and creating some blank files for Hestia
mkdir -p $HESTIA/conf $HESTIA/ssl $HESTIA/data/ips \
	$HESTIA/data/queue $HESTIA/data/users $HESTIA/data/firewall \
	$HESTIA/data/sessions
touch $HESTIA/data/queue/backup.pipe $HESTIA/data/queue/disk.pipe \
	$HESTIA/data/queue/webstats.pipe $HESTIA/data/queue/restart.pipe \
	$HESTIA/data/queue/traffic.pipe $HESTIA/data/queue/daily.pipe $HESTIA/log/system.log \
	$HESTIA/log/nginx-error.log $HESTIA/log/auth.log $HESTIA/log/backup.log
chmod 750 $HESTIA/conf $HESTIA/data/users $HESTIA/data/ips $HESTIA/log
chmod -R 750 $HESTIA/data/queue
chmod 660 /var/log/hestia/*
chmod 770 $HESTIA/data/sessions

# Generating Hestia configuration
rm -f $HESTIA/conf/hestia.conf > /dev/null 2>&1
touch $HESTIA/conf/hestia.conf
chmod 660 $HESTIA/conf/hestia.conf

# Write default port value to hestia.conf
# If a custom port is specified it will be set at the end of the installation process
write_config_value "BACKEND_PORT" "8083"

# Web stack
if [ "$apache" = 'yes' ]; then
	write_config_value "WEB_SYSTEM" "apache2"
	write_config_value "WEB_RGROUPS" "www-data"
	write_config_value "WEB_PORT" "8080"
	write_config_value "WEB_SSL_PORT" "8443"
	write_config_value "WEB_SSL" "mod_ssl"
	write_config_value "PROXY_SYSTEM" "nginx"
	write_config_value "PROXY_PORT" "80"
	write_config_value "PROXY_SSL_PORT" "443"
	write_config_value "STATS_SYSTEM" "awstats"
fi
if [ "$apache" = 'no' ]; then
	write_config_value "WEB_SYSTEM" "nginx"
	write_config_value "WEB_PORT" "80"
	write_config_value "WEB_SSL_PORT" "443"
	write_config_value "WEB_SSL" "openssl"
	write_config_value "STATS_SYSTEM" "awstats"
fi
if [ "$phpfpm" = 'yes' ] || [ "$multiphp" = 'yes' ]; then
	write_config_value "WEB_BACKEND" "php-fpm"
fi

# Database stack
if [ "$mysql" = 'yes' ] || [ "$mysql8" = 'yes' ]; then
	installed_db_types='mysql'
fi
if [ "$postgresql" = 'yes' ]; then
	installed_db_types="$installed_db_types,pgsql"
fi
if [ -n "$installed_db_types" ]; then
	db=$(echo "$installed_db_types" \
		| sed "s/,/\n/g" \
		| sort -r -u \
		| sed "/^$/d" \
		| sed ':a;N;$!ba;s/\n/,/g')
	write_config_value "DB_SYSTEM" "$db"
fi

# FTP stack
if [ "$vsftpd" = 'yes' ]; then
	write_config_value "FTP_SYSTEM" "vsftpd"
fi
if [ "$proftpd" = 'yes' ]; then
	write_config_value "FTP_SYSTEM" "proftpd"
fi

# DNS stack
if [ "$named" = 'yes' ]; then
	write_config_value "DNS_SYSTEM" "bind9"
fi

# Mail stack
if [ "$exim" = 'yes' ]; then
	write_config_value "MAIL_SYSTEM" "exim4"
	if [ "$clamd" = 'yes' ]; then
		write_config_value "ANTIVIRUS_SYSTEM" "clamav-daemon"
	fi
	if [ "$spamd" = 'yes' ]; then
		release_short="$(cut -d '.' -f1 <<< "$release")"
		if [[ -n "$release_short" ]] && [[ $release_short -lt 24 ]]; then
			write_config_value "ANTISPAM_SYSTEM" "spamassassin"
		else
			write_config_value "ANTISPAM_SYSTEM" "spamd"
		fi
	fi
	if [ "$dovecot" = 'yes' ]; then
		write_config_value "IMAP_SYSTEM" "dovecot"
	fi
	if [ "$sieve" = 'yes' ]; then
		write_config_value "SIEVE_SYSTEM" "yes"
	fi
fi

# Cron daemon
write_config_value "CRON_SYSTEM" "cron"

# Firewall stack
if [ "$iptables" = 'yes' ]; then
	write_config_value "FIREWALL_SYSTEM" "iptables"
fi
if [ "$iptables" = 'yes' ] && [ "$fail2ban" = 'yes' ]; then
	write_config_value "FIREWALL_EXTENSION" "fail2ban"
fi

# Disk quota
if [ "$quota" = 'yes' ]; then
	write_config_value "DISK_QUOTA" "yes"
else
	write_config_value "DISK_QUOTA" "no"
fi

# Resource limitation
if [ "$resourcelimit" = 'yes' ]; then
	write_config_value "RESOURCES_LIMIT" "yes"
else
	write_config_value "RESOURCES_LIMIT" "no"
fi

write_config_value "WEB_TERMINAL_PORT" "8085"

# Backups
write_config_value "BACKUP_SYSTEM" "local"
write_config_value "BACKUP_GZIP" "4"
write_config_value "BACKUP_MODE" "zstd"

# Language
write_config_value "LANGUAGE" "$lang"

# Login screen style
write_config_value "LOGIN_STYLE" "default"

# Theme
write_config_value "THEME" "professional"

# Inactive session timeout
write_config_value "INACTIVE_SESSION_TIMEOUT" "60"

# Version & Release Branch
write_config_value "VERSION" "${HESTIA_INSTALL_VER}"
write_config_value "RELEASE_BRANCH" "release"

# Email notifications after upgrade
write_config_value "UPGRADE_SEND_EMAIL" "true"
write_config_value "UPGRADE_SEND_EMAIL_LOG" "false"

# Set "root" user
write_config_value "ROOT_USER" "$username"

# Installing hosting packages
cp -rf $HESTIA_COMMON_DIR/packages $HESTIA/data/

# Update nameservers in hosting package
IFS='.' read -r -a domain_elements <<< "$servername"
if [ -n "${domain_elements[-2]}" ] && [ -n "${domain_elements[-1]}" ]; then
	serverdomain="${domain_elements[-2]}.${domain_elements[-1]}"
	sed -i s/"domain.tld"/"$serverdomain"/g $HESTIA/data/packages/*.pkg
fi

# Installing templates
cp -rf $HESTIA_INSTALL_DIR/templates $HESTIA/data/
cp -rf $HESTIA_COMMON_DIR/templates/web/ $HESTIA/data/templates
cp -rf $HESTIA_COMMON_DIR/templates/dns/ $HESTIA/data/templates

mkdir -p /var/www/html
mkdir -p /var/www/document_errors

# Install default success page
cp -rf $HESTIA_COMMON_DIR/templates/web/unassigned/index.html /var/www/html/
cp -rf $HESTIA_COMMON_DIR/templates/web/skel/document_errors/* /var/www/document_errors/

# Installing firewall rules
cp -rf $HESTIA_COMMON_DIR/firewall $HESTIA/data/
rm -f $HESTIA/data/firewall/ipset/blacklist.sh $HESTIA/data/firewall/ipset/blacklist.ipv6.sh

# Delete rules for services that are not installed
if [ "$vsftpd" = "no" ] && [ "$proftpd" = "no" ]; then
	# Remove FTP
	sed -i "/COMMENT='FTP'/d" $HESTIA/data/firewall/rules.conf
fi
if [ "$exim" = "no" ]; then
	# Remove SMTP
	sed -i "/COMMENT='SMTP'/d" $HESTIA/data/firewall/rules.conf
fi
if [ "$dovecot" = "no" ]; then
	# Remove IMAP / Dovecot
	sed -i "/COMMENT='IMAP'/d" $HESTIA/data/firewall/rules.conf
	sed -i "/COMMENT='POP3'/d" $HESTIA/data/firewall/rules.conf
fi
if [ "$named" = "no" ]; then
	# Remove IMAP / Dovecot
	sed -i "/COMMENT='DNS'/d" $HESTIA/data/firewall/rules.conf
fi

# Installing API
cp -rf $HESTIA_COMMON_DIR/api $HESTIA/data/

# Configuring server hostname
$HESTIA/bin/v-change-sys-hostname $servername > /dev/null 2>&1

# Configuring global OpenSSL options
echo "[ * ] Configuring OpenSSL to improve TLS performance..."
tls13_ciphers="TLS_AES_128_GCM_SHA256:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_256_GCM_SHA384"
if [ "$release" = "22.04" ]; then
	sed -i '/^system_default = system_default_sect$/a system_default = hestia_openssl_sect\n\n[hestia_openssl_sect]\nCiphersuites = '"$tls13_ciphers"'\nOptions = PrioritizeChaCha' /etc/ssl/openssl.cnf
else
	if ! grep -qw "^ssl_conf = ssl_sect$" /etc/ssl/openssl.cnf 2> /dev/null; then
		sed -i '/providers = provider_sect$/a ssl_conf = ssl_sect' /etc/ssl/openssl.cnf
	fi
	if ! grep -qw "^[ssl_sect]$" /etc/ssl/openssl.cnf 2> /dev/null; then
		sed -i '$a \\n[ssl_sect]\nsystem_default = hestia_openssl_sect\n\n[hestia_openssl_sect]\nCiphersuites = '"$tls13_ciphers"'\nOptions = PrioritizeChaCha' /etc/ssl/openssl.cnf
	elif grep -qw "^system_default = system_default_sect$" /etc/ssl/openssl.cnf 2> /dev/null; then
		sed -i '/^system_default = system_default_sect$/a system_default = hestia_openssl_sect\n\n[hestia_openssl_sect]\nCiphersuites = '"$tls13_ciphers"'\nOptions = PrioritizeChaCha' /etc/ssl/openssl.cnf
	fi
fi

# Generating SSL certificate
(umask 077; : > "$HST_STAGE_DIR/hst.pem") || hst_fail "Cannot create certificate workspace"
echo "[ * ] Generating default self-signed SSL certificate..."
$HESTIA/bin/v-generate-ssl-cert $(hostname) '' 'US' 'California' \
	'San Francisco' 'Hestia Control Panel' 'IT' > $HST_STAGE_DIR/hst.pem

# Parsing certificate file
crt_end=$(grep -n "END CERTIFICATE-" $HST_STAGE_DIR/hst.pem | head -n1 | cut -f 1 -d:)
# Newer OpenSSL may emit BEGIN PRIVATE KEY while older flows emit BEGIN RSA PRIVATE KEY.
key_start=$(grep -nE "BEGIN (RSA |EC |ENCRYPTED )?PRIVATE KEY" $HST_STAGE_DIR/hst.pem | head -n1 | cut -f 1 -d:)
key_end=$(grep -nE "END (RSA |EC |ENCRYPTED )?PRIVATE KEY" $HST_STAGE_DIR/hst.pem | head -n1 | cut -f 1 -d:)
if [ -z "$key_start" ] || [ -z "$key_end" ]; then
	key_start=$(grep -n "BEGIN RSA" $HST_STAGE_DIR/hst.pem | head -n1 | cut -f 1 -d:)
	key_end=$(grep -n "END RSA" $HST_STAGE_DIR/hst.pem | head -n1 | cut -f 1 -d:)
fi
check_result $(
	[ -n "$crt_end" ] && [ -n "$key_start" ] && [ -n "$key_end" ]
	echo $?
) "failed to parse generated SSL certificate"

# Adding SSL certificate
echo "[ * ] Adding SSL certificate to Hestia Control Panel..."
cd $HESTIA/ssl
sed -n "1,${crt_end}p" $HST_STAGE_DIR/hst.pem > certificate.crt
sed -n "$key_start,${key_end}p" $HST_STAGE_DIR/hst.pem > certificate.key
chown root:mail $HESTIA/ssl/*
chmod 660 $HESTIA/ssl/*
rm $HST_STAGE_DIR/hst.pem

# Install dhparam.pem
cp -f $HESTIA_INSTALL_DIR/ssl/dhparam.pem /etc/ssl

# Enable SFTP jail
echo "[ * ] Enabling SFTP jail..."
$HESTIA/bin/v-add-sys-sftp-jail > /dev/null 2>&1
check_result $? "can't enable sftp jail"

# Enable SSH jail
echo "[ * ] Enabling SSH jail..."
$HESTIA/bin/v-add-sys-ssh-jail > /dev/null 2>&1
check_result $? "can't enable ssh jail"

# Adding Hestia admin account
echo "[ * ] Creating default admin account..."
(umask 077; printf '%s\n' "$vpass" > "$HST_STAGE_DIR/admin-password") || hst_fail 'Cannot stage password'
$HESTIA/bin/v-add-user "$username" "$HST_STAGE_DIR/admin-password" "$email" "default" "System Administrator"
check_result $? "can't create admin user"
rm -f -- "$HST_STAGE_DIR/admin-password"
unset vpass
$HESTIA/bin/v-change-user-shell "$username" nologin no
$HESTIA/bin/v-change-user-role "$username" admin
$HESTIA/bin/v-change-user-language "$username" "$lang"
$HESTIA/bin/v-change-sys-config-value 'POLICY_SYSTEM_PROTECTED_ADMIN' 'yes'

#----------------------------------------------------------#
#                     Configure Nginx                      #
#----------------------------------------------------------#

echo "[ * ] Configuring NGINX..."
rm -f /etc/nginx/conf.d/*.conf
cp -f $HESTIA_INSTALL_DIR/nginx/nginx.conf /etc/nginx/
cp -f $HESTIA_INSTALL_DIR/nginx/status.conf /etc/nginx/conf.d/
cp -f $HESTIA_INSTALL_DIR/nginx/0rtt-anti-replay.conf /etc/nginx/conf.d/
cp -f $HESTIA_INSTALL_DIR/nginx/agents.conf /etc/nginx/conf.d/
# Copy over cloudflare.inc incase in the next step there are connection issues with CF
cp -f $HESTIA_INSTALL_DIR/nginx/cloudflare.inc /etc/nginx/conf.d/
cp -f $HESTIA_INSTALL_DIR/nginx/phpmyadmin.inc /etc/nginx/conf.d/
cp -f $HESTIA_INSTALL_DIR/nginx/phppgadmin.inc /etc/nginx/conf.d/
cp -f $HESTIA_INSTALL_DIR/logrotate/nginx /etc/logrotate.d/
mkdir -p /etc/nginx/conf.d/domains
mkdir -p /etc/nginx/conf.d/main
mkdir -p /etc/nginx/modules-enabled
mkdir -p /var/log/nginx/domains

# Update dns servers in nginx.conf
for nameserver in $(grep -is '^nameserver' /etc/resolv.conf | cut -d' ' -f2 | tr '\r\n' ' ' | xargs); do
	if [[ "$nameserver" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
		if [ -z "$resolver" ]; then
			resolver="$nameserver"
		else
			resolver="$resolver $nameserver"
		fi
	fi
done
if [ -n "$resolver" ]; then
	sed -i "s/1.0.0.1 8.8.4.4 1.1.1.1 8.8.8.8/$resolver/g" /etc/nginx/nginx.conf
fi

# https://github.com/ergin/nginx-cloudflare-real-ip/
cf_ips="$(curl -fsLm5 --retry 2 https://api.cloudflare.com/client/v4/ips)"

if [ -n "$cf_ips" ] && [ "$(echo "$cf_ips" | jq -r '.success//""')" = "true" ]; then
	cf_inc="/etc/nginx/conf.d/cloudflare.inc"

	echo "[ * ] Updating Cloudflare IP Ranges for Nginx..."
	echo "# Cloudflare IP Ranges" > $cf_inc
	echo "" >> $cf_inc
	echo "# IPv4" >> $cf_inc
	for ipv4 in $(echo "$cf_ips" | jq -r '.result.ipv4_cidrs[]//""' | sort); do
		echo "set_real_ip_from $ipv4;" >> $cf_inc
	done
	echo "" >> $cf_inc
	echo "# IPv6" >> $cf_inc
	for ipv6 in $(echo "$cf_ips" | jq -r '.result.ipv6_cidrs[]//""' | sort); do
		echo "set_real_ip_from $ipv6;" >> $cf_inc
	done
	echo "" >> $cf_inc
	echo "real_ip_header CF-Connecting-IP;" >> $cf_inc
fi

update-rc.d nginx defaults > /dev/null 2>&1
systemctl start nginx >> $LOG
check_result $? "nginx start failed"

#----------------------------------------------------------#
#                    Configure Apache                      #
#----------------------------------------------------------#

if [ "$apache" = 'yes' ]; then
	echo "[ * ] Configuring Apache Web Server..."

	mkdir -p /etc/apache2/conf.d
	mkdir -p /etc/apache2/conf.d/domains

	# Copy configuration files
	cp -f $HESTIA_INSTALL_DIR/apache2/apache2.conf /etc/apache2/
	cp -f $HESTIA_INSTALL_DIR/apache2/status.conf /etc/apache2/mods-available/hestia-status.conf
	cp -f /etc/apache2/mods-available/status.load /etc/apache2/mods-available/hestia-status.load
	cp -f $HESTIA_INSTALL_DIR/logrotate/apache2 /etc/logrotate.d/

	# Enable needed modules
	a2enmod rewrite > /dev/null 2>&1
	a2enmod suexec > /dev/null 2>&1
	a2enmod ssl > /dev/null 2>&1
	a2enmod actions > /dev/null 2>&1
	a2enmod headers > /dev/null 2>&1
	a2dismod --quiet status > /dev/null 2>&1
	a2enmod --quiet hestia-status > /dev/null 2>&1

	# Enable mod_ruid/mpm_itk or mpm_event
	if [ "$phpfpm" = 'yes' ]; then
		# Disable prefork and php, enable event
		a2dismod php$fpm_v > /dev/null 2>&1
		a2dismod mpm_prefork > /dev/null 2>&1
		a2enmod mpm_event > /dev/null 2>&1
		cp -f $HESTIA_INSTALL_DIR/apache2/hestia-event.conf /etc/apache2/conf.d/
	else
		a2enmod ruid2 > /dev/null 2>&1
	fi

	echo "# Powered by hestia" > /etc/apache2/sites-available/default
	echo "# Powered by hestia" > /etc/apache2/sites-available/default-ssl
	echo "# Powered by hestia" > /etc/apache2/ports.conf
	echo -e "/home\npublic_html/cgi-bin" > /etc/apache2/suexec/www-data
	touch /var/log/apache2/access.log /var/log/apache2/error.log
	mkdir -p /var/log/apache2/domains
	chmod a+x /var/log/apache2
	chmod 640 /var/log/apache2/access.log /var/log/apache2/error.log
	chmod 751 /var/log/apache2/domains

	# Prevent remote access to server-status page
	sed -i '/Allow from all/d' /etc/apache2/mods-available/hestia-status.conf

	update-rc.d apache2 defaults > /dev/null 2>&1
	systemctl start apache2 >> $LOG
	check_result $? "apache2 start failed"
else
	update-rc.d apache2 disable > /dev/null 2>&1
	systemctl stop apache2 > /dev/null 2>&1
fi

#----------------------------------------------------------#
#                     Configure PHP-FPM                    #
#----------------------------------------------------------#

if [ "$phpfpm" = "yes" ]; then
	if [ "$multiphp" = 'yes' ]; then
		for v in "${multiphp_v[@]}"; do
			echo "[ * ] Installing PHP $v..."
			$HESTIA/bin/v-add-web-php "$v" > /dev/null 2>&1
		done
	else
		echo "[ * ] Installing PHP $fpm_v..."
		$HESTIA/bin/v-add-web-php "$fpm_v" > /dev/null 2>&1
	fi

	echo "[ * ] Configuring PHP-FPM $fpm_v..."
	# Create www.conf for webmail and php(*)admin
	cp -f $HESTIA_INSTALL_DIR/php-fpm/www.conf /etc/php/$fpm_v/fpm/pool.d/www.conf
	update-rc.d php$fpm_v-fpm defaults > /dev/null 2>&1
	systemctl start php$fpm_v-fpm >> $LOG
	check_result $? "php-fpm start failed"
	# Set default php version to $fpm_v
	update-alternatives --set php /usr/bin/php$fpm_v > /dev/null 2>&1
fi

#----------------------------------------------------------#
#                     Configure PHP                        #
#----------------------------------------------------------#

echo "[ * ] Configuring PHP..."
ZONE=$(timedatectl > /dev/null 2>&1 | grep Timezone | awk '{print $2}')
if [ -z "$ZONE" ]; then
	ZONE='UTC'
fi
for pconf in $(find /etc/php* -name php.ini); do
	sed -i "s%;date.timezone =%date.timezone = $ZONE%g" $pconf
	sed -i 's%_open_tag = Off%_open_tag = On%g' $pconf
done

# Cleanup php session files not changed in the last 7 days (60*24*7 minutes)
echo '#!/bin/sh' > /etc/cron.daily/php-session-cleanup
echo "find -O3 /home/*/tmp/ -ignore_readdir_race -depth -mindepth 1 -name 'sess_*' -type f -cmin '+10080' -delete > /dev/null 2>&1" >> /etc/cron.daily/php-session-cleanup
echo "find -O3 $HESTIA/data/sessions/ -ignore_readdir_race -depth -mindepth 1 -name 'sess_*' -type f -cmin '+10080' -delete > /dev/null 2>&1" >> /etc/cron.daily/php-session-cleanup
chmod 755 /etc/cron.daily/php-session-cleanup

#----------------------------------------------------------#
#                    Configure Vsftpd                      #
#----------------------------------------------------------#

if [ "$vsftpd" = 'yes' ]; then
	echo "[ * ] Configuring Vsftpd server..."
	cp -f $HESTIA_INSTALL_DIR/vsftpd/vsftpd.conf /etc/
	touch /var/log/vsftpd.log
	chown root:adm /var/log/vsftpd.log
	chmod 640 /var/log/vsftpd.log
	touch /var/log/xferlog
	chown root:adm /var/log/xferlog
	chmod 640 /var/log/xferlog
	if [ -s /etc/logrotate.d/vsftpd ] && ! grep -Fq "/var/log/xferlog" /etc/logrotate.d/vsftpd; then
		sed -i 's|/var/log/vsftpd.log|/var/log/vsftpd.log /var/log/xferlog|g' /etc/logrotate.d/vsftpd
	fi
	update-rc.d vsftpd defaults > /dev/null 2>&1
	systemctl start vsftpd >> $LOG
	check_result $? "vsftpd start failed"
fi

#----------------------------------------------------------#
#                    Configure ProFTPD                     #
#----------------------------------------------------------#

if [ "$proftpd" = 'yes' ]; then
	echo "[ * ] Configuring ProFTPD server..."
	echo "127.0.0.1 $servername" >> /etc/hosts
	cp -f $HESTIA_INSTALL_DIR/proftpd/proftpd.conf /etc/proftpd/
	cp -f $HESTIA_INSTALL_DIR/proftpd/tls.conf /etc/proftpd/

	# In Ubuntu 26.04 we need to:
	#   1.- Add modules.conf to proftpd.conf so tls mod is loaded.
	#   2.- Add rules to AppArmor to allow ProFTPD to read the certificates and create the socket.
	ubuntu_major="${release%%.*}"
	if [[ "$ubuntu_major" -ge 26 ]]; then
		# Add modules.conf
		if [[ -f /etc/proftpd/modules.conf ]] && grep -qF "Include /etc/proftpd/tls.conf" /etc/proftpd/proftpd.conf; then
			if ! grep -qF "Include /etc/proftpd/modules.conf" /etc/proftpd/proftpd.conf; then
				sed -i '\|Include /etc/proftpd/tls.conf|i Include /etc/proftpd/modules.conf' /etc/proftpd/proftpd.conf
			fi
		fi

		# Add ruleset for AppArmor
		mkdir -p /etc/apparmor.d/local
		if [[ ! -f /etc/apparmor.d/local/proftpd ]]; then
			cat > /etc/apparmor.d/local/proftpd << 'EOF'
# Configuration added by Hestia
/usr/local/hestia/ssl/certificate.crt r,
/usr/local/hestia/ssl/certificate.key r,
/run/proftpd.sock rw,
EOF
			apparmor_parser -r /etc/apparmor.d/proftpd 2> /dev/null
		elif ! grep -qF "# Configuration added by Hestia" /etc/apparmor.d/local/proftpd; then
			cat >> /etc/apparmor.d/local/proftpd << 'EOF'
# Configuration added by Hestia
/usr/local/hestia/ssl/certificate.crt r,
/usr/local/hestia/ssl/certificate.key r,
/run/proftpd.sock rw,
EOF
			apparmor_parser -r /etc/apparmor.d/proftpd 2> /dev/null
		fi
	fi

	update-rc.d proftpd defaults > /dev/null 2>&1
	systemctl start proftpd >> $LOG
	check_result $? "proftpd start failed"
fi

#----------------------------------------------------------#
#               Configure MariaDB / MySQL                  #
#----------------------------------------------------------#

if [ "$mysql" = 'yes' ] || [ "$mysql8" = 'yes' ]; then
	[ "$mysql" = 'yes' ] && mysql_type="MariaDB" || mysql_type="MySQL"
	echo "[ * ] Configuring $mysql_type database server..."
	mycnf="my-small.cnf"
	if [ $memory -gt 1200000 ]; then
		mycnf="my-medium.cnf"
	fi
	if [ $memory -gt 3900000 ]; then
		mycnf="my-large.cnf"
	fi

	if [ "$mysql_type" = 'MariaDB' ]; then
		# Run mariadb-install-db
		mariadb-install-db >> $LOG
	fi

	# Remove symbolic link
	rm -f /etc/mysql/my.cnf
	# Configuring MariaDB
	cp -f $HESTIA_INSTALL_DIR/mysql/$mycnf /etc/mysql/my.cnf

	# Switch MariaDB inclusions to the MySQL
	if [ "$mysql_type" = 'MySQL' ]; then
		sed -i '/query_cache_size/d' /etc/mysql/my.cnf
		sed -i 's|mariadb.conf.d|mysql.conf.d|g' /etc/mysql/my.cnf
	fi

	if [ "$mysql_type" = 'MariaDB' ]; then
		sed -i 's|/usr/share/mysql|/usr/share/mariadb|g' /etc/mysql/my.cnf
		update-rc.d mariadb defaults > /dev/null 2>&1
		systemctl -q enable mariadb 2> /dev/null
		systemctl start mariadb >> $LOG
		check_result $? "${mysql_type,,} start failed"
	fi

	if [ "$mysql_type" = 'MySQL' ]; then
		update-rc.d mysql defaults > /dev/null 2>&1
		systemctl -q enable mysql 2> /dev/null
		systemctl start mysql >> $LOG
		check_result $? "${mysql_type,,} start failed"
	fi

	# Securing MariaDB/MySQL installation
	mpass=$(gen_pass)
	echo -e "[client]\npassword='$mpass'\n" > /root/.my.cnf
	chmod 600 /root/.my.cnf

	if [ -f '/usr/bin/mariadb' ]; then
		mysql_server="mariadb"
	else
		mysql_server="mysql"
	fi
	# Alter root password
	printf '%s\n' "ALTER USER 'root'@'localhost' IDENTIFIED BY '$mpass'; FLUSH PRIVILEGES;" | "$mysql_server"
		check_result $? "Database password setup failed"
	if [ "$mysql_type" = 'MariaDB' ]; then
		# Allow mysql access via socket for startup
		$mysql_server -e "UPDATE mysql.global_priv SET priv=json_set(priv, '$.password_last_changed', UNIX_TIMESTAMP(), '$.plugin', 'mysql_native_password', '$.authentication_string', 'invalid', '$.auth_or', json_array(json_object(), json_object('plugin', 'unix_socket'))) WHERE User='root';"
		# Disable anonymous users
		$mysql_server -e "DELETE FROM mysql.global_priv WHERE User='';"
	else
		printf '%s\n' "ALTER USER 'root'@'localhost' IDENTIFIED WITH caching_sha2_password BY '$mpass';" | "$mysql_server"
		check_result $? "Database password setup failed"
		$mysql_server -e "DELETE FROM mysql.user WHERE User='';"
		$mysql_server -e "DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');"
	fi
	# Drop test database
	$mysql_server -e "DROP DATABASE IF EXISTS test"
	$mysql_server -e "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%'"
	# Flush privileges
	$mysql_server -e "FLUSH PRIVILEGES;"
fi

#----------------------------------------------------------#
#                    Configure phpMyAdmin                  #
#----------------------------------------------------------#

# Source upgrade.conf with phpmyadmin versions
# shellcheck source=/usr/local/hestia/install/upgrade/upgrade.conf
source $HESTIA/install/upgrade/upgrade.conf

if [ "$mysql" = 'yes' ] || [ "$mysql8" = 'yes' ]; then
	# Display upgrade information
	echo "[ * ] Installing phpMyAdmin version v$pma_v..."

	# Download latest phpmyadmin release
	hst_asset phpmyadmin "phpMyAdmin-$pma_v-all-languages.tar.gz"

	# Unpack files
	hst_run "Extract phpMyAdmin" tar --no-same-owner -xzf "phpMyAdmin-$pma_v-all-languages.tar.gz"

	# Create folders
	mkdir -p /usr/share/phpmyadmin
	mkdir -p /etc/phpmyadmin
	mkdir -p /etc/phpmyadmin/conf.d/
	mkdir /usr/share/phpmyadmin/tmp

	# Configuring Apache2 for PHPMYADMIN
	if [ "$apache" = 'yes' ]; then
		touch /etc/apache2/conf.d/phpmyadmin.inc
	fi

	# Overwrite old files
	cp -rf phpMyAdmin-$pma_v-all-languages/* /usr/share/phpmyadmin

	# Create copy of config file
	cp -f $HESTIA_INSTALL_DIR/phpmyadmin/config.inc.php /etc/phpmyadmin/

	# Set config and log directory
	sed -i "s|'configFile' => ROOT_PATH . 'config.inc.php',|'configFile' => '/etc/phpmyadmin/config.inc.php',|g" /usr/share/phpmyadmin/libraries/vendor_config.php

	# Create temporary folder and change permission
	mkdir -p /var/lib/phpmyadmin/tmp
	chmod 770 /var/lib/phpmyadmin/tmp
	chown -R hestiamail:www-data /usr/share/phpmyadmin/tmp/

	# Generate blow fish
	blowfish=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 32)
	sed -i "s|%blowfish_secret%|$blowfish|" /etc/phpmyadmin/config.inc.php

	# Clean Up
	rm -fr phpMyAdmin-$pma_v-all-languages
	rm -f phpMyAdmin-$pma_v-all-languages.tar.gz

	write_config_value "DB_PMA_ALIAS" "phpmyadmin"
	$HESTIA/bin/v-change-sys-db-alias 'pma' "phpmyadmin"

	# Special thanks to Pavel Galkin (https://skurudo.ru)
	# https://github.com/skurudo/phpmyadmin-fixer
	# shellcheck source=/usr/local/hestia/install/deb/phpmyadmin/pma.sh
	source $HESTIA_INSTALL_DIR/phpmyadmin/pma.sh > /dev/null 2>&1

	# Limit access to /etc/phpmyadmin/
	chown -R root:hestiamail /etc/phpmyadmin/
	chmod 640 /etc/phpmyadmin/config.inc.php
	chmod 750 /etc/phpmyadmin/conf.d/
fi

#----------------------------------------------------------#
#                   Configure PostgreSQL                   #
#----------------------------------------------------------#

if [ "$postgresql" = 'yes' ]; then
	echo "[ * ] Configuring PostgreSQL database server..."
	ppass=$(gen_pass)
	cp -f $HESTIA_INSTALL_DIR/postgresql/pg_hba.conf /etc/postgresql/*/main/
	systemctl restart postgresql
	printf '%s\n' "ALTER USER postgres WITH PASSWORD '$ppass';" | sudo -iu postgres psql >> "$LOG" 2>&1
	check_result $? "PostgreSQL password setup failed"

	mkdir -p /etc/phppgadmin/
	mkdir -p /usr/share/phppgadmin/

	hst_asset phppgadmin "phppgadmin-v$pga_v.tar.gz"
	hst_run "Extract phpPgAdmin" tar --no-same-owner -xzf "phppgadmin-v$pga_v.tar.gz" -C /usr/share/phppgadmin/

	cp -f $HESTIA_INSTALL_DIR/pga/config.inc.php /etc/phppgadmin/

	ln -s /etc/phppgadmin/config.inc.php /usr/share/phppgadmin/conf/

	# Configuring phpPgAdmin
	if [ "$apache" = 'yes' ]; then
		cp -f $HESTIA_INSTALL_DIR/pga/phppgadmin.conf /etc/apache2/conf.d/phppgadmin.inc
	fi

	rm phppgadmin-v$pga_v.tar.gz
	write_config_value "DB_PGA_ALIAS" "phppgadmin"
	$HESTIA/bin/v-change-sys-db-alias 'pga' "phppgadmin"

	# Limit access to /etc/phppgadmin/
	chown -R root:hestiamail /etc/phppgadmin/
	chmod 640 /etc/phppgadmin/config.inc.php
fi

#----------------------------------------------------------#
#                      Configure Bind                      #
#----------------------------------------------------------#

if [ "$named" = 'yes' ]; then
	echo "[ * ] Configuring Bind DNS server..."
	cp -f $HESTIA_INSTALL_DIR/bind/named.conf /etc/bind/
	cp -f $HESTIA_INSTALL_DIR/bind/named.conf.options /etc/bind/
	chown root:bind /etc/bind/named.conf
	chown root:bind /etc/bind/named.conf.options
	chown bind:bind /var/cache/bind
	chmod 640 /etc/bind/named.conf
	chmod 640 /etc/bind/named.conf.options
	aa-complain /usr/sbin/named > /dev/null 2>&1
	echo "/home/** rwm," >> /etc/apparmor.d/local/usr.sbin.named 2> /dev/null
	if ! grep --quiet lxc /proc/1/environ; then
		systemctl status apparmor > /dev/null 2>&1
		if [ $? -ne 0 ]; then
			systemctl restart apparmor >> $LOG
		fi
	fi

	# Ubuntu 26.04 removed the named.conf.default-zones file if doesn't exsists remove it from the config file
	if [ ! -f /etc/bind/named.conf.default-zones ]; then
		sed -i "/^include.*named.conf.default-zones/d" /etc/bind/named.conf
	fi

	# Add root-hints include after named.conf.local if missing
	if [[ -f /etc/bind/named.conf.root-hints ]] \
		&& ! grep -q 'include.*named.conf.root-hints' /etc/bind/named.conf 2> /dev/null; then
		sed -i '/include.*named\.conf\.local/a include "\/etc\/bind\/named.conf.root-hints";' /etc/bind/named.conf
	fi

	update-rc.d bind9 defaults > /dev/null 2>&1
	systemctl start bind9
	check_result $? "bind9 start failed"

	# Workaround for OpenVZ/Virtuozzo
	if [ -e "/proc/vz/veinfo" ] && [ -e "/etc/rc.local" ]; then
		sed -i "s/^exit 0/service bind9 restart\nexit 0/" /etc/rc.local
	fi
fi

#----------------------------------------------------------#
#                      Configure Exim                      #
#----------------------------------------------------------#

if [ "$exim" = 'yes' ]; then
	echo "[ * ] Configuring Exim mail server..."
	gpasswd -a Debian-exim mail > /dev/null 2>&1
	exim_version=$(exim4 --version | head -1 | awk '{print $3}' | cut -f -2 -d .)
	# if Exim version > 4.9.4 or greater!
	if ! version_ge "4.94" "$exim_version"; then
		# Ubuntu 22.04 (Jammy) uses Exim 4.95 instead but config works with Exim4.94
		cp -f $HESTIA_INSTALL_DIR/exim/exim4.conf.4.95.template /etc/exim4/exim4.conf.template
	else
		cp -f $HESTIA_INSTALL_DIR/exim/exim4.conf.template /etc/exim4/
	fi
	# If Dovecot 2.4, modify the local delivery directives"
	if [[ $(dovecot --version) == 2.4* ]] \
		&& [[ -f /etc/exim4/exim4.conf.template ]]; then
		sed -i.bak '
s#  directory = "${extract{5}{:}{${lookup{$local_part}lsearch{/etc/exim4/domains/${lookup{$domain}dsearch{/etc/exim4/domains/}}/passwd}}}}/mail/${lookup{$domain}dsearch{/etc/exim4/domains/}}/${lookup{$local_part}dsearch{${extract{5}{:}{${lookup{$local_part}lsearch{/etc/exim4/domains/${lookup{$domain}dsearch{/etc/exim4/domains/}}/passwd}}}}/mail/${lookup{$domain}dsearch{/etc/exim4/domains/}}}}"#  directory = "${extract{5}{:}{${lookup{$local_part}lsearch{/etc/exim4/domains/${lookup{$domain}dsearch{/etc/exim4/domains/}}/passwd}}}}"#

s#  directory = "${extract{5}{:}{${lookup{$local_part}lsearch{/etc/exim4/domains/${lookup{$domain}dsearch{/etc/exim4/domains/}}/passwd}}}}/mail/${lookup{$domain}dsearch{/etc/exim4/domains/}}/${lookup{$local_part}dsearch{${extract{5}{:}{${lookup{$local_part}lsearch{/etc/exim4/domains/${lookup{$domain}dsearch{/etc/exim4/domains/}}/passwd}}}}/mail/${lookup{$domain}dsearch{/etc/exim4/domains/}}}}/.Spam"#  directory = "${extract{5}{:}{${lookup{$local_part}lsearch{/etc/exim4/domains/${lookup{$domain}dsearch{/etc/exim4/domains/}}/passwd}}}}/.Spam"#

s#  quota_directory = "${extract{5}{:}{${lookup{$local_part}lsearch{/etc/exim4/domains/${lookup{$domain}dsearch{/etc/exim4/domains/}}/passwd}}}}/mail/${lookup{$domain}dsearch{/etc/exim4/domains/}}/${lookup{$local_part}dsearch{${extract{5}{:}{${lookup{$local_part}lsearch{/etc/exim4/domains/${lookup{$domain}dsearch{/etc/exim4/domains/}}/passwd}}}}/mail/${lookup{$domain}dsearch{/etc/exim4/domains/}}}}"#  quota_directory = "${extract{5}{:}{${lookup{$local_part}lsearch{/etc/exim4/domains/${lookup{$domain}dsearch{/etc/exim4/domains/}}/passwd}}}}"#
' /etc/exim4/exim4.conf.template
	fi

	cp -f $HESTIA_INSTALL_DIR/exim/dnsbl.conf /etc/exim4/
	cp -f $HESTIA_INSTALL_DIR/exim/spam-blocks.conf /etc/exim4/
	cp -f $HESTIA_INSTALL_DIR/exim/limit.conf /etc/exim4/
	cp -f $HESTIA_INSTALL_DIR/exim/system.filter /etc/exim4/
	touch /etc/exim4/white-blocks.conf

	if [ "$spamd" = 'yes' ]; then
		sed -i "s/#SPAM/SPAM/g" /etc/exim4/exim4.conf.template
	fi
	if [ "$clamd" = 'yes' ]; then
		sed -i "s/#CLAMD/CLAMD/g" /etc/exim4/exim4.conf.template
	fi

	# Generate SRS KEY If not support just created it will get ignored anyway
	srs=$(gen_pass)
	echo $srs > /etc/exim4/srs.conf
	chmod 640 /etc/exim4/srs.conf
	chmod 640 /etc/exim4/exim4.conf.template
	chown root:Debian-exim /etc/exim4/srs.conf

	rm -rf /etc/exim4/domains
	mkdir -p /etc/exim4/domains

	rm -f /etc/alternatives/mta
	ln -s /usr/sbin/exim4 /etc/alternatives/mta
	update-rc.d -f sendmail remove > /dev/null 2>&1
	systemctl stop sendmail > /dev/null 2>&1
	update-rc.d -f postfix remove > /dev/null 2>&1
	systemctl stop postfix > /dev/null 2>&1
	update-rc.d exim4 defaults
	systemctl start exim4 >> $LOG
	check_result $? "exim4 start failed"
fi

#----------------------------------------------------------#
#                     Configure Dovecot                    #
#----------------------------------------------------------#

if [ "$dovecot" = 'yes' ]; then
	dovecot_version="$(dovecot --version | cut -f -2 -d .)"
	echo "[ * ] Configuring Dovecot POP/IMAP mail server..."
	gpasswd -a dovecot mail > /dev/null 2>&1
	mkdir -p /etc/dovecot/conf.d/
	if [[ "$dovecot_version" = "2.4" ]]; then
		cp -f $HESTIA_COMMON_DIR/dovecot/2.4/dovecot.conf /etc/dovecot/
		cp -f $HESTIA_COMMON_DIR/dovecot/2.4/conf.d/* /etc/dovecot/conf.d/
	else
		cp -f $HESTIA_COMMON_DIR/dovecot/2.3/dovecot.conf /etc/dovecot/
		cp -f $HESTIA_COMMON_DIR/dovecot/2.3/conf.d/* /etc/dovecot/conf.d/
		rm -f /etc/dovecot/conf.d/15-mailboxes.conf
	fi
	cp -f $HESTIA_INSTALL_DIR/logrotate/dovecot /etc/logrotate.d/
	chown -R root:root /etc/dovecot*
	touch /var/log/dovecot.log
	chown -R dovecot:mail /var/log/dovecot.log
	chmod 660 /var/log/dovecot.log
	# Alter config for 2.2
	if [ "$dovecot_version" = "2.2" ]; then
		echo "[ * ] Downgrade dovecot config to sync with 2.2 settings"
		sed -i 's|#ssl_dh_parameters_length = 4096|ssl_dh_parameters_length = 4096|g' /etc/dovecot/conf.d/10-ssl.conf
		sed -i 's|ssl_dh = </etc/ssl/dhparam.pem|#ssl_dh = </etc/ssl/dhparam.pem|g' /etc/dovecot/conf.d/10-ssl.conf
		sed -i 's|ssl_min_protocol = TLSv1.2|ssl_protocols = !SSLv3 !TLSv1 !TLSv1.1|g' /etc/dovecot/conf.d/10-ssl.conf
	fi
	update-rc.d dovecot defaults
	systemctl start dovecot >> $LOG
	check_result $? "dovecot start failed"
fi

#----------------------------------------------------------#
#                     Configure ClamAV                     #
#----------------------------------------------------------#

if [ "$clamd" = 'yes' ]; then
	gpasswd -a clamav mail > /dev/null 2>&1
	gpasswd -a clamav Debian-exim > /dev/null 2>&1
	cp -f $HESTIA_INSTALL_DIR/clamav/clamd.conf /etc/clamav/
	update-rc.d clamav-daemon defaults
	echo -ne "[ * ] Installing ClamAV anti-virus definitions... "
	hst_run "Update ClamAV definitions" /usr/bin/freshclam
	systemctl start clamav-daemon >> $LOG
	check_result $? "clamav-daemon start failed"
fi

#----------------------------------------------------------#
#                  Configure SpamAssassin                  #
#----------------------------------------------------------#
if [ "$spamd" = 'yes' ]; then
	# Set SpamAssassin Service Name
	if [ "$release" = '22.04' ]; then
		spamd_srvname="spamassassin"
	else
		spamd_srvname="spamd"
	fi
	echo "[ * ] Configuring SpamAssassin..."
	update-rc.d $spamd_srvname defaults > /dev/null 2>&1
	sed -i "s/ENABLED=0/ENABLED=1/" /etc/default/$spamd_srvname
	systemctl start $spamd_srvname >> $LOG
	check_result $? "$spamd_srvname start failed"
	unit_files="$(systemctl list-unit-files | grep spamassassin)"
	if [[ "$unit_files" =~ "disabled" ]]; then
		systemctl enable $spamd_srvname > /dev/null 2>&1
	fi
	sed -i "s/#CRON=1/CRON=1/" /etc/default/$spamd_srvname
fi

#----------------------------------------------------------#
#                    Configure Fail2Ban                    #
#----------------------------------------------------------#

if [ "$fail2ban" = 'yes' ]; then
	echo "[ * ] Configuring fail2ban access monitor..."
	cp -rf $HESTIA_INSTALL_DIR/fail2ban /etc/
	if [ "$dovecot" = 'no' ]; then
		fline=$(cat /etc/fail2ban/jail.local | grep -n dovecot-iptables -A 2)
		fline=$(echo "$fline" | grep enabled | tail -n1 | cut -f 1 -d -)
		sed -i "${fline}s/true/false/" /etc/fail2ban/jail.local
	fi
	if [ "$exim" = 'no' ]; then
		fline=$(cat /etc/fail2ban/jail.local | grep -n exim-iptables -A 2)
		fline=$(echo "$fline" | grep enabled | tail -n1 | cut -f 1 -d -)
		sed -i "${fline}s/true/false/" /etc/fail2ban/jail.local
	fi
	if [ "$vsftpd" = 'yes' ]; then
		# Create vsftpd Log File
		if [ ! -f "/var/log/vsftpd.log" ]; then
			touch /var/log/vsftpd.log
		fi
		fline=$(cat /etc/fail2ban/jail.local | grep -n vsftpd-iptables -A 2)
		fline=$(echo "$fline" | grep enabled | tail -n1 | cut -f 1 -d -)
		sed -i "${fline}s/false/true/" /etc/fail2ban/jail.local
	fi
	if [ -f /etc/fail2ban/jail.d/defaults-debian.conf ]; then
		rm -f /etc/fail2ban/jail.d/defaults-debian.conf
	fi

	update-rc.d fail2ban defaults
	# Ubuntu 22.04 doesn't start F2B by default on boot
	update-rc.d fail2ban enable
	systemctl start fail2ban >> $LOG
	check_result $? "fail2ban start failed"
fi

# Configuring MariaDB/MySQL host
if [ "$mysql" = 'yes' ] || [ "$mysql8" = 'yes' ]; then
	(umask 077; printf '%s\n' "$mpass" > "$HST_STAGE_DIR/mysql-password") || hst_fail 'Cannot stage database password'
	hst_run "Register MySQL host" "$HESTIA/bin/v-add-database-host" mysql localhost root "$HST_STAGE_DIR/mysql-password"
	rm -f -- "$HST_STAGE_DIR/mysql-password"
	unset mpass
fi

# Configuring PostgreSQL host
if [ "$postgresql" = 'yes' ]; then
	(umask 077; printf '%s\n' "$ppass" > "$HST_STAGE_DIR/pgsql-password") || hst_fail 'Cannot stage database password'
	hst_run "Register PostgreSQL host" "$HESTIA/bin/v-add-database-host" pgsql localhost postgres "$HST_STAGE_DIR/pgsql-password"
	rm -f -- "$HST_STAGE_DIR/pgsql-password"
	unset ppass
fi

#----------------------------------------------------------#
#                       Install Roundcube                  #
#----------------------------------------------------------#

# Min requirements Dovecot + Exim + Mysql
if ([ "$mysql" == 'yes' ] || [ "$mysql8" == 'yes' ]) && [ "$dovecot" == "yes" ]; then
	echo "[ * ] Installing Roundcube..."
	hst_run "Install locked Roundcube" "$HESTIA/bin/v-add-sys-roundcube"
	write_config_value "WEBMAIL_ALIAS" "webmail"
else
	write_config_value "WEBMAIL_ALIAS" ""
	write_config_value "WEBMAIL_SYSTEM" ""
fi

#----------------------------------------------------------#
#                     Install Sieve                        #
#----------------------------------------------------------#

# Min requirements Dovecot + Exim + Mysql + Roundcube
if [ "$sieve" = 'yes' ]; then
	# Folder paths
	RC_INSTALL_DIR="/var/lib/roundcube"
	RC_CONFIG_DIR="/etc/roundcube"

	echo "[ * ] Installing Sieve Mail Filter..."

	dovecot_version="$(dovecot --version | cut -f -2 -d .)"
	if [[ "$dovecot_version" = "2.4" ]]; then
		# dovecot conf files
		# dovecot.conf install
		sed -i -E 's/protocols = imap/protocols = sieve imap/' /etc/dovecot/dovecot.conf
		#  10-master.conf
		sed -i -E -z 's/    user = dovecot\n  \}\n\}/    user = dovecot\n  \}\n\n  unix_listener auth-master {\n    group = mail\n    mode = 0660\n    user = dovecot\n  }\n\}/' /etc/dovecot/conf.d/10-master.conf
		#  15-lda.conf
		sed -i '/^protocol lda {$/a\  mail_plugins = mail_compress quota sieve' /etc/dovecot/conf.d/15-lda.conf
		#  20-imap.conf
		sed -i "s/quota imap_quota/quota imap_quota imap_sieve/g" /etc/dovecot/conf.d/20-imap.conf
		# replace dovecot-sieve config files
		cp -f "$HESTIA_COMMON_DIR"/dovecot/2.4/sieve/* /etc/dovecot/conf.d

	else
		# dovecot.conf install
		sed -i "s/namespace/service stats \{\n  unix_listener stats-writer \{\n    group = mail\n    mode = 0660\n    user = dovecot\n  \}\n\}\n\nnamespace/g" /etc/dovecot/dovecot.conf

		# Dovecot conf files
		#  10-master.conf
		sed -i -E -z "s/  }\n  user = dovecot\n}/  \}\n  unix_listener auth-master \{\n    group = mail\n    mode = 0660\n    user = dovecot\n  \}\n  user = dovecot\n\}/g" /etc/dovecot/conf.d/10-master.conf
		#  15-lda.conf
		sed -i "s/\#mail_plugins = \\\$mail_plugins/mail_plugins = \$mail_plugins quota sieve\n  auth_socket_path = \/var\/run\/dovecot\/auth-master/g" /etc/dovecot/conf.d/15-lda.conf
		#  20-imap.conf
		sed -i "s/mail_plugins = quota imap_quota/mail_plugins = quota imap_quota imap_sieve/g" /etc/dovecot/conf.d/20-imap.conf

		# Replace dovecot-sieve config files
		cp -f $HESTIA_COMMON_DIR/dovecot/2.3/sieve/* /etc/dovecot/conf.d
	fi

	# Dovecot default file install
	mkdir -p /etc/dovecot/sieve/
	echo -e "require [\"fileinto\"];\n# rule:[SPAM]\nif header :contains \"X-Spam-Flag\" \"YES\" {\n    fileinto \"INBOX.Spam\";\n}\n" > /etc/dovecot/sieve/default

	# exim4 install
	sed -i "s/\stransport = local_delivery/ transport = dovecot_virtual_delivery/" /etc/exim4/exim4.conf.template
	sed -i "s/address_pipe:/dovecot_virtual_delivery:\n  driver = pipe\n  command = \/usr\/lib\/dovecot\/dovecot-lda -e -d \${extract{1}{:}{\${lookup{\$local_part}lsearch{\/etc\/exim4\/domains\/\${lookup{\$domain}dsearch{\/etc\/exim4\/domains\/}}\/accounts}}}}@\${lookup{\$domain}dsearch{\/etc\/exim4\/domains\/}}\n  delivery_date_add\n  envelope_to_add\n  return_path_add\n  log_output = true\n  log_defer_output = true\n  user = \${extract{2}{:}{\${lookup{\$local_part}lsearch{\/etc\/exim4\/domains\/\${lookup{\$domain}dsearch{\/etc\/exim4\/domains\/}}\/passwd}}}}\n  group = mail\n  return_output\n\naddress_pipe:/g" /etc/exim4/exim4.conf.template

	# Permission changes
	touch /var/log/dovecot.log
	chown -R dovecot:mail /var/log/dovecot.log
	chmod 660 /var/log/dovecot.log

	if [ -d "/var/lib/roundcube" ]; then
		# Modify Roundcube config
		mkdir -p $RC_CONFIG_DIR/plugins/managesieve
		cp -f $HESTIA_COMMON_DIR/roundcube/plugins/config_managesieve.inc.php $RC_CONFIG_DIR/plugins/managesieve/config.inc.php
		ln -s $RC_CONFIG_DIR/plugins/managesieve/config.inc.php $RC_INSTALL_DIR/plugins/managesieve/config.inc.php
		chown -R hestiamail:www-data $RC_CONFIG_DIR/
		chmod 751 -R $RC_CONFIG_DIR
		chmod 644 $RC_CONFIG_DIR/*.php
		chmod 644 $RC_CONFIG_DIR/plugins/managesieve/config.inc.php
		sed -i "s/\"archive\"/\"archive\", \"managesieve\"/g" $RC_CONFIG_DIR/config.inc.php
		chmod 640 $RC_CONFIG_DIR/config.inc.php
	fi

	# Restart Dovecot and Exim4
	systemctl restart dovecot > /dev/null 2>&1
	systemctl restart exim4 > /dev/null 2>&1
fi

#----------------------------------------------------------#
#                       Configure API                      #
#----------------------------------------------------------#

if [ "$api" = "yes" ]; then
	# Keep legacy api enabled until transition is complete
	write_config_value "API" "yes"
	write_config_value "API_SYSTEM" "1"
	write_config_value "API_ALLOWED_IP" ""
else
	write_config_value "API" "no"
	write_config_value "API_SYSTEM" "0"
	write_config_value "API_ALLOWED_IP" ""
	$HESTIA/bin/v-change-sys-api disable
fi

#----------------------------------------------------------#
#                  Configure File Manager                  #
#----------------------------------------------------------#

echo "[ * ] Configuring File Manager..."
hst_run "Install File Manager" "$HESTIA/bin/v-add-sys-filemanager" quiet
# Configuring sudoers to remove unsupported requiretty option on Ubuntu 26.04
ubuntu_major="${release%%.*}"
if [[ "$ubuntu_major" -ge 26 ]]; then
	echo 'KexAlgorithms +diffie-hellman-group-exchange-sha256' > /etc/ssh/sshd_config.d/hestia-kex.conf
fi

#----------------------------------------------------------#
#              Configure Web terminal                      #
#----------------------------------------------------------#

# Web terminal
if [ "$webterminal" = 'yes' ]; then
	write_config_value "WEB_TERMINAL" "true"
	systemctl daemon-reload > /dev/null 2>&1
	systemctl enable hestia-web-terminal > /dev/null 2>&1
	systemctl restart hestia-web-terminal > /dev/null 2>&1
else
	write_config_value "WEB_TERMINAL" "false"
fi

#----------------------------------------------------------#
#                  Configure dependencies                  #
#----------------------------------------------------------#

echo "[ * ] Configuring PHP dependencies..."
hst_run "Install PHP dependencies" "$HESTIA/bin/v-add-sys-dependencies" quiet

echo "[ * ] Installing Rclone & Update Restic ..."
# Rclone and Restic were installed from authenticated APT repositories.
command -v rclone >/dev/null && command -v restic >/dev/null || hst_fail "Backup tools missing"

#----------------------------------------------------------#
#                   Configure IP                           #
#----------------------------------------------------------#

# Configuring system IPs
echo "[ * ] Configuring System IP..."
$HESTIA/bin/v-update-sys-ip > /dev/null 2>&1

# Get primary IP
default_nic="$(ip -d -j route show | jq -r '.[] | if .dst == "default" then .dev else empty end')"
# IPv4
primary_ipv4="$(ip -4 -d -j addr show "$default_nic" | jq -r '.[] | select(length > 0) | .addr_info[] | if .scope == "global" then .local else empty end' | head -n1)"
# IPv6
#primary_ipv6="$(ip -6 -d -j addr show "$default_nic" | jq -r '.[] | select(length > 0) | .addr_info[] | if .scope == "global" then .local else empty end' | head -n1)"
ip="$primary_ipv4"
local_ip="$primary_ipv4"

# Configuring firewall
if [ "$iptables" = 'yes' ]; then
	$HESTIA/bin/v-update-firewall
fi

# Get public IP
pub_ipv4="$(curl -fsLm5 --retry 2 --ipv4 https://ip.hestiacp.com/)"
if [ -n "$pub_ipv4" ] && [ "$pub_ipv4" != "$ip" ]; then
	if [ -e /etc/rc.local ]; then
		sed -i '/exit 0/d' /etc/rc.local
	else
		touch /etc/rc.local
	fi

	check_rclocal=$(cat /etc/rc.local | grep "#!")
	if [ -z "$check_rclocal" ]; then
		echo "#!/bin/sh" >> /etc/rc.local
	fi

	# Fix for Proxmox VE containers where hostname is reset to non-FQDN format on reboot
	check_pve=$(uname -r | grep pve)
	if [ ! -z "$check_pve" ]; then
		echo 'hostname=$(hostname --fqdn)' >> /etc/rc.local
		echo ""$HESTIA/bin/v-change-sys-hostname" "'"$hostname"'"" >> /etc/rc.local
	fi
	echo "$HESTIA/bin/v-update-sys-ip" >> /etc/rc.local
	echo "exit 0" >> /etc/rc.local
	chmod +x /etc/rc.local
	systemctl enable rc-local > /dev/null 2>&1
	$HESTIA/bin/v-change-sys-ip-nat "$ip" "$pub_ipv4" > /dev/null 2>&1
	ip="$pub_ipv4"
fi

# Configuring libapache2-mod-remoteip
if [ "$apache" = 'yes' ] && [ "$nginx" = 'yes' ]; then
	cd /etc/apache2/mods-available
	echo "<IfModule mod_remoteip.c>" > remoteip.conf
	echo "  RemoteIPHeader X-Real-IP" >> remoteip.conf
	if [ "$local_ip" != "127.0.0.1" ] && [ "$pub_ipv4" != "127.0.0.1" ]; then
		echo "  RemoteIPInternalProxy 127.0.0.1" >> remoteip.conf
	fi
	if [ -n "$local_ip" ] && [ "$local_ip" != "$pub_ipv4" ]; then
		echo "  RemoteIPInternalProxy $local_ip" >> remoteip.conf
	fi
	if [ -n "$pub_ipv4" ]; then
		echo "  RemoteIPInternalProxy $pub_ipv4" >> remoteip.conf
	fi
	echo "</IfModule>" >> remoteip.conf
	sed -i "s/LogFormat \"%h/LogFormat \"%a/g" /etc/apache2/apache2.conf
	a2enmod remoteip >> $LOG
	systemctl restart apache2
fi

# Adding default domain
$HESTIA/bin/v-add-web-domain "$username" "$servername" "$ip"
check_result $? "can't create $servername domain"

# Adding cron jobs
export SCHEDULED_RESTART="yes"

min=$(gen_pass '012345' '2')
hour=$(gen_pass '1234567' '1')
echo "MAILTO=\"\"" > /var/spool/cron/crontabs/hestiaweb
echo "CONTENT_TYPE=\"text/plain; charset=utf-8\"" >> /var/spool/cron/crontabs/hestiaweb
echo "*/2 * * * * sudo /usr/local/hestia/bin/v-update-sys-queue restart" >> /var/spool/cron/crontabs/hestiaweb
echo "10 00 * * * sudo /usr/local/hestia/bin/v-update-sys-queue daily" >> /var/spool/cron/crontabs/hestiaweb
echo "15 02 * * * sudo /usr/local/hestia/bin/v-update-sys-queue disk" >> /var/spool/cron/crontabs/hestiaweb
echo "10 00 * * * sudo /usr/local/hestia/bin/v-update-sys-queue traffic" >> /var/spool/cron/crontabs/hestiaweb
echo "30 03 * * * sudo /usr/local/hestia/bin/v-update-sys-queue webstats" >> /var/spool/cron/crontabs/hestiaweb
echo "*/5 * * * * sudo /usr/local/hestia/bin/v-update-sys-queue backup" >> /var/spool/cron/crontabs/hestiaweb
echo "10 05 * * * sudo /usr/local/hestia/bin/v-backup-users" >> /var/spool/cron/crontabs/hestiaweb
echo "20 00 * * * sudo /usr/local/hestia/bin/v-update-user-stats" >> /var/spool/cron/crontabs/hestiaweb
echo "*/5 * * * * sudo /usr/local/hestia/bin/v-update-sys-rrd" >> /var/spool/cron/crontabs/hestiaweb
echo "$min $hour * * * sudo /usr/local/hestia/bin/v-update-letsencrypt-ssl" >> /var/spool/cron/crontabs/hestiaweb
echo "41 4 * * * sudo /usr/local/hestia/bin/v-update-sys-hestia-all" >> /var/spool/cron/crontabs/hestiaweb

chmod 600 /var/spool/cron/crontabs/hestiaweb
chown hestiaweb:hestiaweb /var/spool/cron/crontabs/hestiaweb

# Enable automatic updates
$HESTIA/bin/v-add-cron-hestia-autoupdate apt

# Building initial rrd images
$HESTIA/bin/v-update-sys-rrd

# Enabling file system quota
if [ "$quota" = 'yes' ]; then
	echo "[ * ] Configuring quota..."
	$HESTIA/bin/v-add-sys-quota
fi

# Set backend port
$HESTIA/bin/v-change-sys-port $port > /dev/null 2>&1

# Create default configuration files
$HESTIA/bin/v-update-sys-defaults

# Update remaining packages since repositories have changed
echo -ne "[ * ] Installing remaining software updates..."
hst_run "Refresh package indexes" apt-get -qq update
hst_run "Final package upgrade" apt-get -y upgrade
echo

# Starting Hestia service
update-rc.d hestia defaults
systemctl start hestia
check_result $? "hestia start failed"
chown hestiaweb:hestiaweb $HESTIA/data/sessions

# Create backup folder and set correct permission
mkdir -p /backup/
chmod 755 /backup/

# Create cronjob to generate ssl
echo "*/15 * * * * root PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' /usr/local/hestia/bin/v-add-letsencrypt-host >/dev/null 2>&1 && rm -f /etc/cron.d/hestia-ssl" > /etc/cron.d/hestia-ssl

#----------------------------------------------------------#
#              Set hestia.conf default values              #
#----------------------------------------------------------#

echo "[ * ] Updating configuration files..."
BIN="$HESTIA/bin"
source $HESTIA/func/syshealth.sh
syshealth_repair_system_config

# Add /usr/local/hestia/bin/ to PATH variable in .bashrc if it exists
[[ -f /root/.bashrc ]] && echo 'if [ "${PATH#*/usr/local/hestia/bin*}" = "$PATH" ]; then
    . /etc/profile.d/hestia.sh
fi' >> /root/.bashrc

# Add /usr/local/hestia/bin/ to PATH variable in .zshrc if it exists
[[ -f /root/.zshrc ]] && echo 'if [ "${PATH#*/usr/local/hestia/bin*}" = "$PATH" ]; then
    . /etc/profile.d/hestia.sh
fi' >> /root/.zshrc

hst_run "Activate professional theme" "$HESTIA/bin/v-change-user-theme" "$username" professional
hst_run "Record actual component inventory" python3 "$HESTIA/professional/inventory.py" --write
hst_run "Validate installation" python3 "$HESTIA/professional/health.py" --installation-check
hst_run "Enable professional monitor and update hook" python3 "$HESTIA/professional/apply.py" --root "$HESTIA" --source "$HST_BUNDLE_ROOT" --enable-services

#----------------------------------------------------------#
#                   Hestia Access Info                     #
#----------------------------------------------------------#

# Comparing hostname and IP
host_ip=$(host $servername | head -n 1 | awk '{print $NF}')
if [ "$host_ip" = "$ip" ]; then
	ip="$servername"
fi

echo -e "\n"
echo "===================================================================="
echo -e "\n"

# Sending notification to admin email
echo -e "Congratulations!

You have successfully installed Hestia Control Panel on your server.

Ready to get started? Log in using the following credentials:

	Admin URL:  https://$servername:$port" > $tmpfile
if [ "$host_ip" != "$ip" ]; then
	echo "	Backup URL: https://$ip:$port" >> $tmpfile
fi
echo -e -n " 	Username:   $username
	Password:   $displaypass

Thank you for choosing Hestia Control Panel to power your full stack web server,
we hope that you enjoy using it as much as we do!

Please feel free to contact us at any time if you have any questions,
or if you encounter any bugs or problems:

Documentation:  https://docs.hestiacp.com/
Forum:          https://forum.hestiacp.com/
GitHub:         https://www.github.com/hestiacp/hestiacp

Note: Automatic updates are enabled by default. If you would like to disable them,
please log in and navigate to Server > Updates to turn them off.

Help support the Hestia Control Panel project by donating via PayPal:
https://www.hestiacp.com/donate

--
Sincerely yours,
The Hestia Control Panel development team

Made with love & pride by the open-source community around the world.
" >> $tmpfile

send_mail="$HESTIA/web/inc/mail-wrapper.php"
cat $tmpfile | $send_mail -s "Hestia Control Panel" $email

# Congrats
echo
cat $tmpfile
rm -f $tmpfile

# Add welcome message to notification panel
$HESTIA/bin/v-add-user-notification "$username" 'Welcome to Hestia Control Panel!' '<p>You are now ready to begin adding <a href="/add/user/">user accounts</a> and <a href="/add/web/">domains</a>. For help and assistance, <a href="https://hestiacp.com/docs/" target="_blank">view the documentation</a> or <a href="https://forum.hestiacp.com/" target="_blank">visit our forum</a>.</p><p>Please <a href="https://github.com/hestiacp/hestiacp/issues" target="_blank">report any issues via GitHub</a>.</p><p class="u-text-bold">Have a wonderful day!</p><p><i class="fas fa-heart icon-red"></i> The Hestia Control Panel development team</p>'

# Final health and overlay activation must succeed before any success return.
# Clean-up
# Sort final configuration file
sort_config_file

printf '[ ! ] Restart the server after reviewing the completed installation log.\n'
# EOF
