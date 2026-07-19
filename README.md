# MeuFinanceiro

Gestor financeiro pessoal e familiar, open-source e autohospedado, voltado exclusivamente ao contexto brasileiro.

> **Status:** fundação do projeto. Ainda não utilize com dados financeiros reais.

## Objetivo

Permitir que uma residência organize contas pessoais e compartilhadas, orçamentos, cartões, compromissos, empréstimos, investimentos, patrimônio e projeções de caixa mantendo os dados sob controle do próprio usuário.

O sistema não executará, agendará ou iniciará transações financeiras.

## Princípios

- execução local por Docker, com interface Web/PWA;
- funcionamento sem integração bancária obrigatória;
- PostgreSQL local como fonte principal de verdade;
- Open Finance opcional por adaptadores, começando por uma prova de conceito da Pluggy;
- importações OFX, CSV, PDF e QIF com pré-visualização, críticas e reversão;
- privacidade e telemetria desativada por padrão;
- planejamento público por GitHub Issues;
- toda implementação revisada por Pull Request.

## Arquitetura

```text
React + TypeScript
        |
      Caddy
        |
      FastAPI
        |
 PostgreSQL + Worker
```

A distribuição principal é Docker Compose. As imagens escolhidas possuem variantes oficiais para `amd64` e `arm64`.

## Início rápido

Linux, macOS ou WSL:

```bash
./infra/scripts/dev-up.sh
```

Windows PowerShell:

```powershell
./infra/scripts/dev-up.ps1
```

Os scripts geram uma senha local aleatória, constroem os containers e executam o smoke test. A aplicação fica disponível em `http://127.0.0.1:8080`.

Consulte o [runbook do ambiente local](docs/runbooks/LOCAL_DEVELOPMENT.md) para operação, diagnóstico e remoção de dados.

## Estrutura do monorepo

```text
apps/
  api/       FastAPI e OpenAPI
  web/       React + TypeScript; interface provisória
  worker/    processo assíncrono mínimo
packages/
  contracts/ contratos compartilhados futuros
  shared-web/componentes compartilhados futuros
infra/
  caddy/     entrada HTTP local
  scripts/   inicialização e diagnóstico
tests/
  smoke/     validação ponta a ponta do Compose
```

A interface atual é deliberadamente neutra e pode ser substituída pelo design produzido no Google Stitch sem alterar o contrato `/api/v1`.

## Documentação

- [Especificação do produto](docs/PRODUCT_SPECIFICATION.md)
- [Arquitetura inicial](docs/ARCHITECTURE.md)
- [Ambiente local](docs/runbooks/LOCAL_DEVELOPMENT.md)
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

Pull Requests devem começar como draft. Os quality gates principais serão executados quando a PR estiver pronta para revisão, reduzindo consumo desnecessário de GitHub Actions durante o desenvolvimento.

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

1. configurar quality gates e CI econômico;
2. implementar configuração, segredos, migrações e fila persistida;
3. incorporar o shell Web/PWA e o design system;
4. implementar identidade, residência e núcleo financeiro.
