# Implantação Professional 1.2 pelo GitHub

O diagnóstico SSH de 25/10/2026 foi concluído na [execução 40172586048](https://github.com/sabas2025/hestia-cp/actions/runs/40172586048): Ubuntu 26.04.1 LTS, aproximadamente 4 GB RAM, 46 GB livres, sem painéis nos caminhos verificados. Isso não comprova, sozinho, que não há dados fora desses caminhos. Nenhuma instalação foi realizada por essa execução.

Este fluxo instala a revisão **f974fbf852270d0f0b1d0a451b5dea0c409119b4**, Professional 1.2.0/Hestia 1.10.5. O bootstrap fixa o commit e o SHA-256 do manifesto, verifica todos os 1.697 arquivos, recusa arquivos extras, links e caminhos inseguros e preserva a origem verificada em diretório root privado. Não acompanha automaticamente novos commits de main.

## Configuração de DNS

Publique no provedor DNS autoritativo um registro A do hostname escolhido apontando diretamente ao IP da VPS. Caso use um proxy DNS/CDN, mantenha esse hostname em modo somente DNS para a porta 8083. A presença de um AAAA exige revisão do IPv6 antes desta implantação: o bootstrap o recusa enquanto não houver validação do endereço da VPS. O plano só aceita o A da origem prevista no código.

## Preparação local, uma vez, pelo console da VPS

1. Faça um snapshot pelo provedor e confira se há dados próprios a preservar. O backup de configuração criado pelo bootstrap não substitui snapshot nem backup dos sites e bancos.
2. Baixe `ops/vps-implantacao.py` de uma revisão publicada e revisada deste repositório, confira seu SHA-256 e instale como `/usr/local/sbin/hestia-github-implantacao`, propriedade root, modo 0755. Não execute de uma pasta gravável por usuários sem privilégio.
3. Execute como root:

```bash
/usr/local/sbin/hestia-github-implantacao setup \
	--hostname HOSTNAME_REAL --email EMAIL_ADMINISTRATIVO
```

O setup solicita a senha duas vezes com entrada oculta. Use 14–128 caracteres com maiúscula, minúscula e número, sem dois-pontos nem quebra de linha. Ela fica somente em `/etc/hestia-github-deploy/admin-password`, root/0600, e não é enviada ao GitHub. O usuário do painel é `admin`. A configuração fica em `config.json`, no mesmo diretório privado.

O setup valida a chave pública dedicada já usada no diagnóstico e altera somente a autorização dessa chave em `/root/.ssh/authorized_keys`, preservando as outras linhas e um backup privado. Ela passa a executar o helper restrito, que aceita somente `plan`, `start`, `status` e a chamada de diagnóstico anterior. Não libera shell, SFTP, túneis ou comandos arbitrários. O setup requer console root e não pode ser solicitado pela chave do workflow.

Os Secrets `VPS_HOST`, `VPS_SSH_KEY` e `VPS_KNOWN_HOSTS` continuam os mesmos. Mantenha a verificação estrita da chave do host e o console do provedor disponível durante a instalação.

## Executar no GitHub

Abra **Actions → Implantacao Hestia Professional na VPS → Run workflow → main**.

Primeiro selecione `plan`: verifica fonte, DNS, existência de usuário/grupo admin e as barreiras nativas de sistema limpo. A preparação pode baixar a origem para cache privado, mas não instala pacotes. DNS ausente, proxy apontando a outro IP, AAAA não validado, stack existente ou Netplan vazio geram bloqueio, sem `--force` ou correção de rede automática.

Com o plano aprovado, execute novamente com `install`. O workflow solicita a instalação por SSH e acompanha o estado, enquanto um serviço transitório systemd executa o instalador na VPS. Não depende de manter a conexão SSH original aberta. A senha não aparece nos argumentos do processo, nos Secrets ou no resultado público.

O perfil instala Nginx com Apache, PHP 8.4, MariaDB, BIND, Exim/Dovecot/Sieve, ClamAV/antispam de e-mail, firewall/Fail2Ban e limites nativos de recursos, em português, porta 8083. Não instala FTP nem terminal web. As funcionalidades empresariais ainda pendentes em [EMPRESARIAL-1.2.md](EMPRESARIAL-1.2.md) continuam pendentes; ClamAV de e-mail não equivale a antivírus em tempo real dos sites com GUI.

## Estado, integridade e limites

O estado público distingue `queued`, `running`, `succeeded`, `failed`, `launch-failed`, `queue-expired` e `interrupted-review`. `succeeded` exige término do instalador, manifesto instalado verificado, verificações de configuração/saúde, serviço Hestia ativo e conexão TCP local na porta 8083. Não comprova login real, entrega de e-mail, eficácia do WAF/limites, HTTPS público com certificado confiável nem recuperação completa de backups.

A mensagem inicial de boas-vindas por e-mail é suprimida por uma substituição local exata e revisada no script Ubuntu, na cópia de trabalho. O original verificado permanece preservado; os demais arquivos são os da revisão fixada. Isso não desativa serviços de e-mail instalados. O instalador não publica a senha nem envia mensagem de boas-vindas por esse bootstrap.

O serviço tem prazo máximo de 90 minutos; o comando nativo tem timeout menor. O workflow acompanha por até aproximadamente 90 minutos e tolera falhas transitórias de consulta SSH. Cancelar o job GitHub não desfaz nem necessariamente interrompe a instalação na VPS. Use a ação `status` ou o console para consultar antes de qualquer tentativa adicional.

Uma instalação já registrada não é repetida automaticamente. Falha parcial requer revisão por console, sem purge ou rollback automático de pacotes e sem reinstalação sobre os dados. Setup também recusa substituir uma configuração existente silenciosamente. O arquivo de senha é removido quando o worker conclui ou falha normalmente; encerramento forçado pode exigir limpeza administrativa.

## Arquivos privados para recuperação

Todos ficam na VPS, sem upload como artifact do GitHub:

- `/etc/hestia-github-deploy/config.json`: configuração administrativa, root/0600.
- `/etc/hestia-github-deploy/authorized_keys.before-*`: backup das autorizações SSH.
- `/var/lib/hestia-github-deploy/job.json`: estado privado, sem senha.
- `/var/lib/hestia-github-deploy/installation.log`: saída privada do instalador, root/0600.
- `/var/lib/hestia-github-deploy/configuration-before.tar.gz`: SSH, APT, rede e identificação anteriores; contém arquivos sensíveis, root/0600.
- `/var/lib/hestia-github-deploy/source`: origem fixada, conferida por manifesto.
- `/var/lib/hestia-github-deploy/working`: cópia efetivamente usada, com a supressão da mensagem inicial.

Os testes do bootstrap usam fixtures e simulação de comandos externos; não executam um instalador completo nem alteram SSH do host de testes. O diagnóstico real anterior só comprovou leitura. A implantação real só pode ser declarada após o worker na VPS e a verificação de seu resultado.
