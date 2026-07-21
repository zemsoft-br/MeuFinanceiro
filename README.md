# MeuFinanceiro

Gestor financeiro pessoal e familiar, open-source e autohospedado, voltado exclusivamente ao contexto brasileiro.

> **Status:** fundação do projeto. Ainda não utilize com dados financeiros reais.

## Objetivo

Permitir que uma residência organize contas pessoais e compartilhadas, orçamentos, cartões, compromissos, empréstimos, investimentos, patrimônio e projeções de caixa mantendo os dados sob controle do próprio usuário.

O sistema não executará, agendará ou iniciará transações financeiras.

## Princípios

- execução local por Docker, com cliente Flutter Web/PWA;
- uma única base Flutter para Web/PWA e futuros alvos Android, iOS e desktop;
- funcionamento sem integração bancária obrigatória;
- PostgreSQL local como fonte principal de verdade;
- Open Finance opcional por adaptadores, começando por uma prova de conceito da Pluggy;
- importações OFX, CSV, PDF e QIF com pré-visualização, críticas e reversão;
- privacidade e telemetria desativada por padrão;
- planejamento público por GitHub Issues;
- toda implementação revisada por Pull Request.

## Arquitetura

```text
Flutter Web/PWA
       |
   Web estático
       |
     Caddy
       |
    FastAPI
       |
PostgreSQL + Worker
```

A distribuição principal é Docker Compose. As imagens escolhidas possuem variantes oficiais para `amd64` e `arm64`.

`apps/app` é o único cliente do projeto. O serviço `web` do Compose compila o Flutter Web e serve o artefato estático por Caddy. Não existe frontend React, target de rollback ou runtime Node na aplicação.

Node.js permanece apenas como ferramenta de desenvolvimento para validar a sintaxe e os invariantes do JavaScript próprio do PWA. Nenhuma dependência npm é necessária para construir ou executar o frontend.

## Início rápido

Linux, macOS ou WSL:

```bash
./infra/scripts/dev-up.sh
```

Windows PowerShell:

```powershell
./infra/scripts/dev-up.ps1
```

Os scripts geram credenciais administrativas e de runtime independentes, criam o keyring, aplicam as migrações, constroem os containers e executam o smoke test. A aplicação Flutter fica disponível em `http://127.0.0.1:8080`.

Consulte o [runbook do ambiente local](docs/runbooks/LOCAL_DEVELOPMENT.md) para operação, diagnóstico e remoção de dados.

## Quality gates locais

A suíte completa exige Python 3.13, Node.js para os testes PWA, Flutter na revisão fixada e um PostgreSQL descartável informado explicitamente por `TEST_DATABASE_URL` e `TEST_APP_DATABASE_USER`.

```bash
export TEST_DATABASE_URL='postgresql+psycopg://postgres:<senha>@127.0.0.1:<porta>/meufinanceiro_test'
export TEST_APP_DATABASE_USER='postgres'
python infra/scripts/run-quality.py --use-test-database-env
```

No Windows, use `py -3.13` no lugar de `python`. O [runbook de quality gates](docs/runbooks/QUALITY_GATES.md) contém o fluxo completo e o gate Docker Compose.

A suíte valida segurança do repositório, Python, o cliente Flutter, o artefato Web/PWA gerado, dependências e licenças documentadas. A execução local requer a versão exata registrada em `.flutter-version` e `.flutter-revision`.

## Estrutura do monorepo

```text
apps/
  api/       FastAPI e OpenAPI
  app/       cliente Flutter canônico e fontes Web/PWA
  worker/    consumidor da fila persistente
packages/
  security/  keyring, criptografia, senhas e redaction
  persistence/ SQLAlchemy, Alembic, health e fila PostgreSQL
  contracts/ contratos compartilhados futuros
infra/
  caddy/     entrada HTTP local e proxy da API
  web/       build Flutter Web e runtime estático Caddy
  scripts/   inicialização, diagnóstico e quality gates
tests/
  quality/   provas dos validadores do repositório
  smoke/     validação ponta a ponta do Compose
```

O Flutter deve implementar os contratos versionados do produto sem copiar regras financeiras para o cliente. A identidade visual incorporará as referências do Google Stitch sob contratos versionados do repositório.

## Documentação

- [Especificação do produto](docs/PRODUCT_SPECIFICATION.md)
- [Arquitetura inicial](docs/ARCHITECTURE.md)
- [Arquitetura de informação canônica](docs/architecture/INFORMATION_ARCHITECTURE.md)
- [Invariantes financeiras](docs/architecture/FINANCIAL_INVARIANTS.md)
- [Contrato dos dados demonstrativos](docs/architecture/DEMO_DATA_CONTRACT.md)
- [Sequência de implementação](docs/architecture/IMPLEMENTATION_SEQUENCE.md)
- [Auditoria dos protótipos Stitch](docs/design/STITCH_AUDIT.md)
- [Inventário das referências Stitch](docs/design/STITCH_SCREEN_INVENTORY.csv)
- [Manifesto da exportação Stitch](docs/design/STITCH_SOURCE_ARCHIVE.md)
- [Referências visuais do Stitch](docs/design/stitch/references/README.md)
- [Cliente Flutter](docs/runbooks/FLUTTER_CLIENT_MIGRATION.md)
- [Ambiente local](docs/runbooks/LOCAL_DEVELOPMENT.md)
- [Runtime Web/PWA](docs/runbooks/WEB_PWA.md)
- [Persistência e fila de tarefas](docs/runbooks/PERSISTENCE_AND_TASK_QUEUE.md)
- [Gerenciamento do keyring](docs/runbooks/KEY_MANAGEMENT.md)
- [Quality gates e CI](docs/runbooks/QUALITY_GATES.md)
- [Dependências diretas da fundação](docs/DEPENDENCIES.md)
- [Roadmap](docs/ROADMAP.md)
- [Governança](docs/GOVERNANCE.md)
- [Decisões arquiteturais](docs/adr/README.md)
- [Como contribuir](CONTRIBUTING.md)
- [Suporte](SUPPORT.md)
- [Política de segurança](SECURITY.md)

## Colaboração

O projeto utiliza issues como unidade de planejamento. Epics organizam o roadmap, mas colaboradores trabalham em issues pequenas, refinadas e com critérios de aceite verificáveis.

Fluxo principal:

```text
feature/* -> develop -> release/* -> main
```

Pull Requests devem começar como draft. Os quality gates principais são executados automaticamente quando a PR fica pronta para revisão, reduzindo consumo desnecessário de GitHub Actions durante o desenvolvimento.

Todas as contribuições exigem sign-off conforme o [Developer Certificate of Origin 1.1](DCO). Consulte [CONTRIBUTING.md](CONTRIBUTING.md) e a [governança](docs/GOVERNANCE.md) antes de assumir uma issue.

## Licenças e marca

- Código-fonte, scripts, configurações executáveis e testes: [GNU Affero General Public License v3.0 only](LICENSE), identificador SPDX `AGPL-3.0-only`.
- Documentação original dentro de `docs/`: [Creative Commons Attribution 4.0 International](docs/LICENSE.md), identificador `CC-BY-4.0`.
- Titularidade e autoria: [COPYRIGHT.md](COPYRIGHT.md).
- Nome, logotipo e identidade visual: [TRADEMARKS.md](TRADEMARKS.md).
- Modelo de contribuição: [DCO 1.1](DCO), sem CLA nesta fase.

A AGPL permite uso comercial e modificações, mas impõe obrigações de disponibilização do código correspondente nos cenários cobertos pela licença, inclusive para versões modificadas acessadas pela rede.

O uso do código não concede automaticamente direito de apresentar forks, serviços ou distribuições como oficiais do MeuFinanceiro ou da Zemsoft.

A decisão está registrada no [ADR-0004](docs/adr/0004-project-license-and-trademark.md).

## Próximos marcos

1. validar o runtime Flutter Web/PWA no Compose e concluir a issue #36;
2. concluir modo demonstração, instalação, backup e spike Pluggy;
3. implementar identidade, residência e núcleo financeiro;
4. evoluir a mesma base Flutter para Android, iOS e desktop quando esses alvos entrarem no roadmap.
