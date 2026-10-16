#!/bin/bash
# HestiaCP Professional local launcher; GPL-3.0; modified 2026-10-15.
set -o pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || exit 1
source "$SCRIPT_DIR/hst-common.sh" || exit 1
# Parse/help is handled by the selected child. No network, locale or APT changes here.
for arg in "$@"; do [[ $arg != --help && $arg != -h ]] || { hst_usage; exit 0; }; done
hst_os_detect || hst_fail 'Supported: Debian 12/13; Ubuntu 22.04/24.04/26.04 LTS'
child="$SCRIPT_DIR/hst-install-$HST_OS.sh"
[[ -f $child && ! -L $child ]] || hst_fail 'Bundle incomplete: local installer missing'
bash -n "$child" || hst_fail 'Local installer syntax error'
exec bash "$child" "$@"
