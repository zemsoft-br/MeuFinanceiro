# ADR-0031 — Fluxo de caixa v1 como projeção somente leitura sobre o ledger e as recorrências

- Status: Proposed
- Data: 2026-10-10
- Decisores: mantenedores
- Issue: #265 (Epic #180)

## Contexto

A Fase 2 (#180) prevê o fluxo de caixa depois de orçamentos, recorrências, metas e projetos. O ledger (`finance.movements`, ADR-0019/0020) é a única autoridade monetária; o saldo é sempre derivado do opening balance imutável (ADR-0018) e da soma assinada dos Movements, inclusive estornos e pernas `NEUTRAL` de transferência (ADR-0021). As recorrências (ADR-0027) já separam regra (modelo), ocorrência persistida (instância) e Movement (único fato, criado só por **Registrar**). `FINANCIAL_INVARIANTS` §12 exige que projeção não altere dados reais, que cada evento projetado tenha origem e confiança e que transferência interna não altere o saldo consolidado.

A decisão precisa responder: de onde vêm os eventos previstos, se um GET pode gerar ocorrências, como evitar dupla contagem entre previsto e realizado, como tratar moedas, contas e audiência, e como sinalizar uma projeção não confiável sem esconder compromissos.

## Decisão

### Projeção é leitura derivada

O fluxo de caixa é calculado a cada leitura por uma função pura e determinística do domínio (`project_cash_flow`) sobre dados lidos em **uma única transação `REPEATABLE READ` somente leitura**. Não existe tabela, coluna, cache ou materialized view de saldo projetado; nenhuma migration é criada; nenhum Movement, ocorrência ou evento é escrito.

### Fontes

- **Realizado**: opening balance + Movements (todos os papéis e efeitos), com agregados `NUMERIC` exatos sob RLS para o saldo antes da janela e até a data de referência, e a lista dos Movements da janela na ordem do extrato (`effective_date, created_at, id`).
- **Previsto**, somente em datas `>=` data de referência:
  - ocorrência `PENDING` persistida (`EXPECTED_OCCURRENCE`, confiança de ocorrência gerada), no seu snapshot de valor;
  - `PENDING` vencida: entra na data de referência, marcada `overdue` com a data original;
  - **previsão virtual da regra** (`EXPECTED_RULE`): regra `ACTIVE`, de conta `ACTIVE`, para cada mês sem ocorrência viva cuja data agendada (calendário canônico `scheduled_occurrences`) caia entre a referência e o fim da janela, com o estado corrente da regra e sua versão.
- Orçamentos, metas, projetos, cartões, parcelas, empréstimos e observações bancárias **não são fontes** e são declarados em `excludedSources`.

### Persistidas e virtuais — e por que um GET nunca gera

Exigir que o usuário gere cada mês antes de ver o caixa omitiria compromissos conhecidos; gerar dentro do GET violaria a geração explícita do ADR-0027 e transformaria leitura em escrita. A previsão virtual resolve os dois lados: deriva da regra confirmada, é rotulada com origem, regra, versão e mês, e desaparece assim que a ocorrência do mês existe (a ocorrência passa a decidir). Ela nunca cobre datas passadas: um mês passado sem ocorrência pode ter sido pago por um Movement avulso, então é **reportado** (`UNGENERATED_PAST_OCCURRENCES`), não inventado.

### Sem dupla contagem

- `REALIZED`: só o Movement canônico entra; o evento realizado carrega ocorrência, regra e valor esperado para comparar previsto × real. O mês fica coberto e não recebe previsão.
- `SKIPPED`: cobre o mês sem expectativa. `SUPERSEDED`: é histórico; vale a regra corrente.
- Estorno: o `REVERSAL` entra na sua data com o valor oposto; a ocorrência continua `REALIZED` e nada é reaberto.
- `NEUTRAL`: altera o saldo por conta e soma em `neutralIn`/`neutralOut`, nunca em receita ou despesa; transferência entre contas selecionadas se anula no consolidado.
- Regra `PAUSED` não projeta mês novo; sua `PENDING` já gerada continua prevista (pausar impede gerar, não encerra a previsão).

### Datas, janela e limites

Data de referência = data do servidor (relógio injetado; `date.today` na composição, como nas recorrências), devolvida na resposta. Janela inclusiva de até 92 dias, `from <= referência`; padrão 30 dias a partir da referência; janela totalmente passada é histórica (`NOT_APPLICABLE`). Até 50 contas e 2000 eventos por leitura: excedeu, a leitura **falha** com erro explícito, nunca trunca.

A janela também pode ser **relativa**: `days` (1–92), exclusivo com `through`, conta o comprimento a partir de `from` ou, sem `from`, da data de referência do servidor. Assim o cliente escolhe "próximos N dias" sem conhecer nem inventar a data do servidor — inclusive quando a primeira leitura foi recusada (`422`) e ainda não há `referenceDate` no cliente. Janelas de calendário (mês atual, personalizado) continuam exigindo a data devolvida por uma leitura bem-sucedida.

### Moedas, contas e audiência

Cada moeda é um grupo independente; nada é somado entre moedas e não há câmbio. Contas padrão: `ACTIVE` visíveis; contas explícitas precisam ser visíveis (qualquer status), senão `404` indistinguível. A residência e o operador vêm da sessão; membership ativa é exigida; a RLS forçada das contas, Movements, regras e ocorrências decide a audiência antes de qualquer agregação.

### Estados incompletos

`projectionStatus` = `COMPLETE` | `INCOMPLETE` | `NOT_APPLICABLE`, com `issues` (`code`, `severity`, contagem, contas): `OPENING_BALANCE_MISSING`, `OPENING_BALANCE_AFTER_WINDOW_START` e `RULE_ACCOUNT_INACTIVE` tornam a projeção `INCOMPLETE`; `OVERDUE_OCCURRENCES`, `UNGENERATED_PAST_OCCURRENCES`, `PAUSED_RULES` e `HISTORICAL_WINDOW` são `ATTENTION`. Saldo sem opening balance é calculado a partir de zero e dito explicitamente.

### Âncora e risco: prospectivo × histórico

O opening balance ancora o saldo **a partir da sua data efetiva** (ADR-0018). Cada dia da série traz `anchored`: verdadeiro só quando **todas** as contas do grupo têm opening balance efetivo até aquele dia. Antes da âncora (ou sem opening balance) os números da série continuam visíveis, mas são estimativas — o valor de abertura aplicado antes da data ou um saldo que parte de zero — e **nunca** entram na avaliação de risco; por isso `OPENING_BALANCE_AFTER_WINDOW_START` é `INCOMPLETE`. Nenhum Movement sintético é criado e nenhum writer muda.

O risco é dividido em dois fatos distintos, no consolidado e por conta:

- `risk` (prospectivo): somente os dias **ancorados** a partir da data de referência. Um déficit que já aconteceu e foi recuperado não é anunciado como risco futuro.
- `historicalRisk`: somente os dias **ancorados** anteriores à referência — déficit realizado, apresentado como fato, nunca como previsão.

Cada risco traz `evaluatedDays` (dias ancorados avaliados) e é `null` quando não há dia avaliável daquele lado — `null` significa **não avaliável**, nunca "sem risco". Por conta, a âncora é o próprio opening balance da conta.

Contrato do cliente: o parser estrito do Flutter valida `projected` contra a data de referência, `anchored` contra as datas de abertura das contas e cada risco contra os dias que ele afirma avaliar (contagem, datas dentro do conjunto avaliado e, no consolidado, primeiro dia negativo e número de dias negativos conferidos com as flags diárias). Uma resposta que apresente déficit passado como risco futuro ou use dia pré-âncora como evidência é rejeitada como inválida.

### Consistência interna

O domínio verifica que `saldo inicial + realizados até a referência == saldo real na referência` lido do ledger; divergência significa snapshot inconsistente e falha fechado. Entradas fora da janela, de conta não selecionada, de outra moeda, duplicadas ou com vínculo de realização inválido também falham fechado.

## Alternativas consideradas

- **Só ocorrências persistidas**: mais simples, mas um caixa de 90 dias ficaria vazio até o usuário gerar três meses de cada regra; exigiria aviso permanente de cobertura. Rejeitada como padrão; a previsão virtual mantém a origem distinguível.
- **Gerar ocorrências no GET**: rejeitada (leitura com efeito colateral, contraria ADR-0027).
- **Persistir saldo projetado/snapshot diário**: rejeitada (segunda contabilidade, invalidação complexa).
- **Somar moedas com câmbio**: fora do escopo; exige contrato de FX rastreável.
- **Paginação por cursor dos eventos**: o saldo corrido depende de todos os eventos anteriores; preferimos janela curta e recusa explícita acima do teto.
- **Risco único sobre toda a janela**: rejeitado na revisão R2 — numa janela que cruza a referência transformava déficit passado em "risco a partir de" uma data passada.
- **Recalcular a série pré-âncora a partir de zero / Movement sintético de abertura**: rejeitado — criaria um saldo diferente do canônico ou uma escrita; a marcação `anchored` + `INCOMPLETE` mantém o ledger como única autoridade.
- **Presets relativos calculados no cliente a partir de `referenceDate`**: rejeitado — sem uma leitura bem-sucedida não há data, e inventar uma (relógio local) poderia divergir do servidor.

## Consequências positivas

- Nenhuma escrita, migration ou autoridade nova; o ledger continua único.
- Cada evento é explicável (origem, conta, regra/ocorrência/Movement, versão, data original).
- Déficit futuro e primeira data negativa identificáveis por conta e no consolidado, separados do déficit já ocorrido.
- Nenhum trecho sem âncora é tratado como confiável; "não avaliável" é explícito no contrato.

## Consequências negativas e riscos

- A previsão virtual usa o valor corrente da regra; reajustes futuros não existem na v1.
- Data de referência do servidor, sem fuso por residência.
- Janela máxima de 92 dias e teto de eventos podem exigir filtrar contas em residências grandes.
- Cartões, parcelas e empréstimos ainda não aparecem (declarado na resposta e na tela).
- Contrato da resposta mudou na R2 (`risk` anulável, `historicalRisk`, `evaluatedDays`, `anchored`): cliente e servidor são publicados juntos no mesmo artefato; um cliente estrito anterior rejeitaria a resposta nova como inválida (falha fechada, sem dado errado).

## Validação

Testes puros (janela, fronteiras, bissexto, dia 31, estorno, transferência, `PENDING`/vencida/`REALIZED`/`SKIPPED`/`SUPERSEDED`, regra pausada, conta arquivada, multimoeda, determinismo, limites e falha fechada), store em PostgreSQL com RLS forçada e role sem `BYPASSRLS` (audiência, snapshot, número fixo de statements), HTTP real e cliente Flutter. Ver `docs/architecture/FINANCIAL_CASH_FLOW.md`.

## Referências

- `docs/architecture/FINANCIAL_INVARIANTS.md` §2, §3, §5, §6, §10, §12, §18
- ADR-0015, ADR-0016, ADR-0018, ADR-0019, ADR-0020, ADR-0021, ADR-0026, ADR-0027, ADR-0029, ADR-0030
- `docs/architecture/FINANCIAL_BALANCE_STATEMENT.md`, `docs/architecture/FINANCIAL_RECURRENCES.md`
