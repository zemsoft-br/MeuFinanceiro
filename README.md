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
Flutter — Web/PWA e futuros clientes multiplataforma
        |
      Caddy
        |
      FastAPI
        |
 PostgreSQL + Worker
```

A distribuição principal é Docker Compose. As imagens escolhidas possuem variantes oficiais para `amd64` e `arm64`.

### Transição do frontend

A PR #21 integrou um shell React executável para validar navegação, acessibilidade, PWA, cache e runtime estático. O ADR-0008 substitui React por Flutter como cliente canônico.

`apps/app` contém o scaffold Flutter e seus gates de compilação. O shell React permanece temporariamente como runtime servido e caminho de rollback durante a migração da issue #24. Nenhuma nova funcionalidade financeira deve ser implementada nele.

## Início rápido

Linux, macOS ou WSL:

```bash
./infra/scripts/dev-up.sh
```

Windows PowerShell:

```powershell
./infra/scripts/dev-up.ps1
```

Os scripts geram credenciais administrativas e de runtime independentes, criam o keyring, aplicam as migrações, constroem os containers e executam o smoke test. A aplicação fica disponível em `http://127.0.0.1:8080`.

Enquanto a migração Flutter não estiver concluída, esse endereço ainda serve o shell React transitório integrado pela PR #21. O build Flutter desta fase não participa do Compose.

Consulte o [runbook do ambiente local](docs/runbooks/LOCAL_DEVELOPMENT.md) para operação, diagnóstico e remoção de dados.

## Quality gates locais

A suíte obrigatória pode ser executada antes de marcar uma Pull Request como pronta:

```bash
python infra/scripts/run-quality.py
```

Ela valida segurança do repositório, Python, o shell React transitório, o cliente Flutter, dependências e licenças documentadas. Testes de persistência usam PostgreSQL real quando `TEST_DATABASE_URL` está definido; o gate de containers valida a integração completa. Consulte o [runbook de quality gates](docs/runbooks/QUALITY_GATES.md).

A execução local requer a versão exata registrada em `.flutter-version`. Os gates Flutter incluem lockfile, formatação, análise, testes e build Web release.

## Estrutura do monorepo

```text
apps/
  api/       FastAPI e OpenAPI
  app/       cliente Flutter canônico; scaffold Web e gates já versionados
  web/       shell React transitório da PR #21; será removido após paridade Flutter
  worker/    consumidor da fila persistente
packages/
  security/  keyring, criptografia, senhas e redaction
  persistence/ SQLAlchemy, Alembic, health e fila PostgreSQL
  contracts/ contratos compartilhados futuros
infra/
  caddy/     entrada HTTP local
  scripts/   inicialização, diagnóstico e quality gates
tests/
  quality/   provas dos validadores do repositório
  smoke/     validação ponta a ponta do Compose
```

O Flutter deve reproduzir os contratos já validados pelo shell existente sem copiar regras financeiras para o cliente. A identidade visual incorporará as referências do Google Stitch sob contratos versionados do repositório.

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
- [Migração do cliente para Flutter](docs/runbooks/FLUTTER_CLIENT_MIGRATION.md)
- [Ambiente local](docs/runbooks/LOCAL_DEVELOPMENT.md)
- [Shell Web/PWA atual](docs/runbooks/WEB_PWA.md)
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

1. portar o shell responsivo e as rotas existentes para Flutter;
2. servir o build Flutter Web pelo Compose com política PWA auditada;
3. remover o shell React após paridade e smoke aprovados;
4. concluir modo demonstração, instalação, backup e spike Pluggy;
5. implementar identidade, residência e núcleo financeiro.
