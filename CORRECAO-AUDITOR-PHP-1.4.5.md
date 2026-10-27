# Professional 1.4.5 — classificação correta do binário PHP

## Evidência

Em 27/10/2026, o usuário enviou `namei` e `stat` de `/usr/local/hestia/php/bin/php`: arquivo e ancestrais pertencem a root:root, modo 0755, arquivo regular com um link e **72.818.096 bytes**. A auditoria 1.4.4 recusava arquivos acima de 64 MiB (67.108.864 bytes) e apresentava o rótulo genérico `unsafe-binary-not-executed`.

Nesse caso, a recusa foi pelo tamanho. Os metadados mostrados não justificam mudar permissões ou afirmar invasão. Eles também não comprovam procedência do pacote, ausência de vulnerabilidade ou versão do PHP em execução.

## Correção

A sondagem PHP agora valida metadados sem carregar o arquivo inteiro na memória do coletor. Mantém as restrições de arquivo regular, proprietário root, ancestrais controlados, links, permissões e manifesto verificado. O limite padrão de leitura de configurações permanece em 2 MiB; a opção interna de metadados não remove esse limite dos demais consumidores.

O tamanho do executável é classificado separadamente, com limite de 256 MiB para tentar a consulta de versão. Arquivos vazios, maiores que esse limite, sem permissão de execução ou com metadados recusados não são executados. Falhas de comando e saída sem versão reconhecível não são apresentadas como versão corrigida.

Novos estados: `binary-metadata-review-required`, `binary-size-review-required`, `binary-not-executable`, `binary-command-failed`, `binary-version-unverified` e `version-collected`. O identificador `panel` é mantido inclusive em falhas. `binary_metadata_verified` não significa pacote autenticado: `package_integrity_verified`, `running_workers_verified` e `session_upload_progress_verified` continuam falsos nesta sondagem.

## Validação

Suíte local: **315 testes**, zero falhas/erros, 14 exclusões de ambiente. Seis regressões adicionais cobrem:

- Interpretador PHP real de QA, copiado para diretório temporário e preenchido até exatamente 72.818.096 bytes, com consulta real da versão.
- Metadados sem leitura do conteúdo e preservação dos limites normais de configuração.
- Arquivos vazios/maiores que o limite, recusados antes de executar.
- Links, hardlinks, permissões graváveis e FIFO, recusados sem execução.
- Arquivo não executável, comando com falha e saída não reconhecível.
- Identificador do painel correto e nenhuma sondagem PHP quando a camada não está verificada.

A aprovação da entrega exige CI completo sem exclusões, arquivo de atualização fixado conferido, sintaxe, Nginx/OpenSSH, navegador com serviços simulados, consultas de dependências e build/documentação. O teste com PHP de QA não é teste do pacote instalado na VPS.

## Continuar a coleta na VPS

Os metadados já enviados permitem continuar a consulta pontual da versão sem mudar proprietário, permissões ou configuração:

```bash
/usr/local/hestia/php/bin/php -n -r 'echo PHP_VERSION, PHP_EOL;'
```

Essa consulta não depende da instalação da 1.4.5. Ela informa a versão CLI do binário interno, sem validar configuração efetiva de FPM, workers, pacote assinado ou mitigação de upload progress. Depois é necessário conferir versão/candidato/procedência do pacote e os processos usados pelas aplicações.

A revisão 1.4.5 corrige o coletor, **não atualiza o pacote PHP**. Sua instalação, quando aplicada pelo helper fixado e aprovado com `--components ''`, não exige repetir a migração de cache já concluída na 1.4.4. Não executa operações de Nextcloud/WebDAV, não configura nuvem e não ativa A2F pelo titular. O status global conservador da auditoria pode continuar `review-required` enquanto houver aceite operacional pendente.
