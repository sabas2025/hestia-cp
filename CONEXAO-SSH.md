# Hestia CP — preparação de conexão à VPS

Este repositório contém um fluxo **manual de diagnóstico SSH** para a VPS. Acesso solicitado: usuário `root`, porta `22`. O IP precisa ser confirmado pelo proprietário.

O fluxo executa somente `/usr/local/sbin/hestia-github-diagnostico`. Ele consulta sistema, diretórios de painéis, versões PHP, serviços, disco e memória. Não instala o Hestia, não publica a aplicação e não lê senhas, tokens ou arquivos de configuração privados.

## 1. Criar uma chave dedicada

No seu computador, crie uma chave exclusiva para esse diagnóstico:

```bash
ssh-keygen -t ed25519 -C github-hestia-diagnostico -f github-hestia-diagnostico
```

Use uma chave dedicada sem passphrase para esse fluxo e restrinja sua permissão no servidor conforme a próxima etapa. A chave pública termina em `.pub`; a chave privada é o arquivo sem `.pub`. A chave privada deve ser colocada somente no Secret correspondente do GitHub, sem passar pelo chat ou pelo repositório.

## 2. Preparar o comando restrito na VPS

No console confiável da VPS, como root, baixe e revise o script:

```bash
wget -O /root/vps-diagnostico.sh https://raw.githubusercontent.com/sabas2025/hestia-cp/main/ops/vps-diagnostico.sh
bash -n /root/vps-diagnostico.sh
```

Depois de revisar o conteúdo, instale o comando:

```bash
install -o root -g root -m 0755 /root/vps-diagnostico.sh /usr/local/sbin/hestia-github-diagnostico
```

Acrescente em `/root/.ssh/authorized_keys` a chave pública dedicada, com estas opções na mesma linha, preservando as chaves já existentes:

```text
restrict,command="/usr/local/sbin/hestia-github-diagnostico" ssh-ed25519 SUA_CHAVE_PUBLICA github-hestia-diagnostico
```

O diretório `/root/.ssh` deve pertencer a root com modo 0700; `authorized_keys`, a root com modo 0600. A restrição prende essa chave ao diagnóstico e impede seu uso como terminal geral ou encaminhamento SSH.

## 3. Conferir a identidade do servidor

No console confiável da VPS, consulte a fingerprint e a chave pública do host:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
cat /etc/ssh/ssh_host_ed25519_key.pub
```

Construa a linha `known_hosts` com o IP confirmado e a chave do host, sem alterar os valores:

```text
IP_CONFIRMADO ssh-ed25519 CHAVE_PUBLICA_DO_HOST
```

A chave pública do host é diferente da chave pública dedicada do usuário. O fluxo não aceita automaticamente uma chave de host obtida da rede.

## 4. Cadastrar os Secrets

Abra **Settings → Secrets and variables → Actions → New repository secret**:

| Nome | Conteúdo |
|---|---|
| `VPS_HOST` | IP ou hostname confirmado da VPS |
| `VPS_SSH_KEY` | Conteúdo completo da chave privada dedicada, incluindo BEGIN e END |
| `VPS_KNOWN_HOSTS` | Linha `known_hosts` conferida no console da VPS |

Configuração: https://github.com/sabas2025/hestia-cp/settings/secrets/actions

O conector utilizado nesta conversa não permite cadastrar ou ler Secrets. Essa etapa deve ser feita pelo proprietário no GitHub.

## 5. Executar

Abra **Actions → Diagnostico SSH da VPS → Run workflow → main → Run workflow**. O workflow não roda em push, pull request ou agendamento. Seus logs mostrarão o resultado do diagnóstico; a conexão só estará confirmada após uma execução bem-sucedida.

O código completo do pacote HestiaCP Professional está neste repositório; consulte `PROFISSIONAL.md` e `ENTREGA.md`. Este workflow continua dedicado à conexão e ao diagnóstico inicial. Instalar ou migrar o painel é uma etapa posterior; o instalador do Hestia exige sistema limpo.
