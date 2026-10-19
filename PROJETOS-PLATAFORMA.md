# Editor, Docker, Compose, Node.js, marketing e proxy

Ferramentas da camada 1.1. As integrações não significam que Docker, Portainer, code-server ou listmonk já estejam instalados. A central mostra os módulos e libera atalhos HTTPS após configuração. Serviços externos mantêm autenticação própria. Operações de infraestrutura são feitas no terminal administrativo; o PHP não recebe permissões do daemon Docker.

## Online Code Editor

O botão **Abrir editor de arquivos** aparece quando o File Manager está habilitado na sessão Hestia e usa a rota nativa `/fm/`, preservando o escopo da conta. A instalação do File Manager já usa o download fixado por hash da camada anterior. Não foi criado um editor root via HTTP ou uma nova rota de gravação de arquivos.

Para uma experiência de IDE, instale code-server por uma release revisada e execute-o como usuário de aplicação, com autenticação, bind em loopback e TLS no gateway. Não use `--auth none` para exposição pública e não coloque a senha em URL. Registre um projeto `editor` com o dono e o endereço HTTPS; a central libera o atalho somente a esse dono e ao administrador. Alterações de código devem passar por Git, revisão e implantação, não por edição direta de produção como rotina.

## Docker management

Instale Docker Engine e o plugin Compose a partir dos pacotes oficiais adequados à distribuição, após revisão. O instalador Hestia não instala Docker automaticamente. Avalie um host separado para containers: o daemon privilegiado e suas regras de rede ampliam a superfície de administração da VPS.

```bash
python3 professional/projects.py docker containers
python3 professional/projects.py docker images
python3 professional/projects.py docker networks
python3 professional/projects.py docker volumes
python3 professional/projects.py docker disk
python3 professional/projects.py docker container-inspect --target NOME
python3 professional/projects.py docker container-stats --target NOME
python3 professional/projects.py docker container-logs --target NOME
python3 professional/projects.py docker container-restart --target NOME
python3 professional/projects.py docker container-restart --target NOME --apply
```

Também há start, stop e remoção de contêiner, pull/remoção de imagem e criação/remoção de redes e volumes. O pull gerenciado exige digest `imagem@sha256:...`. Nenhum comando remove recursos à força ou executa prune global. Saídas e logs ficam restritos ao terminal do administrador; logs de aplicação podem conter dados pessoais ou tokens e não são publicados pela central.

Para **gerenciamento visual completo**, a integração é com Portainer CE. Gere uma stack privada com a imagem fixada por digest revisado:

```bash
python3 professional/stacks.py portainer --image 'portainer/portainer-ce@sha256:DIGEST_REAL_DE_64_HEXADECIMAIS' --output /etc/hestiacp/professional/projects/portainer.compose.json --apply
```

O comando acima é um modelo: substitua o digest. O gerador não inicia serviços. Revise o arquivo root/0600, use o Compose administrativo para validá-lo e iniciá-lo e cadastre imediatamente o administrador por um acesso protegido. O container publica apenas `127.0.0.1:9443`; use túnel SSH ou gateway HTTPS corretamente configurado, mantendo a verificação do certificado. A stack monta o socket Docker porque o Portainer precisa controlar o daemon: esse acesso equivale à administração do host. Por isso ela é **separada** das stacks de aplicação e recusada pelo guard de Compose comum. Não a entregue a clientes do painel, não exponha o socket em TCP e não desative autenticação.

O Portainer fornece operações adicionais, como console/exec e recursos avançados do daemon. O wrapper local cobre as operações listadas, não reimplementa toda a API Docker. Essa distinção evita apresentar um conjunto limitado de comandos como um gerenciador completo próprio.

## Compose management

Copie e edite `professional/projects.example.json` fora da raiz web, com dono root e modo 0600. Remova os exemplos que não usará. Cada Compose deve ser um arquivo root/0600, com SHA256 aprovado no cadastro. Se ele mudar, a ferramenta recusa a operação até nova revisão. O arquivo Compose pode ser JSON, que é aceito como YAML.

```bash
python3 professional/projects.py compose validate --config /etc/hestiacp/professional/projects.json --project marketing
python3 professional/projects.py compose status --config /etc/hestiacp/professional/projects.json --project marketing
python3 professional/projects.py compose up --config /etc/hestiacp/professional/projects.json --project marketing --apply
python3 professional/projects.py compose logs --config /etc/hestiacp/professional/projects.json --project marketing
```

Há up/down/start/stop/restart/pull/build/status/logs/validate. Down não inclui remoção de volumes. O nome Compose recebe prefixo `hestia-`. `.env` automático é desabilitado; valores necessários devem estar no documento privado revisado. O guard resolve a configuração e recusa privilégio elevado, host networking/PID, dispositivos, capabilities extras, bind mounts, volumes externos/driver host e portas publicadas fora do loopback. Imagens de up/pull devem estar fixadas por digest. Build está disponível para projetos confiáveis revisados; publicar a imagem e aprovar seu digest é necessário antes de up.

Não exponha portas Docker diretamente à internet supondo que o firewall Hestia/Fail2Ban vá filtrá-las: valide as regras do Docker e o gateway. Configurações arbitrárias, extensões desconhecidas e uso rootless precisam de homologação própria; o guard não é um sandbox para executar Compose de pessoas não confiáveis.

## NodeJS Project

Crie uma conta Hestia dedicada, um projeto em `/home/USUARIO/projects/NOME`, instale um Node.js LTS suportado e faça instalação/build de dependências **como o usuário da aplicação**. Não execute scripts npm de um repositório como root. A versão Node deve ser escolhida e mantida conforme o ciclo LTS oficial, não por um download remoto executado como shell.

O exemplo `professional/node-server.example.mjs` escuta em `127.0.0.1`, oferece `/health` e permite encerramento controlado. Adapte a aplicação real para respeitar o bind local. Cadastre dono, diretório, entrypoint, porta e um arquivo privado de ambiente em `/etc/hestiacp/professional/secrets/`.

```bash
python3 professional/projects.py node install --config /etc/hestiacp/professional/projects.json --project hub-node
python3 professional/projects.py node install --config /etc/hestiacp/professional/projects.json --project hub-node --apply
python3 professional/projects.py node start --config /etc/hestiacp/professional/projects.json --project hub-node --apply
```

A unidade `hestia-node-ID.service` usa UID não privilegiado, limites de memória/tarefas, `NoNewPrivileges`, filesystem restrito e reinício em falha. `install` grava a unidade e faz daemon-reload; não habilita nem inicia a aplicação. Use `enable` explicitamente após homologação; status/start/stop/restart estão disponíveis. Revise também portas ocupadas, permissões, dependências e segredos da aplicação.

## Proxy Project

```bash
python3 professional/projects.py proxy templates --config /etc/hestiacp/professional/projects.json --project proxy-app
python3 professional/projects.py proxy templates --config /etc/hestiacp/professional/projects.json --project proxy-app --apply
```

São gerados templates próprios `.tpl/.stpl` em `data/templates/web/nginx/`, sem editar o template default. Eles usam destino HTTP em `127.0.0.1:PORTA`, encaminham hostname/protocolo/IP e suportam upgrade WebSocket. O caminho ACME e o TLS nativo são preservados. Revise e atribua o template ao domínio pelo Hestia; teste `nginx -t`, certificado, WebSocket e aplicação antes de recarregar. A ferramenta não altera DNS nem atribui automaticamente um domínio.

**O proxy direto contorna o WAF Apache.** Coloque um gateway WAF homologado antes dessas aplicações ou forneça proteção adequada no serviço. Cabeçalhos de IP não devem ser confiados de proxies arbitrários; a configuração usa o IP remoto observado pelo Nginx.

## Email Marketing

A integração usa listmonk com PostgreSQL próprio. O gerador exige imagens fixadas e um JSON root/0600 com `db_password`, `admin_username` e `admin_password`, todos com pelo menos 12 caracteres nesta versão. Use senhas aleatórias, exclusivas. Ele não imprime as credenciais.

```bash
python3 professional/stacks.py marketing --image 'listmonk/listmonk@sha256:DIGEST_REAL' --database-image 'postgres@sha256:DIGEST_REAL' --credentials /etc/hestiacp/professional/secrets/marketing.json --output /etc/hestiacp/professional/projects/marketing.compose.json --apply
```

Substitua os digests; não são valores executáveis. Para o template fornecido, escolha PostgreSQL 16 ou 17 revisado, cujo diretório de dados corresponde ao volume configurado. Reavalie o layout antes de usar PostgreSQL 18 ou outra major. A aplicação fica em `127.0.0.1:9100`, e o banco não publica porta no host. Cadastre o SHA256 do documento gerado e use o gerenciamento Compose. O bootstrap inicializa tabelas de forma idempotente; migrações de upgrade exigem backup e execução revisada própria, não são disparadas indiscriminadamente em todo start.

Após a instalação, configure SMTP autenticado, domínio, SPF/DKIM/DMARC, lista com consentimento, opt-in, descadastro, limites de envio e tratamento de bounces. A stack **não envia campanhas**, não importa contatos e não configura SMTP automaticamente. Configure backup e restauração do PostgreSQL e do volume de uploads: eles não pertencem automaticamente ao backup de conta Hestia. O campo de integração não substitui esses controles nem garante entrega dos e-mails.

## Publicar os atalhos

```bash
python3 professional/projects.py catalog publish --config /etc/hestiacp/professional/projects.json --apply
```

O snapshot contém apenas IDs, tipo, dono e URLs HTTPS sem credenciais. Clientes veem apenas seus projetos de aplicação/editor; Docker administrativo e marketing são exclusivos do administrador. Em impersonação, o administrador recebe o mesmo escopo do cliente. URLs com tokens em query são recusadas pela central. Remover um atalho não desativa o serviço externo nem revoga suas credenciais; administre também as permissões da ferramenta.

## Fontes

- https://docs.docker.com/engine/security/
- https://docs.docker.com/compose/how-tos/production/
- https://docs.portainer.io/start/install-ce/server/docker/linux
- https://coder.com/docs/code-server/guide
- https://nodejs.org/en/about/previous-releases
- https://listmonk.app/docs/installation/
