# Professional 1.4.4 — cache independente do diretório nativo do Nginx

## Problema confirmado na VPS

Em 27/10/2026, o usuário confirmou a instalação 1.4.3 com `succeeded`, mas `maintenance.py repair-local` falhou com `ValueError` na fase `cache-parents`. A saída de `namei -l` mostrou `/var/cache/nginx` com proprietário **www-data**, grupo root e modo 0755; seus filhos `hestia-pro/sabas` pertenciam a root.

A rotina anterior exigia todos os ancestrais root, embora utilizasse um diretório nativo pertencente ao worker nesta instalação. Essa combinação não estava coberta pela suíte anterior. Os 302 testes aprovados da 1.4.3 não comprovaram compatibilidade com esse layout real. O gerenciador não pode ser considerado habilitado somente porque a atualização terminou.

## Correção

- Novas zonas Professional usam `/var/cache/hestia-pro/CONTA/DOMINIO`, fora de `/var/cache/nginx`.
- A validação de propriedade root, links e permissões permanece nos pais do novo namespace. Não há `chown -R`, relaxamento de permissões, leitura/cópia ou remoção dos dados do cache antigo.
- O reparo reconhece somente os formatos exatos de pool antigo e novo e exige **domínio explícito** e validação do Nginx para migrar um pool legado. Conta/domínio são verificados no cadastro Hestia. Configurações personalizadas são recusadas.
- O reparo usa o mesmo lock das alterações administrativas de cache. Faz backup privado do arquivo de configuração, prepara os novos pais, altera o pool escolhido e executa `nginx -t`. Recarrega o Nginx se estiver ativo ou o inicia se estiver parado; só depois habilita a política do gerenciador.
- Falha de validação restaura bytes, modo e grupo do pool antes de qualquer recarga. Falha de recarga tenta restaurar a configuração e recuperar o serviço ativo. Alterações externas são preservadas e registradas como `recovery-required`. Se a recuperação falhar, não se declara sucesso. Diretórios vazios novos podem permanecer.
- O recibo de falha inclui motivo e resultado da reversão do cache. Não garante rollback integral de todas as ações; por exemplo, uma falha no recibo final depois da habilitação da política continua sendo uma falha parcial a revisar.

O comando de implantação recomendado seleciona apenas **sabas / ctba.top**. Pools de outros domínios, incluindo `cloud.ctba.top`, ficam fora da migração. Uma recarga do serviço Nginx é compartilhada pelo servidor; não se altera instalação, arquivos, credenciais ou configuração de domínio Nextcloud/WebDAV.

## Verificação da revisão

Suíte local: **309 testes**, zero falhas/erros, 14 exclusões por limitações do ambiente. Sete regressões adicionais cobrem o layout nativo pertencente ao worker/gravável, migração somente do domínio escolhido, idempotência, falhas de validação/recarga, formatos desconhecidos, namespace novo inseguro, preservação de alteração externa e concorrência administrativa. No ambiente local com mapeamento apenas de UID 0, a fixture usa o limite equivalente de diretório gravável; no CI Linux normal também atribui UID 33 ao diretório nativo.

A liberação exige o workflow completo no SHA de entrega: nenhum teste ignorado, configuração real Nginx/OpenSSH, navegador com serviços simulados, somas de arquivos, pacote fixado do atualizador, consultas de vulnerabilidades e build/documentação. A aprovação se limita à revisão corretiva; não comprova aplicação na VPS.

## Aplicação e aceite

Instalar o atualizador **da entrega 1.4.4 fixada e com SHA-256 conferido**, executar `plan --components ''` e `apply --components ''` e aguardar status global `succeeded`, com resultado da camada `to: 1.4.4`. Não reutilizar o helper 1.4.3 para tentar obter a revisão nova.

Depois, executar no console root:

```bash
python3 -I /usr/local/hestia/professional/maintenance.py repair-local --owner sabas --domain ctba.top --enable-filemanager --start-nginx-if-stopped
```

Conferir `state: repaired-local`, `filemanager_enabled: true`, `nginx_active: true` e a migração restrita a ctba.top. Uma segunda execução bem-sucedida pode ter a lista de migrações vazia. Se ocorrer falha, conferir o recibo privado; não repetir a operação para forçar sucesso.

```bash
python3 -I /usr/local/hestia/professional/maintenance.py audit --actor sabasadmin --owner sabas
```

Validar no painel `/professional/editor.php`, logado como **sabasadmin**, conta **sabas**, domínio **ctba.top**. Testar arquivo descartável com upload/download, comparação de bytes, renomeação e edição, usando senha/A2F próprias para alterações. Testar também que páginas autenticadas e conteúdo privado continuam fora do cache.

O Nginx ficará com cache novo inicialmente vazio para o domínio migrado. O cache antigo permanece no disco; limpeza posterior exige decisão separada. Esta revisão não atualiza PHP/Node, não configura Google Drive, não ativa A2F pelo titular e não conclui os requisitos empresariais ainda pendentes.
