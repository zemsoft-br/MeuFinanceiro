# Arquitetura Inicial — MeuFinanceiro

## 1. Objetivos arquiteturais

A arquitetura deve priorizar:

- instalação local simples;
- domínio financeiro independente de provedores externos;
- colaboração paralela com baixo acoplamento;
- segurança adequada para dados financeiros;
- testes determinísticos;
- compatibilidade `amd64` e `arm64`;
- evolução sem exigir aplicativo móvel nativo.

## 2. Stack-base

| Camada | Tecnologia inicial |
|---|---|
| Interface | React + TypeScript + PWA |
| API | FastAPI + Python |
| Persistência | PostgreSQL |
| Migrações | Alembic |
| Worker | Processo Python separado, com fila persistida no PostgreSQL |
| Proxy | Caddy |
| Empacotamento | Docker Compose |
| Contrato | OpenAPI |
| Testes | Pytest e testes frontend apropriados à stack escolhida |

Redis não é obrigatório na fundação. Ele somente será introduzido mediante necessidade comprovada.

## 3. Topologia local

```text
Navegador / PWA
       |
       v
     Caddy
       |
       +--------> Frontend estático
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

- `web`;
- `api`;
- `worker`;
- `postgres`;
- `caddy`.

## 4. Organização do repositório

Estrutura proposta:

```text
MeuFinanceiro/
├── apps/
│   ├── api/
│   ├── web/
│   └── worker/
├── packages/
│   ├── contracts/
│   └── shared-web/
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

A estrutura final deve ser validada pela issue de bootstrap técnico antes de iniciar funcionalidades.

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

Regras financeiras não devem ficar em rotas, componentes React ou adaptadores da Pluggy.

## 6. Fonte de verdade

O modelo local normalizado é a fonte de verdade.

Provedores e arquivos são fontes de observação. Seus registros podem:

- criar candidatos a movimentação;
- atualizar dados de origem;
- propor conciliações;
- confirmar projeções;
- gerar críticas.

Eles não podem sobrescrever silenciosamente decisões do usuário.

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

Filtros de autorização devem existir na camada de caso de uso e persistência, não apenas no frontend.

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

### 8.3 Tempo

- Datas financeiras sem horário devem ser tipos de data.
- Instantes de auditoria e integração devem ser UTC.
- Apresentação usa o fuso configurado da residência.
- Competência, vencimento, liquidação e importação são conceitos distintos.

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
- nunca enviados ao frontend sem necessidade;
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

## 15. Frontend

Princípios:

- PWA responsiva;
- acessibilidade mínima WCAG AA nos fluxos principais;
- componentes compartilhados;
- formulários com validação consistente;
- estados de erro e carregamento explícitos;
- nenhuma regra financeira exclusiva do cliente;
- suporte a instalação no Android e iOS conforme limitações do navegador.

O frontend pode manter cache de interface, mas o backend local é a autoridade sobre dados financeiros.

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

## 18. Estratégia de evolução

- ADR obrigatório para decisões estruturais.
- Módulos novos entram por issue aprovada.
- Mudanças de contrato exigem migração e compatibilidade documentadas.
- Provedores externos entram por adaptadores.
- Dependências novas precisam justificar custo operacional, segurança e manutenção.
