# Arquitetura Inicial — MeuFinanceiro

## 1. Direção arquitetural

O MeuFinanceiro é um gestor financeiro pessoal e familiar, autohospedado e voltado ao Brasil. A arquitetura prioriza instalação local, soberania dos dados, segurança, testes determinísticos e evolução por contratos explícitos.

Flutter é a única tecnologia de cliente. `apps/app` atende Web/PWA e será reutilizado por Android, iOS e desktop quando esses alvos entrarem no roadmap. Um segundo frontend exige novo ADR.

## 2. Stack canônica

| Camada | Tecnologia |
|---|---|
| Cliente | Flutter + Dart |
| Estado | Riverpod |
| Rotas | GoRouter |
| API | FastAPI + Python 3.13 |
| Contrato HTTP | OpenAPI |
| Persistência | PostgreSQL 18 |
| Migrações | Alembic |
| Worker | Python com fila PostgreSQL-backed |
| Entrada HTTP | Caddy |
| Runtime Web | Flutter Web estático em Caddy não-root |
| Distribuição | Docker Compose |

Node.js é usado somente para testar a sintaxe e os invariantes do JavaScript próprio do PWA. Não existe React, Vite, manifesto npm do frontend ou runtime Node na aplicação.

## 3. Topologia local

```text
Navegador / PWA Flutter
          |
          v
     Caddy externo
       /       \
      v         v
Flutter Web   FastAPI
  estático       |
                 +--> PostgreSQL
                 +--> Worker e fila
                 +--> anexos
                 +--> adaptadores externos
```

Serviços do Compose:

- `caddy`: única porta publicada e proxy de `/api`;
- `web`: build Flutter servido por Caddy interno;
- `api`: casos de uso e contrato HTTP;
- `worker`: tarefas assíncronas;
- `db-bootstrap`: role de aplicação;
- `migrate`: migrações Alembic;
- `postgres`: fonte local de verdade.

## 4. Organização do repositório

```text
apps/
  api/        FastAPI
  app/        cliente Flutter
  worker/     consumidor da fila
packages/
  contracts/
  persistence/
  security/
infra/
  caddy/
  web/
  scripts/
docs/
tests/
compose.yaml
```

A árvore `apps/web` é proibida pelo quality gate.

## 5. Backend e domínio

O backend segue ports/adapters. Cada módulo pode conter entidades, value objects, casos de uso, portas, adaptadores, rotas e testes.

Módulos previstos:

- identidade e residência;
- contas e livro financeiro;
- orçamentos e recorrências;
- cartões e faturas;
- importações e conciliação;
- projeções;
- empréstimos;
- patrimônio e investimentos;
- notificações.

Regras financeiras não ficam em rotas, widgets Flutter, providers, service worker ou adaptadores externos.

## 6. Fonte de verdade

O modelo normalizado no backend é a fonte principal de verdade. Arquivos e provedores externos são fontes de observação: podem criar candidatos, propor conciliações e atualizar metadados, mas não sobrescrevem silenciosamente decisões do usuário.

Persistência financeira no dispositivo exige decisão própria sobre autoridade, sincronização, criptografia, conflitos, expiração e revogação.

## 7. Livro financeiro

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

Contratos:

- dinheiro não usa `float`;
- arredondamento é explícito;
- competência, vencimento, liquidação e importação são distintos;
- correções relevantes são rastreáveis;
- lotes importados são reversíveis;
- transferências não duplicam receita ou despesa.

## 8. Identidade e autorização

Todo recurso financeiro pertence a uma residência. Recursos pessoais também possuem proprietário explícito. A autorização é aplicada nos casos de uso e na persistência; controles visuais não constituem proteção.

## 9. Importações e integrações

Importadores seguem o fluxo:

```text
probe -> parse -> preview -> validate -> commit -> rollback
```

OFX, CSV, PDF, OCR e QIF entram por adaptadores. Pluggy e outros provedores permanecem opcionais. Indisponibilidade externa não impede uso manual.

## 10. Worker

A fila persistente registra estado, tentativas, agendamento, lease, chave de idempotência e erro sanitizado. Handlers devem ser idempotentes ou possuir compensação explícita.

## 11. Cliente Flutter

Princípios:

- organização por feature;
- GoRouter para rotas e deep links;
- Riverpod para estado e composição;
- Material 3 adaptado ao Design System;
- acessibilidade e responsividade testadas;
- estados de loading, vazio, erro e indisponibilidade explícitos;
- nenhuma regra financeira exclusiva do cliente;
- assets e fontes locais.

## 12. Web/PWA

O pipeline canônico é:

```text
Flutter fixado
  -> pubspec.lock
  -> build Web release sem CDN
  -> finalização estrita
  -> validação PWA/cache
  -> imagem Caddy não-root
```

O service worker:

- não intercepta `/api` nem `/api/*`;
- armazena somente shell e assets seguros;
- aceita apenas respostas `GET`, same-origin, bem-sucedidas e `basic`;
- usa rede primeiro para navegação e executáveis;
- limita fallback SPA a rotas sem extensão;
- remove caches antigos conhecidos;
- não substitui o backend como autoridade.

## 13. Segurança e operação

- segredos são únicos por instalação e não são versionados;
- PostgreSQL não publica porta por padrão;
- keyring fica fora do banco;
- containers executam sem privilégios desnecessários;
- logs evitam conteúdo financeiro e material sensível;
- acesso remoto requer TLS e controles adicionais;
- backups incluem banco, anexos, configuração e keyring, com restauração testada.

## 14. Quality gates

A suíte obrigatória cobre:

- DCO e segurança do repositório;
- rejeição do frontend legado;
- Ruff, mypy e Pytest;
- PostgreSQL descartável para testes de persistência;
- auditoria e licenças Python;
- testes do JavaScript próprio do PWA;
- toolchain Flutter fixada;
- formatação, análise, testes e build Flutter;
- validação do artefato Web;
- Compose, health, fila, usuário não-root e restart.

Quando GitHub Actions estiver indisponível, o merge permanece bloqueado até execução local equivalente registrada na PR.

## 15. Evolução

Mudanças em autoridade dos dados, modelo monetário, autenticação, persistência local, criptografia, segundo cliente, cache financeiro, providers ou distribuição exigem issue e, quando arquiteturais, ADR.

Detalhes complementares estão em:

- `docs/adr/0008-flutter-multiplatform-client.md`;
- `docs/architecture/FINANCIAL_INVARIANTS.md`;
- `docs/architecture/INFORMATION_ARCHITECTURE.md`;
- `docs/runbooks/WEB_PWA.md`;
- `docs/runbooks/QUALITY_GATES.md`;
- `docs/runbooks/PERSISTENCE_AND_TASK_QUEUE.md`.
