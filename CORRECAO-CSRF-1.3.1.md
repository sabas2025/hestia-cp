# Professional 1.3.1 — navegação interna e CSRF

As páginas de operações, plataforma, editor e A2F enviavam
`Referrer-Policy: no-referrer`. Ao seguir um link dessas páginas, o navegador
omitia o cabeçalho `Referer` exigido pelo Hestia em rotas internas protegidas.
A versão 1.3.1 usa `same-origin`, como a página inicial Professional: conserva
a referência na mesma origem e a omite ao navegar para outra origem.

A correção preserva o guard nativo, a política CSRF configurada, os tokens de
formulário e a autenticação. Não exige desativar CSRF nem reinstalar o painel.
Um link direto ou favorito para uma rota protegida ainda pode ser recusado;
entre pela raiz do painel e navegue pelos menus.

Os testes usam respostas PHP reais e navegação Chromium nas cinco páginas
Professional. Verificam que a rota com o guard nativo aceita a referência
interna, que formulários conservam a origem e que outras origens não recebem
essa referência. Requisições sem
referência ou com referência estrangeira continuam recusadas no nível 1.
A autenticação desses testes é uma fixture explícita, sem acesso a uma VPS.

Para atualizar uma instalação íntegra existente, use o atualizador publicado
com fonte e inventário fixados. Execute `plan --components ''` e depois
`apply --components ''`: essa atualização não repete a instalação das
dependências opcionais. Confirme `status` com estado `succeeded`, versão de
destino 1.3.1 e a saúde da camada antes de testar a navegação autenticada.

Essa correção não instala Nextcloud. Um `occ` ausente e `status.php` com 404
indicam que a aplicação não foi encontrada no caminho consultado. Depois de
recuperar a navegação, confirme o diretório e instale pela interface nativa,
sem apagar arquivos existentes para forçar uma reinstalação.
