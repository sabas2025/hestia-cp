# Operações empresariais 1.2 — entrega parcial

Revisão de 25/10/2026. Base suportada: HestiaCP 1.10.5. Camada Professional 1.2.0, sem equivalência funcional anunciada com cPanel. A publicação e os testes isolados não são implantação na VPS.

## O que esta revisão acrescenta

A página `/professional/business.php` prepara alterações de TTL, limite padrão de envio por caixa postal, perfil de cache, política SSH e recursos da slice do usuário. O titular precisa revisar o plano, confirmar sua própria senha e um novo código A2F e acompanhar o histórico. O administrador pode gerenciar contas ativas com login desabilitado; essa conta não pode atuar como titular da operação.

Os planos privados vencem em dez minutos. O servidor revalida propriedade do domínio, papel do ator, delegação, versão do Hestia, integridade dos arquivos instalados e configuração atual. Mudanças concorrentes exigem um novo plano. A senha e o código chegam por stdin ao helper, sem entrar nos argumentos, no plano ou no histórico. Não há campo para comandos arbitrários.

A confirmação cria uma tarefa transitória do systemd; ela não aguarda um comando administrativo longo dentro da requisição web. O ticket expira em sessenta segundos e contém apenas ator, plano, operação e nonce. O worker verifica novamente a autorização e o manifesto. Cada ticket só pode ser consumido uma vez. Tarefa expirada antes de iniciar pode ser reenviada com nova confirmação enquanto o plano ainda for válido; o nonce anterior perde validade.

O estado `queued` significa somente que a tarefa entrou na fila. `applied` significa que os comandos e validações previstos terminaram; **não comprova funcionamento da aplicação nem eficácia dos limites**. `failed-restored` registra falha com reversão concluída. `recovery-required`, `applying`, `rolling-back` ou execução interrompida exigem revisão administrativa. A reversão de um plano aplicado exige nova senha/A2F e recusa configurações alteradas desde a aplicação.

## Aplicação em homologação

Use uma origem revisada fora de `/usr/local/hestia`, um snapshot do provedor e backup com recuperação testada. Em instalação existente, aplique a camada; o instalador completo do Hestia se destina a sistema limpo. Confirme as dependências do guia [1.1.1](CORRECOES-1.1.1.md), incluindo os módulos Python de A2F. As novas operações usam systemd, os comandos nativos e os binários de Nginx/OpenSSH do sistema suportado.

Exemplo, após revisar a origem e substituir seu caminho:

```bash
python3 /caminho/revisado/hestia-cp/professional/apply.py \
  --root /usr/local/hestia \
  --source /caminho/revisado/hestia-cp \
  --enable-services
```

O aplicador não sobrescreve templates de cache diferentes nem modificações de autenticação desconhecidas. O File Manager legado permanece bloqueado. Se já estiver instalado, revise o procedimento de `--quarantine-filemanager` no guia anterior: ele preserva o componente fora do diretório web. O timer habilitado pelo aplicador é o de saúde; destinos de backup e seus timers exigem configuração própria.

Verifique o manifesto após aplicar:

```bash
python3 /usr/local/hestia/professional/apply.py \
  --root /usr/local/hestia --source /usr/local/hestia --refresh
```

`verified` verifica os arquivos comparados ao manifesto privado criado na aplicação. Não é assinatura independente nem atestado de inviolabilidade contra root. Uma nova versão oficial exige revisão; o aplicador não reaplica um core antigo sobre a atualização.

## Delegação por conta

Sem arquivo adicional, as mudanças ficam restritas a administradores. Para conceder a uma conta as três operações delegáveis, revise `professional/business-access.example.json`, substitua a conta e instale a configuração em `/usr/local/hestia/professional/business-access.json`, propriedade root e modo `0600`. O formato é:

```json
{"schema":1,"grants":{"exampleuser":["dns-ttl","mail-rate","cache-profile"]}}
```

A conta só atua nos próprios domínios. Remover uma concessão bloqueia planos existentes e tarefas ainda não executadas. SSH e recursos não são delegáveis nesta revisão. Não há editor de papéis completo, SSO ou passkeys publicados nesta entrega.

## DNS e e-mail

O diagnóstico consulta A, AAAA, NS, SOA, MX, TXT, CAA, DS, DNSKEY, DMARC e dois seletores DKIM exemplificativos, somente para uma zona pertencente à conta. Indica presença de registros e quantidade de SPF, sem provar cadeia DNSSEC, propagação global, independência dos servidores ou reputação do IP. PTR precisa ser conferido com o provedor. Domínios de e-mail cuja zona não está no Hestia exigem diagnóstico externo.

A alteração de TTL usa o comando nativo e pode atualizar o serial também na reversão. O limite de e-mail é padrão **por caixa postal**, em mensagens por hora, e não soma todas as caixas do domínio. Exceções por caixa prevalecem. DKIM, encaminhamento, TLS, fila, SPF alinhado, DMARC e envio/recebimento precisam de testes reais. Rspamd, quarentena gráfica e migração IMAP não foram acrescentados.

## Cache de sites

O perfil `professional-safe` é opcional por domínio e exige Nginx na frente de Apache. Ele usa uma zona com prefixo próprio, preserva as extensões estáticas existentes e valida Nginx antes do reload. O hook executável acompanha os templates HTTP e TLS para criar a zona durante o rebuild nativo.

Somente respostas 200 de conteúdo público podem entrar no cache, por sessenta segundos. Métodos diferentes de GET/HEAD, qualquer cookie, autorização, parâmetros na URL e rotas sensíveis ficam fora; respostas com `Set-Cookie` não são armazenadas. As regras nativas adicionais permanecem. Os mecanismos de controle de cache enviados pela origem não são desativados. Isso reduz cobertura de cache em troca de cautela com sessões; a política precisa de teste da aplicação.

Para desativar, prepare o perfil `default`. A reversão pode restaurar o perfil anterior enquanto a configuração permanecer igual. Antes de excluir um domínio diretamente pelo painel nativo, desative o perfil; uma zona sem domínio pode exigir limpeza administrativa. O ensaio local validou sintaxe; não mediu HIT/MISS sob tráfego, privacidade entre usuários ou desempenho. Redis, OPcache e purge seletivo com interface não estão implementados aqui.

## SSH e chaves temporárias

As políticas são `keys-only`, `sftp-only` e `disabled`; o administrador de recuperação é protegido. O sistema exige o Include padrão de drop-ins, valida `sshd -t` e confere os valores efetivos de `sshd -T -C` antes de recarregar. Configuração anterior que prevaleça sobre as restrições causa recusa e reversão.

Antes de restringir senhas, o root precisa revisar as chaves públicas em `/etc/ssh/hestia-keys/CONTA` e testar uma conexão nova. Mantenha a sessão atual e console do provedor. **SFTP-only não cria chroot**; não anuncia isolamento de arquivos ou substituição do shell Unix da conta.

O helper `professional/ssh_keys.py` oferece plano por padrão e escrita só com `--apply`. Ele recebe um arquivo de chave pública Ed25519, chave de segurança Ed25519 ou ECDSA P-256; não aceita chave privada. A validade deve incluir timezone e estar entre cinco minutos e trinta dias no futuro. Pode restringir até dezesseis redes CIDR com `--from-network`.

```bash
python3 /usr/local/hestia/professional/ssh_keys.py \
  --owner exampleuser --public-key /root/chave-publica.pub \
  --expires 'DATA_FUTURA_COM_TIMEZONE' --from-network 192.0.2.1/32
```

Substitua data e rede por valores reais aprovados. O resultado planeja uma linha `restrict,expiry-time=...`, desabilitando encaminhamentos e PTY; isso não impede por si só execução de comandos. A linha só entra em vigor no caminho de chaves usado pela política SSH. Uma chave já autorizada por outra linha é recusada, evitando aparência falsa de restrição temporária. Revogue pelo `--remove ID --apply`. Não há bastion, CA SSH ou chroot automático nesta entrega.

## Recursos

A interface permite `MemoryMax`, `TasksMax` e `IOWeight` na slice `user-UID.slice`, verificando UID real da conta. Os limites nativos de CPU e `MemoryHigh` não são sobrescritos. A alteração faz `daemon-reload` e não migra nem reinicia processos.

Use “Conferir cobertura de recursos” para identificar processos da conta fora da slice. Ausência de processos, leitura incompleta ou processos externos produz cobertura incompleta. Mesmo todos os processos observados dentro da slice não provam cobertura futura. Confira cgroups e controladores disponíveis, valores efetivos do systemd, comportamento sob carga e serviços PHP/Node/Docker/bancos separadamente. Limite de RAM rígido pode provocar encerramento por falta de memória quando estiver efetivo; dimensione em homologação.

## Backups e proteção de retenção

Os fluxos Restic/rclone da 1.1.1 continuam disponíveis para Google Drive, S3, FTPS, FTP com aceite explícito, SFTP e nuvem privada. Eles incluem tar nativo de sites e dumps SQL, com criptografia e ensaio de leitura dos arquivos. Não foi substituída a geração integral por snapshots ou incrementais de arquivos.

Nova opção booleana `append_only` nas duas configurações de backup: quando verdadeira, a ação de retenção/`forget --prune` é recusada antes de executar comandos. A operação normal conserva o comportamento anterior por padrão. **Essa política local não torna o armazenamento imutável.** Configure permissões remotas independentes, Object Lock/WORM ou servidor append-only e identidade separada de manutenção. Credenciais com poder de exclusão continuam tendo esse poder fora do helper.

Nesta revisão não há importação SQL automática em laboratório, restauração granular completa nem teste real em provedores. Backups antigos podem conter dados sensíveis e precisam de política própria. Não apagar automaticamente cópias históricas válidas.

## Recuperação de operações interrompidas

Os registros privados ficam em `data/professional-business/plans`, `queue` e `events.jsonl`; rotação do log é incluída com integração de serviços. A exclusão de um ticket não desfaz uma alteração. Não edite estados para reaplicar às cegas.

Se faltar energia ou um processo for encerrado entre a modificação e a gravação final, pode haver configuração parcial sem rollback concluído. Consulte a unidade `hestia-business-ID-NONCE`, os comandos e os arquivos salvos no plano, valide o estado dos serviços e prepare a recuperação com console e backup. A fila serializa operações deste módulo; outras ferramentas nativas não compartilham o lock. Snapshots recusam mudanças concorrentes detectadas, mas não tornam o core inteiro transacional.

## Limites da entrega e próximos módulos

| Área | Entregue nesta revisão | Ainda necessário |
|---|---|---|
| Operações | GUI, revisão, delegação limitada, senha/A2F, fila e reversão | Papéis completos, passkeys/SSO e permissões por equipe |
| DNS/e-mail | TTL, diagnóstico e limite padrão de envio | DNS redundante homologado/DNSSEC, migração, quarentena e entregabilidade real |
| Segurança | Mantidas correções A2F, WAF/Fail2Ban e bloqueio do File Manager | WAF fora do Apache, on-access de sites com GUI, cobertura efetiva e logs remotos |
| Backups | Guard de retenção append_only sobre os fluxos existentes | Incrementais/snapshots, Object Lock externo, laboratório SQL e recuperação integral |
| SSH | Políticas, conferência efetiva e chaves com prazo | Chroot, bastion, certificados e teste remoto |
| Sites e cache | Cache público opcional | Staging, GitHub deploy/rollback, Redis/OPcache e purge pela GUI |
| Recursos | Configuração da slice e diagnóstico de cobertura | Cobertura rígida de PHP/Docker/bancos, teste de carga e controle gráfico completo de CPU |
| Observabilidade | Monitor anterior e histórico privado da nova operação | Alertas externos, métricas, SLO e central de incidentes |
| Plataforma | Mantidos geradores e integrações opcionais existentes | Docker/Compose/NoSQL gráficos completos, OpenLiteSpeed e marketing instalado |
| Multi-server | Nenhuma nova implementação de HA | Replicação, quórum, fencing, failover e testes de perda de nó |
| Distribuição | Locks atualizados, CI e checksums | Assinatura de release, proveniência e âncora externa inviolável |

Consulte [AUDITORIA-1.2.md](AUDITORIA-1.2.md) para as evidências da revisão publicada. Nenhum item pendente deve ser anunciado como ativo só porque aparece nesta matriz.
