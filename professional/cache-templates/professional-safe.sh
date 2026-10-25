#!/bin/bash
# HESTIA_PRO_BUSINESS_V1
set -eu
[[ $EUID == 0 && $# -ge 2 && $1 =~ ^[a-z][a-z0-9_]{1,29}$ ]] || exit 1
exec /usr/bin/python3 -I /usr/local/hestia/professional/cache_pool_entry.py "$1" "$2"
