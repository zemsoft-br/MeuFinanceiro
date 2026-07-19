# Dependências diretas da fundação

## Objetivo

Registrar as versões efetivamente escolhidas e suas licenças declaradas. Este inventário não substitui o SBOM, os notices nem a análise de dependências transitivas exigidos antes da primeira distribuição pública.

## Imagens e runtimes

| Componente | Versão fixada | Uso | Licença principal declarada |
|---|---:|---|---|
| Python | 3.13.14 | API, worker e gates locais | PSF-2.0 |
| Node.js | 24.18.0 LTS | build, testes e servidor de desenvolvimento Web | MIT |
| PostgreSQL | 18.4 | persistência local | PostgreSQL License |
| Caddy | 2.11.3 | proxy HTTP local | Apache-2.0 |

As imagens `python:*‑slim`, `node:*‑alpine`, `postgres:*‑alpine` e `caddy:*‑alpine` incluem pacotes do sistema sob licenças variadas. O inventário transitivo e os notices das imagens serão gerados e revisados antes da primeira release distribuível.

## Dependências Python da aplicação

| Pacote | Versão | Uso | Licença declarada |
|---|---:|---|---|
| FastAPI | 0.139.2 | API HTTP e OpenAPI | MIT |
| Pydantic Settings | 2.14.2 | configuração por ambiente | MIT |
| psycopg | 3.3.4 | driver PostgreSQL | LGPL-3.0-only |
| SQLAlchemy | 2.0.51 | acesso à persistência da API | MIT |
| Uvicorn | 0.51.0 | servidor ASGI | BSD-3-Clause |
| httpx | 0.28.1 | testes da API | BSD-3-Clause |
| pytest | 9.1.1 | testes Python | MIT |
| setuptools | 80.9.0 | build dos pacotes locais | MIT |

## Ferramentas Python de qualidade

| Pacote | Versão | Uso | Licença declarada |
|---|---:|---|---|
| Ruff | 0.15.22 | lint e formatação | MIT |
| mypy | 2.3.0 | análise estática | MIT |
| pip-audit | 2.10.1 | auditoria de vulnerabilidades Python | Apache-2.0 |

Essas ferramentas são instaladas em `.quality-venv` pelo script local e não fazem parte das imagens de execução da aplicação.

## Dependências Web

| Pacote | Versão | Uso | Licença declarada |
|---|---:|---|---|
| React | 19.2.7 | interface | MIT |
| React DOM | 19.2.7 | renderização Web | MIT |
| Vite | 8.1.5 | desenvolvimento e build | MIT |
| TypeScript | 7.0.2 | tipagem e compilação | Apache-2.0 |
| `@vitejs/plugin-react` | 6.0.3 | integração React/Vite | MIT |
| `@types/react` | 19.2.17 | tipos de desenvolvimento | MIT |
| `@types/react-dom` | 19.2.3 | tipos de desenvolvimento | MIT |
| `@types/node` | 24.13.3 | tipos para testes Node | MIT |
| ESLint | 10.7.0 | lint do frontend | MIT |
| `@eslint/js` | 10.0.1 | regras JavaScript recomendadas | MIT |
| typescript-eslint | 8.64.0 | integração TypeScript/ESLint | MIT |
| eslint-plugin-react-hooks | 7.1.1 | regras de Hooks | MIT |
| eslint-plugin-react-refresh | 0.5.3 | segurança de Fast Refresh | MIT |
| globals | 17.7.0 | ambientes globais ESLint | MIT |

## Avaliação

Não foi identificada incompatibilidade direta que impeça a combinação com `AGPL-3.0-only`. A LGPL do psycopg permite uso e distribuição nas condições da própria licença; seus avisos e código-fonte correspondente devem ser tratados no inventário de terceiros aplicável.

Os gates geram inventários preliminares das dependências instaladas e bloqueiam famílias conhecidas que exigem revisão específica. Esse controle não substitui revisão jurídica nem um SBOM da release.

## Atualização

Toda alteração de versão ou inclusão de dependência deve atualizar este arquivo e registrar:

- finalidade;
- licença;
- impacto transitivo;
- riscos de segurança e manutenção;
- alternativa sem a dependência.

Versões diretas permanecem fixadas. O `package-lock.json` deve ser atualizado no mesmo Pull Request que altera `package.json`. Dependabot pode propor atualizações, mas merge automático não é permitido.
