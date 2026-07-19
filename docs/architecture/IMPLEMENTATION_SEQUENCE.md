# Sequência de implementação após a fundação

- Issue: #22
- Alinhamento: `docs/ROADMAP.md`
- Objetivo: decompor o material visual em trabalho técnico pequeno e dependente

## 1. Estado atual

Integrado em `develop`:

- visão e arquitetura;
- governança;
- licença e DCO;
- monorepo e Docker Compose;
- quality gates;
- configuração e criptografia;
- persistência, migrações e fila PostgreSQL;
- shell Web/PWA React transitório da PR #21;
- ADR-0008, que define Flutter como cliente canônico.

Ainda não existe funcionalidade financeira.

O shell React é referência executável e rollback temporário. Nenhuma funcionalidade financeira nova deve ser implementada nele.

## 2. Gate imediato — migração Flutter

Concluir a issue #24 antes da Fase 1:

1. scaffold Flutter em `apps/app`;
2. quality gates de Dart e Flutter;
3. paridade das rotas `/`, `/componentes` e `/sistema`;
4. tema, componentes-base e navegação responsiva;
5. health check operacional, degradado, indisponível e timeout;
6. PWA e cache seguro sem respostas `/api/`;
7. build Web reproduzível em Docker;
8. smoke por Caddy/Compose;
9. validação de acessibilidade, desktop e mobile;
10. remoção do React somente após paridade aprovada.

Enquanto esse gate estiver aberto, trabalho de backend independente pode avançar apenas quando não depender de contratos do cliente e não iniciar funcionalidades financeiras de Fase 1.

## 3. Demais gates antes da Fase 1

Concluir:

1. issue #9 de modo demonstração refinada com `DEMO_DATA_CONTRACT.md`;
2. issue #10 de instalação, atualização e backup;
3. issue #11 de spike Pluggy sem contaminar o domínio;
4. issue #2 de configuração administrativa do repositório;
5. decisões de dinheiro, IDs, autorização e imutabilidade.

## 4. Próximas decisões estruturais

Abrir issues independentes para:

### 4.1 Dinheiro e arredondamento

Definir:

- `numeric` versus unidade mínima;
- escala;
- moeda;
- conversão;
- arredondamento;
- serialização OpenAPI e Dart.

### 4.2 Identidade, residência e autorização

Definir:

- usuário local;
- associação;
- papéis;
- escopos;
- proprietário;
- filtros no caso de uso;
- eventual RLS;
- sessão e revogação.

### 4.3 Livro financeiro

Definir:

- agregados;
- estados;
- imutabilidade;
- saldo de abertura;
- reversão;
- liquidação;
- transferências;
- rateios;
- auditoria.

### 4.4 Anexos

Definir:

- porta de armazenamento;
- criptografia;
- hash;
- metadados;
- quarentena;
- autorização;
- backup.

### 4.5 Persistência local do cliente

Não implementar por inferência a partir do termo local-first.

Qualquer SQLite, WASM ou cache financeiro no Flutter exige issue e ADR específicos para:

- autoridade dos dados;
- sincronização;
- criptografia;
- expiração;
- revogação;
- migrações;
- conflitos;
- comportamento por plataforma.

## 5. Fase 1 — Identidade, residência e núcleo financeiro

Ordem recomendada:

1. autenticação local mínima;
2. residência e associações;
3. autorização e escopos;
4. categorias-base;
5. contas;
6. saldo de abertura;
7. movimentações;
8. transferências;
9. rateios;
10. anexos;
11. auditoria financeira;
12. Dashboard inicial.

Cada item deve ser dividido em PRs de schema, domínio/API e cliente Flutter quando isso reduzir risco.

Uma PR de interface só começa após o contrato de API e autorização relevante estar estável ou explicitamente mockado por contrato versionado.

## 6. Fase 2 — Planejamento

Após o livro estável:

1. regras de categorização;
2. caixa de pendências;
3. orçamentos;
4. recorrências;
5. assinaturas assistidas;
6. metas;
7. projetos;
8. fluxo de caixa;
9. cenários.

## 7. Fase 3 — Importações

1. contrato comum;
2. observação externa;
3. lote e revisão;
4. OFX;
5. CSV/XLSX;
6. deduplicação;
7. conciliação;
8. rollback;
9. regras de importação.

Pluggy só entra depois desse pipeline.

## 8. Fase 4 — Cartões e projeções

1. cartões;
2. compras;
3. parcelamentos;
4. faturas;
5. liquidação;
6. projeção;
7. calendário;
8. alertas internos.

A ordem pode ser ajustada para cartões antes de planejamento, desde que o modelo de compra e liquidação esteja decidido.

## 9. Fases posteriores

Seguir `docs/ROADMAP.md`:

- Pluggy;
- empréstimos;
- patrimônio;
- investimentos;
- documentos e automações avançadas;
- distribuição e maturidade;
- ativação progressiva dos alvos Flutter Android, iOS e desktop a partir da mesma base.

Os protótipos não antecipam dependências técnicas.

## 10. Estrutura de issues

Cada issue deve conter:

- problema;
- resultado observável;
- escopo incluído;
- escopo excluído;
- dependências;
- decisões vigentes;
- modelo de dados afetado;
- autorização;
- idempotência;
- auditoria;
- migração;
- testes;
- estados de interface;
- referência Stitch;
- riscos;
- alvos Flutter afetados.

## 11. Tamanho de PR

Preferir uma finalidade por PR.

Exemplos aceitáveis:

- adicionar value object de dinheiro e contrato OpenAPI;
- criar tabelas e repositórios de residência;
- implementar autorização de leitura pessoal;
- criar transferência atômica;
- adicionar componente Flutter de seletor de conta;
- implementar uma rota e seus estados sem criar domínio paralelo.

Evitar:

- “implementar módulo financeiro completo”;
- schema, importador, relatórios e interface na mesma PR;
- migrações conflitantes paralelas;
- adoção de biblioteca sem ADR quando estrutural;
- manter implementação equivalente em React e Flutter;
- copiar HTML do Stitch para widgets sem reconstrução semântica.

## 12. Gates financeiros

Toda PR de domínio precisa provar:

- ausência de `float`;
- arredondamento;
- datas;
- autorização;
- auditoria;
- concorrência;
- idempotência;
- reversão;
- ausência de dupla contabilização;
- migração simétrica ou plano explícito.

## 13. Gates do cliente Flutter

Toda experiência precisa provar:

- `dart format`;
- `flutter analyze`;
- testes unitários e de widget pertinentes;
- semântica acessível;
- teclado e foco no Web;
- contraste;
- escalonamento de texto;
- loading;
- vazio;
- erro;
- permissão;
- API indisponível;
- deep link e navegação reversa;
- desktop e mobile;
- ausência de overflow;
- nenhuma dependência obrigatória de CDN;
- nenhuma regra financeira exclusiva do cliente;
- build Web release quando houver mudança executável;
- smoke do runtime quando houver impacto no artefato servido.

## 14. Uso do Stitch em issues

A issue deve citar:

- artefato canônico;
- estados auxiliares;
- componentes reutilizáveis;
- divergências conhecidas;
- regras que não podem ser inferidas do visual.

Capturas não substituem critérios de aceite.
