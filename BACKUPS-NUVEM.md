> **Operação atual 1.1.1:** leia [CORRECOES-1.1.1.md](CORRECOES-1.1.1.md) antes de usar os procedimentos abaixo. A2F, estados WAF, drill histórico e disponibilidade do File Manager foram alterados. O texto 1.0/1.1 abaixo permanece como referência histórica onde houver diferença.

# Backup de sites e bancos em nuvem — versão 1.1

O novo `professional/cloud_backup.py` cria um backup nativo de uma conta Hestia e envia uma cópia criptografada pelo Restic para cada destino configurado. O Rclone fornece os transportes. A operação começa em modo de planejamento e exige `--apply` para executar.

## Destinos

| Provider | Backend Rclone | Configuração exigida |
|---|---|---|
| `google-drive` | `drive` | OAuth próprio, pasta dedicada e configuração privada |
| `amazon-s3` | `s3`, provider `AWS` | Bucket e IAM limitados ao prefixo de backup |
| `private-s3` | `s3` | MinIO ou outro S3 compatível, com endpoint HTTPS |
| `ftps` | `ftp` | `explicit_tls = true` ou `tls = true`; certificado verificado |
| `ftp` | `ftp` | `allow_plain_ftp: true` explicitamente; os dados do Restic são criptografados, mas FTP expõe autenticação e metadados do transporte |
| `sftp` | `sftp` | Chave dedicada e `known_hosts_file` previamente conferido |
| `private-webdav` | `webdav` | Endpoint HTTPS de nuvem privada/Nextcloud |

O código recusa remotes inline, caminhos com `..`, TLS desativado, comandos externos no arquivo de transporte, arquivos permissivos e symlinks. Cada arquivo Rclone deve conter **um único remote**, compatível com o provider declarado. Configurações criptografadas do próprio Rclone não são aceitas por este validador; use arquivo root/0600 protegido no sistema. O conteúdo do backup continua criptografado pelo Restic.

## Configuração inicial

Use uma VPS de homologação com Hestia 1.10.5. Instale Restic e Rclone pelos repositórios autenticados do sistema, verifique as versões e a disponibilidade de `rclone serve restic --stdio`. Ative o backup **local** do Hestia; `BACKUP_SYSTEM` deve incluir `local`. Mantenha capacidade para o arquivo nativo, uma cópia privada temporária e recuperação. A cópia fica sob `data/professional-staging`, com margem mínima de espaço de 20%, e é removida ao concluir. As permissões e o dono do arquivo nativo são preservados para manter o download pelo painel funcionando.

```bash
install -d -o root -g root -m 0700 /etc/hestiacp/professional/secrets
install -o root -g root -m 0600 professional/cloud-backup.example.json /etc/hestiacp/professional/cloud-backup.json
```

Edite o JSON privado e substitua os exemplos. Para cada destino, gere uma senha forte do Restic, guarde-a em um arquivo root/0600 e mantenha uma cópia independente fora da VPS. Perder a senha significa perder o acesso ao backup criptografado. Não use a mesma credencial IAM do ambiente de produção para manutenção destrutiva dos backups.

Configure cada remote no arquivo indicado:

```bash
rclone config --config /etc/hestiacp/professional/secrets/drive.conf
chmod 0600 /etc/hestiacp/professional/secrets/drive.conf
```

Autorize o Google Drive no fluxo OAuth do Rclone, preferencialmente com client ID próprio e escopo compatível com uma pasta dedicada. A central não coleta tokens. Para Amazon, configure o remote com provider AWS, região e credenciais de serviço limitadas. Para FTPS, configure o modo TLS correto do servidor e mantenha a validação de certificado. Para SFTP, use uma chave exclusiva e um arquivo de host keys conferido por um canal confiável; ambos root/0600 para este validador.

## Executar e agendar

Nos exemplos, substitua `hubapp` pela conta real. Depois de aplicar a camada em `/usr/local/hestia`, execute:

```bash
cd /usr/local/hestia
python3 professional/cloud_backup.py plan --user hubapp --config /etc/hestiacp/professional/cloud-backup.json
python3 professional/cloud_backup.py init --user hubapp --target drive-principal --config /etc/hestiacp/professional/cloud-backup.json --apply
python3 professional/cloud_backup.py init --user hubapp --target amazon-secundario --config /etc/hestiacp/professional/cloud-backup.json --apply
python3 professional/cloud_backup.py run --user hubapp --config /etc/hestiacp/professional/cloud-backup.json --apply
python3 professional/cloud_backup.py check --user hubapp --config /etc/hestiacp/professional/cloud-backup.json --apply
python3 professional/cloud_backup.py drill --user hubapp --target drive-principal --config /etc/hestiacp/professional/cloud-backup.json --apply
```

Inicialize **cada destino uma vez**. `run` produz um único arquivo nativo e tenta todos os destinos; uma falha não impede a tentativa dos seguintes. Sucesso parcial tem status de falha global e conserva o registro das cópias que terminaram. Os relatórios públicos não incluem senhas, tokens, caminhos de credenciais ou a saída de erro do provedor.

O timer fornecido roda às 03:15 no fuso do servidor, com até 20 minutos de variação. Habilite-o somente depois dos testes:

```bash
systemctl enable --now hestia-professional-cloud-backup@hubapp.timer
systemctl list-timers hestia-professional-cloud-backup@hubapp.timer
journalctl -u hestia-professional-cloud-backup@hubapp.service
```

Não habilite simultaneamente o timer antigo e o novo para a mesma conta. Eles compartilham o bloqueio por usuário. Ajuste frequência, RPO e RTO ao volume real: a configuração informa o objetivo, não garante que uma execução diária termine em menos de 24 horas. O timer tem timeout de 24 horas e cada comando externo, de 6 horas.

Retenção é uma operação explícita por destino:

```bash
python3 professional/cloud_backup.py retention --user hubapp --target drive-principal --config /etc/hestiacp/professional/cloud-backup.json --apply
```

São mantidos pontos diários, semanais e mensais, filtrados pela tag da conta. Retenção remove dados e não é agendada automaticamente. Configure versionamento/Object Lock ou um destino append-only independente conforme a política do provedor; o código não afirma configurar imutabilidade. Teste a convivência entre Object Lock e prune antes de habilitar retenção.

## O que é verificado

- Conta ativa, destino, configuração privada e arquivo nativo recém-criado.
- Presença de arquivo de dados de **cada site** e dump de **cada banco cadastrado** na conta. Exclusões nativas de web/DB que produzam cobertura incompleta interrompem o envio.
- Leitura dos cabeçalhos do tar sem extração privilegiada; entradas absolutas e `..` são recusadas.
- Hash SHA256 do arquivo, snapshot confirmado pelo Restic e checagem do repositório após envio.
- `check`: leitura amostral de 5% dos dados do repositório; não equivale a ler 100% dos blocos.
- `drill`: seleção de snapshot específico, margem de espaço de 20%, restauração verificada em temporário e conferência estrutural dos arquivos de sites/bancos. O diretório de teste é removido.

**Limites:** presença de dumps não demonstra que o SQL importa corretamente. O pacote não declara consistência transacional entre múltiplos serviços, nem testa o HUB/Tiny/VSM real. Backups de volumes Docker, banco PostgreSQL do listmonk, configuração privada dos novos serviços e arquivos fora da conta Hestia exigem rotinas adicionais. Não trate o backup da conta como cobertura automática de todos os volumes do servidor.

Antes de produção, execute uma importação SQL e restauração de aplicação em uma VPS isolada, registre duração/RTO e valide arquivos, permissões, jobs e integrações. Siga a estratégia 3-2-1 com uma cópia independente das credenciais da VPS.

## Fontes

- https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html
- https://restic.readthedocs.io/en/stable/040_backup.html
- https://restic.readthedocs.io/en/stable/045_working_with_repos.html
- https://rclone.org/drive/
- https://rclone.org/s3/
- https://rclone.org/ftp/
- https://rclone.org/sftp/
