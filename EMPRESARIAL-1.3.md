# Hestia Professional 1.3 — atualização da instalação existente

Esta entrega acrescenta ferramentas operacionais. A publicação no GitHub e a aplicação
na VPS são estados diferentes. Não reutilize `hst-install.sh` nem o comando `start`
do bootstrap de instalação para atualizar um servidor que já tem sites e e-mail.

## Conteúdo implementado

| Área | Entrega 1.3 | Limite de validação |
| --- | --- | --- |
| Editor online | Navegação, leitura, criação, salvamento, validação PHP/JSON, hash de concorrência e 50 revisões privadas por conta | UTF-8 até 256 KiB; somente `public_html` de domínios pertencentes à conta; sem links; gravações exigem senha e A2F |
| Docker | Inventários, logs, recursos, estado, iniciar/parar/reiniciar/remover, imagens por digest, redes e volumes | Administrador; daemon local; exclusão confirmada; sem terminal ou comando arbitrário |
| Compose, Node e marketing | Inventário e operações de ciclo de vida dos projetos registrados | Configuração privada revisada é necessária; não cria uma aplicação a partir de seu código nem conclui a configuração do listmonk |
| Backups | Exibe backup nativo separado do fluxo criptografado; executar, verificar, ensaiar recuperação do arquivo, retenção e agendamento dos destinos cadastrados | Credenciais e repositório reais são necessários; ensaio de TAR não comprova importação SQL ou recuperação do site |
| WAF e Fail2Ban | Interface de perfis observação/básico/intermediário/avançado e ativação/desativação gerenciada | WAF Apache; aplicações diretas no Nginx, Node e painel 8083 exigem cobertura específica |
| Permissões | Aceita os arquivos nativos root:root 660 e diretórios 770 | Continua recusando gravação por outras contas/grupos e caminhos com links |
| Atualização | Fonte imutável, manifesto SHA-256, inspeção prévia, backup dos arquivos alterados, verificação e reversão de falhas capturadas | Reversão de arquivos da camada; não reverte pacotes ou uma queda abrupta de energia |
| Dependências | Instalação pelo console de Restic/rclone, ModSecurity/CRS, Docker/Compose e Node usando APT autenticado | Não substitui Docker CE/customizado por outro pacote; conflitos exigem revisão; pacotes não são removidos automaticamente em falhas |

As novas ferramentas estão em `/professional/editor.php` e `/professional/platform.php`.
A central principal contém os links. Operações administrativas passam pela fila com
reautenticação. Uma solicitação aceita não prova que o trabalho terminou: consulte
**Solicitações** e depois **Tarefas**, verificando `succeeded` ou `failed`.

## Implantar

O helper `ops/vps-atualizar.py` da publicação final contém o commit e o SHA-256 do
manifesto da fonte aprovada. Baixe uma revisão imutável, confira o SHA-256 publicado
para o helper e instale-o como `/usr/local/sbin/hestia-professional-update`, root:root 0755.

Fonte fixada nesta entrega: `fb8cb26905b0ce3da4cf9c8713a6eb55772dbfc2`, 1.737 arquivos;
SHA-256 de `SHA256SUMS`: `b8af0f75529e1bba0dc3fa07a15b7c88bea603f118f99cecdf2f240479021c3d`.
A revisão posterior fixa o bootstrap nessa fonte e acrescenta testes de encerramento
da tarefa. A CI também baixa e verifica o ZIP imutável sem acessar a VPS.

```bash
/usr/local/sbin/hestia-professional-update plan
/usr/local/sbin/hestia-professional-update apply
/usr/local/sbin/hestia-professional-update status
```

O IP de recuperação é obtido de `SSH_CONNECTION`. Fora de uma sessão SSH direta,
informe `--admin-cidr SEU_IP_PUBLICO/32` (IPv6 `/128`) em `plan` e `apply`. O helper
inicia uma tarefa systemd, que continua após a saída do terminal. O estado final só
fica `succeeded` após atualização, configuração das dependências e inspeção local.
Para atualizar somente os arquivos da camada, use `apply --components ''`.

Os registros e cópias de reversão ficam em `/var/lib/hestia-professional-upgrade`,
restritos a root. A configuração de dependências mantém estado privado em
`/usr/local/hestia/data/professional-dependencies/status.json`. Uma falha nas
dependências pode ocorrer depois da atualização dos arquivos; `overlay_updated`
mostra essa diferença. Não reinstale o painel para corrigir isso.

O WAF começa com `DetectionOnly`/PL1. Após revisar o tráfego do site, o administrador
pode selecionar **Básico** na interface e testar requisições legítimas e bloqueios.
Os endereços de recuperação e as exceções efetivas anteriores do Fail2Ban são preservados.
Não há declaração de teste de ataque apenas porque o módulo está carregado.

## Cadastro necessário na VPS

1. Entre com `sabasadmin` em `/professional/twofactor.php`; leia o QR no seu
   autenticador, confirme o código e guarde os códigos de recuperação fora da VPS.
   Não envie senhas, sementes ou códigos por chat/GitHub.
2. Para nuvem, configure `/etc/hestiacp/professional/cloud-backup.json` e os arquivos
   de credenciais com root:root 0600. Use o exemplo e o fluxo documentado em
   `professional/cloud_backup.py`. Drive, S3 Amazon/privado, SFTP, FTPS, FTP e
   WebDAV dependem de autorização/destino próprio. FTP requer aceite explícito da
   ausência de TLS; FTPS/SFTP são preferíveis. Nenhum destino é inventado ou
   habilitado sem credenciais. Inicialize, execute, verifique e faça o ensaio antes
   de ligar o timer da conta. Para `ctba.top`, a conta proprietária é `sabas`.
3. Para projetos, cadastre `professional/projects.example.json` no caminho privado
   `/etc/hestiacp/professional/projects.json`, ajustando conta, porta, domínio e
   imagens por digest. Use os geradores existentes de Node/proxy/stacks para revisão
   pelo console. Compose gerenciado recusa bind mounts, privilégios e portas públicas.
   A implantação de Portainer com socket Docker continua uma integração separada,
   administrativa, equivalente a acesso root; o gerador não significa instalação.

## Requisitos que continuam sem entrega completa

Não estão implementados/homologados como produto nesta versão: OpenLiteSpeed como
backend alternativo, antivírus em tempo real com GUI, administração NoSQL e
replicação de bancos, cluster/failover automático, limite conjunto de CPU/RAM
cobrindo PHP/Docker/SQL por usuário, backup incremental de arquivos/blocos e WORM
verificado no provedor. Os protótipos antigos permanecem excluídos do instalador.
O assistente existente gera orientações e diagnósticos locais; não é um agente
autônomo nem altera o DNS do provedor externo.

Esses itens exigem implementação e testes próprios. Cluster/replicação/failover
também precisam de outros servidores e definição de quorum, topologia, RPO/RTO e
recuperação. `append_only` local não comprova Object Lock/WORM. Restic sobre o TAR
completo atual não equivale a snapshots ou incrementais diretos dos sites.

## Aceitação na VPS

- Confira `status`, `health.py`, `security.py status` e a integridade da camada.
- Confirme A2F do administrador, login normal e códigos de recuperação.
- Salve e restaure um arquivo de teste sem dados sensíveis no editor.
- Verifique as seis jails e teste banimento com um IP de teste, preservando o de recuperação.
- Faça backup de `sabas`, envio ao destino e recuperação em ambiente separado;
  importe o SQL de teste e valide o site antes de considerar restauração homologada.
- Verifique envio/recebimento de e-mail e autenticação SPF/DKIM/DMARC após a atualização.

Os testes automatizados usam fixtures e respostas de serviços simuladas. Capturas
de `editor-preview.html` e `platform-preview.html` são prévias ilustrativas e não
prints da VPS. A validação remota só pode ser afirmada com resultados coletados lá.
