# ADR-0028 — Sugestões assistidas de recorrência: derivadas, determinísticas e sempre confirmadas

- Status: Accepted
- Data: 2026-10-07
- Decisores: mantenedores

## Contexto

A #254 entregou recorrências mensais manuais (ADR-0027; issue #254 fechada, PR #255 integrada ao `develop`). A #256 acrescenta **assinaturas assistidas**: detectar padrões mensais em Movements já realizados e sugerir ao usuário a criação de uma recorrência **existente**. O ledger (`finance.movements`) continua sendo o único fato realizado; uma sugestão não é Movement, ocorrência nem recorrência, não altera saldo, extrato, classificação ou orçamento e nunca é aceita sozinha.

A decisão precisa responder: o que é detectado e como se explica, o que identifica uma sugestão sem virar autoridade, onde mora o feedback do usuário, como aceitar cria uma recorrência sem estado parcial e sem duplicata, e como a audiência é aplicada antes de qualquer agrupamento.

## Decisão

### Sugestão é derivada, nunca persistida

A sugestão é calculada **na leitura** a partir de Movements visíveis ao operador. `GET` nunca escreve, não há job, agendador nem aceitação automática. O único estado persistido é a **decisão explícita** do usuário (abaixo). A detecção é provider-neutral: sem Pluggy, merchant, IDs de provedor, fuzzy, ML, LLM ou pontuação opaca.

### Detector v1: regras fechadas e explicáveis

Entram apenas Movements `STANDARD` `EXPENSE` de contas **ACTIVE**, com data efetiva dentro da janela de **12 meses civis** (do primeiro dia do mês de `hoje − 11 meses` até `hoje`; datas futuras não são realizadas). Saem: `REVERSAL`, `INCOME`/`NEUTRAL`, `STANDARD` já revertido, Movement ligado a `finance.recurrence_occurrences` e descrição ausente ou vazia após normalizar.

O agrupamento é **somente dentro da mesma conta** por `(conta, EXPENSE, moeda, descrição normalizada)`. A normalização é a do contrato de categorização, reutilizada (`normalize_categorization_text`): trim externo → NFC → `casefold` → NFC; acentos, pontuação e espaços internos são preservados. Descrição parecida mas diferente é outro grupo.

Há sugestão se, e somente se:

1. a **corrida** (a sequência final de meses civis consecutivos que termina na última observação do grupo) tem **pelo menos 3 meses** e **exatamente uma** observação em cada mês;
2. a corrida termina no **mês atual ou no anterior** (um padrão que parou não é assinatura em curso);
3. as datas cabem numa **janela de cobrança**: existe um dia âncora `D` (1..31) tal que, para toda observação no mês `M` e dia `d`, `|min(D, último_dia(M)) − d| ≤ 3`. O corte no fim do mês é entendido (31 → 28/29/30). Escolhe-se a âncora de menor maior desvio, depois menor desvio total, depois menor dia (escolha total e independente da ordem de entrada);
4. nenhuma recorrência da conta já representa o mesmo grupo (mesma conta, `EXPENSE`, moeda e descrição normalizada, em qualquer status).

Conservador em caso de ambiguidade: mês mais recente com duas cobranças, lacuna, corrida curta ou datas dispersas **não** geram sugestão. Um mês duplicado ou uma lacuna *antes* da corrida apenas encerram a corrida. O valor pode variar e é evidência, não falha: expõe-se cada valor e data observados, mínimo, máximo, último, `suggestedExpectedAmount` (= último valor observado) e `amountBehavior` `FIXED` (todos iguais) ou `VARIABLE`. Tudo em `Decimal`, nunca `float`.

Códigos de motivo enumerados e determinísticos: `EXACT_DESCRIPTION`, `CONSECUTIVE_MONTHS`, `ONE_PER_MONTH`, `DAY_WINDOW`, `AMOUNT_FIXED` | `AMOUNT_VARIABLE`. Não existe confiança numérica.

### Fingerprint: identidade, não autoridade

`fingerprint` é um SHA-256 com prefixo de tamanho sobre `meufinanceiro:recurrence-suggestion:v1`, instalação, residência, conta, `EXPENSE`, moeda e descrição normalizada. Não inclui IDs de Movement nem datas, para que o feedback sobreviva a novas observações. **Não é um resource ID e conhecê-lo não prova acesso**: `accept` e `dismiss` reexecutam o detector para o operador e só agem sobre um fingerprint que **ele** produz agora; um fingerprint inexistente, forjado, de outra conta, de outra residência ou de conta invisível é o mesmo `404` sanitizado.

### Audiência antes de agrupar

A leitura roda sob o papel de runtime com RLS forçada: os Movements que o operador não enxerga nunca entram no agrupamento. `PERSONAL` não vaza, `SHARED` segue grant + membership ativa, `HOUSEHOLD` segue a audiência da conta e outra residência falha fechado. Aceitar é **somente do dono da conta** (alinhado à #254); ver não implica aceitar (`canAccept`).

### Feedback e proveniência: `finance.recurrence_suggestion_decisions`

Tabela append-only com RLS `ENABLE` + `FORCE`: `id` (UUID v4), instalação, residência, `account_id`, `operator_id`, `fingerprint`, `decision` (`ACCEPTED` | `DISMISSED`), `recurrence_id` (somente `ACCEPTED`), `evidence_digest` (SHA-256 do que foi mostrado) e `decided_at`. Única por `(instalação, operador, fingerprint)` e por `recurrence_id`. O runtime só tem `SELECT` e `INSERT`; um gatilho recusa `UPDATE` e não há grant de `DELETE`.

- `DISMISSED` esconde **só para o operador que dispensou**: a política de leitura o limita ao próprio operador e outro membro não herda a rejeição.
- `ACCEPTED` é proveniência da recorrência criada e fica legível para toda a audiência da conta: a sugestão deixa de aparecer para todos mesmo que o dono renomeie a recorrência (a descrição aceita pode divergir da normalizada).
- **Replay idempotente, conflito fail-closed:** repetir a mesma decisão devolve a existente; decisão incompatível (aceitar o que foi dispensado, dispensar o que já foi aceito, aceitar de novo com outra chave) é `409`.

### Aceite: uma transação, um writer

O aceite exige `idempotencyKey` UUID v4, `description`, `expectedAmount`, `startDate`, `dayOfMonth` e `endDate` opcional. **Conta, efeito e moeda vêm da sugestão** e o cliente não os amplia. Dentro de **uma única transação**: contexto e membership → replay pela chave da recorrência → decisão prévia → **reexecução do detector** para o operador (o candidato ainda existe, não há recorrência equivalente, a conta continua ACTIVE e do operador) → criação da recorrência pelo **mesmo writer da #254**, extraído para uma função que opera numa transação do chamador (`create_recurrence_in_transaction`; comportamento externo idêntico, como foi feito com o Movement na #254) → gravação da decisão `ACCEPTED`. Tudo ou nada: não existe recorrência aceita sem proveniência nem proveniência sem recorrência. Um gatilho do banco só aceita `ACCEPTED` ligando uma recorrência criada **nesta transação**, da mesma conta e do mesmo dono. Aceitar **não cria ocorrência nem Movement**.

- **Retry idêntico converge:** mesma chave e mesmo material devolvem a mesma recorrência, outro material é `409`; a resposta de replay não depende de a sugestão ainda existir.
- **Concorrência:** duas aceitações simultâneas não duplicam, porque a unicidade da decisão desfaz a transação perdedora inteira (inclusive a recorrência que ela inseriu).
- **Candidato obsoleto** entre o `GET` e o aceite (a sugestão sumiu ou a recorrência equivalente já existe) é `409` com refetch: o servidor nunca aceita um estado antigo.

### Dispensa

Explícita, idempotente e **por operador**; só aceita fingerprint que corresponda a sugestão atualmente visível e revalidável (ou uma dispensa já registrada pelo mesmo operador, para o replay). Não altera o ledger e não cria recorrência. Não existe "nunca perguntar de novo" entre usuários.

### Limites

A leitura varre no máximo `SUGGESTION_SCAN_MAX` (20 000) Movements da janela e devolve no máximo `SUGGESTION_LIST_MAX` (100) sugestões; ultrapassar qualquer um é erro explícito, nunca truncamento silencioso. O custo em statements é constante: contexto, membership, uma varredura, uma consulta de recorrências e uma de decisões, sem N+1.

## Alternativas consideradas

- **Persistir sugestões (tabela de candidatos):** segunda cópia que envelhece e exige job. Rejeitada; a derivação é barata e sempre atual.
- **Detecção em segundo plano ou aceitação automática:** viola "nunca sem confirmação". Rejeitada.
- **Fuzzy, merchant, ML/LLM ou confiança numérica:** opacos e sem prova. Rejeitados na v1.
- **Fingerprint como UUID/recurso ou incluindo Movements/datas:** viraria autoridade ou perderia o feedback a cada nova cobrança. Rejeitado.
- **Aceitar com compensação (criar a recorrência e depois gravar a decisão):** janelas de estado parcial. Rejeitada; transação única com o writer extraído.
- **Decisão sem unicidade, deduplicada em código:** corrida entre aceites duplicaria recorrências. Rejeitada; a unicidade no banco é a barreira.
- **`DISMISSED` compartilhado entre membros:** um membro silenciaria o outro. Rejeitado.
- **Sugerir contas arquivadas ou receitas:** fora da v1.

## Consequências

- o usuário vê assinaturas prováveis com evidências e motivos, sem efeito algum até confirmar;
- uma recorrência criada por aceite é uma recorrência #254 comum (mesma RLS, CAS e histórico de revisões);
- o writer de recorrência ganhou um ponto de entrada transacional compartilhado;
- risco aceito (P2): uma recorrência equivalente criada manualmente *ao mesmo tempo* que um aceite pode coexistir com ele, porque equivalência é semântica de sugestão e não invariante do banco; a dispensa não expira quando surgem novas evidências.

## Validação

Domínio (3 meses, 2 meses, lacuna, duplicata, normalização, `FIXED`/`VARIABLE`, dias 28–31, fingerprint estável e não forjável), persistência e RLS (PERSONAL, SHARED, HOUSEHOLD, entre residências, dispensa só do operador, append-only), aceite (1 recorrência, 0 Movement, 0 ocorrência, replay, concorrência, rollback, candidato obsoleto), API HTTP, contratos de qualidade, Flutter (sem retry automático nem sucesso otimista) e o smoke vertical da #256.

## Referências

- #180, #254, #256
- ADR-0015, ADR-0022, ADR-0024, ADR-0026, ADR-0027
- `docs/architecture/FINANCIAL_RECURRENCE_SUGGESTIONS.md`
