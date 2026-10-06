# ADR-0025 — Caixa de pendências derivada, paginada por keyset e sem estado persistido

- Status: Accepted
- Data: 2026-10-05
- Decisores: mantenedores

## Contexto

A #245 entregou classificação e rateio manual (ADR-0022) e a #247 entregou regras determinísticas com preview e apply explícitos (ADR-0024). Ambas já determinam, a partir do estado canônico, quando um Movement está sem classificação. A Fase 2 (#180) pede agora uma caixa para revisar esses Movements, juntando a sugestão das regras e as ações já existentes.

A decisão precisa responder: o que é uma "pendência", se ela vira uma segunda fonte de verdade, como a lista cresce sem custo proporcional ao extrato, como uma busca filtrada por estado de regra continua limitada, quem pode agir e como a tela evita afirmar sucesso que o servidor não confirmou.

## Decisão

### Pendência é um fato derivado, nunca estado persistido

Um Movement está pendente quando, no estado canônico atual:

```text
role = STANDARD
result_effect IN (INCOME, EXPENSE)
sem movement_allocation_set (portanto sem classificação corrente)
visível ao operador (RLS)
```

Não existe `pending`, `reviewed`, `inbox_status`, `category_id` ou equivalente em `finance.movements`, nem tabela ou fila de pendências. `finance.movements` continua o único ledger e `movement_allocation_sets` a única autoridade de classificação. `NEUTRAL` e `REVERSAL` nunca entram. Um `STANDARD` já estornado continua classificável (ADR-0022: a classificação de reversões deriva do original), portanto continua pendente até ser classificado. Dismiss, snooze e atribuição a membro exigiriam estado próprio e ficam para outro contrato.

Consequência: uma classificação manual, por regra ou concorrente remove o item na leitura seguinte, sem nenhuma sincronização, e não há como a caixa divergir do ledger.

### A sugestão é a avaliação da #247, sem outro matcher

Cada item recebe `MATCHED`, `AMBIGUOUS` ou `NO_MATCH` do mesmo pipeline de preview/apply: regras `ACTIVE` da conta, descarte das cujo alvo está ausente, `DISABLED` ou incompatível com a audiência da conta, maior prioridade única vence e empate é `AMBIGUOUS`. A caixa só chama `usable_categorization_rules` e `evaluate_movement_categorization`; nenhuma comparação de texto, prioridade ou elegibilidade existe na rota, no serviço ou no Flutter. `matchedRuleId` e `suggestedCategoryId` existem apenas em `MATCHED`; `AMBIGUOUS` nunca carrega regra. Um teste prova que, para a mesma conta, a caixa e o preview devolvem o mesmo estado, regra e categoria.

### Paginação keyset opaca, ordenada e limitada

A leitura é `GET /finance/pending-movements`, residence-scoped, com ordem `effective_date DESC, id DESC`, `limit` de 1 a 100 (padrão 50) e `cursor` opaco. O cursor carrega apenas a coordenada de ledger `(effective_date, id)` e uma impressão digital dos filtros ativos; é versionado, estrito, recusa qualquer malformação e não pode ser reutilizado sob outros filtros. Não é um token de autorização: visibilidade é sempre decidida pela RLS da leitura que ele alimenta. `offset`, `page` e busca textual são recusados. Uma coordenada exata não duplica nem perde itens quando Movements são criados ou classificados entre páginas.

Filtros v1: `accountId`, `resultEffect` (`INCOME`/`EXPENSE`) e `ruleStatus`. Os dois primeiros vão ao SQL; `ruleStatus` não pode ir, porque o matching mora só no domínio.

### Custo limitado por requisição

- Sem filtro de regra: uma leitura de regras, uma de categorias e uma página (três statements cada, contexto + membership + consulta). Nada é lido por Movement, conta, allocation, regra ou categoria.
- Com `ruleStatus`: as mesmas leituras fixas e, no máximo, 5 lotes de 100 candidatos. Se o orçamento acaba antes de preencher a página, a resposta traz o que casou (possivelmente nada) **e um cursor**: a página pode ser curta, nunca ilimitada. O cliente segue o cursor.
- A consulta limita e ordena os Movements antes de juntar contas, o que permite caminhar um índice parcial e parar após `limit + 1` linhas. Juntar primeiro fazia o planner partir das contas e ordenar a residência inteira (medido: de ~4,2 s para ~5 ms em 60 mil Movements, com RLS forçada).
- A migration `0022` cria dois índices parciais (residência e residência+conta, `effective_date DESC, id DESC`, apenas `STANDARD` `INCOME`/`EXPENSE`). É somente desempenho: nenhuma tabela, coluna, grant, policy ou trigger muda, e nenhum estado de caixa é persistido. A base não esperava migration; este é o menor custo para manter a leitura limitada, e é simétrica por downgrade.

### Autorização

A caixa lista o que a RLS torna visível e informa `canClassify` por item: o operador é dono de uma conta `ACTIVE`, exatamente a autoridade de escrita da classificação manual e do apply. Um item visível pode ser somente leitura (conta de outro membro ou arquivada) e a UI não oferece mutação. Conhecer ids nunca prova autorização; qualquer escrita continua restrita ao que a #245 e a #247 já permitem. A sugestão exibida a um não dono usa as regras que a RLS lhe mostra e é apenas informativa.

### Escritas: as canônicas, sem sucesso otimista

Não existe endpoint de escrita da caixa. `Aplicar sugestão` chama o apply da #247 e `Classificar` chama a classificação da #245, uma vez cada. A aplicação exige confirmação explícita e o servidor reavalia tudo sob os locks existentes (resultado `CONFLICT`/`ALREADY_CLASSIFIED`/`NO_MATCH`/`AMBIGUOUS` quando o estado mudou). O Flutter nunca remove um item por antecipação: após qualquer resposta de escrita, inclusive conflito, rejeição ou resultado desconhecido, lê novamente a primeira página e as categorias e substitui a lista pelo estado canônico. Se essa releitura falha, o item permanece, a lista é marcada como possivelmente desatualizada e novas escritas ficam bloqueadas até um Atualizar. Resultado ambíguo (transporte, 5xx, 2xx inválido) nunca é reenviado automaticamente; o retry explícito e idêntico da classificação manual reutiliza a chave de idempotência.

## Alternativas consideradas

- **Persistir status da caixa (`pending`, `reviewed`) em `finance.movements` ou em tabela própria:** cria uma segunda autoridade que pode divergir do ledger e da classificação. Rejeitada.
- **Fila persistente com dismiss/snooze/ownership:** exige contrato próprio; fora da v1.
- **Offset como contrato principal:** duplica ou perde itens sob inserções e classificações concorrentes e custa proporcionalmente à profundidade. Rejeitado em favor do keyset.
- **Empurrar o matching para SQL para filtrar por `ruleStatus`:** duplicaria o matcher da #247 em outra linguagem e abriria divergência. Rejeitada; usa-se orçamento de varredura fixo.
- **Carregar toda a lista e paginar no cliente ou no serviço:** custo proporcional ao extrato e payload ilimitado (o problema do preview da #247). Rejeitado.
- **Auto-apply, aprendizado, criação automática de regra:** explicitamente fora do escopo.

## Consequências positivas

- Uma única autoridade: a caixa nunca diverge do ledger nem da classificação e não há reparo ou sincronização.
- Leitura limitada e verificada por plano de execução, com número constante de statements por página.
- Reuso integral da avaliação, dos locks e das escritas auditadas já provadas nas #245/#247.
- A UI só mostra o que o servidor persistiu e confirmou.

## Consequências negativas e riscos

- Com `ruleStatus`, a página pode vir curta ou vazia com cursor; o cliente precisa seguir o cursor ("Continuar procurando").
- A varredura de uma residência quase toda classificada percorre mais entradas do índice antes de achar `limit` pendências (limitada pelo orçamento, nunca por N+1).
- A caixa lista Movements de contas arquivadas e Movements `STANDARD` estornados enquanto não classificados, ambos sem ação para quem não pode classificar.
- A sugestão mostrada a um operador que não é dono pode diferir da que o dono vê (regras visíveis diferem por audiência).
- A criação dos índices bloqueia escritas em `finance.movements` durante a migration (instalação local de pequeno porte).
- A v1 não oferece seleção múltipla; aplicar várias sugestões é uma a uma.

## Validação

Domínio (avaliação, cursor), PostgreSQL com role não-superuser e RLS forçada (derivação, exclusões, keyset estável sob escritas concorrentes, filtros, isolamento de residência e audiência, somente leitura, número constante de statements, plano que usa o índice e para cedo), migration downgrade/re-upgrade, API ponta a ponta (equivalência com o preview, sanitização, verbos, concorrência manual × apply × regra alterada, smoke vertical com ledger idêntico), Flutter (controller, telas, contrato da resposta, ausência de remoção otimista e de retry automático) e testes de contrato de fonte. Ver `docs/architecture/FINANCIAL_PENDING_INBOX.md`.

## Referências

- #170
- #171
- #180
- #245
- #247
- #249
- ADR-0016
- ADR-0022
- ADR-0023
- ADR-0024
- `docs/architecture/FINANCIAL_PENDING_INBOX.md`
- `docs/architecture/FINANCIAL_CATEGORIZATION_RULES.md`
- `docs/architecture/FINANCIAL_MOVEMENT_CLASSIFICATION_API.md`
