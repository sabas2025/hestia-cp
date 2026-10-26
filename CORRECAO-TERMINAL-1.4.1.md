# Professional 1.4.1 — comandos do Terminal Web

A lista nativa apresenta o serviço com o identificador `web-terminal`, mas
consulta a unidade `hestia-web-terminal`. Os botões de iniciar, parar e
reiniciar encaminhavam o identificador de apresentação ao systemd, que podia
recusar a operação por não encontrar uma unidade com esse nome.

Os três comandos nativos agora convertem esse identificador para
`hestia-web-terminal` após validar os argumentos. Chamadas com o nome canônico
continuam válidas. O tratamento dos outros serviços e múltiplas versões PHP
permanece coberto pelos testes.

Foi corrigido também o retorno de iniciar/parar: o resultado do systemctl
ficava oculto pelo sucesso posterior do registro no log. Uma falha real passa
a produzir retorno de erro, mesmo quando o registro no log funciona.

A correção mantém o requisito de Node.js 24 ou posterior para ativar o
Terminal Web. Não instala outro Node, não recompila dependências e não altera
portas ou firewall. Um nome correto não garante que o serviço real consiga
iniciar; pacote, runtime, dependências nativas e configuração ainda devem ser
verificados se a unidade correta falhar.

## Atualizar e validar

Use o helper publicado e conferido por SHA-256. Em uma instalação existente,
execute `plan --components ''`, depois `apply --components ''` e aguarde
`status` com `succeeded`, destino 1.4.1. O snapshot de reversão inclui as três
CLIs nativas acrescentadas à camada. Os testes conferem também a reversão de
uma instalação anterior, cujo manifesto ainda não gerenciava essas CLIs.

Depois da atualização, no console root:

```bash
/usr/local/hestia/bin/v-start-service web-terminal
systemctl is-active hestia-web-terminal.service
```

Para diagnosticar uma recusa, reúna apenas os campos de estado e a versão do
runtime, sem exportar configurações completas nem registros de sessões:

```bash
/usr/bin/node --version
systemctl show hestia-web-terminal.service web-terminal.service \
  --property=Id,LoadState,ActiveState,SubState,Result,ExecMainStatus --no-pager
/usr/local/sbin/hestia-professional-update status
```

Testes executam as CLIs Bash reais com bootstrap de autenticação e systemctl
explicitamente substituídos por fixtures. Cobrem ambos os nomes, falhas de
iniciar/parar/reiniciar, preservação dos demais serviços, firewall e múltiplos
PHPs. Isso não inicia serviços nem acessa uma VPS durante o CI.
