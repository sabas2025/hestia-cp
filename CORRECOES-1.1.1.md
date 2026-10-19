# Correções Professional 1.1.1

Data: 19/10/2026. Base Hestia compatível: 1.10.5. Referência dos problemas: [auditoria de verificação](AUDITORIA-VERIFICACAO-2026-10-19.md). Esta é uma distribuição modificada, sem implantação na VPS do proprietário durante o desenvolvimento.

## Correções por prioridade

| Prioridade | Achado | Alteração no código |
|---|---|---|
| P1 | A01 — links de segurança rejeitados | Preferências recebem o token da sessão; A2F usa rota própria autenticada, com CSRF no POST. |
| P1 | A02 — refresh revalidava o próprio arquivo | Verificação contra manifesto root/0600 salvo na implantação, incluindo hashes, modos e proprietário. Divergência bloqueia a central com estado de revisão; não reescreve nem reaprende silenciosamente os arquivos. |
| P1 | A03 — `false` não desligava WAF gerenciado | Política própria passa a `SecRuleEngine Off` e jails próprias a `enabled=false`, com validação/reload/rollback. Componentes não gerenciados são identificados como `unmanaged`, sem afirmar que foram desligados. |
| P1 | A04 — cadastro e recuperação A2F frágeis | Preparação expira em dez minutos, ligada à sessão; confirmação do primeiro TOTP; senha atual para alterações; fator atual para desativar/renovar; recuperação descartável por hash, controle de tentativas e de reutilização. |
| P1 | A04 — seed usado como recuperação | Rota antiga de reset deixa de modificar contas; seed/QR de fator já ativo deixam de aparecer na edição nativa. Login aceita recuperação descartável apenas depois de validar a senha. |
| P1 | A04 — troca de senha como contorno da reautenticação | Troca de senha na edição nativa exige as credenciais do ator real, incluindo fator quando cadastrado; impersonação não fornece as credenciais do titular. |
| P1 | A05 — conferência de backup insuficiente | Novo manifesto histórico dentro do snapshot, hash do tar e checagem das compressões internas no drill. Importação SQL e teste da aplicação permanecem etapas operacionais obrigatórias. |
| P1 | A06 — módulos incompletos | Aplicador exclui os protótipos empresariais e suas unidades. Não publica botões ou serviços de HA/antivírus/NoSQL como prontos. |
| P2 | A07 — falha recente oculta por sucesso anterior | Snapshot separado para última tentativa; cartão mostra última tentativa e último sucesso, preservando a cópia válida. |
| P2 | A08 — testes podiam passar com skips | Modo de release falha com testes pulados ou ferramentas ausentes; navegador usa prévia regenerada. CI do fork reativado, sem secrets nem acesso à VPS. |
| P2 | A09 — manutenção e versões | Política 1.1.1, versão da central lida da política, inventário de dependências/locks, verificações de advisories e Dependabot. |
| P2 | A10 — observabilidade | Monitor indica deriva de implantação, falhas/tarefas sem atualização e ausência de execuções; eventos de alteração A2F privados com rotação. |

## Mudanças importantes de operação

### Autenticação

Abra `/professional/twofactor.php` com a própria conta. Não funciona em impersonação. A preparação do QR não ativa o fator. Leia o QR gerado localmente, confirme sua senha e um código de seis dígitos. Guarde os dez códigos `HPR-…` exibidos somente nessa resposta. Cada um pode substituir um TOTP uma única vez, junto com a senha no login. Renovar invalida os anteriores. Códigos TOTP já usados precisam aguardar a próxima janela.

Contas existentes continuam usando seu autenticador. O antigo “código de recuperação” que era o seed deixa de desativar A2F. Com senha e autenticador, use **Renovar códigos de recuperação** para migrar a recuperação. Sem o autenticador/códigos, use um procedimento administrativo de identidade por canal confiável, mantendo o acesso SSH/console de recuperação. Não envie segredos ao chat ou GitHub.

O material temporário de cadastro é cifrado com AES-GCM; a chave fica em `/etc/hestiacp/professional/secrets/mfa.key`, root/0600. A perda dessa chave invalida cadastros ainda pendentes, que podem ser preparados novamente. O fator ativo mantém o formato nativo em `user.conf`, protegido pelas permissões do Hestia. A cópia nativa de conta agora omite o seed ativo e o QR. **Não foi feita migração geral dos seeds ativos para KMS/criptografia externa**: alterar esse formato sem controlar toda a atualização oficial poderia bloquear os autenticadores após uma atualização. Essa revisão continua pendente.

Os hashes de recuperação, contadores e eventos ficam em `data/professional-mfa`, root/0700, fora do JSON da central. Esse estado não é incluído automaticamente no backup nativo de uma conta. Ao recriar uma conta que tinha A2F a partir de uma cópia nova, o perfil restaurado permanece com login do painel bloqueado, sem seed/QR, até recuperação administrativa e recadastro por identidade verificada. Restaurar somente arquivos/bancos de uma conta existente não troca seu fator. Valide esse procedimento em homologação antes de depender dele. Os logs são locais e não são apresentados como imutáveis contra root. Não há envio automático de notificações por e-mail nesta versão.

### File Manager legado

A consulta atual encontrou advisories na árvore Composer do File Manager e no ZIP previamente fixado. Há dependências antigas cujo salto para uma major corrigida exige adaptação. O componente fica **bloqueado para instalação e sem atalho**, até existir um build revisado e testado. Não foram apagados arquivos de sites. A integração alternativa code-server continua opcional e exige instalação/autenticação próprias.

Em instalação existente, o aplicador recusa prosseguir se encontrar `web/fm`. Após backup e revisão, a opção `--quarantine-filemanager` move o componente para `professional/quarantine/filemanager-ID`, fora da área web, com pasta root/0700, e grava `FILE_MANAGER=false`. Preserva o conteúdo para revisão e não toca em `/home`. Não recoloque esse diretório na área pública sem corrigir e homologar as dependências. O hash antigo permanece no lock como referência histórica; hash correto não significa versão segura.

### Backups

A cópia de `hestia/user.conf` é sanitizada no staging nativo: seed e QR não entram no tar. Para contas com A2F, ela registra `LOGIN_DISABLED=yes` e necessidade de recadastro; o arquivo da conta em funcionamento não é alterado. O validador multicloud recusa arquivos que ainda contenham material de provisionamento. Backups antigos podem conter seeds: revise acesso/retenção e rotacione o fator após aplicar a correção; não são apagados automaticamente.

Novas cópias multicloud contêm `account-manifest.json` com inventário histórico e hash do tar. O drill verifica esse inventário, não os domínios/bancos que passaram a existir depois. Verifica também gzip/zstd internos sem extrair caminhos dos sites ou executar SQL.

Snapshots antigos sem manifesto exigem um procedimento de recuperação separado, revisado; o novo drill recusa tratá-los como se tivessem a mesma evidência. Isso não apaga nem declara corrompidas as cópias antigas. O caminho legado `backup.py` continua disponível para compatibilidade, com suas limitações antigas; use `cloud_backup.py` para o fluxo reforçado e não agende os dois para a mesma conta.

Importar SQL, recuperar volumes e testar login/jobs/callbacks em ambiente isolado continuam obrigatórios para homologação. As verificações de código não medem RPO/RTO real, nem configuram WORM/Object Lock. O novo fluxo ainda produz o tar nativo completo; os incrementais avançados não foram entregues como parte desta correção.

### WAF/Fail2Ban

No JSON privado, `waf` e `fail2ban` passam a representar o estado desejado dos componentes gerenciados. Ambos podem ser `false`. Para componente já gerenciado, `false` desativa sua política com validação e reload. Para componente nunca gerenciado, não altera políticas de terceiros e informa `unmanaged`; desligamento de políticas externas exige revisão própria. Desabilitar o WAF reduz a proteção e deve ser uma decisão operacional deliberada.

O estado distingue `managed`, `desired_state` e `effective_policy`. Esta última representa a política aplicada/configurada, não a aprovação de um pentest. Apache, Nginx direto e a porta do painel mantêm os limites de cobertura descritos no guia de segurança.

## Aplicar em homologação

Faça snapshot e backup testado antes. Use uma cópia revisada deste repositório **fora de `/usr/local/hestia`** como origem. A implantação recusa hotfixes nativos desconhecidos em autenticação; não contorne essa recusa sem comparar as alterações locais.

```bash
sudo apt-get update
sudo apt-get install python3-qrcode python3-cryptography zstd
sha256sum -c SHA256SUMS
sudo /usr/bin/python3 professional/apply.py \
  --root /usr/local/hestia --source "$PWD" --enable-services
```

Se houver File Manager instalado, revise a preservação/quarentena e acrescente `--quarantine-filemanager` ao comando de implantação. Isso desativa somente essa interface opcional. O instalador completo continua exclusivo para sistema limpo; não o use sobre CyberPanel/aaPanel/Hestia existente.

O hook de atualização agora verifica o manifesto salvo. Caso indique revisão, preserve o pacote oficial atualizado e reaplique uma camada compatível a partir de uma fonte revisada. Não copie de volta arquivos antigos de autenticação para “resolver” a divergência. As atualizações oficiais de segurança não foram desativadas.

## Verificação e pendências

Veja `professional/test-results/verification-1.1.1.json`, os testes de regressão em `professional/tests/test_corrections.py` e o inventário em `professional/test-results/dependencies-1.1.1.json`. A auditoria final registra a revisão publicada e quais verificações foram repetidas sobre ela.

Permanece necessário homologar instalação/atualização reais, credenciais/destinos e restauração SQL/aplicação na infraestrutura. OpenLiteSpeed, antivírus on-access com GUI, HA de aplicações/bancos, MongoDB/Redis gráficos, incrementais avançados e controles empresariais de ativação continuam fora desta entrega. Bloquear protótipos incompletos é uma correção de distribuição; não equivale a implementar esses recursos.
