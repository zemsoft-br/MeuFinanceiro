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

## Arquitetura planejada

```text
React + TypeScript + PWA
          |
        Caddy
          |
        FastAPI
          |
     PostgreSQL + Worker
```

A distribuição principal será Docker Compose, com imagens `amd64` e `arm64`. Um instalador/gerenciador local será avaliado para reduzir a complexidade para usuários não técnicos.

## Documentação

- [Especificação do produto](docs/PRODUCT_SPECIFICATION.md)
- [Arquitetura inicial](docs/ARCHITECTURE.md)
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

Consulte [CONTRIBUTING.md](CONTRIBUTING.md) e a [governança](docs/GOVERNANCE.md) antes de assumir uma issue.

## Licença

A licença ainda está em decisão. A proposta atual é `AGPL-3.0-only`, documentada no [ADR-0004](docs/adr/0004-project-license-and-trademark.md). Nenhuma licença foi aplicada até a decisão ser formalmente aceita.

## Próximos marcos

1. estabilizar documentação, governança e contratos;
2. criar monorepo, ambiente Docker e quality gates;
3. implementar identidade, residência e núcleo financeiro;
4. abrir progressivamente issues independentes para colaboração comunitária.
