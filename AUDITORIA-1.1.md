# Auditoria e evolução profissional — 1.1.0

Data: 19/10/2026. Repositório: https://github.com/sabas2025/hestia-cp. Base auditada: commit `693493ece2848c2f0e9559b081be2960e428a67c`, camada 1.0 sobre a revisão Hestia registrada em `UPSTREAM.json`.

## Conclusão

Foram implementados backups multicloud com cobertura estrutural de sites e bancos, assistente local, perfis WAF/Fail2Ban com recuperação, ferramentas de projetos e configuração guiada de A2F. A correção de maior prioridade é a geração **local** do QR de A2F, substituindo o provedor externo encontrado na base. O pacote está publicado como código para homologação; nenhuma instalação, conexão SSH autenticada ou mudança de serviço foi realizada na VPS do proprietário.

A análise incluiu inventário da árvore publicada, instaladores, operações privilegiadas, permissões, snapshots, autenticação da central, gerenciamento de conta, geração/verificação TOTP, caminhos de backup, integração com atualizações, interface e dependências das novas funcionalidades. Foram revistos os limites com documentação primária dos fornecedores. Não é alegada revisão manual linha a linha dos mais de 500 comandos legados, nem pentest completo de toda a plataforma ou certificação de equivalência com cPanel.

## Achados e tratamento

| ID | Prioridade | Evidência no código | Tratamento nesta versão |
|---|---|---|---|
| P01 | P0 | `web/inc/2fa/secret.php` usava `QRServerProvider` para gerar o QR a partir do URI de provisionamento | Provedor local PHP → Python por stdin, SVG sem rede; instalação de `python3-qrcode`; falha impede salvar A2F incompleta |
| P02 | P1 | `v-check-user-2fa` passava o segredo TOTP como argumento ao PHP; helper também aceitava GET | Segredo/token por stdin; scripts recusam HTTP e entradas inválidas; comando público Hestia mantém a interface de usuário/token |
| P03 | P1 | Backup só tinha um destino por arquivo e não distinguia sucesso parcial | Schema 2 com 1–8 destinos, execução por destino, estado agregado e persistência das cópias concluídas |
| P04 | P1 | Apenas existir um tar novo não demonstrava presença dos sites e dumps esperados | Inventário da conta e conferência de cada site/banco antes do envio; ausência aborta sem upload |
| P05 | P1 | Arquivos privados exigiam validação mais forte de tipos, ancestrais e links | Leitura com `O_NOFOLLOW`/`O_NONBLOCK`, arquivo regular root/0600, limites e ancestrais controlados; FIFO e symlink são recusados |
| P06 | P1 | Variáveis de ambiente podem alterar transporte e subprocessos do backup | Novo fluxo usa ambiente reduzido, credenciais em arquivos privados e remotes nomeados; saída sensível do provedor não é publicada |
| P07 | P1 | WAF precisava de implantação compatível com o servidor, sem editar o núcleo a cegas | Perfis para Apache + ModSecurity2/CRS; recusa de Nginx-only, loader desconhecido e política adicional que exija merge |
| P08 | P1 | Reload incorreto poderia deixar Apache ou Fail2Ban indisponível | Backup transacional, validação conjunta antes dos reloads e restauração da configuração anterior; recuperação malsucedida informa necessidade de console |
| P09 | P1 | Reconfigurar SSH jail pode bloquear o administrador ou apagar exceções | Uso das jails nativas, consulta da lista efetiva de ignoreip, mesclagem, IP administrativo e verificação do peer SSH |
| P10 | P1 | Socket Docker acessível ao PHP permitiria administrar o host a partir do painel | Nenhuma permissão do socket ao navegador/PHP; operações no CLI root e integração Portainer exclusiva do administrador |
| P11 | P1 | Compose de aplicação pode expor portas, host filesystem e privilégios | Aprovação SHA256, imagem por digest, loopback, volumes nomeados e recusa de privilégios/binds/host networking no fluxo gerenciado |
| P12 | P1 | Node.js executado como root ampliaria o impacto de falha da aplicação | Unidade systemd com usuário não privilegiado, limites e hardening; instalação/build de dependências continua sob o dono da aplicação |
| P13 | P1 | Atalhos e snapshots de projetos poderiam vazar acesso entre clientes | Filtro por proprietário e papel atual, restrição na impersonação, HTTPS e recusa de credenciais/tokens em URL |
| P14 | P2 | Configuração DNS/e-mail exigia um roteiro verificável | Assistente determinístico local com domínio/IP validados, SPF/DMARC de exemplo, DKIM real obrigatório e exportação JSON; sem shell arbitrário ou alteração automática |
| P15 | P2 | Interface não diferenciava módulo disponível no código de serviço instalado | Cartões com necessidade de configuração e atalhos somente após cadastro; prints identificados como prévia ilustrativa |

Durante a validação com o parser real do Fail2Ban 1.1.0, a interpolação `known/ignoreip` falhou na configuração nativa sem esse valor anterior. O código foi corrigido para obter a lista efetiva do daemon e mesclá-la explicitamente. O teste real de configuração passou depois da correção; não foi iniciado daemon nem aplicada regra de firewall nessa validação.

## Entregas e funcionamento

- `cloud_backup.py`: Google Drive, Amazon S3, FTPS, FTP com aceite explícito, SFTP, WebDAV privado e S3 privado via Restic/Rclone; inicialização, execução, checagem, recuperação e retenção.
- `assistant.py` e formulário da central: planos locais de DNS, e-mail, servidor, backup e segurança. O assistente não é um agente de IA com execução de comandos; não precisa de uma chave de IA e não transfere dados a um modelo externo.
- `security.py`: plano/diff, quatro perfis, aplicação, status e rollback. ModSecurity trata as requisições; Fail2Ban trata repetição de autenticação. Uma proteção não substitui a outra.
- `projects.py`: contêineres/imagens/redes/volumes, ações Compose, unidade Node e geração de templates Nginx. `stacks.py` gera stacks privadas revisáveis de Portainer/listmonk.
- Editor online: acesso ao File Manager nativo quando habilitado; integração code-server opcional. Docker visual completo: integração com Portainer, não uma reimplementação de toda sua API dentro do Hestia. Marketing: integração listmonk com banco próprio e configuração SMTP posterior, sem envio de campanha.
- A2F: configuração pelo fluxo nativo, estado booleano na central e inventário agregado dos administradores. Os segredos continuam no armazenamento nativo protegido, não no payload da central.

## Verificações

Resultado detalhado: `professional/test-results/verification-1.1.json`. A execução final registra testes Python, asserções PHP, sintaxe e navegador. Os testes de operações que dependeriam de VPS, banco, nuvem ou daemon usam fixtures e executores controlados; não são apresentados como operações reais de produção.

- Suíte Python: **64 testes**, incluindo isolamento por conta/papel, autenticação HTTP simulada explicitamente, falhas de backup, transportes, recusa de symlinks/FIFO, retenção com destino, rollback e limites de Docker/Compose.
- PHP: **32 asserções** da central, incluindo sigilo dos segredos, escopo de projetos, impersonação e URLs inseguras; sintaxe dos helpers de A2F e da central aprovada.
- A2F: geração SVG e roundtrip de código TOTP com a revisão `85408c4e775dba7c0802f2d928efd921d530bc5b` da biblioteca RobThree, a mesma fixada no Composer lock; entradas inválidas e helper ausente recusados.
- Navegador: larguras de 360, 768 e 1440 px; busca, estado vazio, formulário, download disponível, recusa de IP privado, zero requisições de rede no roteiro e zero erros JS/overflow.
- Bash/JavaScript/Python: sintaxe aprovada. ShellCheck do lançador/código compartilhado e verificações de erro dos instaladores preservadas.
- Fail2Ban 1.1.0: parser real validou o override junto da configuração nativa Hestia, em diretório de teste com logs fictícios, sem execução de ações de firewall.

Os testes de PHP usaram 8.3.6; a versão padrão de sites configurada no instalador continua 8.4. A inspeção visual é da prévia produzida pelo template PHP, não de um login real em Hestia instalado. O registro 1.0 permanece em `verification.json` como histórico.

## Pendências e melhorias recomendadas

| Prioridade | Trabalho restante | Condição para concluir |
|---|---|---|
| P1 | Homologar instalação e atualização nas distribuições suportadas | VPS descartável limpa, teste de instalação/upgrade, serviços reais e retorno validado |
| P1 | Ativar destinos reais, recuperar SQL e aplicação | Credenciais, OAuth/IAM/host keys, conexão com provedor e ensaio completo independente |
| P1 | Cobrir PostgreSQL/volumes Docker e configurações externas à conta Hestia | Rotina específica de dump, cópia de volumes e recuperação; backup da conta não cobre esses objetos automaticamente |
| P1 | Proteger proxies Node/Docker, Nginx-only e porta 8083 | Gateway/conector WAF homologado, restrição de portas e validação de IP real; WAF Apache não cobre tráfego que o contorna |
| P1 | Endurecer o fluxo nativo de cadastro/recuperação de A2F | Confirmação antes de concluir cadastro, reautenticação na troca/desativação, recuperação de uso único e revisão do armazenamento do seed |
| P1 | Impedir perda por comprometimento da conta de backup | Cópia offline/append-only ou Object Lock, credenciais separadas e teste de retenção sob imutabilidade |
| P2 | Medir capacidade e RPO/RTO efetivos | Volume real, duração, banda, armazenamento, alertas e rotina de tratamento de falhas |
| P2 | Expandir observabilidade e CI | SLO, métricas, alertas com responsável, matriz automatizada de VPS e análise de dependências com triagem |
| P2 | Homologar serviços externos e e-mail marketing | Digests/versionamento, autenticação, SMTP, opt-in/descadastro, bounces e restauração do banco |

Não foram configurados DNS real, PTR, credenciais de nuvem, destinatários de alertas, conta de A2F, serviço SMTP, Docker daemon ou campanhas. Não foi realizado scan ativo da VPS, teste de carga, ensaio de DDoS ou teste de recuperação de produção. As recomendações acima continuam abertas; o relatório não as confunde com as correções de código já verificadas.

Guias operacionais: `BACKUPS-NUVEM.md`, `SEGURANCA-A2F-WAF.md`, `PROJETOS-PLATAFORMA.md` e `PROFISSIONAL.md`. Os links de fontes primárias estão nesses guias. A versão 1.1 preserva GPL e atribuição; atualizações oficiais diferentes da versão revisada exigem compatibilidade antes de reativar a camada.
