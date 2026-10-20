# Auditoria final das correções Professional 1.1.1

Data de fechamento: **20/10/2026**. Repositório: [sabas2025/hestia-cp](https://github.com/sabas2025/hestia-cp).

Revisão funcional auditada: [`35cb5e5a7ff77fadc1146c8e453411d8be8456d3`](https://github.com/sabas2025/hestia-cp/commit/35cb5e5a7ff77fadc1146c8e453411d8be8456d3), árvore `91bce6bf12066542b5985978eceb085aa010c95f`, camada Professional **1.1.1**, base Hestia **1.10.5**. A publicação deste relatório acrescenta documentação, evidências e checksums; não altera os executáveis dessa revisão.

## Parecer

**As correções descritas abaixo estão no código publicado e foram verificadas. O conjunto de funcionalidades empresariais solicitado não está integralmente implementado, e o sistema não foi homologado na VPS.** O CI do mesmo commit funcional terminou com sucesso. A contenção do File Manager vulnerável e a exclusão dos protótipos incompletos fazem parte das correções; não significam entrega de substitutos completos.

Não houve conexão SSH autenticada à VPS, instalação/atualização do painel em produção, mudança de firewall real, ativação de A2F em contas do proprietário, operação em provedores de nuvem ou restauração SQL de produção. Publicação GitHub e testes isolados não comprovam funcionamento desses serviços na infraestrutura.

## Método e evidências

1. Conferência do `main`, commit funcional e árvore remota completa, sem truncamento.
2. Download independente do ZIP do commit funcional pelo GitHub; comparação dos **1.659 blobs** com os hashes Git da árvore. Nenhuma divergência. Os modos de execução da cópia foram restabelecidos a partir dos modos Git.
3. Conferência das **1.658 entradas de `SHA256SUMS`** da revisão funcional: nenhuma divergência. O manifesto não inclui o próprio hash. Isso verifica consistência com a revisão consultada; não constitui assinatura independente nem armazenamento imutável.
4. Revisão dirigida de autenticação/A2F, autorização/CSRF, implantação e atualização, backup/recuperação, WAF/Fail2Ban, dependências, distribuição de módulos e observabilidade. A [auditoria anterior](AUDITORIA-VERIFICACAO-2026-10-19.md) registra os problemas originais; o [guia de correções](CORRECOES-1.1.1.md) detalha a nova operação.
5. Suíte completa executada durante a correção e novamente sobre o código baixado na etapa anterior da auditoria. Resultado registrado: 92 testes Python, 34 asserções PHP, sintaxe de 329 arquivos PHP e 679 scripts Bash; navegador nas larguras 360, 768 e 1440.
6. Conferência independente do [CI do commit funcional](https://github.com/sabas2025/hestia-cp/actions/runs/39302605426), job `118231397292`: conclusão **success**. Instalação de ferramentas, checkout da biblioteca TOTP fixada, verificações obrigatórias sem skips e consultas de advisories concluíram com sucesso.
7. No fechamento, novo controle negativo em ambiente sem PHP, QR, ShellCheck e navegador: retorno **1**, estado `incomplete-or-failed`. Os erros por ausência dessas dependências e os skips são esperados nesse controle e não são apresentados como aprovação funcional. A execução completa aprovada é a registrada na revisão e confirmada pelo CI.

Evidências: [execução completa](professional/test-results/verification-1.1.1.json), [consolidação final](professional/test-results/final-audit-1.1.1.json), [controle negativo do fechamento](professional/test-results/negative-release-1.1.1.json), [advisories consultados](professional/test-results/advisories-1.1.1.json) e [inventário de dependências](professional/test-results/dependencies-1.1.1.json). O JSON final distingue registros da etapa anterior, verificações repetidas no fechamento e resultado independente do GitHub.

## Resultado por achado e prioridade

| Achado | Estado verificado | Correção aplicada e limite |
|---|---|---|
| A01 / P1 — navegação de segurança e CSRF | Corrigido no código | Links de preferências recebem token da sessão. A2F tem rota própria autenticada e CSRF no POST; a conta titular é exigida. Testes cobrem o contrato e o isolamento. |
| A02 / P1 — refresh aceitava a própria alteração | Corrigido no código | Manifesto privado persistido compara hash, modo e proprietário, sem reaprender alterações. Deriva/versão incompatível gera revisão e bloqueio da central; hotfixes nativos desconhecidos são recusados. Não houve ensaio de atualização real da VPS. |
| A03 / P1 — desligamento WAF/Fail2Ban | Corrigido no código | Políticas próprias podem ser desativadas com validação, reload e rollback. Estado distingue desejado, gerenciado e política configurada; políticas externas ficam `unmanaged`. Não houve teste de ataque/banimento real. |
| A04 / P1 — cadastro/recuperação A2F e reautenticação | Corrigido, com dívida residual explícita | Cadastro pendente expira em dez minutos e exige primeiro TOTP, senha e vínculo de sessão. Recuperação descartável por hash; bloqueio de reutilização e tentativas. Rota antiga não desativa por seed. Troca de senha exige credenciais do ator real. Seeds ativos ainda usam o formato nativo protegido por permissões, sem migração KMS. |
| A05 / P1 — evidência insuficiente do backup | Reforçado; restauração integral pendente | Manifesto histórico e hash do tar no snapshot; verificação das compressões internas gzip/zstd. Não executa SQL nem comprova recuperação da aplicação. Cópias antigas sem manifesto exigem procedimento próprio. |
| A06 / P1 — módulos empresariais incompletos | Contido na distribuição | Protótipos de HA, antivírus, recursos, NoSQL e incrementais e suas unidades ficam fora da publicação/aplicação. A implementação completa continua pendente. |
| A07 / P2 — sucesso antigo escondia falha recente | Corrigido no código | Última tentativa é armazenada separadamente do último sucesso; a interface mostra ambos e preserva a cópia válida. Falha de provedor foi simulada em teste. |
| A08 / P2 — aprovação com verificações ausentes | Corrigido e confirmado pelo CI | Release falha com skips/ferramentas ausentes. Prévia é regenerada antes do navegador. Modo rápido informa incompleto. Workflow executa testes sem acesso à VPS. |
| A09 / P2 — dependências e manutenção | Reforçado; File Manager bloqueado | Versão 1.1.1 consistente, locks/inventário, CI de advisories e Dependabot. Dependências ativas consultadas sem avisos; File Manager legado bloqueado até adaptação e testes. Assinatura/proveniência de release ainda pendentes. |
| A10 / P2 — observabilidade | Parcialmente atendido | Monitor detecta deriva, falhas/tarefas antigas e ausência de backups; eventos A2F privados e configuração de rotação. Alertas externos, métricas operacionais e retenção imutável não foram configurados. |

### Achado adicional corrigido: segredo A2F no backup de conta

A cópia de `hestia/user.conf` no staging do backup nativo agora omite seed e QR. Para conta com A2F, registra bloqueio de login e necessidade de recadastro após recriação; a conta ativa original não é modificada. O validador multicloud recusa arquivos com material de provisionamento. Testes cobrem sanitização, conta original preservada e rejeição de arquivo inseguro.

Recriar uma conta protegida a partir de uma cópia nova exige recuperação administrativa de identidade e recadastro antes de liberar o login. Esse procedimento ainda precisa de restauração real em homologação. Backups históricos podem conter seeds: revisar acesso/retenção e rotacionar fatores; não foram apagados automaticamente.

## Resultados e interpretação

| Verificação | Resultado / alcance |
|---|---|
| Integridade do commit funcional no fechamento | 1.659 blobs correspondentes; 1.658 checksums corretos |
| Execução completa registrada | 92 Python, zero falhas/erros/skips; 34 asserções PHP; 26 grupos aprovados |
| Sintaxe ampla | 329 PHP e 679 Bash aprovados |
| Navegador | Central e A2F em 360/768/1440; dados ilustrativos, sem VPS |
| CI do commit funcional | Sucesso, incluindo verificações obrigatórias e advisories |
| Controle negativo do fechamento | Código 1, `incomplete-or-failed`; dependências ausentes identificadas |
| Build e documentação na etapa anterior | Build JS/CSS aprovado; 8 testes de documentação aprovados; scanner Markdown validado |
| Fixture zstd adicional na etapa anterior | Dump comprimido válido aceito; stream corrompido rejeitado; SQL não executado |
| Serviços e provedores reais | Não homologados nesta auditoria |

O relatório completo de testes de release foi publicado junto do código. Os resultados adicionais da etapa anterior são registros resumidos, não novos logs brutos recriados no fechamento. Os testes usam contas sintéticas, diretórios temporários e simulações de operações externas; o bootstrap de autenticação nativo é representado por fixture em parte dos testes web.

### Dependências

A consulta registrada encontrou zero advisories nos três escopos npm ativos (raiz, navegador de testes e terminal) e nos dois escopos Composer ativos (`web/inc` e `web/src`). A árvore npm foi atualizada e o wrapper de lint Markdown substitui a cadeia vulnerável anterior. O CI repetiu as consultas dos locks e passou. Isso não equivale a inventário de CVEs dos pacotes do sistema operacional da VPS nem garante ausência de vulnerabilidades desconhecidas.

O File Manager legado tem avisos nas dependências de origem e no ZIP anteriormente fixado. A instalação está bloqueada; atalho não é aprovado; instalação existente exige preservação/quarentena explícita pelo aplicador. A opção `--quarantine-filemanager` move o componente para diretório privado, sem apagar sites. A migração de dependências e reativação desse componente continuam pendentes.

## Pedidos que continuam incompletos

| Recurso solicitado | Situação real após as correções |
|---|---|
| Backup Google Drive/S3/FTPS/FTP/nuvem privada, sites e bancos | Fluxo publicado; provedores, credenciais, importação SQL e recuperação da aplicação ainda não homologados. FTP exige aceite explícito. |
| Assistente servidor/DNS/e-mail | Assistente local de roteiros; não é agente autônomo de configuração. |
| WAF/Fail2Ban | Gestão publicada, com cobertura WAF Apache; sem cobertura automática geral de Nginx direto, Docker, Node e porta do painel. |
| Editor online/Docker gráfico/Email Marketing | Integrações opcionais code-server/Portainer/listmonk; não foram instaladas ou configuradas. |
| Compose/Node/Proxy | Ferramentas CLI/geradores publicados; aplicações, TLS e tráfego real não homologados. |
| CPU/RAM por usuário | Base possui pacotes/cgroups com `MemoryHigh`; expansão com barreira de RAM e cobertura de todos os processos, inclusive PHP/Docker, não foi entregue nem comprovada. |
| OpenLiteSpeed | Não implementado como backend integrado. |
| Antivírus em tempo real com GUI | ClamAV de e-mail existe na base; proteção on-access de sites e interface completa continuam pendentes. |
| Multi-server, espelhamento, balanceamento e failover | Cluster DNS nativo existe; HA de aplicações, quórum/fencing e perda de nó não implementados/homologados. |
| Replicação SQL e MongoDB/Redis gráficos | Sem solução completa publicada. |
| Incrementais avançados/snapshots/blocos | Fluxo publicado ainda produz tar nativo completo; não equivale a JetBackup. |
| Tamper-proof Enterprise | Logs e hashes locais não resistem a root com controle das chaves. Sem âncora WORM/Object Lock externa, assinatura e proveniência de release. |
| Ativar/desativar todos os recursos pela GUI | Controle geral por módulo ainda não entregue; controles específicos de segurança não cumprem todo o pedido. |

## Próximas correções e critérios de aceite

1. **P1 — homologação isolada:** instalação em OS suportado limpo, atualização oficial, aplicação da camada e revisão da deriva; autenticação com conta existente, novo cadastro, recuperação, troca de senha e recuperação por console. Não executar o instalador completo sobre painel existente.
2. **P1 — recuperação de dados:** testar cada destino com credenciais próprias, restaurar conta protegida e seus bancos, importar SQL e validar a aplicação; medir espaço de staging e RPO/RTO. Proteger/revisar arquivos históricos com seeds. Manter File Manager bloqueado até build corrigido.
3. **P1 — eficácia de proteção:** validar WAF/Fail2Ban real, exclusões, falsos positivos e rollback; definir cobertura dos serviços fora do Apache. Migrar seeds ativos para proteção adicional somente com plano compatível de atualização e recuperação.
4. **P2 — operação:** alertas externos, métricas, restauração periódica, revisão de dependências, release assinado/proveniência e ancoragem externa dos registros/cópias.
5. **P2/P3 — expansão:** entregar cada módulo empresarial com autorização/CSRF/A2F, isolamento, transações/rollback, limites efetivos e testes de falha. HA exige replicação consistente, quórum/fencing e testes de perda de nó antes de ser anunciado como disponível.

O [guia de aplicação em homologação](CORRECOES-1.1.1.md#aplicar-em-homologação) descreve dependências e comando a partir de uma origem revisada fora do Hestia instalado. Não houve implantação remota nesta entrega. A revisão é de código e testes dirigidos; não é pentest completo, certificação de segurança ou equivalência funcional com cPanel.

## Capturas

As capturas são renderizações reais da prévia do código, com **dados ilustrativos e nenhuma VPS conectada**. Não demonstram serviços ativos.

![A2F na prévia para celular — dados ilustrativos](docs/screenshots/1.1.1/mfa-confirmation-360.png)
