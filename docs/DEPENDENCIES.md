# Dependências diretas da fundação

## Objetivo

Registrar as versões efetivamente escolhidas e suas licenças declaradas. Este inventário não substitui o SBOM, os notices nem a análise de dependências transitivas exigidos antes da primeira distribuição pública.

O ADR-0008 definiu Flutter como cliente canônico. Durante a Fase C da issue #24, Flutter torna-se o runtime Web padrão e o shell React permanece versionado somente como rollback explícito até sua remoção na Fase D.

## Imagens e runtimes atuais

| Componente | Versão fixada | Uso | Licença principal declarada |
|---|---:|---|---|
| Python | 3.13.14 | API, worker, migração e gates locais | PSF-2.0 |
| Node.js | 24.18.0 LTS | build, testes e rollback do shell React transitório | MIT |
| Flutter SDK | 3.44.6 | toolchain do cliente canônico e build Web | BSD-3-Clause |
| Dart SDK | fornecido pelo Flutter 3.44.6 | linguagem, análise, formatação e testes do cliente | BSD-3-Clause |
| PostgreSQL | 18.4 | persistência local e fila de tarefas | PostgreSQL License |
| Caddy | 2.11.3 | proxy HTTP local e runtime estático Flutter | Apache-2.0 |
| Debian Bookworm slim | rolling da tag oficial | estágio de build Flutter no Docker | licenças variadas por pacote |

A versão Flutter é registrada em `.flutter-version` e a revisão exata em `.flutter-revision`. O Dart não é atualizado de forma independente: a revisão do Flutter altera o SDK Dart compatível e exige atualização conjunta do lockfile e dos gates.

Node.js deixou de ser o caminho ativo do frontend, mas permanece durante a Fase C para construir, testar e executar o target `react-runtime` de rollback. Será removido junto do shell antigo, salvo se uma ferramenta futura justificar sua permanência por decisão explícita.

As imagens `python:*‑slim`, `node:*‑alpine`, `postgres:*‑alpine`, `caddy:*‑alpine` e `debian:*‑slim` incluem pacotes do sistema sob licenças variadas. O inventário transitivo e os notices das imagens serão gerados e revisados antes da primeira release distribuível.

## Toolchain Flutter

A fundação fixa:

- Flutter `3.44.6` e revisão `ee80f08bbf97172ec030b8751ceab557177a34a6`;
- alvo Web gerado pelo próprio Flutter;
- `pubspec.lock` versionado;
- resolução com `flutter pub get --enforce-lockfile`;
- `dart format` em modo de verificação;
- `flutter analyze`;
- `flutter test`;
- `flutter build web --release --no-web-resources-cdn`;
- manifesto, carregador e service worker mantidos pelo projeto;
- validação do source e do artefato final servido.

A instalação local precisa disponibilizar no `PATH` exatamente a versão de `.flutter-version`. O script `infra/scripts/check-flutter-toolchain.py` rejeita ausência, saída inválida ou divergência de versão.

O Dockerfile `infra/web/Dockerfile` instala a mesma toolchain em estágio descartável, confirma a revisão antes do build e copia somente `build/web` para o runtime Caddy final.

## Dependências Flutter diretas

| Pacote | Versão | Uso | Licença declarada |
|---|---:|---|---|
| `flutter` | SDK 3.44.6 | framework do cliente | BSD-3-Clause |
| `flutter_localizations` | SDK 3.44.6 | infraestrutura de localização | BSD-3-Clause |
| `flutter_riverpod` | 3.3.2 | estado, composição e injeção | MIT |
| `go_router` | 17.3.0 | rotas declarativas e deep links | BSD-3-Clause |
| `flutter_test` | SDK 3.44.6 | testes unitários e de widget | BSD-3-Clause |
| `flutter_lints` | 6.0.0 | regras estáticas recomendadas | BSD-3-Clause |

O lockfile também registra dependências transitivas e hashes dos pacotes hospedados. Antes da primeira distribuição pública, a release deverá produzir inventário transitivo, notices e SBOM do artefato Flutter.

Não foram adicionados nesta etapa:

- biblioteca HTTP adicional;
- serialização ou geração de código;
- SQLite/WASM;
- armazenamento seguro;
- analytics ou telemetria;
- bibliotecas específicas de Android, iOS ou desktop;
- biblioteca JavaScript de PWA.

O carregador e o service worker usam somente APIs nativas do navegador. Capacidades adicionais exigem issue, revisão de licença e justificativa próprias.

## Pacotes de sistema do estágio Flutter

O estágio de build instala, via Debian Bookworm:

- `ca-certificates`;
- `curl`;
- `git`;
- `libglu1-mesa`;
- `unzip`;
- `xz-utils`;
- `zip`.

Esses pacotes não são copiados para a imagem final. Permanecem sujeitos ao inventário transitivo da imagem de build e à política de atualização de bases.

## Dependências Python da aplicação

| Pacote | Versão | Uso | Licença declarada |
|---|---:|---|---|
| FastAPI | 0.139.2 | API HTTP e OpenAPI | MIT |
| Pydantic Settings | 2.14.2 | configuração por ambiente | MIT |
| psycopg | 3.3.4 | driver PostgreSQL | LGPL-3.0-only |
| SQLAlchemy | 2.0.51 | persistência e transações compartilhadas | MIT |
| Alembic | 1.18.5 | migrações de schema | MIT |
| Uvicorn | 0.51.0 | servidor ASGI | BSD-3-Clause |
| cryptography | 49.0.0 | AES-256-GCM autenticado | Apache-2.0 OR BSD-3-Clause |
| argon2-cffi | 25.1.0 | hashing Argon2id de senhas | MIT |
| httpx | 0.28.1 | testes da API | BSD-3-Clause |
| pytest | 9.1.1 | testes Python | MIT |
| setuptools | 80.9.0 | build dos pacotes locais | MIT |

## Pacotes internos

| Pacote | Versão | Uso | Licença |
|---|---:|---|---|
| meufinanceiro-security | 0.1.0 | keyring, envelopes, senhas e redaction compartilhados | AGPL-3.0-only |
| meufinanceiro-persistence | 0.1.0 | engine, transações, Alembic, health e fila PostgreSQL | AGPL-3.0-only |

## Ferramentas Python de qualidade

| Pacote | Versão | Uso | Licença declarada |
|---|---:|---|---|
| Ruff | 0.15.22 | lint e formatação | MIT |
| mypy | 2.3.0 | análise estática | MIT |
| pip-audit | 2.10.1 | auditoria de vulnerabilidades Python | Apache-2.0 |

Essas ferramentas são instaladas em `.quality-venv` pelo script local e não fazem parte das imagens de execução da aplicação.

## Dependências Web transitórias do rollback React

| Pacote | Versão | Uso | Licença declarada |
|---|---:|---|---|
| React | 19.2.7 | shell Web de rollback da PR #21 | MIT |
| React DOM | 19.2.7 | renderização Web do rollback | MIT |
| Vite | 8.1.5 | build transitório do rollback | MIT |
| TypeScript | 6.0.3 | tipagem e compilação do shell transitório | Apache-2.0 |
| `@vitejs/plugin-react` | 6.0.3 | integração React/Vite | MIT |
| `@types/react` | 19.2.17 | tipos de desenvolvimento | MIT |
| `@types/react-dom` | 19.2.3 | tipos de desenvolvimento | MIT |
| `@types/node` | 24.13.3 | tipos para testes Node | MIT |
| ESLint | 10.7.0 | lint do frontend transitório | MIT |
| `@eslint/js` | 10.0.1 | regras JavaScript recomendadas | MIT |
| typescript-eslint | 8.64.0 | integração TypeScript/ESLint | MIT |
| eslint-plugin-react-hooks | 7.1.1 | regras de Hooks | MIT |
| eslint-plugin-react-refresh | 0.5.3 | segurança de Fast Refresh | MIT |
| globals | 17.7.0 | ambientes globais ESLint | MIT |

Essas dependências não são base para novas funcionalidades. O Container Quality constrói e executa o target de rollback para impedir que ele apodreça durante a janela da Fase C. A Fase D removerá esse conjunto junto de `apps/web`.

## Avaliação

Não foi identificada incompatibilidade direta que impeça a combinação das dependências atuais com `AGPL-3.0-only`. A LGPL do psycopg permite uso e distribuição nas condições da própria licença; seus avisos e código-fonte correspondente devem ser tratados no inventário de terceiros aplicável.

Alembic e SQLAlchemy declaram MIT. A inclusão do Alembic evita um mecanismo de migração próprio e mantém o schema versionado com uma dependência amplamente auditada.

`cryptography` utiliza licença dual permissiva Apache-2.0/BSD-3-Clause. `argon2-cffi` declara MIT. Ambas permanecem sujeitas ao inventário transitivo e aos notices da distribuição.

Flutter, `go_router` e `flutter_lints` declaram BSD-3-Clause. `flutter_riverpod` declara MIT. O uso dessas dependências permanece sujeito ao inventário transitivo e à inclusão dos notices aplicáveis na distribuição.

Caddy declara Apache-2.0 e já era usado como gateway. A Fase C reutiliza a mesma versão fixada como servidor estático interno, sem adicionar uma nova família de runtime ao artefato final.

Os gates geram inventários preliminares das dependências instaladas e bloqueiam famílias conhecidas que exigem revisão específica. Esse controle não substitui revisão jurídica nem um SBOM da release.

## Atualização

Toda alteração de versão ou inclusão de dependência deve atualizar este arquivo e registrar:

- finalidade;
- licença;
- impacto transitivo;
- riscos de segurança e manutenção;
- alternativa sem a dependência.

Versões diretas permanecem fixadas. O lockfile correspondente deve ser atualizado no mesmo Pull Request que altera o manifesto de dependências. Merge automático de atualizações não é permitido.
