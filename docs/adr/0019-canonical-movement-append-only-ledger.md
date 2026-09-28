# ADR-0019 — Movement canônico e ledger append-only

- Status: Accepted
- Data: 2026-08-11
- Decisores: mantenedores

## Contexto

O núcleo financeiro já possui conta canônica, categorias e um saldo de abertura imutável. Falta definir o evento que altera economicamente uma conta e que futuramente permitirá derivar saldo, caixa, competência, transferências e relatórios.

Persistir movimentações antes dessa decisão cristalizaria semântica de sinal, datas, reversão e classificação econômica no schema e nas APIs. O risco seria criar um ledger mutável, duplicar autoridade de saldo ou promover observações bancárias pendentes diretamente ao domínio.

## Decisão

### Um Movement é um efeito em uma conta

Um Movement representa um efeito monetário **efetivo** em exatamente uma conta financeira canônica.

Movement não representa:

- projeção ou recorrência futura;
- observação externa pendente;
- saldo atual;
- orçamento;
- fatura inteira;
- transferência inteira.

Esses conceitos podem produzir ou referenciar Movements, mas não substituem o ledger.

### Amount assinado

O Movement usa `Money` do ADR-0015.

O sinal do amount é a única direção canônica do efeito sobre a conta:

```text
amount > 0 -> aumenta o saldo da conta
amount < 0 -> reduz o saldo da conta
amount = 0 -> inválido
```

Não existe segundo campo `credit/debit`, evitando duas fontes que possam divergir.

Quando o ledger estiver persistido, o saldo poderá ser derivado conceitualmente por:

```text
opening balance + soma dos amounts canônicos efetivos
```

Nenhuma coluna mutável de saldo é criada por esta decisão.

### Resultado econômico separado do sinal

O Movement original possui `result_effect`:

```text
INCOME
EXPENSE
NEUTRAL
```

Semântica:

- `INCOME`: efeito de receita e amount positivo;
- `EXPENSE`: efeito de despesa e amount negativo;
- `NEUTRAL`: altera saldo, mas não compõe receita/despesa; aceita sinal positivo ou negativo, sempre não-zero.

A separação evita classificar transferências, principal de empréstimo, liquidações ou ajustes patrimoniais como receita/despesa apenas por aumentarem ou reduzirem uma conta.

### Datas financeiras explícitas

Todo Movement original informa:

```text
effective_date
competence_date
```

`effective_date` é a data em que o efeito participa do saldo/caixa.

`competence_date` é a data de reconhecimento econômico para relatórios por competência.

Ambas são `date`. Timestamps como `created_at` pertencem à auditoria técnica, não substituem datas financeiras.

O domínio não define default silencioso entre as duas datas. Um caso de uso pode escolher explicitamente a mesma data para ambas.

O opening balance do ADR-0018 continua significando saldo no início de `effective_date`, antes dos Movements efetivos nessa data.

### Descrição

Movement original possui descrição canônica obrigatória, normalizada e limitada.

Descrição e amount são dados financeiros sensíveis e não aparecem em `repr` ou diagnósticos genéricos.

### Audiência herdada da conta

Movement não possui grants, `visibility_scope` ou owner independentes.

Sua audiência é a audiência da conta financeira à qual pertence. A futura persistência deve consultar a conta sob o contexto RLS corrente, como já ocorre com o opening balance.

Conhecer `movement_id` nunca comprova autorização.

### Categoria fora do primeiro contrato

`category_id` não faz parte do primeiro Movement canônico.

Categorias atuais suportam `PERSONAL` e `HOUSEHOLD`, enquanto contas também suportam `SHARED`. Incorporar diretamente uma categoria poderia criar vazamento de classificação ou uma audiência incompatível com a conta.

O vínculo de classificação será implementado em uma fronteira própria depois que o ledger base estiver estável e puder definir comportamento de redaction/visibilidade.

### Append-only

Movement é imutável após persistência.

Não existe edição destrutiva de:

- account;
- amount;
- result effect;
- effective date;
- competence date;
- description.

Não existe status mutável `PENDING` no ledger. Dados pendentes continuam em suas próprias fronteiras e só entram no ledger quando forem promovidos explicitamente a evento efetivo.

### Reversão integral

Correção do Movement canônico é feita por novo evento de reversão.

O comando de reversão recebe somente:

```text
movement_id original
effective_date
competence_date
reason
```

O chamador não informa amount, account, currency ou result effect da reversão.

O futuro serviço de ledger deve ler o original e derivar:

- mesma conta;
- mesma moeda;
- mesmo `result_effect`;
- amount exatamente oposto.

A reversão integral cancela o efeito do original sem alterá-lo.

Regras futuras de persistência:

- target deve ser Movement original, não outra reversão;
- no máximo uma reversão integral por original;
- reversão também é append-only;
- reprocessamento usa idempotência independente;
- partial refund/partial correction não é representado como reversão parcial nesta primeira semântica.

### Transferências

Uma transferência futura não será um único Movement atravessando duas contas.

Ela criará atomicamente dois Movements `NEUTRAL`:

```text
origem  -> amount negativo
destino -> amount positivo
```

Os dois serão ligados por um `transfer_id` separado do `movement_id`.

A atomicidade e o contrato de transferência pertencem a issue própria.

### Idempotência

A criação persistente futura deve exigir uma idempotency key independente do resource ID, conforme ADR-0017.

A chave evita duplicação por retry sem transformar um ID operacional no ID do Movement.

Formato, escopo e retenção dessa chave serão definidos antes da persistence/API do ledger.

### Identidade

Cada Movement persistido usará UUID v4 RFC 4122 local e opaco conforme ADR-0017.

Permanecem identidades distintas:

```text
movement_id
idempotency key
reversal link
transfer_id
correlation id
provider/import identity
```

## Alternativas consideradas

### Amount sempre positivo + campo CREDIT/DEBIT

Rejeitada por duplicar direção em dois campos e complicar agregação. Amount assinado produz uma única fonte de verdade para o efeito na conta.

### PENDING/CONFIRMED dentro do Movement

Rejeitada. Projeções e observações externas têm lifecycle próprio. O ledger canônico representa efeitos efetivos.

### Editar Movement existente

Rejeitada por destruir auditabilidade e alterar retrospectivamente saldos e relatórios. Correções usam reversão + novo evento quando necessário.

### Embutir categoria no primeiro schema

Adiada por incompatibilidade de audiência entre conta `SHARED` e categorias atuais.

### Transferência como um row com duas contas

Rejeitada como Movement básico. Cada conta precisa de um efeito local simples; uma operação de transferência coordena dois efeitos atomicamente.

## Consequências positivas

- saldo derivável por soma simples;
- caixa e competência explícitos;
- receita/despesa separadas de movimentos neutros;
- correções auditáveis;
- observações externas não contaminam o ledger;
- transferências futuras não causam dupla contabilização de resultado;
- ACL permanece centrada na conta.

## Consequências negativas e riscos

- persistence de Movement precisa validar reversões consultando o original;
- vínculo com categoria exige uma etapa posterior;
- partial refunds/correções parciais ainda não possuem contrato próprio;
- dois campos de data aumentam a responsabilidade da UX futura;
- idempotência precisa ser resolvida antes da persistence pública.

## Validação

O pacote `meufinanceiro-finance` materializa esta decisão com contratos puros para Movement original e comando de reversão, cobrindo:

- amount não-zero;
- coerência de INCOME/EXPENSE/NEUTRAL;
- duas datas explícitas;
- descrição normalizada;
- UUID local da conta/original;
- reversal draft sem amount/account/currency/result effect;
- redaction de material financeiro.

## Referências

- #124
- #139
- ADR-0015
- ADR-0016
- ADR-0017
- ADR-0018
- `docs/architecture/FINANCIAL_INVARIANTS.md`
- `docs/architecture/FINANCIAL_OPENING_BALANCE.md`
