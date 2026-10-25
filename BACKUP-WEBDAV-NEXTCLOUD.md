# Backup WebDAV / Nextcloud

## O que está disponível

O módulo de backups da camada Professional 1.3 aceita WebDAV HTTPS pelo provider
`private-webdav`. Nextcloud usa esse mesmo transporte com `vendor = nextcloud`.
Não é necessário reinstalar o Hestia nem alterar o código do módulo para usar
esse destino. Esta entrega acrescenta modelos e procedimento; não instala um
servidor Nextcloud nem ativa uma conta remota.

Os exemplos usam a conta fictícia Hestia `cliente`. Substitua esse nome pela
conta real responsável pelos sites e bancos. Outras contas devem ter execução
separada. Use uma conta dedicada na nuvem e uma pasta exclusiva para cada VPS.

## Modelos

- [Configuração do destino](docs/examples/cloud-backup-nextcloud.json).
- [Transporte Nextcloud sem credenciais](docs/examples/rclone-nextcloud.conf).

O JSON contém apenas um destino e é um exemplo, não uma substituição automática
da configuração em uso. Se já houver outros destinos, acrescente o objeto
`nextcloud` à lista `targets` existente, sem apagar os demais. O limite do
módulo é de oito destinos. Não cadastre duas entradas apontando para o mesmo
repositório remoto.

## Preparar o Nextcloud

1. No Nextcloud, copie a URL WebDAV mostrada nas configurações de Arquivos.
   O formato usual é
   `https://cloud.example.com/remote.php/dav/files/USUARIO/`.
   Preserve um eventual subdiretório da instalação e o identificador exato da conta.
2. Em configurações pessoais, Segurança, crie uma senha de aplicativo dedicada
   para o backup. Ela pode ser revogada sem alterar a senha principal.
3. Verifique espaço, quota e acesso de leitura/gravação da conta à pasta escolhida.
   Para proteção contra perda da VPS, o armazenamento deve estar em outro servidor
   ou serviço independente.
4. Use HTTPS com certificado válido. O módulo recusa WebDAV HTTP e opções que
   desabilitem a verificação do certificado.

Para outro servidor WebDAV, use a URL fornecida pelo serviço e selecione
`vendor = other` no Rclone, mantendo `provider = private-webdav` no JSON.

## Cadastrar o transporte no console root

Não envie senha, token ou arquivo de credenciais ao chat ou GitHub.

```bash
umask 077
install -d -o root -g root -m 0700 /etc/hestiacp/professional/secrets
rclone config --config /etc/hestiacp/professional/secrets/nextcloud.conf
```

Crie o remote chamado `nextcloud`, backend `webdav`, URL real, vendor
`nextcloud`, usuário e senha de aplicativo. Informe a senha somente no prompt
interativo. O Rclone grava o campo `pass` no formato esperado; não cole a senha
diretamente em texto simples nesse campo.

Esse arquivo deve conter somente o remote `nextcloud`, pertencer a root e ter
modo 0600. Não ative a criptografia do próprio arquivo de configuração Rclone:
o validador atual precisa lê-lo; sua proteção é a permissão do sistema.
A ofuscação do campo `pass` não substitui essa proteção.

```bash
chown root:root /etc/hestiacp/professional/secrets/nextcloud.conf
chmod 0600 /etc/hestiacp/professional/secrets/nextcloud.conf
```

Teste apenas a conexão e listagem, sem enviar arquivos:

```bash
rclone lsd nextcloud: \
  --config /etc/hestiacp/professional/secrets/nextcloud.conf
```

Uma listagem bem-sucedida não comprova permissão de gravação nem recuperação.
Não publique a saída completa se ela contiver nomes privados.

## Senha de criptografia e configuração

O Restic exige uma senha própria, diferente da senha de aplicativo Nextcloud.
O exemplo abaixo cria um arquivo novo sem sobrescrever senha existente:

```bash
python3 - <<'PY'
import os
import secrets

path = "/etc/hestiacp/professional/secrets/nextcloud.password"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write(secrets.token_urlsafe(48) + "\n")
print("Senha Restic criada em arquivo privado; guarde uma cópia fora da VPS.")
PY
```

Não gere outra senha para um repositório existente. Guarde uma cópia protegida
fora da VPS: ela é necessária para recuperar os dados.

Preencha o modelo JSON e salve ou mescle em
`/etc/hestiacp/professional/cloud-backup.json`, root:root, modo 0600.
Os arquivos de configuração e senhas não podem ser links simbólicos.
Não altere arquivos da camada instalada para cadastrar destinos.

## Planejar, enviar e recuperar

Validar a configuração local sem executar backup:

```bash
/usr/bin/python3 /usr/local/hestia/professional/cloud_backup.py plan \
  --user cliente --config /etc/hestiacp/professional/cloud-backup.json
```

O planejamento lê todos os destinos da configuração e seus arquivos privados,
mas não testa o serviço remoto. Se algum destino estiver incompleto, o plano
falha; mantenha rascunhos separados da configuração operacional.

Inicializar **somente se for um repositório novo e dedicado**:

```bash
/usr/bin/python3 /usr/local/hestia/professional/cloud_backup.py init \
  --user cliente --target nextcloud \
  --config /etc/hestiacp/professional/cloud-backup.json --apply
```

Enviar um backup nativo novo apenas para esse destino e verificar o repositório:

```bash
/usr/bin/python3 /usr/local/hestia/professional/cloud_backup.py run \
  --user cliente --target nextcloud \
  --config /etc/hestiacp/professional/cloud-backup.json --apply

/usr/bin/python3 /usr/local/hestia/professional/cloud_backup.py check \
  --user cliente --target nextcloud \
  --config /etc/hestiacp/professional/cloud-backup.json --apply
```

Ensaio de recuperação em diretório temporário:

```bash
/usr/bin/python3 /usr/local/hestia/professional/cloud_backup.py drill \
  --user cliente --target nextcloud \
  --config /etc/hestiacp/professional/cloud-backup.json --apply
```

Repita `run`, `check` e `drill` com `--user outra_conta` para outra conta real. Substitua o nome fictício antes de executar. A inicialização do mesmo repositório é feita uma única vez,
não novamente para cada conta. Snapshots são identificados por tags de conta.

No painel, o destino cadastrado pode ser usado em **Ferramentas → Backup em
nuvem**, informando `nextcloud` no campo de destino. Operações pela interface
exigem senha/A2F e acompanhamento do resultado da tarefa; credenciais ficam
no console. O agendamento diário atua nos destinos da configuração; revise os
horários e o fuso da VPS depois dos testes.

## Aceite e limites

- Registrar resultado de envio, snapshot, verificação e recuperação para cada conta.
- `check` lê amostra de 5% dos dados; não é uma leitura completa do repositório.
- `drill` recupera o arquivo, confere SHA-256, inventário histórico e fluxos
  comprimidos; não importa SQL nem inicia o site.
- Para comprovar recuperação da aplicação, restaurar o site e importar o banco
  em ambiente separado, validando funcionamento e duração.
- A cópia cobre a conta Hestia e seus dumps cadastrados, não todos os volumes
  Docker ou arquivos externos à conta.
- O módulo cria TAR nativo completo antes do Restic. Não é snapshot por blocos.
- Retenção é explícita, pode apagar snapshots e não é ativada neste procedimento.
  WebDAV/Nextcloud não comprova armazenamento imutável/WORM.
- Modelo validado localmente não equivale a backup configurado na VPS. A conexão
  real depende da URL, conta e senha de aplicativo.

## Referências

- [Nextcloud: URL WebDAV e senha de aplicativo](https://docs.nextcloud.com/server/latest/user_manual/en/files/access_webdav.html).
- [Rclone: backend WebDAV e vendor Nextcloud](https://rclone.org/webdav/).
- [Backups em nuvem e limites da camada](BACKUPS-NUVEM.md).
