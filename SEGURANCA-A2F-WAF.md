> **Operação atual 1.1.1:** leia [CORRECOES-1.1.1.md](CORRECOES-1.1.1.md) antes de usar os procedimentos abaixo. A2F, estados WAF, drill histórico e disponibilidade do File Manager foram alterados. O texto 1.0/1.1 abaixo permanece como referência histórica onde houver diferença.

# A2F, WAF e Fail2Ban — operação 1.1

Esta entrega adiciona controles ao código. Nenhuma proteção foi ativada na VPS do proprietário durante o desenvolvimento.

## Autenticação de Dois Fatores

A central mostra o estado real da conta, um roteiro e o botão **Configurar A2F**, que abre as preferências nativas do Hestia no escopo correto. O coletor informa apenas a quantidade de administradores ativos sem A2F. Segredos TOTP, QR Codes e recuperação não entram no JSON da central.

A auditoria identificou `QRServerProvider` no gerador nativo. Ele foi substituído por um provedor local que envia o URI ao `professional/qr.py` por stdin. O helper usa `python3-qrcode`, gera SVG localmente e não acessa um serviço de QR externo. A verificação TOTP também lê segredo e token por stdin; a interface HTTP dos scripts de geração/verificação é recusada. Falha de geração impede salvar uma configuração de A2F incompleta.

Os novos instaladores incluem `python3-qrcode`. Em um Hestia existente, instale-o pelo APT autenticado **antes** de aplicar a camada. O aplicador verifica hashes dos quatro arquivos nativos de A2F e recusa sobrepor uma modificação local desconhecida. Uma versão diferente de Hestia exige revisão.

Para ativar na conta real: habilite A2F nas preferências, leia o QR Code no autenticador e guarde a recuperação fora do servidor. Mantenha a sessão atual aberta e teste novo login em outra janela, com senha e código temporário. Confira horário/NTP do servidor e do celular. Não confirme ativação apenas porque um QR foi exibido.

O cadastro e a desativação continuam sujeitos ao fluxo nativo do Hestia; esta versão não implementa passkeys, códigos de recuperação de uso único nem uma nova exigência de reautenticação nesse fluxo. O segredo permanece no armazenamento nativo, que exige proteção dos arquivos, disco e backups. Recomendação de próxima etapa: confirmação TOTP antes da conclusão do cadastro, reautenticação para troca/desativação e recuperação de uso único, com revisão específica de autenticação. Se uma instalação anterior gerou o QR por serviço externo, reavalie a rotação do fator no fluxo nativo.

## WAF

| Perfil | ModSecurity | CRS | Uso |
|---|---|---|---|
| `observacao` | DetectionOnly | PL1 | Homologação e identificação de falsos positivos |
| `basico` | On | PL1 | Proteção inicial após revisão |
| `intermediario` | On | PL2 | Aplicações já ajustadas e monitoradas |
| `avancado` | On | PL3 | Maior rigor e acompanhamento próximo |

O perfil altera também a tolerância das jails gerenciadas quando `fail2ban: true`: 5/5/4/3 tentativas e banimento de 10/15/30/60 minutos. **Observação refere-se ao WAF; Fail2Ban continua banindo tentativas de autenticação.** Para observar somente o WAF, configure `fail2ban: false`.

A aplicação automática é limitada ao Hestia com Apache, normalmente atrás de Nginx, e ModSecurity 2 + CRS instalados pela distribuição. Instale `libapache2-mod-security2` e `modsecurity-crs`, prepare `modsecurity.conf`, confira o carregamento de `security2_module` e teste o Apache. A ferramenta não instala conectores binários, não baixa regras executáveis e não desativa validação de TLS.

O módulo carrega a configuração base, configura inspeção de requisição, aplica o nível antes das regras e preserva os caminhos padrão de exclusões por aplicação do CRS. Políticas adicionais ou loader customizado exigem mesclagem manual, em vez de substituição silenciosa. A configuração proposta e o diff podem ser inspecionados antes da aplicação.

```bash
install -o root -g root -m 0600 professional/security.example.json /etc/hestiacp/professional/security.json
```

Edite o arquivo, informe o IP administrativo real em `admin_cidrs` e mantenha acesso ao console do provedor. O exemplo `192.0.2.10/32` é inválido para sua administração real. Exceções só aceitam redes estreitas, /24 ou mais específico no IPv4 e /64 no IPv6. Quando executado por SSH, o IP da conexão deve estar incluído.

```bash
python3 professional/security.py plan --config /etc/hestiacp/professional/security.json
python3 professional/security.py apply --config /etc/hestiacp/professional/security.json --apply
python3 professional/security.py status
```

São salvos bytes, modos e hashes dos arquivos anteriores. Todos os serviços alterados são validados antes de qualquer reload. Falha restaura os arquivos e tenta recarregar a configuração anterior. Se a recuperação do serviço também falhar, a ferramenta informa necessidade de console e preserva a transação. O ID de rollback é registrado no resultado:

```bash
python3 professional/security.py rollback --transaction ID_DA_TRANSACAO_ATIVA --apply
```

O rollback só aceita a transação ativa, não caminhos arbitrários. Restaurar configuração não desfaz todas as consequências de um banimento já aplicado; revise os banimentos com as ferramentas nativas do Fail2Ban.

## Fail2Ban

São aproveitadas as jails nativas `ssh-iptables` e `hestia-iptables`, filtros e ação Hestia, sem criar outra jail SSH concorrente. O arquivo novo é `jail.d/99-hestia-professional.local`; a lista efetiva de IPs/redes/hostnames ignorados é consultada no daemon e mesclada com os IPs administrativos, sem depender de uma interpolação ausente na configuração original. Planejamento e aplicação exigem as jails em operação. A ferramenta não reescreve o firewall inteiro.

Não foi criado um filtro que bane qualquer IP por receber HTTP 403: isso confundiria rejeições normais com ataque e poderia bloquear clientes, callbacks Tiny/VSM e serviços atrás de NAT. Expanda para jails de e-mail ou aplicação apenas com logs apropriados e testes de falsos positivos.

## Cobertura e testes na VPS

O WAF Apache inspeciona somente tráfego que passa pelo Apache. Arquivos estáticos servidos diretamente pelo Nginx, a porta do painel 8083, proxy direto para Node/Docker, conexões ao backend e DDoS volumétrico não ganham cobertura automaticamente. Para Nginx-only ou proxies diretos, use um gateway WAF homologado ou um conector ModSecurity v3 compatível; esta versão recusa prometer ativação automática nessas arquiteturas.

O limite de corpo padrão é 128 MiB e o limite de dados sem arquivos, 1 MiB. Ajuste esses valores junto com Nginx/PHP/aplicação para os vídeos de devolução do CRM. Limites do WAF não substituem limites e inspeção de upload da aplicação. Corpos de resposta não são inspecionados nesta configuração. Logs minimizam cabeçalhos/corpos, mas mensagens de regras podem conter dados correspondentes; restrinja acesso, revise retenção/logrotate e dados pessoais.

Na homologação, verifique requisição legítima e teste controlado de SQLi/XSS, login, upload grande, API, OAuth, assinatura de webhook, e-mail, IPv6, endereço real por proxy e rollback. Exceções devem tratar a regra/rota específica; não desative o WAF global para liberar o HUB. Restrinja a exposição de portas e use proteção de rede do provedor conforme a necessidade.

## Fontes

- https://coreruleset.org/docs/1-getting-started/1-1-crs-installation/
- https://coreruleset.org/docs/2-how-crs-works/2-2-paranoia_levels/
- https://github.com/fail2ban/fail2ban/blob/master/config/jail.conf
- https://hestiacp.com/docs/user-guide/account
- https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html
- https://github.com/RobThree/TwoFactorAuth/tree/v3.0.3
