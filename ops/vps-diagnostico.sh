#!/bin/bash
# Read-only server inspection. Intended as an SSH forced command for a dedicated key.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C

if (($#)); then
    printf 'Este diagnostico nao aceita argumentos.\n' >&2
    exit 64
fi
if [[ -n ${SSH_ORIGINAL_COMMAND:-} && $SSH_ORIGINAL_COMMAND != /usr/local/sbin/hestia-github-diagnostico ]]; then
    printf 'Comando remoto nao permitido.\n' >&2
    exit 64
fi

printf '%s\n' '=== Conexao SSH estabelecida ==='
printf 'Usuario: '; id -un
printf 'Kernel: '; uname -srmo
printf '\n%s\n' '=== Sistema operacional ==='
if [[ -r /etc/os-release ]]; then awk '/^(ID|VERSION_ID|PRETTY_NAME)=/' /etc/os-release; fi

printf '\n%s\n' '=== Paineis e pilhas detectados ==='
found=no
for path in /usr/local/hestia /usr/local/CyberCP /usr/local/lsws /www/server/panel /usr/local/cpanel; do
    if [[ -d $path ]]; then printf 'Presente: %s\n' "$path"; found=yes; fi
done
[[ $found == yes ]] || printf 'Nenhum dos caminhos conhecidos foi encontrado.\n'

printf '\n%s\n' '=== PHP CLI ==='
for binary in php php8.4; do
    if command -v "$binary" >/dev/null 2>&1; then
        printf '%s: ' "$binary"
        "$binary" -n -r 'echo PHP_VERSION, PHP_EOL;' 2>/dev/null || printf 'Falha na leitura da versao\n'
    fi
done

printf '\n%s\n' '=== Estado dos servicos ==='
if command -v systemctl >/dev/null 2>&1; then
    for service in hestia lsws lscpd nginx apache2 mariadb mysql; do
        state=$(systemctl is-active "$service" 2>/dev/null) || true
        printf '%s: %s\n' "$service" "${state:-indisponivel}"
    done
fi

printf '\n%s\n' '=== Armazenamento ==='
df -h / || true
printf '\n%s\n' '=== Memoria ==='
if command -v free >/dev/null 2>&1; then free -m; fi
printf '\n%s\n' 'Diagnostico concluido. Nenhuma instalacao ou alteracao de configuracao foi executada.'
