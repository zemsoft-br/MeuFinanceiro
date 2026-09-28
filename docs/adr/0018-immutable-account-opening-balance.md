# ADR-0018 — Saldo de abertura imutável por conta

- Status: Accepted
- Data: 2026-08-11
- Decisores: mantenedores

## Contexto

`finance.accounts` foi criada sem coluna de saldo porque saldo atual é estado derivado, não atributo mutável da conta. Antes do Movement completo, ainda é necessário representar o ponto inicial explícito a partir do qual os futuros movimentos serão acumulados.

Uma coluna `balance` ou `initial_balance` na conta criaria autoridade concorrente com o livro e permitiria correções destrutivas sem trilha. Também deixaria ambígua a diferença entre ausência de informação e saldo zero.

## Decisão

### Anchor único e opcional

Cada conta pode possuir **zero ou um** saldo de abertura.

Ausência do anchor significa que nenhum saldo inicial foi informado. Isso é diferente de um anchor explícito com `Money(0, currency)`.

O anchor é um recurso append-once. Runtime não recebe `UPDATE` ou `DELETE`.

### Valor

O valor é `Money` do ADR-0015:

```text
amount: Decimal finito
currency: código ASCII uppercase de três letras
```

A persistência usa `NUMERIC(24,8)` e moeda separada.

A moeda deve ser exatamente a moeda da conta. O vínculo é protegido também por FK composta no PostgreSQL.

Valores positivos, zero e negativos são válidos. O sinal representa o saldo econômico no início do período e não receita/despesa.

### Data efetiva

`effective_date` é uma `date` e representa o saldo existente **no início do dia financeiro dessa data**, antes de qualquer Movement que futuramente tenha efeito nessa mesma data.

Essa definição permite que o futuro saldo derivado use o anchor como estado inicial e some eventos a partir de `effective_date`, sem precisar atribuir horário artificial ao saldo de abertura.

A ordenação e semântica completa de Movement continuam decisão própria.

### Criação

Neste primeiro recorte somente o `owner_operator_id` da conta pode criar o anchor.

A conta deve estar `ACTIVE`, o ator deve possuir membership ativa na mesma residência e o contexto de residência/operador é derivado server-side.

Outro membro pode ler o anchor quando já possui audiência sobre a conta, mas não pode criá-lo.

### Imutabilidade e correções

O saldo de abertura não é editado nem substituído silenciosamente.

Uma correção futura deve ser representada por evento explícito do livro — ajuste, reversão ou mecanismo equivalente definido pelo contrato de Movement — preservando o anchor original.

Não haverá múltiplas versões mutáveis do saldo de abertura nesta etapa.

### Relação com saldo atual

O saldo de abertura não é saldo atual, cache nem observação bancária.

Conceitualmente:

```text
saldo derivado = saldo de abertura + efeitos canônicos do livro
```

A fórmula operacional só será implementada após o contrato de Movement.

Saldos observados por Pluggy/importadores continuam observações externas e não alteram este anchor automaticamente.

### Audiência

O anchor não possui ACL independente. Sua audiência é exatamente a audiência da conta.

A RLS de `finance.account_opening_balances` valida a existência da conta visível sob o mesmo `app.current_residence_id` e `app.current_operator_id`.

Isso evita duplicar grants/audiência e acompanha futuras mudanças autorizadas da conta.

## Alternativas consideradas

### Coluna `initial_balance` em `finance.accounts`

Rejeitada. Mistura identidade/configuração da conta com estado financeiro e incentiva mutação destrutiva.

### Coluna `balance` atualizável

Rejeitada como fonte de verdade. Saldo atual deve ser derivado ou cache recalculável, nunca autoridade concorrente com eventos.

### Criar um Movement antes do contrato de Movement

Rejeitada. Forçaria semântica de sinal, reversão, competência, auditoria e idempotência antes das respectivas decisões.

### Múltiplas versões do opening balance

Adiada. Correção por versionamento específico criaria um mini-ledger paralelo. O livro canônico futuro será a fronteira correta para ajustes.

## Consequências positivas

- nenhum saldo mutável em `finance.accounts`;
- ausência permanece distinta de zero;
- anchor é auditável e não destrutivo;
- moeda não diverge da conta;
- audiência é herdada da conta;
- correções futuras convergem para o livro financeiro em vez de criar segundo ledger.

## Consequências negativas e riscos

- enquanto Movement/ajuste não existir, um anchor informado incorretamente não pode ser corrigido pela interface;
- cálculo de saldo atual continua indisponível nesta etapa;
- `effective_date` exige UX futura clara sobre “início do dia”.

Esses custos são preferíveis a introduzir mutabilidade financeira prematura.

## Validação

A implementação deve provar:

- zero ou um anchor por conta;
- zero explícito diferente de ausência;
- moeda igual à conta;
- owner-only create;
- leitura herdando audiência da conta;
- conta arquivada recusando novo anchor;
- runtime sem update/delete;
- segunda criação fail-closed;
- valores financeiros redigidos em `repr`/erros.

## Referências

- #124
- #137
- ADR-0015
- ADR-0016
- ADR-0017
- `docs/architecture/FINANCIAL_ACCOUNTS.md`
- `docs/architecture/FINANCIAL_INVARIANTS.md`
