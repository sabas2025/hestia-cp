# Professional 1.4.6 — aparência integrada ao HestiaCP

A Central, Operações e diagnóstico, Arquivos por domínio, Ferramentas do servidor
e Segurança A2F agora usam um layout compartilhado com o tema visual do HestiaCP.

## Alterações

- Cabeçalho com logotipo, conta atual, uso de disco e tráfego e links de conta.
- Navegação horizontal para os recursos permitidos da conta e para as cinco páginas Professional.
- Estilos nativos para botões, campos e seletores, com o tema selecionado no HestiaCP.
- Tema claro, escuro e tema personalizado Professional compatíveis com o mesmo layout.
- Layout responsivo, foco visível, atalho para o conteúdo e navegação por teclado.
- Um único arquivo de layout para manter as páginas consistentes.

O layout lê metadados da conta autenticada pelo helper nativo do painel. Links de
administração não são exibidos a clientes ou em contexto de personificação.
Endpoints, verificações de autorização, A2F, CSRF e confirmação de operações
continuam nos respectivos controladores. Nenhuma política CSP foi flexibilizada;
a página A2F continua sem JavaScript. O código não carrega o bootstrap Alpine do
painel nativo nas páginas Professional.

O tema personalizado Professional deixou de importar o CSS do dashboard para as
páginas nativas. Suas regras visuais agora se aplicam também à Central quando
esse tema é selecionado. Outros temas seguem usando seus próprios estilos.

## Verificação e limites

- Testes HTTP verificam acesso anônimo, papéis, contexto da conta, guarda de
  templates, CSP e privacidade da navegação; incluem o layout compartilhado.
- Testes de navegador verificam cinco páginas, três temas e três larguras
  (360, 768 e 1440 pixels), com CSP ativa, sem transbordamento horizontal.
- Os testes funcionais do editor e das operações usam respostas de serviços
  simuladas e verificam a limpeza de senha/código após cada envio.
- A CI conserva capturas com dados sintéticos e o relatório de verificação.

Esses testes não acessam a VPS. Capturas de teste não comprovam implantação,
backup em nuvem, entrega de e-mail, bloqueio WAF ou ativação real da A2F.

## Aplicação na VPS

Use o atualizador publicado e validado para esta versão, primeiro `plan` e depois
`apply`, ambos com `--components ''`. Isso atualiza a camada Professional sem
instalar pré-requisitos nem reaplicar perfis WAF/Docker/backup. O atualizador
verifica a instalação existente e guarda uma cópia dos arquivos substituídos.

Confirme `state: succeeded` e `results.overlay.to: 1.4.6` no status antes de
considerar a atualização instalada. Depois abra as cinco páginas com sua própria
conta, confira o tema ativo e valide os formulários. A instalação do HUB em
`hub01.ctba.top` e a configuração Nextcloud/WebDAV não fazem parte desta alteração.
