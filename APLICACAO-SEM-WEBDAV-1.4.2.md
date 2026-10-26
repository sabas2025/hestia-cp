# Professional 1.4.2 — correções locais e preparação de nuvem

Escopo autorizado: avançar nas pendências da conversa, **sem implantar ou configurar Nextcloud/WebDAV**. Destinos já existentes são preservados. Nenhuma destas alterações de fonte comprova implantação na VPS.

## Entrega desta versão

- A configuração de extensões oferece o acesso ao gerenciador por domínio quando a camada Professional está instalada. Não tenta ativar o File Manager legado bloqueado. O fallback nativo permanece disponível sem a camada.
- O cabeçalho recebe atalho para o gerenciador, preservando o link da Central e o HTML atual do painel. Os arquivos alterados entram no manifesto e no snapshot de reversão, incluindo instalações 1.4.0 cujo manifesto ainda não os gerenciava.
- O cache prepara diretórios pais root antes de publicar a zona ou executar a mudança de template. A travessia por descritores recusa links e pais graváveis por outras contas. Não altera donos/permissões de diretórios existentes nem remove cache. O diretório final continua sendo criado pelo Nginx com o usuário correto.
- `professional/maintenance.py` audita módulo, acesso do backend, permissões `hestiaweb`, A2F, Nginx, Terminal, Fail2Ban, versões PHP e destinos. Não afirma que versão CLI comprova todos os workers ou a terceira mitigação PHP. `repair-local` permite habilitar explicitamente o novo módulo e preparar caches gerenciados; iniciar Nginx requer flag e passa antes pelo teste de configuração.
- `professional/cloud_setup.py` cadastra Google Drive, AWS/S3 privado, FTPS, FTP com aceite explícito e SFTP a partir de um arquivo rclone privado previamente autorizado. OAuth Google exige cliente próprio e refresh token. Faz validação local e conexão de leitura; preserva destinos/retenção existentes e não inicializa repositório, envia backup, aplica retenção ou habilita timers. A senha Restic é solicitada no console e nunca vai para argumentos ou JSON público.
- Inventário inclui PHP 8.0–8.5, pacote interno do painel, Node e Docker. Remove a revisão antiga fixa, que não provava a origem instalada.

## Após a atualização fixada

Primeiro confirme `hestia-professional-update status` com `succeeded` e destino `1.4.2`. Depois, no console root:

```bash
python3 -I /usr/local/hestia/professional/maintenance.py repair-local \
  --enable-filemanager --start-nginx-if-stopped
python3 -I /usr/local/hestia/professional/maintenance.py audit \
  --actor sabasadmin --owner sabas
python3 /usr/local/hestia/professional/inventory.py
```

O reparo requer integridade válida. Não altera senhas, A2F, pacotes, projetos ou Nextcloud/WebDAV. Diretórios vazios de cache criados podem permanecer se outra validação recusar a operação. O recibo fica em `data/professional-maintenance/last-repair.json`; um resultado de falha não deve ser tratado como reparo completo.

Entre no painel com a própria conta `sabasadmin`, sem personificação. Clique no novo atalho **Gerenciador de arquivos**, informe conta `sabas`, carregue domínios e abra `ctba.top`. Leitura/listagem não exigem A2F. Para gravar, enviar, criar pasta ou renomear, configure A2F, guarde recuperação fora da VPS e confirme senha/código novo. Um código de erro na opção antiga não é diagnóstico do novo módulo.

O teste de aceite usa arquivo descartável: listar, criar pasta, enviar texto pequeno, baixar e comparar bytes, renomear, editar e recuperar uma revisão. Não sobrescrever arquivos da aplicação. Validar que outra conta não consegue acessá-lo. Não registrar senhas ou códigos em capturas.

## Google Drive — autorização privada ainda necessária

1. No Google Cloud da conta titular, crie projeto, habilite Drive API e configure um cliente OAuth **Desktop** próprio. Para execução contínua, revise a publicação do aplicativo; tokens de aplicativo externo em Testing expiram em sete dias para estes escopos.
2. No computador, abra túnel para a VPS: `ssh -L 127.0.0.1:53682:127.0.0.1:53682 root@179.197.72.245`. Mantenha a sessão aberta. O túnel precisa de uma chave/acesso SSH que permita encaminhamento; a chave restrita de implantação GitHub pode recusá-lo.
3. Nessa sessão root, prepare pasta privada e execute rclone interativamente:

```bash
umask 077
install -d -o root -g root -m 0700 /etc/hestiacp/professional/secrets
rclone config --config /etc/hestiacp/professional/secrets/google-drive.conf
```

Crie um único remote `drivebackup`, tipo Google Drive, informe o cliente próprio/segredo somente no console. Para repositório novo, use escopo `drive.file`, que só vê itens criados/autorizados para esse aplicativo. Autorize no navegador do computador pelo link localhost fornecido. Não envie o link de autenticação, token ou arquivo de configuração no chat. Não precisa liberar a porta OAuth no firewall público. Se o túnel não for permitido, siga o fluxo headless oficial com `rclone authorize` no computador.

4. Após OAuth e antes de inicializar qualquer repositório, cadastre:

```bash
python3 -I /usr/local/hestia/professional/cloud_setup.py \
  --name google-drive --provider google-drive --remote drivebackup \
  --folder ctba-backups/restic \
  --transport /etc/hestiacp/professional/secrets/google-drive.conf
```

Guarde a senha Restic fora da VPS. O cadastro recusa duplicatas, arquivos públicos, configurações de múltiplos remotes, verificação TLS desativada e alterações concorrentes. Timers/serviços de backup ativos devem ser revisados/pausados e retomados no console; o cadastro não os para automaticamente. Não encerrar jobs em execução.

5. Após `configured`, execute separadamente, verificando cada resultado antes do próximo:

```bash
python3 /usr/local/hestia/professional/cloud_backup.py plan --user sabas --target google-drive --config /etc/hestiacp/professional/cloud-backup.json
python3 /usr/local/hestia/professional/cloud_backup.py init --user sabas --target google-drive --config /etc/hestiacp/professional/cloud-backup.json --apply
python3 /usr/local/hestia/professional/cloud_backup.py run --user sabas --target google-drive --config /etc/hestiacp/professional/cloud-backup.json --apply
python3 /usr/local/hestia/professional/cloud_backup.py check --user sabas --target google-drive --config /etc/hestiacp/professional/cloud-backup.json --apply
python3 /usr/local/hestia/professional/cloud_backup.py drill --user sabas --target google-drive --config /etc/hestiacp/professional/cloud-backup.json --apply
```

O drill confere recuperação do arquivo/manifesto, sem importar SQL ou subir a aplicação. O aceite completo exige restauração de aplicação, SQL e e-mail em ambiente separado. Só depois habilite `systemctl enable --now hestia-professional-cloud-backup@sabas.timer` e confira `systemctl list-timers --all --full --no-pager 'hestia-professional-cloud-backup@*'`. Não habilitar retenção destrutiva como parte do primeiro teste. O serviço pode processar outros destinos já cadastrados: revise a configuração antes de habilitá-lo.

## Segurança PHP e demais pendências

A auditoria consulta o binário PHP interno e os CLIs disponíveis. Ainda são necessários inventário APT/autenticidade/candidatos dos pacotes instalados, correção de builds vulneráveis, revisão da configuração PHP efetiva e reinício controlado de todos os workers. As versões 8.2.35/8.3.36/8.4.27/8.5.12 incluem as correções de 21/10; não comprovam a mitigação adicional de 23/10 nem backports 8.0/8.1. Esta versão **não instala correções de PHP/Node por APT** e não substitui o runtime global pelo formulário.

```bash
apt-cache policy hestia-php php8.0-fpm php8.1-fpm php8.2-fpm php8.3-fpm php8.4-fpm nodejs
```

A aplicação de bloqueio WAF exige revisar tráfego legítimo e exceções antes de sair de observação. Fail2Ban precisa de ensaio que preserve acesso administrativo. O Terminal usa `hestia-web-terminal.service`; Node atual e dependências ainda precisam de comprovação. A atualização inclui a correção de alias 1.4.1, sem instalar Node 24.

Docker/Compose, Node e proxy requerem aplicações/configurações reais; marketing requer plataforma, SMTP e fluxos de inscrição/descadastro. DNS/e-mail avançados, SSH, cobertura CPU/RAM e alertas precisam de aceite operacional. Este código não transforma geradores em serviços implantados.

OLS é uma alternativa à pilha atual e exige migração validada. HA/failover/replicação exigem outros nós, rede, quórum e testes de perda. Antivírus on-access, MongoDB/Redis gráfico, snapshots/incrementais de bloco, WORM externo e central completa de toggles **continuam sem implementação completa**. Não ativar protótipos excluídos nem alegar que esta revisão entrega esses requisitos. A VPS de aproximadamente 4 GiB não é prova de capacidade para todos esses serviços simultâneos.

## Evidência exigida para fechar

Código e CI aprovados → fonte fixada → aplicação `succeeded` → auditoria na VPS → testes funcionais por recurso. Acesso SSH desta sessão, credenciais de provedores, cadastro A2F e nós adicionais não foram disponibilizados. As etapas dependentes permanecem identificadas, sem inventar sucesso remoto.

Fontes: [avisos oficiais PHP](https://www.php.net/index.php), [rclone Drive](https://rclone.org/drive/), [autorização remota rclone](https://rclone.org/remote_setup/), [OAuth Google](https://developers.google.com/identity/protocols/oauth2).
