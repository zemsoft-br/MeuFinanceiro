# Categorias financeiras canônicas

Status: **fundação da taxonomia financeira / issue #135**.

## Objetivo

`finance.categories` fornece a primeira árvore classificatória do domínio financeiro sem antecipar Movement, saldo, regras automáticas ou taxonomia de provider.

A categoria é um recurso financeiro local com UUID v4, residência, owner e audiência.

## Estrutura

```text
id
installation_id
residence_id
owner_operator_id
visibility_scope
parent_id nullable
name
status
created_at
updated_at
disabled_at nullable
```

Estados estruturais:

```text
ACTIVE
DISABLED
```

O runtime inicial cria somente `ACTIVE`.

## Árvore

`parent_id` permite profundidade livre.

A FK composta do parent inclui:

```text
parent_id
installation_id
residence_id
owner_operator_id
visibility_scope
```

Portanto um child não pode cruzar instalação, residência, owner ou audiência do parent.

Self-parent é proibido. O runtime não possui `UPDATE`; por isso não pode mover nós nem formar ciclos multi-nó após a criação. Ao criar um filho, o store exige que o parent exista, esteja `ACTIVE` e pertença ao mesmo owner/scope.

## Audiência

Este recorte suporta somente:

```text
PERSONAL
HOUSEHOLD
```

`PERSONAL` é visível apenas ao owner ativo da residência. `HOUSEHOLD` é visível a qualquer membership ativa na mesma residência.

`SHARED` é rejeitado no domínio e no PostgreSQL. Uma árvore compartilhada exige definir herança de grants antes de ser segura: grants independentes por nó poderiam tornar filhos visíveis sem seus ancestrais ou expor nomes de paths parcialmente privados.

## RLS

`finance.categories` usa:

```text
ENABLE ROW LEVEL SECURITY
FORCE ROW LEVEL SECURITY
```

Contexto:

```text
app.current_residence_id
app.current_operator_id
```

SELECT exige mesma residência, membership ativa e owner ou `HOUSEHOLD`.

INSERT exige mesma residência, owner igual ao ator atual, membership ativa, scope suportado, `ACTIVE` e `disabled_at IS NULL`.

O runtime recebe apenas:

```text
SELECT, INSERT
```

Não existem permissões de update/delete neste recorte.

## Store

`FinancialCategoryStore` expõe somente:

```text
create_category
list_categories
get_category
```

Owner e residência não vêm do draft; são parâmetros confiáveis da camada autenticada. `get_category` reduz inexistência/invisibilidade ao mesmo erro sanitizado para membro ativo.

## Neutralidade

A categoria não possui:

- amount ou saldo;
- `income/expense kind`;
- Movement ID;
- provider/external resource ID;
- FITID;
- regra automática;
- tag;
- confidence score.

Esses conceitos entram somente quando seus próprios contratos forem definidos.

## Migration

```text
0012_financial_categories
  <- 0011_financial_accounts
```

A migration é simétrica por downgrade e não altera `finance.accounts`.

## Fora do escopo

- `SHARED` e herança de grants;
- carga inicial/fixture de categorias;
- edição/movimentação/desativação/exclusão;
- tags;
- regras e aprendizado;
- rateios;
- Movement/ledger;
- saldo de abertura;
- API/Flutter;
- Pluggy/importadores;
- deploy/HML/produção.

## Validação

Testes sintéticos foram escritos para domínio, árvore em múltiplos níveis, RLS, parent scope, self-parent, rejeição de `SHARED`, lifecycle, permissões runtime e migration downgrade/reupgrade.

Nesta sessão, esses testes não são declarados como executados; a validação disponível é revisão estática via GitHub.
