# Auditoria e correções — HestiaCP Professional 1.4.3

Data de referência: 26 de outubro de 2026, horário de Brasília.
Base revisada: `0b1144f84dd4d104ac73321ec0f34aa631adf7ab` (Professional 1.4.2 sobre Hestia 1.10.5).

## Conclusão e limite da aprovação

A revisão encontrou falhas reais no código e na forma de apresentar os resultados. A 1.4.3 corrige os itens desta tabela e mantém as correções de integração do gerenciador e do cache da 1.4.2. A aprovação desta revisão depende da execução completa do workflow **Professional release checks** no commit de entrega, incluindo o arquivo de atualização fixado. Não equivale à aprovação de toda a VPS, à implementação de todos os requisitos empresariais, nem a uma certificação de segurança.

Não houve acesso SSH autenticado, execução na VPS ou teste ofensivo contra o servidor nesta auditoria. As reproduções usaram configurações, sessões, arquivos e comandos simulados em diretórios temporários. Sessões PHP foram criadas e verificadas pelo interpretador real; os testes do processo Node usaram uma VM isolada com dependências substituídas. Os testes de navegador usam respostas HTTP simuladas, não serviços de produção.

Nextcloud/WebDAV foi excluído das alterações operacionais por solicitação do usuário. Nenhum domínio, instalação, credencial ou conteúdo de Nextcloud foi alterado. Testes que preservam uma configuração antiga de WebDAV verificam somente bytes e metadados, sem conexão ao destino.

## Achados e correções

As prioridades indicam a ordem de correção neste projeto; não são escores CVSS nem novos identificadores CVE.

| ID | Prioridade | Evidência anterior | Correção e verificação |
| --- | --- | --- | --- |
| A01 | Alta | O terminal imprimia HESTIASID e o enviava como argumento ao PHP. Identificadores de sessão são credenciais de acesso. | JSON por stdin, argumentos fixos, erros genéricos sem SID. Testes verificam ausência do identificador em argv e logs, inclusive quando o processo falha. Não foram inspecionados logs históricos da VPS. |
| A02 | Alta | Cookies chamados `constructor`, `__proto__` e `toString` provocavam TypeError no parser com objeto comum. A exceção ocorria antes da autenticação. | Dicionário sem protótipo; SID único, sintaxe e tamanho limitados; handshake síncrono. Reprodução isolada dos três nomes e de cookies duplicados/inválidos. |
| A03 | Alta | O auxiliar do terminal confiava no conteúdo da sessão sem revalidar expiração, papel atual, suspensão e bloqueio de login. | Verifica sessão existente, contexto, tempo e IP, configuração atual da conta e autorização para impersonação. Revalida a cada 30 segundos. Testes reais de sessões PHP cobrem revogação, expiração, IP e administrador protegido. Isso não comprova o processo instalado na VPS. |
| A04 | Defesa adicional | O serviço privilegiado não removia explicitamente grupos suplementares antes de criar o PTY. A escuta não era limitada ao proxy local. | `setgroups([])`, UID/GID limitados, escuta em 127.0.0.1, até 32 clientes, limite de mensagem e buffer, tratamento de erro de transporte. Não se afirma exploração de privilégio no servidor nem proteção contra todo DoS. |
| A05 | Alta | Uma atualização incompleta dos dois arquivos do terminal poderia misturar protocolos de autenticação. | Par reconhecido por SHA-256, backup privado, restauração dos dois arquivos em falha; recusa de versões desconhecidas ou incompletas. Atualizador inclui ambos no snapshot e reinicia o serviço ativo, restaurando arquivos e serviço anterior se a validação posterior falhar. Testes injetam falhas de escrita e de validação. |
| A06 | Média | Cadastro de novo destino de nuvem recusava metadados legítimos de tarefas concluídas com modo 0640, tratando-os como segredos que exigem 0600. | Leitura de metadados com validação de propriedade, tipo, links e permissões apropriadas; tarefas ativas continuam bloqueando o cadastro. Configurações, senhas e tokens continuam privados. |
| A07 | Média | Reparo ativava a política do gerenciador antes de `nginx -t`; uma falha deixava alteração parcial e recibo anterior de sucesso. | Pré-validação da política e dos pools, preparação dos pais do cache, validação/start do Nginx e só depois habilitação do gerenciador. Recibos running/succeeded/failed-or-partial. Diretórios vazios de cache podem permanecer em falha; não se declara rollback integral desse reparo. |
| A08 | Média | A auditoria podia executar auxiliares mesmo com integridade inválida, aceitar JSON de formato incorreto, confundir configuração de nuvem inválida com ausente e aceitar versão PHP RC como corrigida. | Recusa das sondagens privilegiadas sem manifesto verificado, validação do contrato JSON, estado review-required para configuração inválida e classificação separada para pré-lançamentos. |
| A09 | Média | Qualquer tarefa registrada, inclusive somente `init`, podia deixar o indicador de backup em nuvem verde. | Contagem de tarefas deixa de comprovar entrega. A inspeção mantém aviso explícito até verificação dos destinos, cópias e recuperação. `cloud_delivery_tested` continua falso nesta inspeção somente de leitura. Teste de inicialização concluída e de metadado malformado. |
| A10 | Média | Campo de destino era ignorado ao ativar/desativar um timer da conta. | Recusa de destino individual nessas operações, com indicação explícita de que o agendamento processa todos os destinos cadastrados. O operador deve deixar o campo vazio. |
| A11 | Defesa adicional | Links de projetos permitiam query strings, que poderiam publicar tokens digitados por engano no cadastro administrativo. | Recusa de query strings, fragmentos e credenciais; aceita links HTTPS simples. Não há evidência de token real exposto. |
| A12 | Defesa adicional | Operação A2F não verificava explicitamente os metadados dos arquivos de configuração antes de lê-los. | Verifica arquivos e ancestrais controlados por root antes da autenticação e novamente dentro do lock. Teste confirma recusa de configuração gravável por outros usuários, sem chamar o verificador de senha. |

## Gerenciador de arquivos por domínio

A página correta é `/professional/editor.php`, acessível pelos links da camada Professional. Na configuração do servidor, a revisão 1.4.2 substituiu o seletor do gerenciador legado por um link para o gerenciador por domínio quando a camada Professional está presente. O link global para a Central já existia por injeção durante a aplicação da camada; esta auditoria não o apresenta como uma funcionalidade inteiramente nova.

O administrador `sabasadmin` deve escolher a conta **sabas** para acessar `ctba.top`. Upload, download, renomear, criar pasta e editor de texto estão implementados com escopo no `public_html` do domínio, checagens de proprietário, links e caminho, limites de tamanho, concorrência e reautenticação nas alterações. Upload/download têm limite de 64 MiB e o editor tem limite menor definido pelo módulo. Arquivos privados ocultos, links e arquivos de proprietário diferente podem não aparecer por política. Isso não corresponde a todas as funções do File Manager do cPanel: por exemplo, não se promete extração de arquivos, gerenciador de permissões irrestrito ou execução de comandos.

O fluxo legado continua bloqueado pela revisão de dependências. Não se libera uma versão antiga vulnerável para eliminar uma mensagem de erro. A política do novo gerenciador é independente de `FILE_MANAGER=true`; alterações exigem senha e A2F próprias. O último relatório da VPS ainda mostrava um administrador sem A2F.

## Requisitos anteriores: código versus implantação

| Pedido | Situação demonstrável até esta auditoria | Aceitação ainda necessária |
| --- | --- | --- |
| DNS e e-mail | Serviços ativos, registros e TLS foram demonstrados pelo usuário; envio/recebimento foram confirmados na conversa. | DNSSEC validado, independência de servidores autoritativos, política antispam/antivírus, reputação e entrega contínua não estão certificados. |
| Backups do site e banco | Duas cópias nativas catalogadas e presentes, segundo a última saída da VPS. Fluxo de nuvem usa backup da conta e dumps nativos. | Restaurar em ambiente isolado, importar SQL e testar aplicação. Presença do arquivo não basta. |
| Google Drive/S3/FTPS/FTP/SFTP/nuvem privada | Restic/rclone e cadastro privado implementados; Google Drive foi a escolha do usuário. | Última evidência: nenhum destino, nenhuma execução e nenhum timer de nuvem. Faltam OAuth/configuração privada, init, run, check, drill e agendamento. FTP transmite credenciais sem TLS e exige escolha explícita. |
| WAF e Fail2Ban | WAF disponível em observação nos sites Apache; seis jails Fail2Ban ativas na última saída. | Teste controlado de bloqueio e falsos positivos. WAF em observação não bloqueia ataques e não cobre automaticamente porta 8083, proxies diretos ou todo tráfego. |
| A2F | Fluxos de cadastro, confirmação e recuperação implementados. | Ativação pelo administrador; a auditoria não gera, expõe ou ativa um segredo sem sua participação. |
| Docker/Compose/Node/proxy/marketing | Inventário e operações administrativas limitadas para projetos registrados; imagens e Compose aprovados por hash. | Não é gestão irrestrita nem comprovação de aplicações em produção. Cada projeto precisa configuração, deploy, isolamento e teste. Node ≥24 é requisito do terminal e não foi confirmado na VPS. |
| Assistente virtual | Diagnósticos e orientações determinísticas presentes. | Não é um agente autônomo que configura DNS/e-mail e verifica todos os resultados. |
| CPU/RAM por usuário | Há políticas e observação de cgroups. | Cobertura de PHP, Docker, correio e bancos fora do user slice não está garantida. Não equivale a isolamento integral por conta. |
| Cache/SSH | Correção dos pais do cache e operações restritas implementadas; Nginx foi recuperado pelo usuário. | Testes de conteúdo privado sem cache, persistência após reboot, acesso SSH alternativo e cobertura das políticas. |
| OpenLiteSpeed, HA/clustering, failover, NoSQL/replicação, antivírus on-access com GUI, snapshots de bloco, WORM externo | Não há implementação completa comprovada desses pedidos. | Projetos próprios, infraestrutura/credenciais e validação. Restic sobre arquivo tar não é snapshot incremental por bloco nem equivale a JetBackup. Manifesto local não é garantia tamper-proof empresarial. |

## Método e verificações de liberação

Revisados os limites de confiança web → auxiliar privilegiado → tarefa, autorização atual, A2F/CSRF, propriedade e links de arquivos, configuração privada, comandos fixos, atualizador e rollback, gerenciador, cache, backups, políticas WAF/Fail2Ban, inventário e declarações de funcionamento. Os módulos empresariais experimentais permanecem fora da implantação. Não houve escaneamento invasivo nem inventário atualizado obtido diretamente do servidor.

- Suíte Python local: **302 testes**, sem falhas, **14 ignorados por dependências/limitações do ambiente local**. Esse resultado sozinho não aprova a liberação.
- Sintaxe da árvore: **340 arquivos PHP e 683 scripts Bash**, sem erro.
- Critério obrigatório no GitHub: suíte sem testes ignorados; validação de cache Nginx e políticas OpenSSH; controlador PHP; navegador em larguras 360/768/1440; somas SHA-256; chave/repositório APT; arquivo de atualização fixado; avisos de dependências e build/documentação.
- A evidência final deve ser o workflow concluído com sucesso no SHA exato de entrega. Um selo de uma revisão anterior não serve como validação da 1.4.3.

## Verificação posterior na VPS

Depois de instalar o atualizador da entrega aprovada, validar seu SHA-256 e executar `plan`/`apply`, aguarde `status` terminar. Não execute novamente o instalador completo do Hestia.

```bash
hestia-professional-update status
python3 -I /usr/local/hestia/professional/maintenance.py audit --actor sabasadmin --owner sabas
python3 -I /usr/local/hestia/professional/inventory.py
python3 -I /usr/local/hestia/professional/health.py
```

Se o manifesto estiver verificado, o reparo explícito do gerenciador/cache pode ser executado:

```bash
python3 -I /usr/local/hestia/professional/maintenance.py repair-local --enable-filemanager --start-nginx-if-stopped
python3 -I /usr/local/hestia/professional/maintenance.py audit --actor sabasadmin --owner sabas
```

Validar pelo painel: escolher sabas → ctba.top; listar pasta, baixar arquivo de teste, criar pasta, enviar arquivo, editar e renomear usando A2F; comparar os bytes baixados e remover apenas os dados de teste. A auditoria por CLI não substitui esse teste autenticado.

Terminal: builds desconhecidas são preservadas e recusadas, não sobrescritas. Instalação e ativação dependem do pacote revisado, Node ≥24 e unidade `hestia-web-terminal`. Reinício do serviço interrompe terminais ativos. Testar autenticação, suspensão/expiração e acesso pelo proxy. Revisar quem pode ler os logs históricos e planejar revogação de sessões se necessário; esta atualização não apaga logs nem força logout global.

Google Drive: cadastrar o remote com cliente OAuth próprio e credenciais somente na VPS, registrar por `cloud_setup.py`, inicializar um destino explícito e validar cópia/recuperação antes de agendar. O timer de conta processa todos os destinos existentes; não habilitá-lo se algum destino estiver fora do escopo autorizado, inclusive um WebDAV antigo. Não enviar tokens, senhas ou arquivos privados para a conversa ou GitHub.

PHP: os números relatados 8.2.35/8.3.36/8.4.27 correspondem às correções anunciadas em 21/10, mas isso não prova os workers em execução, o PHP interno do painel nem a mitigação de upload progress anunciada em 23/10. Conferir pacotes, configuração efetiva e reinício controlado de todos os SAPIs; 8.0/8.1 exigem revisão própria. Referência primária: <https://www.php.net/index.php>. Não há declaração de que todas as falhas PHP foram corrigidas no servidor.
