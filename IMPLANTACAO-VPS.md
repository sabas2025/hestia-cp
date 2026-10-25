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

O setup solicita a senha duas vezes com entrada oculta. Use 14–128 caracteres com maiúscula, minúscula e número, sem dois-pontos nem quebra de linha. Ela fica somente em `/etc/hestia-github-deploy/admin-password`, root/0600, e não é enviada ao GitHub. O usuário inicial do painel é `admin`; `setup --username NOME` permite escolher outro nome válido. A configuração fica em `config.json`, no mesmo diretório privado.

O setup valida a chave pública dedicada já usada no diagnóstico e altera somente a autorização dessa chave em `/root/.ssh/authorized_keys`, preservando as outras linhas e um backup privado. Ela passa a executar o helper restrito, que aceita somente `plan`, `start`, `status` e a chamada de diagnóstico anterior. Não libera shell, SFTP, túneis ou comandos arbitrários. O setup requer console root e não pode ser solicitado pela chave do workflow.

Os Secrets `VPS_HOST`, `VPS_SSH_KEY` e `VPS_KNOWN_HOSTS` continuam os mesmos. Mantenha a verificação estrita da chave do host e o console do provedor disponível durante a instalação.

## Executar no GitHub

Abra **Actions → Implantacao Hestia Professional na VPS → Run workflow → main**.

Primeiro selecione `plan`: verifica fonte, DNS, existência de usuário/grupo admin e as barreiras nativas de sistema limpo. A preparação pode baixar a origem para cache privado, mas não instala pacotes. DNS ausente, proxy apontando a outro IP, AAAA não validado, stack existente ou Netplan vazio geram bloqueio, sem `--force` ou correção de rede automática.

Com o plano aprovado, execute novamente com `install`. O workflow solicita a instalação por SSH e acompanha o estado, enquanto um serviço transitório systemd executa o instalador na VPS. Não depende de manter a conexão SSH original aberta. A senha não aparece nos argumentos do processo, nos Secrets ou no resultado público.

O perfil instala Nginx com Apache, PHP 8.4, MariaDB, BIND, Exim/Dovecot/Sieve, ClamAV/antispam de e-mail, firewall/Fail2Ban e limites nativos de recursos, em português, porta 8083. Não instala FTP nem terminal web. As funcionalidades empresariais ainda pendentes em [EMPRESARIAL-1.2.md](EMPRESARIAL-1.2.md) continuam pendentes; ClamAV de e-mail não equivale a antivírus em tempo real dos sites com GUI.

## Estado, integridade e limites

O estado público distingue `queued`, `running`, `succeeded`, `failed`, `launch-failed`, `queue-expired` e `interrupted-review`. `succeeded` exige término do instalador, manifesto instalado verificado, verificações de configuração/saúde, serviço Hestia ativo e conexão TCP local na porta 8083. Não comprova login real, entrega de e-mail, eficácia do WAF/limites, HTTPS público com certificado confiável nem recuperação completa de backups.

A mensagem inicial de boas-vindas por e-mail é suprimida por uma substituição local exata e revisada no script Ubuntu, na cópia de trabalho. O original verificado permanece preservado; a referência da chave APT também recebe a correção exata descrita adiante; os demais arquivos são os da revisão fixada. Isso não desativa serviços de e-mail instalados. O instalador não publica a senha nem envia mensagem de boas-vindas por esse bootstrap.

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
- `/var/lib/hestia-github-deploy/working`: cópia efetivamente usada, com a supressão da mensagem inicial e a correção da referência da chave APT.

Os testes do bootstrap usam fixtures e simulação de comandos externos; não executam um instalador completo nem alteram SSH do host de testes. O diagnóstico real anterior só comprovou leitura. A implantação real só pode ser declarada após o worker na VPS e a verificação de seu resultado.

## Evidências do bootstrap

O [CI da revisão do bootstrap](https://github.com/sabas2025/hestia-cp/actions/runs/40174521420) foi aprovado. A suíte completa foi repetida sobre o ZIP publicado: **149 testes Python, zero falhas/erros/skips e 33 grupos aprovados**. A conferência encontrou **1.703 blobs e modos Git correspondentes e 1.702 checksums corretos**, sem divergências antes/depois dos testes. Os 22 testes novos exercitam o bootstrap e a comunicação do workflow com serviços simulados. A origem antiga fixada pelo instalador também foi baixada, extraída e verificada em seus 1.697 arquivos.

[Evidência estruturada](professional/test-results/vps-bootstrap-validation.json) e [suíte local](professional/test-results/verification-vps-bootstrap.json). Esse resultado valida o código publicado; a instalação real e o aceite dos serviços na VPS continuam pendentes.

## Grupo admin já existente

Se o plano informar `Administrator group already exists: admin`, preserve o grupo Linux. A instalação ainda não foi executada; escolha um nome livre para o administrador do painel.

O bootstrap atualizado oferece um comando de console root, indisponível pela chave SSH restrita:

```bash
/usr/local/sbin/hestia-github-implantacao set-user --username sabasadmin
```

Esse comando altera somente a configuração privada do bootstrap, com backup da configuração anterior. Valida o nome e recusa usuário/grupo já existente ou instalação já iniciada. Preserva a senha, as chaves SSH e os usuários/grupos do sistema. Não execute novamente `setup` nem apague grupos para contornar o bloqueio.

Depois de atualizar o helper instalado e executar `set-user`, rode `plan` novamente no GitHub. `installer_args` passa o usuário configurado ao instalador nativo; o instalador grava esse nome como `ROOT_USER`. O login do painel passa a ser o nome escolhido, usando a senha definida anteriormente.

[Evidência da correção de nome](professional/test-results/vps-username-fix.json) e [suíte atualizada](professional/test-results/verification-vps-username-fix.json). As evidências anteriores de 149 testes correspondem à revisão inicial do bootstrap, sem esta atualização.


## Recuperação da falha de chave APT em 25/10/2026

A primeira instalação parou na segunda atualização de índices, antes de `Upgrade installed packages` e `Install selected packages`. O lock usava `install/deb/deb_signing.key` (chave de assinatura de pacotes), que não verifica os metadados APT do Hestia. A referência correta é `https://apt.hestiacp.com/pubkey.gpg`, como no instalador oficial. A assinatura do `resolute/InRelease` foi validada na [inspeção isolada 40177808155](https://github.com/sabas2025/hestia-cp/actions/runs/40177808155), sem conectar à VPS.

A correção fixa SHA-256 `0020f1fb33bc0c53062a967b5c87fb51fd42550ab7ada15824cc1e4882b40dea` e fingerprint primário `159F0BD6EC2656F183BFD07BA189E93654F0B0E5`. O arquivo `install/assets.lock.tsv` foi corrigido. Para a origem antiga fixada pelo bootstrap, somente essa linha é substituída na cópia de trabalho depois da verificação integral da origem; contratos diferentes ou duplicados são recusados. A origem preservada continua imutável. O CI agora verifica o hash da chave oficial e a assinatura real do repositório Ubuntu 26.04.

Após baixar e verificar a revisão corrigida do helper, execute **somente no console root interativo**:

```bash
/usr/local/sbin/hestia-github-implantacao recover-apt-key
/usr/local/sbin/hestia-github-implantacao plan
```

`recover-apt-key` é restrito à tentativa inicial com estado `failed/installing`, à identidade da configuração atual e à sequência exata de eventos do log: primeira atualização aprovada, dependências iniciais aprovadas e segunda atualização encerrada em 100 com `NO_PUBKEY A189E93654F0B0E5`. O comando adquire os locks de implantação e instalação nativa, verifica que o serviço anterior está inativo/descarregado, executa o preflight de sistema limpo e recusa painel existente, credencial pendente, evidência ausente ou chave instalada desconhecida. Tentativas que chegaram à atualização de pacotes ou a etapas posteriores exigem outra análise.

A recuperação verifica hash e fingerprint da chave oficial, substitui atomicamente somente `/usr/share/keyrings/hestia-keyring.gpg` e exige que `apt-get update` termine sem erro. Não usa `trusted=yes`, `--allow-unauthenticated`, mudança de política criptográfica nem importação por ID curto. Preserva o modo público do diretório de keyrings.

Depois solicita novamente a senha, duas vezes, com entrada oculta. A senha anterior foi removida pelo worker quando a tentativa falhou; escolha a senha local do administrador configurado, sem colocá-la no GitHub ou no chat. O comando mantém hostname, e-mail, usuário do painel e autorizações SSH.

Com o novo plano aprovado, arquiva a tentativa anterior em `/var/lib/hestia-github-deploy/history/apt-key-*`: ticket, workspace, log, backup de configuração, cópia do log nativo, keyring anterior, resultado do APT e registro `recovery.json`, todos protegidos pelo diretório root privado. O log nativo original permanece no lugar. Não remove bancos, usuários, grupos ou pacotes. Em erro normal, restaura os arquivos movidos e a chave anterior e remove a nova senha. Se houver desligamento/encerramento forçado durante o arquivamento, preserve as duas pastas e faça revisão manual; não há retomada automática.

O retorno `state: recovered` significa **recuperação preparada, sem executar o instalador**. Consulte `plan`; somente com `state: ready`, execute `start` no console ou `install` no workflow. Não execute novamente `setup` nem remova `job.json` manualmente. Uma segunda execução de recuperação após sucesso é recusada. O aviso antigo de `TERM` era secundário; o helper também define `TERM=dumb`.


## Bloqueio em fresh-installation-plan após a senha

O registro observado na VPS confirmou `failed/fresh-installation-plan`: a validação da chave, o APT e a validação local da senha foram concluídos; a verificação seguinte bloqueou ou falhou. Esse registro antigo não guardava os motivos. A revisão atual passa a preservar e exibir as categorias de bloqueio retornadas pelo plano, sem imprimir senha ou erros brutos de comandos.

Foi reproduzida uma causa no código: o instalador Ubuntu verificado pode acrescentar `127.0.0.1 HOSTNAME` em `/etc/hosts` antes de configurar os repositórios. O plano usa a resolução do sistema, que considera esse arquivo. Ao repetir o plano depois da falha inicial, o hostname passa a resolver localmente para loopback e deixa de atender ao IP público exigido, mesmo com o DNS externo correto. Isso é uma causa reproduzida nos testes; sua presença na VPS será confirmada pela comparação dos arquivos, não apenas pelo nome da fase.

`recover-apt-key` agora compara `/etc/hosts` com o membro regular único `etc/hosts` no backup privado `configuration-before.tar.gz`. Se ambos forem iguais, não altera o arquivo. Se a única diferença for exatamente a linha de loopback adicionada pelo instalador ao hostname configurado, salva o arquivo atual em `hosts-before-recovery` e restaura os bytes anteriores atomicamente, preservando modo e grupo. Qualquer outra diferença bloqueia a recuperação para revisão. Backups com links, membros duplicados ou tamanho excessivo são recusados sem extração de caminhos no sistema.

A recuperação mantém a verificação original de DNS, IPv6, contas, serviços e sistema limpo. Não ignora a validação nem altera o DNS público. Se uma etapa posterior falhar normalmente, também devolve `/etc/hosts` ao estado encontrado antes da recuperação. O resultado aprovado informa `hosts_restored_from_verified_backup`; em bloqueio do plano, o resultado e `recovery.json` incluem `reasons`. Uma senha aceita não precisa ser mudada por causa desse bloqueio, mas será solicitada novamente porque o arquivo temporário é removido ao falhar.
