# ADR-0029 — Metas financeiras com destinação virtual de saldo existente

- Status: Accepted
- Data: 2026-10-07
- Decisores: mantenedores

## Contexto

A Fase 2 (#180) pede que uma pessoa ou família defina uma meta (reserva, viagem), acompanhe quanto já foi **destinado** a ela e quanto falta. O ledger (`finance.movements`, ADR-0019/0020) é a única autoridade monetária e o saldo de conta é sempre derivado (ADR-0018 + Movements, estornos e pernas de transferência). Orçamentos (ADR-0026) e recorrências (ADR-0027) já provaram o padrão: planejamento persistido, fato derivado, CAS, idempotência, RLS `FORCE`. `FINANCIAL_INVARIANTS` §11.1 exige que destinação virtual classifique parte de saldo existente, não crie caixa e não aloque a mesma unidade monetária integralmente a duas metas.

A decisão precisa responder: o que persiste, como a destinação evita consumir duas vezes a mesma disponibilidade sob concorrência sem reimplementar saldo, o que acontece quando despesas posteriores derrubam o saldo, e quem lê e quem escreve.

## Decisão

### A meta é planejamento; a destinação é um evento virtual

`finance.goals` guarda a identidade e os dados de planejamento (título, descrição opcional, moeda, alvo > 0 em `NUMERIC(24,8)`, prazo opcional, audiência, dono, `version` para CAS, chave de idempotência e digest). `finance.goal_allocation_events` é um histórico **append-only** de `ALLOCATE` (valor positivo) e `RELEASE` (valor negativo) por meta e conta, com ator, chave de idempotência, digest e instante. O destinado é sempre a soma dos eventos; nunca existe coluna `allocated`, `remaining` ou saldo virtual.

Uma destinação **não é** Movement, transferência, receita, despesa, linha de orçamento, saldo bancário nem dinheiro bloqueado. Não cria linha em `finance.movements`, `finance.budgets` nem em ocorrências de recorrência, e `finance.movements` não ganha `goal_id`. Mover dinheiro de verdade continua sendo uma transferência (ADR-0021), outra operação.

### Contrato v1

- audiência `PERSONAL` ou `HOUSEHOLD` (`SHARED` não existe em metas); moeda e alvo explícitos, sem conversão cambial;
- título de 1 a 96 caracteres, descrição opcional de até 280, sem caracteres de controle; prazo opcional;
- prazo: ao criar, ou ao alterá-lo, a data deve estar entre `hoje(UTC) - 1 dia` (tolerância de fuso) e 100 anos à frente; manter o prazo já gravado numa edição não revalida (uma meta antiga continua editável depois do prazo);
- identidade imutável: escopo, dono e moeda (decidem quais contas podem lastrear a meta);
- edição é substituição completa de título, descrição, alvo e prazo com `expectedVersion` obrigatório (CAS); **nenhuma edição apaga ou reescreve eventos**;
- reduzir o alvo abaixo do já destinado é permitido e **explícito**: o resumo passa a `EXCEEDED` com o excedente, sem ajuste automático.

### Contas elegíveis

| Meta | Conta que pode lastreá-la |
|---|---|
| `PERSONAL` | conta `PERSONAL` do **mesmo dono**, mesma moeda |
| `HOUSEHOLD` | conta `HOUSEHOLD` do **mesmo dono**, mesma moeda; os demais membros ativos leem |

`SHARED` nunca é elegível. Uma meta usa de 1 a N contas (até 25) da mesma moeda; uma conta sustenta N metas. Nova destinação exige conta `ACTIVE`; a **liberação** de um vínculo histórico continua possível depois do arquivamento. Como uma meta `HOUSEHOLD` só usa contas `HOUSEHOLD`, o resumo nunca divulga saldo de conta pessoal a outro membro. Só o dono escreve (edita, destina, libera); ler uma meta da casa nunca implica escrever (`canEdit` é decidido no servidor **e** no banco).

### Disponibilidade: o saldo canônico, sob lock por conta

A disponibilidade de uma conta é `saldo canônico − Σ destinado (todas as metas, líquido de liberações)`. O saldo **não é recalculado por uma agregação própria**: o store lê, na mesma transação, a conta, o saldo de abertura e os Movements pelos mesmos leitores do ledger e chama `derive_financial_account_balance_and_statement` (a função que já define abertura + Movements + estornos + pernas de transferência `NEUTRAL` como movimento de caixa). A extração foi mínima: os três leitores transacionais (`get_account`, `get_opening_balance`, `list_movements`) ganharam uma variante que aceita a `Connection`, e os métodos antigos delegam a ela (uma só implementação da consulta). A composição transacional vive em `financial_balance_transaction.py`, para que `financial_balance_query.py` continue neutro de SQLAlchemy; um teste prova que o saldo transacional é igual ao do serviço canônico num ledger com despesa, receita, estorno e transferência.

Atomicidade: toda destinação (e liberação) adquire `pg_advisory_xact_lock(hashtextextended('meufinanceiro:goal-account:' || account_id, 0))` **antes** de ler saldo e total destinado. O lock é por conta e de transação: duas destinações concorrentes à mesma conta (metas diferentes ou a mesma) se serializam, e a segunda, em `READ COMMITTED`, já enxerga o evento da primeira. A mesma chave é adquirida (reentrante) pelo gatilho `BEFORE INSERT` dos eventos, de modo que nem um caminho de aplicação que esqueça o lock consegue violar o saldo virtual por meta/conta. O lock não impede Movements: eles não adquirem esse lock e **nunca são bloqueados** por metas.

O banco garante a estrutura (gatilho): audiência/dono/moeda/status da conta, sinal do evento, `saldo virtual (meta, conta) ≥ 0`, no máximo 500 eventos e 25 contas por meta (a partir de 475 eventos só `RELEASE` é aceito: 25 ficam reservados para devolver uma vez cada conta). A regra de disponibilidade contra o saldo canônico é do store, sob o lock, e não é duplicada em SQL (isso seria uma segunda implementação de saldo, exatamente o que a decisão evita). Se a atomicidade acima não fosse segura, a tarefa seria bloqueada e documentada; ela é segura porque lock e leitura do saldo vivem na mesma transação.

### Saldo que cai depois: reportar, nunca reparar

Despesas posteriores reduzem o saldo canônico e **não alteram nenhum evento**. O resumo compara, por conta, `saldo canônico` com `Σ destinado em todas as metas` e devolve `backingStatus` `COVERED` ou `INSUFFICIENT` e o `shortfall`. Na v1 a insuficiência é da **conta** (não há atribuição de culpa entre metas e nenhum reequilíbrio). Enquanto a conta estiver insuficiente, nenhuma nova destinação é aceita nela (a disponibilidade é negativa), mas liberar continua permitido. A UI diz que não há garantia bancária.

### Escrita: replay-safe, CAS e idempotência

- criar meta usa `idempotencyKey` UUID v4 e digest SHA-256 do material canônico (operador + título, descrição, escopo, moeda, alvo, prazo): mesma chave e mesmo material é replay; mesma chave com outro material ou outro operador é `409`;
- cada evento usa a própria `idempotencyKey` (UUID v4) e digest de operador + meta + tipo + conta + valor; replay devolve o evento original sem novo lançamento; material diferente é `409`;
- editar é `UPDATE ... WHERE version = :expected`: versão antiga é `409` sem gravar;
- o Flutter nunca reenvia automaticamente nem refaz o CAS após `409`: relê o estado canônico e exige nova ação explícita.

### Append-only no banco

O runtime recebe `SELECT, INSERT` em `goal_allocation_events` e **nenhum** `UPDATE`/`DELETE`; um gatilho `BEFORE UPDATE` rejeita a reescrita também do dono das tabelas (como nas demais tabelas append-only do projeto, `DELETE` não é concedido ao runtime; a limpeza administrativa de demonstração e de testes é do dono). Em `goals` o runtime atualiza apenas `title, description, target_amount, target_date, version, updated_at, updated_by_operator_id`; um gatilho exige versão + 1 e identidade imutável. Não há `DELETE` de meta.

### RLS

`ENABLE + FORCE` nas duas tabelas, runtime non-superuser, sem bypass administrativo. Meta: `PERSONAL` só o dono; `HOUSEHOLD` qualquer membro ativo; `INSERT`/`UPDATE` somente o dono com membership ativa. Evento: visível se a meta é visível; `INSERT` somente quando a meta pertence ao operador (e ele é o `actor`) e a conta é visível. Conhecer um id nunca prova autorização: meta, conta ou fingerprint inexistente, invisível ou incompatível são o mesmo erro sanitizado.

### Leitura consistente e custo

O resumo roda numa transação `REPEATABLE READ` somente leitura com número fixo de statements (contexto, membership, meta, eventos da meta, total destinado por conta numa agregação `GROUP BY`) mais o saldo canônico **de cada conta da meta** (≤ 25, três leituras por conta). A lista devolve as metas com o destinado agregado por meta (uma agregação, sem N+1). Limites explícitos e falha sem truncar: 200 metas por dono e residência, 25 contas e 500 eventos por meta; ao exceder, a escrita é recusada (`409`) e a leitura de um estado que viole o limite falha (`503` sanitizado) em vez de cortar.

### Fora do audit financeiro fechado

Como orçamentos e recorrências, metas não são mutação do ledger nem da classificação: `finance.audit_events` não é ampliado. A autoria fica em `owner_operator_id`, `updated_by_operator_id`, `actor_operator_id` e nos timestamps; o histórico completo é o próprio log append-only.

## Alternativas consideradas

- **Meta como Movement/transferência para uma conta "reserva":** criaria um segundo ledger e mudaria o saldo bancário. Rejeitada.
- **Persistir `allocated`/`remaining` ou saldo virtual:** divergiria dos eventos. Rejeitada.
- **Bloquear Movements que reduziriam o saldo abaixo do destinado:** transformaria destinação virtual em dinheiro bloqueado e quebraria o ledger. Rejeitada.
- **Reequilibrar eventos quando o saldo cai:** reescrever ou apagar história. Rejeitada; reporta-se.
- **Agregar o saldo em SQL próprio dentro do store:** segunda implementação de saldo. Rejeitada; reutiliza-se a função canônica.
- **Lock de linha da conta (`SELECT ... FOR UPDATE`):** exigiria `UPDATE` do runtime em `finance.accounts`. O advisory lock transacional não amplia privilégios.
- **`SERIALIZABLE`:** retentativas automáticas são proibidas por contrato; o lock por conta dá a mesma garantia sem elas.
- **Atribuir a insuficiência a metas específicas:** exigiria política de prioridade. Fica para decisão própria.
- **Projetos, aporte agendado, câmbio, `SHARED`, notificações:** fora da v1.

## Consequências

- o destinado de uma meta pode ficar acima do saldo atual da conta e a UI mostra o alerta como o servidor entrega;
- toda destinação paga a leitura canônica do saldo da conta, proporcional aos Movements **dela** e não ao ledger: ~0,85 s numa conta com 20 mil Movements, ~0,03 s numa conta tranquila (inalterado por 60 mil Movements de outras contas) e ~1,9 s para o resumo de 25 contas / 50 mil Movements (PG 18.4, runtime não-superuser, RLS forçada); contas com ledger muito maior que isso seriam o gatilho para uma decisão própria de saldo materializado, sem tocar esta regra;
- metas não são arquivadas nem apagadas na v1 (o teto de 200 por dono é o limite explícito até existir um ciclo de vida).

## Validação

Domínio (contrato, elegibilidade, disponibilidade, progresso, resumo), schema/RLS/FORCE com role non-superuser entre residências e audiências, append-only (UPDATE/DELETE negados), CAS e idempotência (incluindo concorrência), concorrência de duas metas sobre saldo finito, liberação sem negativo, saldo que cai depois, estornos e transferência `NEUTRAL`, moeda, limites, ausência de Movement novo, plano/contagem de statements, API HTTP, contratos de qualidade e Flutter.

## Referências

- #180, #260
- ADR-0015, ADR-0016, ADR-0017, ADR-0018, ADR-0019, ADR-0020, ADR-0021, ADR-0026, ADR-0027
- `docs/architecture/FINANCIAL_INVARIANTS.md` §11.1
- `docs/architecture/FINANCIAL_GOALS.md`
