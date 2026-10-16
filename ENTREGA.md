# Registro das alterações — HestiaCP Professional 1.0.0

Data: 15/10/2026. Base: HestiaCP 1.10.5. As alterações foram aplicadas ao código deste pacote; nenhuma VPS foi acessada ou modificada.

## Correções da auditoria

| Achado | Alteração implementada | Verificação |
|---|---|---|
| A01 — `eval` | Parser explícito e expansão de variáveis sem reinterpretação de shell | Entradas com apóstrofos, cifrão, espaços e tentativa de comando |
| A02 — status do APT | Etapas críticas executam sincronamente e propagam o status real | APT simulado com retorno 42 encerra com 42 e mantém o log |
| A03 — temporários | Diretório privado exclusivo, arquivos sensíveis 0600 e configuração publicada por renomeação | Modos, symlinks, integridade e limpeza |
| A04 — código pela rede | Remoção de `curl | bash` e self-update implícito; Rclone/Restic por APT; componentes externos fixados por hash | Download com falha e hash divergente são recusados |
| A05 — lançador | Execução somente do filho local, matriz de SO explícita, HTTPS/timeout/retry para recursos externos | SO com aspas, distribuições/versões incompatíveis e sintaxe |
| A06 — credenciais | Entrada silenciosa e confirmada, FD/arquivo restrito; senhas de conta e banco fora dos argumentos externos | Espaços/apóstrofos preservados, arquivo inseguro e múltiplas linhas recusados |
| A07 — implantação | Inspeção sem alterações, confirmação inicial, bloqueio de pilha existente e concorrência; sem force/purge de conflitos | CyberPanel, aaPanel, Hestia e dados MySQL existentes bloqueados |
| A08 — confiança do APT | Remoção do relaxamento global no Ubuntu; keyrings com bytes aprovados e repositórios HTTPS | Busca dos padrões antigos e conferência do lock |
| A09 — conclusão | Upgrade final aguardado; configuração/serviços verificados antes das mensagens de sucesso | Ordem da conclusão e testes de propagação de erro |
| A10 — recuperação/log | `trap`, recuperação da política anterior, log por execução e preservação do original se recuperação falhar | Falhas e saídas 7/130/143; modos originais preservados |
| A11 — validação | Porta, FQDN, usuário, opções, booleanos, PHP e modo não interativo validados cedo | Matriz de entradas válidas e inválidas, EOF e campos ausentes |
| A12 — componentes | PHP 8.4 padrão, lista reduzida, política de revisão, lock e inventário efetivo | Sintaxe, hashes, aplicação idempotente e revisão de upgrade |

Os hashes fixados registram os bytes aprovados durante a montagem, obtidos pelas fontes HTTPS indicadas; não representam assinatura digital própria dos fornecedores. Pacotes do sistema continuam sob autenticação do APT. A origem e a versão dos componentes devem ser revisadas ao atualizar o lock.

## Camada profissional implementada

- Central responsiva com visão geral, atalhos, busca, estado vazio e atualização manual.
- Autenticação reaproveitada do Hestia; autorização adicional contra dados atuais de conta e papel.
- Separação de dados de administrador/cliente e de contas em contexto de impersonação.
- Bloqueio de conta suspensa, mudança de papel, comandos fora da lista permitida e troca de conta por parâmetro de URL.
- Respostas privadas sem cache, CSP, escape de conteúdo e ausência de códigos 2FA ou hashes de senha nos dados enviados ao navegador.
- Aviso para configurar 2FA, acesso às preferências e perfil de API de consulta sem wildcard.
- Tema em caminho customizado, link no painel nativo e reaplicação por hook preservando o anterior.
- Coletor de saúde, prazo de validade da coleta, inventário, monitoramento por timer e alertas visíveis.
- Backup consistente nativo com cópia criptografada, controle de concorrência, estado de andamento e verificação de prazo.
- Ensaio de recuperação isolado com estimativa de espaço, verificação de arquivo e duração registrada.
- Ferramenta de inspeção e roteiro de migração do HUB, sem alterar dados ou DNS.
- Prévia visual em `professional/preview.html`, com dados explicitamente ilustrativos.

## Resultados

| Grupo | Resultado |
|---|---|
| Testes Python | 43 aprovados; nenhum erro ou teste pulado na execução registrada |
| Asserções PHP | 29 aprovadas |
| HTTP local | Incluído na suíte Python: autenticação simulada explicitamente em fixture, escopo, suspensão, métodos e headers |
| Revisão visual | 360, 768 e 1440 px; busca e estado vazio funcionais; sem overflow horizontal ou erros de JS |
| Bash/PHP/JavaScript | Sintaxe aprovada nos arquivos novos ou alterados da camada |
| ShellCheck | Código comum/lançador sem warnings selecionados; filhos sem achados de nível error; a base legada não foi inteiramente refatorada para remover todos os avisos históricos |
| Implantação real | Não realizada |

O resultado detalhado acompanha `professional/test-results/verification.json`. Os testes PHP foram executados em PHP 8.3.6, e não equivalem a instalar toda a pilha em PHP 8.4. Os comandos de operação foram testados com fixtures e executores simulados onde exigiriam banco, serviço ou armazenamento real.

## Etapas que dependem do servidor

O código e as ferramentas foram entregues. Para ativar a operação, ainda é necessário cadastrar o destino e o segredo do backup, configurar o autenticador 2FA, apontar o DNS, emitir certificado real e homologar a instalação e o HUB em uma VPS nova.

Não foi criado um importador automático de CyberPanel/cPanel, nem foi comprovada a restauração completa de banco e aplicação em uma máquina real. O ensaio automatizado fornecido cobre a recuperação da cópia Restic e a leitura do arquivo de backup. As integrações Tiny/VSM e o envio/recebimento real de e-mail permanecem parte da homologação operacional.

Uma atualização oficial diferente de 1.10.5 é preservada, mas exige revisão desta camada antes de reabrir a central customizada. O pacote não é uma certificação de equivalência funcional com cPanel/WHM.

## Arquivos centrais

`install/hst-common.sh`, os três instaladores, `install/assets.lock.tsv`, `professional/apply.py`, `professional/health.py`, `professional/inventory.py`, `professional/backup.py`, `professional/migration.py`, unidades systemd, `web/professional/` e o tema em `web/css/themes/custom/professional.css`.

Instruções: `PROFISSIONAL.md`. Rastreamento da origem: `UPSTREAM.json`. Diferenças completas: `ALTERACOES.patch`.
