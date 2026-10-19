# Auditoria de código e verificação das alterações solicitadas

Data: **19/10/2026**. Repositório: **sabas2025/hestia-cp**.

Revisão funcional auditada: [`56c2cbea1e16e97b77aeb31fa4ee11fe2d093ef4`](https://github.com/sabas2025/hestia-cp/commit/56c2cbea1e16e97b77aeb31fa4ee11fe2d093ef4), camada Professional **1.1.0**, base Hestia **1.10.5**. As evidências se referem a essa revisão, anterior à publicação deste relatório.

## Parecer

**Parte dos pedidos está implementada no código publicado. O conjunto completo solicitado ainda não foi entregue nem homologado em produção.** A central, os fluxos de backup multicloud, as ferramentas administrativas e as correções locais de A2F existem. Muitas funções gráficas são atalhos para produtos externos que ainda precisam ser instalados. Os módulos empresariais novos continuam em desenvolvimento fora da revisão publicada.

Nenhuma conexão SSH autenticada à VPS, instalação, ativação de A2F, mudança de firewall, operação em nuvem ou restauração de produção foi executada nesta auditoria. A existência de um arquivo, cartão ou gerador de configuração não demonstra funcionamento de um serviço. Esta publicação acrescenta relatório e evidências; **não aplica correções funcionais aos problemas encontrados**.

O resumo anterior precisava de uma precisão: **a base já possui limitação de CPU/memória por pacotes e cluster DNS**. O trabalho adicional é ampliar a cobertura, verificar a aplicação real e integrar a administração. Cluster DNS não equivale a replicar sites/bancos ou fornecer alta disponibilidade de aplicações. Limites de uma slice não abrangem automaticamente todos os processos de um UID.

## Método e cobertura

1. Consulta do `main` e da árvore remota completa pelo conector GitHub, sem truncamento.
2. Comparação de **1.630 arquivos e modos Git**, por hash de blob, com o manifesto da publicação. Todos corresponderam. Uma cópia isolada foi reconstruída com os três arquivos publicados que diferiam do desenvolvimento local.
3. Verificação dos **1.629 arquivos listados em `SHA256SUMS`** dessa revisão: nenhuma divergência. O próprio manifesto não inclui seu hash. Isso demonstra consistência com a revisão consultada, não uma assinatura de origem independente.
4. Reexecução da suíte publicada, lint amplo e revisão manual dirigida a instalador, dependências, implantação/atualização, autenticação/A2F, autorização, snapshots, backup/recuperação, WAF/Fail2Ban, Docker/Compose/Node/proxy, integrações e módulos empresariais locais.
5. Reprodução adicional de contratos de CSRF, divergência de estado do WAF, status de backup após falha e atualização com origem igual ao destino.
6. Consulta a documentação primária de Hestia, OWASP, systemd, Restic e ClamAV para avaliar requisitos e recomendações.

O inventário e lint abrangem a árvore; a revisão manual é dirigida aos fluxos descritos. Não foi feita revisão manual linha a linha dos mais de 500 comandos legados, pentest completo, análise de binários dos fornecedores, validação integral de CVEs transitivos, teste de carga ou certificação de equivalência com cPanel. Não há evidência de prontidão geral para produção.

## Verificação dos pedidos anteriores

Nesta matriz, **publicado** significa presente na revisão auditada. **Integração** exige um produto/serviço separado e configuração operacional. **Desenvolvimento** significa código local ainda não publicado nem homologado.

| Pedido | Resultado verificado | Evidência e limite |
|---|---|---|
| Instalador auditado e endurecido | Publicado | `install/hst-common.sh`, instaladores Debian/Ubuntu, hashes de ativos, modo de inspeção e bloqueio de instalação sobre painel existente. Instalação completa em OS limpo ainda não testada. |
| Interface profissional e responsiva | Publicado | `web/professional/`, tema e prints. Busca/isolamento de dados testados; dados da prévia são ilustrativos. |
| Google Drive / Amazon / FTPS / FTP / nuvem privada | Publicado, sem configuração real | `professional/cloud_backup.py`, Restic/Rclone; também SFTP/WebDAV/S3 privado. Credenciais e provedores não foram testados. FTP exige aceite explícito. |
| Backup de sites e bancos | Publicado com verificação estrutural | Inventário de domínios/bancos e presença dos arquivos/dumps no tar nativo. Não comprova consistência interna de cada dump ou recuperação da aplicação. |
| Retenção e recuperação | Publicado, ensaio limitado | Recuperação Restic e estrutura de arquivo. Importação SQL, login da aplicação e RPO/RTO reais pendentes. |
| Assistente virtual servidor/DNS/e-mail | Publicado como assistente local de roteiros | `assistant.py` e formulário JavaScript. Não é agente de IA nem executor automático de alterações. |
| WAF básico a avançado | Publicado para Apache | ModSecurity2/CRS, observação/PL1/PL2/PL3, validação e rollback. Nginx-only, painel 8083 e proxies diretos não estão automaticamente cobertos. |
| Fail2Ban | Base nativa + gestão publicada | Jails SSH/painel existentes, preservação de exceções e recuperação. Sem teste de banimento real nesta auditoria. |
| Configurar A2F | Parcialmente concluído | QR offline e verificação TOTP publicados/testados. Atalho da central possui defeito CSRF; cadastro/recuperação ainda precisam de reforço. |
| Online Code Editor | Integração publicada | File Manager nativo quando habilitado e cadastro opcional de code-server. Não é uma nova IDE completa instalada no painel. |
| Full Docker management gráfico | Integração publicada | CLI administrativo e gerador Portainer. Não há gerenciador visual próprio completo nem Portainer instalado por esta entrega. |
| Docker Compose management | Publicado por CLI | Operações e guard de configuração/hash/digest. Interface gráfica depende de integração. Não trata Compose arbitrário como sandbox seguro. |
| NodeJS Project | Publicado por CLI | Unidade systemd não root, memória/tarefas e configuração de projeto. Runtime, dependências/build e aplicação real pendentes. |
| Proxy Project | Publicado como gerador | Templates Nginx loopback/WebSocket/ACME; domínio/TLS/atribuição e WAF no gateway requerem homologação. |
| Email Marketing | Integração publicada | Gerador listmonk + PostgreSQL. Sem SMTP configurado, contatos importados ou campanhas enviadas. |
| CPU/RAM por usuário | Base nativa presente; expansão em desenvolvimento | `v-update-user-cgroup` e tela de pacotes existem. Nativo usa `MemoryHigh`, sem `MemoryMax`; abrangência de PHP/Docker não comprovada. `resources.py` local não está no GitHub auditado. |
| OpenLiteSpeed | Pendente | Não há implantação OLS publicada. Integração isolada planejada não substitui nativamente Apache/Nginx. |
| Antivírus em tempo real com GUI | Desenvolvimento | ClamAV para e-mail já existe na base. `antivirus.py` e unidade on-access locais não estão publicados; GUI e prevenção real não homologadas. |
| Multisservidor / espelhamento / balanceamento | Parcial na base; restante em desenvolvimento | Cluster DNS nativo existe. HAProxy local gera configuração; não implementa espelhamento de arquivos nem controle central completo. |
| Failover automático | Desenvolvimento incompleto | Estrutura local depende de controladores externos, quórum e fencing. Não houve teste de perda de nó nem failover real. |
| Replicação SQL primário/réplica | Pendente como solução completa | Integrações locais não criam/configuram cluster MySQL/MariaDB/PostgreSQL completo. Não há comprovação de réplica, atraso ou recuperação. |
| MongoDB/Redis pela GUI | Desenvolvimento | Coletor local inicial; sem GUI administrativa completa publicada e sem cluster real. |
| Incrementais avançados / snapshots | Desenvolvimento | `incremental.py` local usa arquivos + dumps; sem restauração integral homologada, snapshots nativos ou replicação de blocos. Fluxo publicado ainda gera tar completo. |
| Tamper-proof Enterprise | Não entregue como garantia | Cadeia HMAC local inicial é evidência de adulteração sob condições; root com chave/ledger pode reescrevê-la. Sem âncora externa WORM/Object Lock configurada. |
| Ativar/desativar todos os módulos na GUI | Pendente | Não há tela publicada com esse controle por módulo. Opções de componentes do instalador não cumprem esse requisito em operação. |

## Resultados das verificações

| Verificação | Resultado desta execução |
|---|---|
| Integridade remota | 1.630 arquivos e modos correspondem à árvore GitHub |
| `SHA256SUMS` da revisão | 1.629 entradas corretas |
| Python | 64 testes, zero falhas, zero erros, zero pulados na execução completa |
| PHP da central | 32 asserções aprovadas |
| Lint de toda a árvore PHP | 325 arquivos aprovados com PHP 8.3.6 |
| Sintaxe Bash | 678 scripts aprovados, incluindo os comandos legados identificados pelo shebang |
| Grupos da suíte publicada | 20 aprovados, incluindo ShellCheck dirigido, JS/Node, Python e navegador |
| Navegador | 360, 768 e 1440 px, sem overflow/erro JS nos casos existentes |
| A2F offline | QR SVG + roundtrip TOTP com a revisão Composer-locked de RobThree |
| Fail2Ban | Parser real 1.1.0 aceitou a configuração nativa + override em diretório de teste |
| Reprodução adicional | Quatro comportamentos documentados abaixo reproduzidos em ambiente temporário |

A primeira execução teve uma falha por ausência de `python3-qrcode` em `/usr/bin/python3` do ambiente desta auditoria. Após preparar essa dependência, a suíte completa passou. A falha inicial foi preservada nas evidências; não representa uma vulnerabilidade encontrada na geração TOTP. Os instaladores já listam a dependência; para aplicar sobre instalação existente ela precisa estar disponível previamente.

Os testes de autenticação HTTP usam um substituto explícito de `main.php`; verificam a central sob identidades controladas, não um login real completo em Hestia. Serviços, nuvens e bancos são simulados nos testes operacionais. O teste visual usa a prévia estática e não valida o destino dos atalhos no painel nativo. **Os 64 testes passarem não invalida os defeitos adicionais reproduzidos.**

## Achados e melhorias, por prioridade

### A01 — P1 — Atalhos de A2F/preferências rejeitados pelo CSRF nativo

**Evidência:** `web/professional/view.php` publica três links `/edit/user/?user=admin` na fixture. `web/edit/user/index.php` chama `verify_csrf($_GET)`. Ao usar a própria função de `web/inc/main.php` com uma sessão sintética válida, os três links retornaram `false`.

**Impacto:** o usuário pode ser redirecionado ao login ao tentar configurar segurança; a integração de A2F pela central não está concluída. A proteção CSRF não deve ser removida para contornar o defeito.

**Melhoria:** construir URL com usuário e token da sessão, escape HTML e teste que navegue até a rota nativa autenticada. Existe uma correção local desses links, mas ela **não está na revisão auditada** e não foi publicada como parte deste relatório.

### A02 — P1 — Atualização pode considerar aplicado um arquivo de A2F substituído

**Evidência:** o hook criado por `professional/apply.py` usa `--source /usr/local/hestia --root /usr/local/hestia --refresh`. No fixture, após implantação inicial, um arquivo de A2F foi substituído por conteúdo sintético mantendo `VERSION=1.10.5`. O refresh retornou `applied` e manteve esse conteúdo. Quando origem e destino são iguais, comparar os arquivos entre si não demonstra que ainda contêm a correção aprovada.

**Impacto:** o refresh não garante preservação/revalidação das correções de A2F após substituição por pacote. Não foi executado upgrade real, nem afirmado que um pacote concreto já reintroduziu o provedor externo.

**Melhoria:** usar uma referência aprovada independente da árvore instalada, verificar hashes dos arquivos implantados e interromper com estado de revisão quando um pacote os alterar. Homologar instalação, upgrade/reinstalação de mesma versão e upgrade de versão distinta. Preservar atualizações oficiais de segurança; não sobrescrever cegamente correções novas do fornecedor.

### A03 — P1 — Seleção de gerenciamento WAF confundida com estado efetivo

**Evidência:** aplicar o perfil com `waf=true` e depois aplicar `waf=false, fail2ban=true` mantém `SecRuleEngine On` no arquivo gerenciado, mas grava `waf:false` no snapshot público. `render()` omite o arquivo quando o componente é false; não o desativa nem mede seu estado efetivo.

**Impacto:** a propriedade pode ser interpretada como proteção desativada mesmo com política anterior em funcionamento. Também não existe opção que desative simultaneamente os dois componentes, pois a validação exige pelo menos um selecionado.

**Melhoria:** separar `managed`, `desired_state`, `effective_state` e horário da verificação. Criar operações explícitas de ativação/desativação com validação, rollback e confirmação do estado real. Documentar imediatamente que `false` hoje significa não gerenciar nesta operação, não desligar o serviço.

### A04 — P1 — Cadastro, alteração e recuperação de A2F ainda dependem do fluxo antigo

**Evidência:** `web/edit/user/index.php` ativa o fator após geração e permite desativação no fluxo da sessão, sem confirmação de código do fator já cadastrado nessa ação. O template `web/templates/pages/edit_user.php` exibe `$v_twofa` como “Account Recovery Code”; esse valor é o próprio seed reutilizável, não um conjunto de códigos descartáveis.

**Impacto:** risco de cadastro não confirmado e exposição do material de provisionamento a quem já possui acesso à sessão de edição. Nenhum acesso anônimo a esses valores foi demonstrado.

**Melhoria:** confirmação TOTP antes de finalizar cadastro, reautenticação recente para troca/desativação, recuperação de uso único armazenada por hash, notificação de alterações e proteção do seed com chave externa ao mesmo backup. TOTP precisa do segredo recuperável para verificação; não se resolve substituindo o seed por hash. Passkeys podem ser uma etapa posterior.

### A05 — P1 — Homologação de backup/recuperação e instalação ainda ausente

**Evidência:** os próprios resultados marcam `sql_import_tested:false` e `application_restored:false`. `validate_archive()` verifica nomes/tamanhos dos membros do tar externo; não testa os dados comprimidos internos com uma importação SQL. A cópia multicloud depende de tar completo e espaço adicional para staging.

**Impacto:** backup estruturalmente válido pode ainda exigir correção para restaurar uma aplicação. Não há RPO/RTO medido, restauração em destino independente ou comprovação das credenciais/provedores.

**Melhoria:** teste completo em VPS descartável, recuperação de cada banco e arquivos, validação da aplicação, volumes Docker/PostgreSQL externos, inventário versionado incluído no snapshot e comparação com o inventário da época do backup. Hoje o drill compara com o inventário atual; sites criados depois da cópia podem causar rejeição que não significa corrupção da cópia histórica. Acrescentar cópia imutável/offline e chave de recuperação separada.

### A06 — P1 antes de disponibilizar módulos empresariais — Escopo e segurança incompletos

**Evidência local:** `resources.py`, `antivirus.py`, `cluster.py`, `incremental.py`, `nosql.py` e `enterprise.py` não constam entre os 1.630 arquivos publicados. Não existem testes específicos deles na suíte auditada. O aplicador não habilita suas unidades empresariais. O código local de HAProxy grava configuração antes de validar; recurso/cluster podem deixar alterações parciais se comandos posteriores falharem. O worker de solicitações precisa validar arquivo regular e tratar erros/concorrência de forma consistente.

**Melhoria:** manter fora de produção até completar testes, transações/rollback, dependências, GUI com CSRF/RBAC/A2F, estados efetivos e autorização por conta. Não usar usuário/senha de banco root para monitoramento. Quórum/fencing precisam ser verificados na infraestrutura; um booleano no JSON não prova sua existência. Nenhum botão deve promover banco apenas por falha de HTTP ou parar um controlador de replicação sem avaliar o efeito na base.

Para recursos, evitar duas autoridades concorrentes sobre a mesma slice: integrar com os limites nativos, oferecer `MemoryMax` como barreira adicional e comprovar o cgroup real de cada processo, incluindo PHP-FPM, Node, cron e contêineres. Para ClamAV, validar fanotify, assinaturas, exclusão do scanner, logs/rotação e teste EICAR isolado antes de indicar prevenção ativa. Antivírus de e-mail não equivale a proteção on-access de sites.

### A07 — P2 — Histórico de sucesso por destino oculta a última tentativa falha

**Evidência:** após uma execução bem-sucedida e uma falha de provedor simulada, o job indica `failed`, enquanto o snapshot por destino conserva `succeeded` da execução anterior. A cópia antiga continua válida e não deve ser apagada, mas não há um campo separado de última tentativa no cartão do destino.

**Melhoria:** manter `last_success`, `last_attempt`, erro genérico e idade por destino; mostrar falha recente junto do RPO da última cópia válida. Acrescentar alertas com responsável. Não rotular backup antigo como perdido quando apenas a nova tentativa falhou.

### A08 — P2 — Suíte pode reportar sucesso com verificações importantes ausentes

**Evidência:** ao remover `TWOFA_LIBRARY_ROOT`, Playwright e Chrome do ambiente, o runner retornou `status:passed` com dois testes pulados e sem grupo de navegador. `outcome.wasSuccessful()` aceita skips, e o navegador é opcional sem registro explícito de ausência. Além disso, o teste publicado verifica o href defeituoso e usa um HTML pré-gerado.

**Melhoria:** criar modo obrigatório de CI que falhe na ausência de dependência/verificação exigida, gere a prévia a partir do template antes de testar e cubra navegação para rotas nativas. Manter um modo rápido local opcional, com resultado explicitamente incompleto. O único workflow ativo hoje é diagnóstico SSH manual; lint/testes originais estão arquivados e não fornecem CI deste fork.

### A09 — P2 — Política de componentes e manutenção precisam acompanhar a versão

**Evidência:** `UPSTREAM.json` e aplicador indicam 1.1.0, mas `professional/component-policy.json` e texto do preflight ainda indicam 1.0.0/1.0. Os hashes fixos dos ativos são positivos, porém não constituem processo contínuo de manutenção ou garantia de ausência de CVEs.

**Melhoria:** versão única, SBOM com dependências transitivas, revisão de advisories/atualizações com triagem, assinatura/proveniência de releases e controle de mudanças do lock. Os badges do README original apontam para o upstream, não comprovam testes deste fork. Preservar atribuição GPL e distinguir claramente a distribuição modificada.

### A10 — P2 — Observabilidade e operação profissional precisam avançar

O coletor comprova disponibilidade de módulo/daemon, não eficácia da política WAF. Acrescentar checagens sintéticas, alertas de indisponibilidade/backup/certificado, métricas por usuário, filas e espaço/inodes, trilha administrativa e retenção de logs com minimização de dados. Testar limites de upload e falsos positivos antes de publicar vídeos de devolução ou callbacks do HUB. SMTP/marketing precisam de consentimento, descadastro, autenticação do domínio e tratamento de bounces.

## Ordem recomendada e critérios de aceite

| Etapa | Entrega | Evidência necessária para concluir |
|---|---|---|
| 1 — Correções da camada existente | A01–A04, sem ampliar serviços | Rotas nativas autenticadas funcionando; preservação de A2F em reinstalação/upgrade; estado WAF verdadeiro; troca/desativação com reautenticação e cadastro confirmado |
| 2 — Instalação e recuperação | A05 e matriz de OS suportados | VPS limpa descartável; instalação e upgrade reais; recuperação isolada de sites/bancos/volumes; RPO/RTO e rollback registrados |
| 3 — Qualidade e acompanhamento | A07–A10 | CI obrigatório sem skips relevantes; builds reprodutíveis; avisos de falha; política e inventário atualizados |
| 4 — Recursos e antivírus | Integração com base nativa | Teste real do cgroup por processo; limites sob carga controlada; prevenção ClamAV e logs; controles gráficos auditados |
| 5 — Serviços opcionais | OLS, MongoDB/Redis e incrementais | Isolamento, autenticação, portas privadas, backup/restore, medição de deduplicação e ativação/desativação reversível |
| 6 — Alta disponibilidade e integridade | Aplicações, bancos e armazenamento externo | Pelo menos nós/quórum adequados; perda de nó/rede e retorno sem split-brain; RPO definido; trilha ancorada externamente sob credenciais separadas |

Não há estimativa confiável de prazo/custo sem inventário real da VPS, volume de dados, número de servidores e metas de disponibilidade. Homologar esses itens é parte da entrega, não uma etapa implicitamente concluída por existir uma opção na tela.

## Evidências e reprodução

- [Resultados consolidados](professional/audits/2026-10-19/evidence.json): execução inicial, execução completa, ausência de ferramentas, lint/checksums e reproduções.
- [Script de reprodução](professional/audits/2026-10-19/reproduce_findings.py): apenas arquivos temporários, funções nativas extraídas e executores simulados.
- [Auditoria anterior 1.1](AUDITORIA-1.1.md), [backups](BACKUPS-NUVEM.md), [A2F/WAF](SEGURANCA-A2F-WAF.md) e [projetos](PROJETOS-PLATAFORMA.md).

Execute o script contra uma cópia da revisão funcional indicada no início; executar contra código futuro pode produzir resultados diferentes. Exemplo, com PHP local disponível:

```bash
python3 professional/audits/2026-10-19/reproduce_findings.py \
  --source /caminho/para/revisao-56c2cbe \
  --php /usr/bin/php \
  --output /tmp/hestia-audit-evidence.json
```

## Referências primárias consultadas

- Hestia releases: https://github.com/hestiacp/hestiacp/releases — 1.10.5 indicada como latest na consulta. A base funcional deste fork continua a revisão registrada em `UPSTREAM.json`, não uma alegação de identidade com o tag oficial.
- OWASP MFA: https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html — reautenticação na troca de fator e recuperação de uso único.
- systemd recursos: https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html — diferença entre `MemoryHigh` e `MemoryMax` e escopo de unidades/slices.
- Restic backup: https://restic.readthedocs.io/en/stable/040_backup.html — snapshots e tratamento de falhas/leitura incompleta.
- Restic repositórios: https://restic.readthedocs.io/en/stable/045_working_with_repos.html — verificações de dados e deduplicação; o produto suporta deduplicação, mas alimentar um tar novo não elimina a criação desse tar.
- ClamAV on-access: https://docs.clamav.net/manual/OnAccess.html — kernel/fanotify, scanner separado, prevenção e logs.
