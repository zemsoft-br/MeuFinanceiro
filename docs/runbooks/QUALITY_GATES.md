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
- testes da API, Worker, persistência, segurança e validadores de qualidade;
- inventário e política preliminar de licenças Python;
- `pip-audit`;
- instalação reprodutível do shell React transitório por `npm ci`;
- ESLint, TypeScript, testes e build Vite;
- `npm audit` com bloqueio em severidade alta ou crítica;
- inventário e política preliminar de licenças Node;
- validação da versão Flutter fixada em `.flutter-version`;
- resolução Flutter com `pubspec.lock` obrigatório e `--enforce-lockfile`;
- verificação de formatação Dart;
- `flutter analyze`;
- testes Flutter;
- build Web Flutter em modo release.

React e Flutter permanecem nos gates enquanto o shell React for o runtime ativo. A remoção dos gates Node ocorrerá somente junto da remoção validada do frontend antigo.

### Container Quality

Executa somente quando arquivos de containers, Compose, dependências do runtime ou smoke tests são alterados:

- validação do contrato Compose;
- build das imagens com atualização das bases;
- inicialização com espera por health checks;
- smoke test Web → Caddy → API → PostgreSQL;
- restart completo e novo smoke test;
- captura de estado e logs em falha;
- encerramento gracioso com remoção do ambiente descartável.

O scaffold Flutter ainda não é servido pelo Compose. Alterar apenas `apps/app` e os gates Flutter não comprova runtime de container e não substitui a futura PR de Docker/PWA.

O PostgreSQL utilizado é descartável e não possui dados reais.

## Execução local

Pré-requisitos:

- Python 3.13;
- Node.js 24 e npm, enquanto React permanecer;
- Flutter na versão exata de `.flutter-version`;
- Dart fornecido por essa instalação Flutter;
- Git;
- Docker Compose somente para o gate de containers.

Valide a toolchain Flutter isoladamente:

```bash
python infra/scripts/check-flutter-toolchain.py
```

Suíte principal:

```bash
python infra/scripts/run-quality.py
```

Para recriar o ambiente virtual dos gates:

```bash
python infra/scripts/run-quality.py --recreate
```

O script executa Python, React transitório e Flutter nessa ordem. Quando Flutter não estiver no `PATH`, estiver em versão diferente ou o lockfile não existir, a execução falha com uma mensagem explícita antes dos comandos do cliente.

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

## Lockfiles dos clientes

São obrigatórios:

- `apps/web/package-lock.json` para o shell React transitório;
- `apps/app/pubspec.lock` para o cliente Flutter.

O workflow não gera lockfile ausente. A ausência falha deliberadamente e exige geração e revisão no mesmo Pull Request que altera o manifesto.

Para Flutter:

```bash
cd apps/app
flutter pub get
flutter pub get --enforce-lockfile
```

O primeiro comando atualiza o lockfile de forma consciente. O segundo comprova que a resolução é reproduzível sem modificá-lo.

## Instalação Flutter no GitHub Actions

O workflow:

1. lê `.flutter-version`;
2. restaura um cache separado por sistema, arquitetura e versão;
3. quando necessário, clona a tag correspondente do repositório oficial Flutter;
4. adiciona o SDK ao `PATH`;
5. desativa analytics no SDK do runner;
6. prepara somente os artefatos Web necessários;
7. executa `check-flutter-toolchain.py` antes dos gates do cliente.

A versão não é escolhida por um action de terceiros nem por canal móvel. Atualizações exigem PR explícita, revisão do changelog, novo lockfile e execução completa dos gates.

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

Falhas Flutter devem ser classificadas por etapa:

- instalação ou divergência da toolchain;
- lockfile;
- formatação;
- análise estática;
- teste;
- compilação Web.

No gate de containers, uma falha captura:

```bash
docker compose ps --all
docker compose logs --no-color --tail 200
```

Esses logs devem continuar sanitizados. Não adicione dados reais a testes ou mensagens de erro.

## Provas de bloqueio

`tests/quality/` comprova, entre outros contratos:

- um commit com DCO é aceito;
- um commit sem `Signed-off-by` é rejeitado;
- um arquivo `.pem` rastreado é rejeitado;
- versão Flutter válida é lida;
- saída de máquina do Flutter é validada;
- ausência de Flutter produz mensagem acionável;
- divergência de versão bloqueia o gate.

Falhas intencionais permanecem confinadas aos diretórios temporários dos testes e nunca são commitadas no repositório real.

## Checks esperados para rulesets

Após estabilização, os rulesets de `develop` e `main` devem exigir:

- `Mandatory quality gates`;
- `Docker Compose integration` apenas quando o workflow for aplicável.

A obrigatoriedade deve ser configurada somente depois que os nomes e triggers forem confirmados em uma PR real para evitar bloqueio administrativo do repositório.
