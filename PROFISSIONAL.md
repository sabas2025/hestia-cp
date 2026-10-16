# HestiaCP Professional 1.0.0 — guia de uso

Modificações locais de 15/10/2026 sobre HestiaCP 1.10.5, revisão `c14350f40c71b71f36e3945e42607d7d9c4980eb`. Este é um pacote modificado, independente da release oficial. A licença GPL-3.0 e a atribuição original foram preservadas.

## Conteúdo

- Instaladores de Debian e Ubuntu corrigidos, lançador local e biblioteca comum.
- Central autenticada em `/professional/`, tema responsivo, busca e atalhos.
- Diagnóstico, inventário, backup criptografado, ensaio de recuperação e inspeção de migração.
- Integração com systemd e hook de atualização que preserva o hook anterior.
- `professional/preview.html`: prévia independente com dados ilustrativos; abra no navegador.
- Testes e resultados em `professional/tests/` e `professional/test-results/verification.json`.
- `ALTERACOES.patch`, `UPSTREAM.json` e `SHA256SUMS` para revisão.

## 1. Inspecionar um servidor

Extraia o pacote inteiro e abra o terminal na pasta que contém este guia.

```bash
sha256sum -c SHA256SUMS
bash install/hst-install.sh --preflight
```

O primeiro comando verifica a integridade interna dos arquivos; os hashes não são uma assinatura digital do mantenedor. O segundo não instala pacotes, não gera certificados e não modifica serviços. A inspeção retorna erro quando encontra outro painel, pilha web conflitante, banco existente, sistema incompatível ou recursos insuficientes.

Sistemas aceitos pelo código: Debian 12/13 e Ubuntu 22.04/24.04/26.04, em x86_64 ou aarch64. São exigidos pelo menos 1 GB de RAM e 10 GiB livres; o dimensionamento real depende das aplicações e dos serviços selecionados. Essas combinações não foram instaladas em VMs durante esta entrega.

**Para uma VPS que já usa CyberPanel, aaPanel ou outro painel, prepare um servidor novo.** O instalador bloqueia essa sobreposição e rejeita `--force`.

## 2. Instalar em uma VPS nova de homologação

```bash
bash install/hst-install.sh --apply
```

O instalador pede confirmação antes de alterações, usuário, hostname, e-mail e uma senha digitada sem eco. O PHP padrão dos sites é 8.4. A senha deve ter 14 a 128 caracteres, letras maiúsculas, minúsculas e número; dois-pontos, quebras de linha e prefixo `/tmp/` são rejeitados por compatibilidade com a criação de conta. Espaços, apóstrofos e caracteres como `$` e `*` são preservados.

Para uma instalação voltada somente ao HUB, selecione os componentes necessários. Exemplo, com e-mail e DNS hospedados fora desta VPS:

```bash
bash install/hst-install.sh --apply \
  --apache yes --phpfpm yes --multiphp 8.4 \
  --vsftpd no --proftpd no --named no \
  --exim no --dovecot no --clamav no --spamassassin no \
  --api no --webterminal no --lang pt-br
```

Esse exemplo mantém Apache atrás de Nginx para aplicações que usam `.htaccess`. A opção `--api no` controla a API administrativa do painel; não desativa APIs da aplicação HUB, Tiny ou VSM.

Para automação, use um arquivo de senha já criado sob `/root`, pertencente a root, com modo 0600. Não passe a senha no argumento:

```bash
bash install/hst-install.sh --apply --interactive no \
  --username paineladmin --hostname painel.seudominio.tld \
  --email administrador@seudominio.tld \
  --password-fd 3 3</root/hestia-admin-password
```

Substitua os dados de exemplo. O hostname deve ser válido e seu DNS precisa apontar para a VPS antes de emitir um certificado confiável. Se a emissão inicial não for possível, uma tarefa tenta novamente a cada 15 minutos e só é removida após sucesso. Revise os logs antes de reiniciar; o script não reinicia a VPS automaticamente.

Os logs ficam em `/root/hst_install_backups/`, com acesso restrito. Falhas interrompem etapas críticas e preservam o status. A recuperação de `policy-rc.d` é automática; se ela falhar, o original é mantido para recuperação manual. Não há promessa de rollback de pacotes: use snapshot do provedor e backup validado.

## 3. Aplicar somente a central a um Hestia 1.10.5 existente

Após backup/snapshot e revisão das alterações, execute no servidor Hestia de homologação:

```bash
python3 professional/apply.py \
  --root /usr/local/hestia --source "$PWD" --enable-services
/usr/local/hestia/bin/v-change-user-theme admin professional
```

Substitua `admin` pelo usuário real. Esse comando instala a camada adicional e aplica modificações pontuais nos comandos de dependências, sem reinstalar a pilha do servidor. Ele não altera retroativamente todas as configurações produzidas por um instalador oficial antigo. O instalador corrigido, por sua vez, é exclusivo para sistemas limpos.

A central fica em `https://SEU-HOST:8083/professional/`, ou na porta configurada. Um link é acrescentado ao painel nativo. O administrador vê o resumo do servidor; o cliente recebe apenas informações da sua conta. Contas suspensas e contextos inválidos são recusados. Nenhum endpoint de escrita ou executor de comandos arbitrários foi adicionado à central.

Ative o 2FA nas preferências de segurança, faça a leitura do QR Code e guarde o código de recuperação. Essa etapa depende do autenticador do administrador e não é simulada pelo instalador.

## 4. Diagnóstico e inventário

```bash
python3 /usr/local/hestia/professional/health.py
python3 /usr/local/hestia/professional/inventory.py
systemctl status hestia-professional-health.timer
```

O coletor verifica espaço, inodes, serviços configurados, PHP CLI instalado e certificado do painel. O timer atualiza a coleta a cada cinco minutos. Informações com mais de 15 minutos são identificadas como desatualizadas. Alertas aparecem na central e no journal; nenhuma mensagem é enviada a terceiros e nenhum serviço é reiniciado automaticamente.

O inventário registra as versões efetivamente instaladas e os hashes dos componentes externos. As chaves de repositório e arquivos de phpMyAdmin, phpPgAdmin, File Manager, Roundcube e Composer são conferidos contra `install/assets.lock.tsv`. Rclone e Restic usam os repositórios autenticados do sistema. Uma mudança de bytes exige revisão do lock; o pacote não desativa TLS ou validação de assinatura para contornar erros.

## 5. Configurar cópia criptografada

Crie `/etc/hestiacp/professional/backup.json`, pertencente a root e com modo 0600, usando `professional/backup.example.json` como modelo. Configure um destino real e um arquivo de senha do Restic, também root/0600. Use SSH por chave para SFTP ou as credenciais próprias do backend escolhido. O exemplo inclui um domínio inválido de propósito e não efetua qualquer transferência.

Campos: `repository`, `password_file`, `keep_daily`, `rpo_hours` e `rto_minutes`. Guarde a senha do repositório fora da VPS em local seguro; sem ela não há recuperação dos dados criptografados.

Inspecione o plano:

```bash
python3 /usr/local/hestia/professional/backup.py plan \
  --user hubapp --config /etc/hestiacp/professional/backup.json
```

As operações reais exigem `--apply`:

```bash
python3 /usr/local/hestia/professional/backup.py init --user hubapp --config /etc/hestiacp/professional/backup.json --apply
python3 /usr/local/hestia/professional/backup.py run --user hubapp --config /etc/hestiacp/professional/backup.json --apply
python3 /usr/local/hestia/professional/backup.py check --user hubapp --config /etc/hestiacp/professional/backup.json --apply
python3 /usr/local/hestia/professional/backup.py drill --user hubapp --config /etc/hestiacp/professional/backup.json --apply
```

`init` inicializa um repositório novo. `run` cria um arquivo consistente usando o backup nativo do Hestia, aceita somente um arquivo recém-concluído, copia para o Restic e verifica o repositório. `drill` estima espaço, exige margem de 20%, recupera em pasta temporária exclusiva, verifica o arquivo e remove o ensaio. Ele não restaura a aplicação em produção. A restauração completa do HUB e de seu banco deve ser ensaiada em homologação.

Para agendar a cópia depois de validar o destino:

```bash
systemctl enable --now hestia-professional-backup@hubapp.timer
```

O horário padrão é 03:15, no fuso do servidor, com atraso aleatório de até 20 minutos. Adeque o horário e o RPO à operação. Aplique retenção de forma explícita com a ação `retention --apply`; ela restringe a seleção à tag do usuário. O pacote não ativa timers de backup sem destino configurado. O backup nativo local continua existindo.

## 6. Inspecionar a migração do HUB

```bash
python3 professional/migration.py --public /CAMINHO/DO/HUB/public --php php8.4
```

O comando lê a versão CLI, extensões, presença de `.htaccess` e arquivos sensíveis dentro de `public/`. Ele não copia arquivos, altera DNS ou usa tokens Tiny/VSM.

Antes da mudança de DNS, valide: usuário e banco dedicados; versão do PHP no FPM e nos jobs; diretório público correto; HTTPS; bloqueio de arquivos privados por HTTP; jobs e prevenção de concorrência; OAuth/callbacks e fluxos Tiny/VSM com dados de teste aprovados; restauração de banco e arquivos; procedimento de retorno e RPO/RTO.

## 7. Atualizações e manutenção

As atualizações oficiais de segurança continuam ativas. CSS e arquivos adicionais usam caminhos próprios. O hook anterior, quando existente, é preservado em `/etc/hestiacp/hooks/post_install.before-professional.sh` e executado antes da reaplicação da camada.

A camada foi revisada para 1.10.5. Em uma versão diferente, a central responde com indisponibilidade explícita até revisão de compatibilidade; os fluxos nativos continuam disponíveis. O hook não recoloca um núcleo antigo sobre uma atualização oficial nova. Revise a compatibilidade e o lock de dependências antes de aprovar uma nova versão da camada.

## 8. Testes e limites da entrega

Resultados registrados: 43 testes Python, 29 asserções PHP e verificações visuais em 360/768/1440 px. Também passaram sintaxe Bash/PHP/JavaScript e as verificações de ShellCheck documentadas no resultado. PHP local dos testes: 8.3.6; PHP padrão configurado para os sites: 8.4. A suíte HTTP usa uma substituição explícita da autenticação apenas em uma árvore temporária de teste, não no produto.

Para reproduzir os testes, tenha Python 3, PHP, Node e ShellCheck. Para a parte visual, configure `PLAYWRIGHT_MODULE` e `CHROME_BIN` apontando para ferramentas de desenvolvimento já disponíveis:

```bash
python3 professional/tests/run_checks.py
```

A instalação do Hestia, SMTP real, certificados de domínio reais, backups externos e integrações do HUB não foram executados nesta entrega. A suíte inclui um teste visual reproduzível; resultados indisponíveis por falta de ferramentas devem ser tratados como pendentes.

Consulte `ENTREGA.md` para a correspondência entre os achados da auditoria e as alterações implementadas.
