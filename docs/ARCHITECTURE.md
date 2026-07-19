# Arquitetura Inicial — MeuFinanceiro

## 1. Objetivos arquiteturais

A arquitetura deve priorizar:

- instalação local simples;
- domínio financeiro independente de provedores externos;
- colaboração paralela com baixo acoplamento;
- segurança adequada para dados financeiros;
- testes determinísticos;
- compatibilidade `amd64` e `arm64`;
- uma única base de cliente para Web/PWA e futuros alvos Android, iOS e desktop;
- evolução sem duplicar regras entre plataformas.

## 2. Stack-base

| Camada | Tecnologia inicial |
|---|---|
| Interface | Flutter + Dart; Web/PWA como primeiro alvo operacional |
| API | FastAPI + Python |
| Persistência | PostgreSQL |
| Migrações | Alembic |
| Worker | Processo Python separado, com fila persistida no PostgreSQL |
| Proxy | Caddy |
| Empacotamento | Docker Compose |
| Contrato | OpenAPI |
| Testes | Pytest, `flutter_test`, testes de integração e smoke do Compose |

Redis não é obrigatório na fundação. Ele somente será introduzido mediante necessidade comprovada.

A PR #21 integrou um shell React transitório. O ADR-0008 define Flutter como cliente canônico e a issue #24 controla a migração. Nenhuma nova funcionalidade financeira deve ser criada no frontend React.

## 3. Topologia local

```text
Cliente Flutter Web/PWA
       |
       v
     Caddy
       |
       +--------> Artefato Flutter Web estático
       |
       +--------> FastAPI
                    |
                    +--> PostgreSQL
                    +--> Armazenamento de anexos
                    +--> Adaptadores externos
                    |
                    +--> Worker PostgreSQL-backed
```

Serviços iniciais esperados no Docker Compose:

- `web`, servindo o build Flutter Web após a migração;
- `api`;
- `worker`;
- `postgres`;
- `caddy`.

O nome do serviço `web` descreve o artefato servido e não obriga o uso de React.

## 4. Organização do repositório

Estrutura alvo:

```text
MeuFinanceiro/
├── apps/
│   ├── api/
│   ├── app/        Flutter multiplataforma
│   └── worker/
├── packages/
│   ├── contracts/
│   └── shared-app/ componentes e contratos compartilhados futuros
├── infra/
│   ├── docker/
│   └── scripts/
├── docs/
│   ├── adr/
│   └── runbooks/
├── tests/
├── .github/
├── compose.yaml
└── README.md
```

Durante a migração:

- `apps/web` permanece como shell React transitório da PR #21;
- `apps/app` será criado pela issue #24;
- o React só será removido após paridade, testes e smoke do runtime Flutter;
- a coexistência não autoriza dois clientes funcionais permanentes.

A estrutura final deve ser validada pela migração técnica antes de iniciar funcionalidades financeiras.

## 5. Arquitetura de backend

O backend seguirá separação por domínio e ports/adapters.

```text
apps/api/app/
├── core/
│   ├── config/
│   ├── security/
│   ├── database/
│   └── observability/
├── modules/
│   ├── households/
│   ├── identities/
│   ├── accounts/
│   ├── ledger/
│   ├── budgets/
│   ├── cards/
│   ├── imports/
│   ├── reconciliation/
│   ├── forecasts/
│   ├── loans/
│   ├── investments/
│   └── notifications/
├── integrations/
│   ├── banking/
│   ├── importers/
│   └── notifications/
└── main.py
```

Cada módulo deve conter, conforme necessário:

- entidades e value objects;
- casos de uso;
- portas de persistência e integração;
- adaptadores de infraestrutura;
- rotas e schemas de API;
- testes unitários e de integração.

Regras financeiras não devem ficar em rotas, widgets Flutter, providers, caches locais ou adaptadores da Pluggy.

## 6. Fonte de verdade

O modelo local normalizado no backend é a fonte de verdade.

Provedores e arquivos são fontes de observação. Seus registros podem:

- criar candidatos a movimentação;
- atualizar dados de origem;
- propor conciliações;
- confirmar projeções;
- gerar críticas.

Eles não podem sobrescrever silenciosamente decisões do usuário.

O cliente Flutter pode manter estado de interface e caches explicitamente autorizados. Persistência local de dados financeiros não se torna autoridade e exige decisão própria sobre sincronização, criptografia, expiração, revogação e conflitos.

## 7. Identidade e residência

Entidades mínimas:

```text
User
Household
HouseholdMembership
PermissionRole
ResourceVisibility
```

Todo recurso financeiro deve pertencer a uma residência. Recursos pessoais também possuem proprietário explícito.

Filtros de autorização devem existir na camada de caso de uso e persistência, não apenas no cliente.

## 8. Livro financeiro

O núcleo não deve representar tudo como uma única tabela sem semântica.

Conceitos iniciais:

```text
FinancialAccount
FinancialEntry
EntryAllocation
Settlement
Transfer
ImportBatch
ExternalObservation
ReconciliationLink
Attachment
AuditEvent
```

### 8.1 Imutabilidade e correções

- Dados importados de origem devem ser preservados.
- Correções financeiras relevantes devem ser rastreáveis.
- Exclusões destrutivas devem ser evitadas em favor de cancelamento, reversão ou arquivamento.
- Lotes importados precisam ser reversíveis.
- Alterações automáticas devem registrar regra e confiança.

### 8.2 Dinheiro

- Valores monetários não usam `float`.
- Persistência usa tipos decimais ou inteiros em unidade mínima conforme decisão formal.
- Arredondamentos devem ser explícitos e testados.
- Moeda inicial é BRL, mas o cartão pode registrar moeda original e conversão.
- Serialização para Dart não pode degradar precisão monetária.

### 8.3 Tempo

- Datas financeiras sem horário devem ser tipos de data.
- Instantes de auditoria e integração devem ser UTC.
- Apresentação usa o fuso configurado da residência.
- Competência, vencimento, liquidação e importação são conceitos distintos.
- Testes do cliente e backend usam relógio controlável quando a regra depender do tempo.

## 9. Importadores

Todos os importadores implementam um contrato comum:

```text
probe(input) -> ImporterMatch
parse(input, options) -> ImportPreview
validate(preview) -> CriticismReport
commit(preview, decisions) -> ImportBatch
rollback(batch) -> RollbackResult
```

Adaptadores previstos:

- OFX;
- CSV;
- PDF por instituição/layout;
- PDF genérico;
- OCR experimental;
- QIF.

Nenhum importador deve persistir diretamente sem passar pelo fluxo de pré-visualização e validação.

## 10. Integrações Open Finance

Contrato conceitual:

```text
BankingProvider
├── authenticate/configure
├── list_connections
├── sync_accounts
├── sync_transactions
├── sync_credit_cards
├── sync_investments
├── sync_loans
└── disconnect
```

O primeiro adaptador será Pluggy, condicionado a uma prova de conceito do Conector 200.

Credenciais e tokens:

- criptografados em repouso;
- nunca registrados em logs;
- nunca enviados ao cliente sem necessidade;
- removíveis sem apagar obrigatoriamente o histórico.

## 11. Worker e tarefas

Tarefas previstas:

- sincronizações bancárias;
- geração de recorrências;
- projeções;
- notificações;
- reprocessamento de regras;
- importações demoradas;
- manutenção de anexos e backups.

A fila inicial será persistida no PostgreSQL com:

- estado;
- tentativas;
- agendamento;
- lock com expiração;
- idempotency key;
- erro sanitizado;
- correlação com usuário e residência.

## 12. Segurança

### 12.1 Requisitos mínimos

- autenticação obrigatória;
- sessões revogáveis;
- 2FA planejado para acesso remoto;
- proteção contra brute force;
- CORS e hosts restritos;
- PostgreSQL sem porta pública por padrão;
- segredos gerados no instalador;
- criptografia de credenciais, tokens, anexos e backups;
- bloqueio por inatividade;
- auditoria de ações sensíveis;
- logs sem valores ou descrições financeiras por padrão.

### 12.2 Criptografia

Nem todos os campos financeiros serão criptografados individualmente, pois isso inviabilizaria consultas e relatórios eficientes.

Proteção recomendada:

- criptografia do disco do host;
- chaves fora do banco;
- criptografia de segredos e dados pessoais selecionados;
- anexos criptografados;
- backups criptografados;
- TLS no acesso remoto.

Persistência local no cliente, quando adotada, deverá definir proteção equivalente por plataforma e não poderá assumir que armazenamento local comum é seguro.

## 13. Anexos

O backend controla anexos por uma porta de armazenamento.

Implementação inicial:

- filesystem local dedicado;
- nomes físicos não derivados do nome original;
- metadados no PostgreSQL;
- hash de integridade;
- criptografia;
- limites de tamanho e tipo;
- quarentena durante processamento.

S3 compatível pode ser adicionado posteriormente sem alterar o domínio.

## 14. API pública

- API REST versionada.
- OpenAPI como contrato executável.
- Erros estruturados com código estável.
- Paginação e filtros padronizados.
- Idempotência em mutações financeiras críticas.
- Webhooks de saída somente após definição de assinatura e segurança.
- DTOs Dart devem ser gerados ou mantidos sob contrato testável, sem duplicar semântica financeira.

## 15. Cliente Flutter

Princípios:

- uma única base para Web/PWA e futuros Android, iOS e desktop;
- `go_router` para rotas e deep links;
- Riverpod para estado e injeção de dependências;
- organização por feature, com `core`, `routing`, `theme` e adaptadores de plataforma;
- Material 3 adaptado ao Design System do MeuFinanceiro;
- acessibilidade WCAG AA nos fluxos Web principais;
- componentes compartilhados;
- formulários com validação consistente;
- estados de erro e carregamento explícitos;
- nenhuma regra financeira exclusiva do cliente;
- suporte a instalação PWA conforme limitações do navegador;
- assets e fontes empacotados, sem CDN obrigatória;
- abstrações de persistência e plataforma testáveis.

O Flutter Web é o primeiro alvo operacional. Android, iOS e desktop usarão a mesma base quando entrarem no roadmap, sem criar outro domínio.

### 15.1 PWA e cache

- cache de shell não pode armazenar respostas `/api/` indiscriminadamente;
- `index.html`, service worker, `version.json`, `main.dart.js` e WASM exigem política explícita de revalidação;
- somente assets realmente imutáveis recebem cache longo;
- atualização de versão deve ser testada;
- o backend local permanece autoridade sobre dados financeiros.

### 15.2 Qualidade

O cliente deverá passar por:

- `dart format`;
- `flutter analyze`;
- testes unitários;
- testes de widget;
- build Web release;
- auditoria de dependências e licenças;
- smoke Docker/Caddy;
- inspeção desktop e mobile;
- testes de teclado, foco, semântica, contraste e overflow.

## 16. Observabilidade e telemetria

Observabilidade local:

- logs estruturados;
- request/correlation ID;
- métricas de saúde;
- página de diagnóstico;
- exportação sanitizada de suporte.

Telemetria externa:

- desativada por padrão;
- opt-in explícito;
- sem dados financeiros, pessoais ou bancários;
- separada da verificação de atualização.

## 17. Backup e restauração

O contrato de backup deve incluir:

- PostgreSQL;
- anexos;
- configuração necessária;
- versão do aplicativo e schema;
- manifesto de integridade;
- criptografia antes de armazenamento externo.

A restauração deve ser testada automaticamente em CI quando possível e documentada em runbook.

Dados locais do cliente, quando existirem, devem ser tratados como cache reconstruível ou possuir estratégia explícita de inclusão, migração e invalidação. Eles não substituem o backup do backend.

## 18. Estratégia de evolução

- ADR obrigatório para decisões estruturais.
- Módulos novos entram por issue aprovada.
- Mudanças de contrato exigem migração e compatibilidade documentadas.
- Provedores externos entram por adaptadores.
- Dependências novas precisam justificar custo operacional, segurança e manutenção.
- Nenhuma funcionalidade financeira nova será implementada no shell React transitório.
- A remoção do React ocorrerá somente após paridade Flutter, quality gates e smoke aprovados.
