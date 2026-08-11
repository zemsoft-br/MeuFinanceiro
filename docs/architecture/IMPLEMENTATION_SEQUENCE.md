# Sequência de implementação após a fundação

- Issue de alinhamento: #22
- Roadmap: `docs/ROADMAP.md`
- Cliente canônico: Flutter em `apps/app`

## 1. Estado da fundação

Concluído:

- visão, arquitetura e governança;
- licença, DCO e política de segurança;
- monorepo e Docker Compose;
- configuração, keyring e criptografia;
- persistência, migrações e fila PostgreSQL;
- Flutter Web/PWA como único cliente;
- rotas `/`, `/componentes` e `/sistema`;
- tema, componentes, navegação responsiva e health check;
- runtime Web estático não-root;
- manifesto, service worker e cache auditado;
- remoção de React, Vite, npm e do target de rollback;
- quality gate que bloqueia a reintrodução do frontend legado.

A migração Flutter foi integrada pela PR #37 no commit
`26ee8715e0f50dbdfa7105b4deb7427ab05596c1`, com validação local e workflows
`Quality` e `Container Quality` aprovados.

## 2. Gates antes da Fase 1

Concluir:

1. modo demonstração conforme `DEMO_DATA_CONTRACT.md`;
2. instalação, atualização, backup e restauração;
3. spike Pluggy sem contaminar o domínio;
4. configuração administrativa do repositório;
5. decisões de dinheiro, IDs, autorização e imutabilidade.

Trabalho de backend independente pode avançar quando não depender de contratos ainda abertos e não antecipar uma decisão estrutural.

A Fase 1 está organizada pela Epic #124. A decisão de dinheiro foi concluída pela #125 / ADR-0015 e a audiência financeira pela #129 / ADR-0016. IDs financeiros, capacidade por papel e imutabilidade ainda precisam de recortes explícitos antes dos agregados que dependam deles.

## 3. Decisões estruturais imediatas

### 3.1 Dinheiro e arredondamento — resolvido

ADR-0015 define:

- `Decimal` finito como representação Python;
- contrato futuro `NUMERIC(24,8)` + moeda separada;
- moeda ASCII uppercase de três letras;
- amount HTTP como string decimal fixed-point;
- ausência de `float` como autoridade financeira;
- arredondamento sempre explícito por escala e modo;
- operações cross-currency fail-closed.

O value object inicial está em `packages/finance`.

### 3.2 Identidade, residência e audiência financeira — resolvido para o primeiro schema

Autenticação local, operador e residência primária foram antecipados pelas issues #84/#85 e #88/#89.

ADR-0016 / #129 define a audiência dos recursos financeiros:

- todo recurso possui `residence_id`, `owner_operator_id` e `visibility_scope`;
- `PERSONAL` pertence somente ao proprietário;
- `SHARED` exige grant explícito além de membership ativa;
- `HOUSEHOLD` pertence à audiência de todas as memberships ativas da residência;
- papel administrativo não concede bypass para conteúdo pessoal;
- ator e residência efetivos são derivados server-side;
- persistência financeira futura usa RLS com `app.current_residence_id` e `app.current_operator_id`;
- capacidade de mutação por papel permanece separada da audiência.

A primeira tabela de contas já pode aplicar esse contrato sem inventar visibilidade ad hoc. Matriz completa de papéis, convites e troca de residência continuam em issues próprias.

### 3.3 Livro financeiro

Definir:

- agregados e estados;
- imutabilidade;
- saldo de abertura;
- reversão e liquidação;
- transferências e rateios;
- auditoria.

### 3.4 Anexos

Definir:

- porta de armazenamento;
- criptografia e hash;
- metadados e quarentena;
- autorização;
- backup e restauração.

### 3.5 Persistência local do cliente

Não implementar por inferência do termo local-first. SQLite, WASM ou cache financeiro no Flutter exige issue e ADR específicos para autoridade, sincronização, criptografia, expiração, revogação, migrações e conflitos.

## 4. Fase 1 — Identidade, residência e núcleo financeiro

Ordem recomendada:

1. autenticação local mínima — fundação entregue;
2. residência e associações — fundação entregue;
3. audiência financeira pessoal/compartilhada/familiar — ADR-0016 / #129;
4. contrato canônico de conta financeira;
5. categorias-base;
6. saldo de abertura;
7. movimentações;
8. transferências;
9. rateios;
10. anexos;
11. auditoria financeira;
12. API/Flutter e dashboard inicial.

A próxima entrega deve ser o contrato canônico de conta financeira e sua persistência mínima, aplicando Money do ADR-0015 e audiência do ADR-0016 desde o primeiro schema.

Cada item deve ser dividido em PRs de schema, domínio/API e cliente Flutter quando isso reduzir risco. Interface começa após contrato de API e autorização estar estável ou mockado por contrato versionado.

## 5. Fase 2 — Planejamento

Após o livro estável:

1. regras de categorização;
2. caixa de pendências;
3. orçamentos;
4. recorrências;
5. assinaturas assistidas;
6. metas e projetos;
7. fluxo de caixa;
8. cenários.

## 6. Fase 3 — Importações

1. contrato comum;
2. observação externa;
3. lote e revisão;
4. OFX;
5. CSV/XLSX;
6. deduplicação;
7. conciliação;
8. rollback;
9. regras de importação.

Pluggy só entra depois desse pipeline como fonte de observações, sem substituir o livro canônico.

## 7. Fase 4 — Cartões e projeções

1. cartões;
2. compras;
3. parcelamentos;
4. faturas;
5. liquidação;
6. projeção;
7. calendário;
8. alertas internos.

A ordem pode ser ajustada desde que compra, liquidação e dupla contabilização estejam resolvidas.

## 8. Fases posteriores

Seguir `docs/ROADMAP.md`:

- Pluggy e Open Finance;
- empréstimos;
- patrimônio e investimentos;
- documentos e automações;
- distribuição e maturidade;
- Android, iOS e desktop a partir da mesma base Flutter.

Parte significativa da fundação Pluggy/Open Finance já foi antecipada pela Epic #63, mas a integração não substitui os contratos do núcleo financeiro.

Os protótipos não antecipam dependências técnicas.

## 9. Estrutura de issues

Cada issue deve conter:

- problema e resultado observável;
- escopo incluído e excluído;
- dependências e decisões vigentes;
- modelo de dados afetado;
- autorização;
- idempotência e concorrência;
- auditoria e migração;
- testes;
- estados de interface;
- referência Stitch;
- riscos;
- alvos Flutter afetados.

## 10. Tamanho de PR

Preferir uma finalidade por PR.

Exemplos aceitáveis:

- adicionar value object de dinheiro e contrato OpenAPI;
- criar tabelas e repositórios de residência;
- implementar autorização de leitura pessoal;
- criar transferência atômica;
- adicionar componente Flutter de seletor de conta;
- implementar uma rota e seus estados sem domínio paralelo.

Evitar:

- implementar módulo financeiro completo em uma PR;
- combinar schema, importador, relatórios e interface;
- migrações conflitantes paralelas;
- adotar biblioteca estrutural sem ADR;
- introduzir outra tecnologia de cliente;
- copiar HTML do Stitch para widgets sem reconstrução semântica.

## 11. Gates financeiros

Toda PR de domínio precisa provar:

- ausência de `float` para dinheiro;
- arredondamento e datas corretos;
- autorização;
- auditoria;
- concorrência e idempotência;
- reversão;
- ausência de dupla contabilização;
- migração simétrica ou plano explícito.

## 12. Gates do cliente Flutter

Toda experiência precisa provar:

- `dart format` e `flutter analyze`;
- testes unitários e de widget;
- semântica acessível, teclado e foco no Web;
- contraste e escalonamento de texto;
- loading, vazio, erro, permissão e API indisponível;
- deep links e navegação reversa;
- desktop e mobile;
- ausência de overflow;
- nenhuma CDN obrigatória;
- nenhuma regra financeira exclusiva do cliente;
- build Web release quando aplicável;
- smoke quando houver impacto no runtime servido.

## 13. Uso do Stitch

A issue deve citar:

- artefato canônico;
- estados auxiliares;
- componentes reutilizáveis;
- divergências conhecidas;
- regras que não podem ser inferidas do visual.

Capturas não substituem critérios de aceite.
