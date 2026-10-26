# Professional 1.4.0 — arquivos por domínio e ativação do Terminal Web

A Central Professional agora reúne navegação de pastas, busca na página,
listagem paginada, editor UTF-8, criação de pasta, upload, download e
renomeação de arquivos. Um atalho também aparece ao editar um domínio com a
conta titular. Administradores podem selecionar outra conta na Central;
usuários comuns acessam somente seus próprios domínios ativos.

## Uso

1. Abra a Central Professional → Gerenciador de arquivos por domínio.
2. Selecione a conta, carregue os domínios e abra a pasta desejada.
3. Use Editar, Baixar ou Renomear na linha do arquivo; use Upload e Nova pasta
   na barra de ferramentas. O caminho é relativo ao `public_html` do domínio.
4. Para gravar, criar pasta, iniciar upload ou renomear, confirme a senha do
   próprio painel e um código A2F novo. Ative a A2F antes de usar essas ações.

O editor continua disponível em `/professional/editor.php`. O parâmetro
`domain` apenas seleciona uma sugestão: a propriedade é verificada no servidor.
O File Manager legado e suas dependências bloqueadas permanecem desativados.
O novo gerenciador não depende de Node.js e não é liberado pela opção antiga
File Manager das configurações nativas.

## Limites e garantias verificáveis

- Escopo: árvore `public_html` de cada domínio. Não gerencia o diretório pessoal
  inteiro, raízes personalizadas externas nem `public_shtml` separado.
- Listagem: 100 itens por página, até 10 mil entradas examinadas por pasta;
  busca filtra a página atual. Pastas e arquivos ocultos são recusados,
  exceto `.htaccess`. Links simbólicos, hardlinks e arquivos de outro dono
  não são apresentados ou transferidos. Diretórios compartilhados graváveis
  por grupo/outros requerem revisão e são recusados.
- Upload e download: até 64 MiB por arquivo, em blocos de 256 KiB. O upload
  confere tamanho e SHA-256 e publica por rename atômico sem sobrescrever.
  Um arquivo existente, inclusive criado durante o envio, é preservado.
- O envio usa uma autorização aleatória válida por 15 minutos, vinculada ao
  ator, conta, domínio, nome, tamanho e hash. Blocos seguintes não reutilizam
  o código A2F: usam essa autorização restrita a um único envio.
- Estágio do upload fica fora da raiz pública, com arquivos privados root.
  Há até dois uploads por conta e oito no total. Estágios expirados são limpos
  no início de um novo upload; não há limpeza periódica dedicada nesta versão.
- Downloads conferem a identidade e metadados do arquivo entre blocos e
  abortam se houver alteração. O navegador recebe um arquivo para download,
  sem exibir HTML ou SVG enviados como conteúdo do painel.
- Editor: texto UTF-8 até 256 KiB, validação de JSON/PHP, hash de concorrência
  e versões anteriores privadas. Renomeações preservam bytes e proprietário,
  exigem a versão atual e não substituem o destino. Renomear pode exigir
  atualizar referências no próprio site; a interface não reescreve links.
- Upload é publicação de conteúdo autorizado do site; não extrai arquivos,
  não executa instaladores e não comprova varredura antivírus em tempo real.
  Para arquivos maiores, use o acesso SFTP da conta.

## Ativar ou desativar o módulo

O módulo vem habilitado. Um administrador pode desativar todas as operações
pela política privada persistente, que não é substituída pelo atualizador.
Execute como root; troque `False` por `True` para reativar:

```python
from pathlib import Path
import sys
sys.path.insert(0, '/usr/local/hestia/professional')
from ops import private_directory
from mfa import root_json
folder = private_directory(Path('/usr/local/hestia/data/professional-filemanager'), 0o700)
root_json(folder / 'policy.json', {'schema': 1, 'enabled': False})
```

## Terminal Web e Node.js

O ativador nativo exige Node.js 24 ou posterior. A instalação das ferramentas
Node Professional pode disponibilizar o Node da distribuição em versão 22,
adequada a outros projetos, mas insuficiente para esse ativador.

A correção verifica `/usr/bin/node`, instalação e estado do serviço antes de
registrar `WEB_TERMINAL=true`. Falhas em instalação, partida, habilitação ou
verificação não são reportadas como ativação concluída. O formulário não
substitui o Node global por outro major nem instala repositório NodeSource.
Uma versão insuficiente continua sendo recusada; o requisito não foi reduzido.

Para salvar outras configurações com Node 22, recarregue a página e deixe
Terminal Web em Não. Se uma tentativa antiga deixou o sinalizador incoerente,
o comando nativo `v-delete-sys-web-terminal` permite desativar o componente;
a revisão e instalação de Node 24 continuam sendo tarefa do console.
Esta versão não atualiza o Node nem ativa o terminal automaticamente.

## Atualização e validação

Use o helper publicado com fonte, inventário e SHA-256 fixados. Em instalações
existentes, `plan --components ''` e `apply --components ''` atualizam a camada
sem reinstalar dependências opcionais. Aguarde `status` com `succeeded` e
confirme versão de destino 1.4.0 e integridade. O snapshot de reversão da
camada inclui o template de edição do domínio e o ativador do terminal.

Os testes de filesystem cobrem conteúdo binário, blocos, expiração, A2F,
isolamento, links, permissões, colisões e consistência. Os testes de navegador
usam a interface real com respostas de serviço explicitamente simuladas em
360, 768 e 1440 px; exercitam edição, upload dividido, download e renomeação.
Testes separados verificam o guard CSRF nativo e o ativador Bash real com
Node/serviços de teste. Esses testes não acessam nem atualizam uma VPS.
