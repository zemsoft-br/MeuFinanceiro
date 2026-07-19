# Quality gates e CI econômica

## Objetivo

Manter a mesma suíte obrigatória disponível localmente e no GitHub Actions sem consumir minutos a cada push intermediário de uma Pull Request draft.

## Política de execução

Os workflows principais escutam eventos de Pull Request, mas os jobs somente executam quando a PR não está em draft. O fluxo esperado é:

1. abrir a PR como draft;
2. desenvolver e fazer pushes sem executar automaticamente a suíte principal;
3. executar os gates localmente;
4. marcar a PR como pronta para revisão;
5. o GitHub Actions executar `Quality` e, quando aplicável, `Container Quality`;
6. novos pushes em PR pronta iniciarem nova execução e cancelarem a anterior do mesmo workflow.

Ambos os workflows também expõem `workflow_dispatch` para diagnóstico ou validação manual.

## Gates obrigatórios

### Quality

Executa:

- DCO para todos os commits da PR;
- detecção de nomes de arquivos sensíveis, arquivos financeiros reais e padrões óbvios de segredo;
- Ruff lint e formatação do Python;
- mypy em modo estrito para API e Worker;
- testes da API e dos validadores de qualidade;
- inventário e política preliminar de licenças Python;
- `pip-audit`;
- instalação reprodutível do frontend por `npm ci`;
- ESLint;
- TypeScript;
- testes frontend;
- build Vite;
- `npm audit` com bloqueio em severidade alta ou crítica;
- inventário e política preliminar de licenças Node.

### Container Quality

Executa somente quando arquivos de containers, Compose, dependências ou smoke tests são alterados:

- validação do contrato Compose;
- build das imagens com atualização das bases;
- inicialização com espera por health checks;
- smoke test Web → Caddy → API → PostgreSQL;
- restart completo e novo smoke test;
- captura de estado e logs em falha;
- encerramento gracioso com remoção do ambiente descartável.

O PostgreSQL utilizado é descartável e não possui dados reais.

## Execução local

Pré-requisitos:

- Python 3.13;
- Node.js 24;
- npm;
- Git;
- Docker Compose somente para o gate de containers.

Suíte principal:

```bash
python infra/scripts/run-quality.py
```

Para recriar o ambiente virtual dos gates:

```bash
python infra/scripts/run-quality.py --recreate
```

Gate de containers:

```bash
cp .env.example .env
# Substitua POSTGRES_PASSWORD por valor local aleatório.
docker compose config --quiet
docker compose build --pull
docker compose up --detach --wait --wait-timeout 180
bash tests/smoke/compose-smoke.sh
docker compose restart
docker compose up --detach --wait --wait-timeout 120
bash tests/smoke/compose-smoke.sh
docker compose down --volumes --remove-orphans --timeout 30
```

No Windows, o gate de aplicação pode ser executado pelo mesmo script Python. O smoke test pode ser executado por WSL ou por ambiente Unix equivalente enquanto não houver uma versão PowerShell específica.

## Lockfile frontend

`apps/web/package-lock.json` é obrigatório para `npm ci`, cache e auditoria reprodutíveis.

Durante a implantação inicial, caso o lockfile ainda não exista, o workflow `Quality`:

1. gera o arquivo com scripts de instalação desativados;
2. publica o artefato `web-package-lock` com retenção de um dia;
3. falha deliberadamente;
4. exige que o arquivo revisado seja incorporado ao repositório.

Mudanças futuras em `package.json` devem atualizar e revisar o lockfile no mesmo Pull Request.

## Política de dependências

- versões diretas permanecem fixadas;
- lockfiles são obrigatórios quando suportados pelo ecossistema;
- atualizações devem ocorrer em PR própria ou em mudança que justifique explicitamente o acoplamento;
- `docs/DEPENDENCIES.md` deve ser atualizado quando uma dependência direta for adicionada, removida ou alterada;
- auditorias de segurança não autorizam atualização automática sem revisão;
- licenças ausentes, personalizadas, source-available ou incompatíveis bloqueiam o merge até análise;
- artefatos, fontes, imagens, modelos e dados externos também exigem procedência e licença.

O Dependabot propõe atualizações semanalmente, mas não realiza merge automático.

## Diagnóstico de falhas

Os comandos executados são exibidos no log. O workflow não imprime `.env`, senhas ou payloads financeiros.

No gate de containers, uma falha captura:

```bash
docker compose ps --all
docker compose logs --no-color --tail 200
```

Esses logs devem continuar sanitizados. Não adicione dados reais a testes ou mensagens de erro.

## Provas de bloqueio

`tests/quality/test_quality_scripts.py` cria repositórios temporários e comprova que:

- um commit com DCO é aceito;
- um commit sem `Signed-off-by` é rejeitado;
- um arquivo `.pem` rastreado é rejeitado.

Falhas intencionais permanecem confinadas aos diretórios temporários dos testes e nunca são commitadas no repositório real.

## Checks esperados para rulesets

Após estabilização, os rulesets de `develop` e `main` devem exigir:

- `Mandatory quality gates`;
- `Docker Compose integration` apenas quando o workflow for aplicável.

A obrigatoriedade deve ser configurada somente depois que os nomes e triggers forem confirmados em uma PR real para evitar bloqueio administrativo do repositório.
