# Quality gates e CI econômica

## Objetivo

Manter a mesma suíte obrigatória disponível localmente e no GitHub Actions sem consumir minutos a cada push intermediário de uma Pull Request draft.

## Política de execução

Os workflows principais escutam eventos de Pull Request, mas os jobs somente executam quando a PR não está em draft. O fluxo esperado é:

1. abrir a PR como draft;
2. desenvolver e fazer pushes sem executar automaticamente a suíte principal;
3. executar os gates locais possíveis;
4. marcar a PR como pronta para revisão;
5. o GitHub Actions executar `Quality` e, quando aplicável, `Container Quality`;
6. novos pushes em PR pronta iniciarem nova execução e cancelarem a anterior do mesmo workflow.

Ambos os workflows também expõem `workflow_dispatch` para diagnóstico ou validação manual. Quando o GitHub Actions estiver indisponível por cota ou incidente externo, a PR permanece bloqueada para merge até que a suíte equivalente seja executada localmente e os resultados sejam registrados.

## Gates obrigatórios

### Quality

Executa:

- DCO para todos os commits da PR;
- detecção de nomes de arquivos sensíveis, arquivos financeiros reais e padrões óbvios de segredo;
- Ruff lint e formatação do Python;
- mypy em modo estrito para API e Worker;
- testes da API, Worker, persistência, segurança e validadores de qualidade;
- inventário e política de licenças Python;
- `pip-audit`;
- instalação reprodutível do rollback React por `npm ci`;
- ESLint, TypeScript, testes e build Vite enquanto React permanecer versionado;
- `npm audit` com bloqueio em severidade alta ou crítica;
- inventário e política de licenças Node;
- validação da versão e revisão Flutter fixadas;
- resolução Flutter com `pubspec.lock` obrigatório e `--enforce-lockfile`;
- verificação de formatação Dart;
- `flutter analyze`;
- testes Flutter;
- build Web Flutter release com `--no-web-resources-cdn` e `--pwa-strategy=none`;
- finalização estrita do artefato, removendo apenas o worker legado vazio;
- validação do manifesto, index, service worker, ícones, CanvasKit local e ausência de worker legado no artefato gerado.

React e Flutter permanecem nos gates durante a Fase C. A remoção dos gates Node ocorrerá somente na Fase D, junto da remoção validada do frontend antigo e do target de rollback.

### Container Quality

Executa quando arquivos de containers, Compose, runtime Flutter/React, PWA ou smoke tests são alterados:

- validação do contrato Compose;
- build das imagens com atualização das bases;
- build do target Flutter padrão;
- extração de `/srv` da imagem Flutter e validação do artefato realmente servido;
- build separado do target `react-runtime` para comprovar o rollback;
- inicialização com espera por health checks;
- smoke Web → Caddy → API → PostgreSQL;
- validação das rotas Flutter e do manifesto;
- validação textual da exclusão de `/api/` no service worker;
- validação dos headers de cache;
- `404` para asset inexistente;
- execução não-root do serviço Web;
- restart completo e novo smoke test;
- captura de estado e logs em falha;
- encerramento gracioso com remoção do ambiente descartável.

O PostgreSQL utilizado é descartável e não possui dados reais.

## Execução local

Pré-requisitos da suíte completa:

- Python 3.13;
- Node.js 24 e npm enquanto React permanecer;
- Flutter na versão e revisão exatas do repositório;
- Dart fornecido por essa instalação Flutter;
- Git;
- Docker Compose somente para o gate de containers.

Valide a toolchain Flutter isoladamente:

```bash
python infra/scripts/check-flutter-toolchain.py
```

Valide apenas o contrato PWA versionado, sem build:

```bash
python infra/scripts/check-flutter-web-contract.py --source-only
```

Suíte principal:

```bash
python infra/scripts/run-quality.py
```

Para recriar o ambiente virtual dos gates:

```bash
python infra/scripts/run-quality.py --recreate
```

O script executa Python, React transitório e Flutter nessa ordem. O build Flutter é seguido pela finalização e pela validação de `apps/app/build/web`.

Gate de containers:

```bash
cp .env.example .env
# Substitua as senhas por valores locais aleatórios.
docker compose config --quiet
docker compose build --pull

docker compose up --detach --wait --wait-timeout 180
bash tests/smoke/compose-smoke.sh

docker compose restart
docker compose up --detach --wait --wait-timeout 120
bash tests/smoke/compose-smoke.sh

docker compose down --volumes --remove-orphans --timeout 40
```

No Windows, o gate de aplicação pode ser executado pelo mesmo script Python. O smoke Bash pode ser executado por WSL ou por ambiente Unix equivalente. `dev-up.ps1` mantém um smoke básico nativo que exige o bootstrap Flutter.

## Build Flutter Web

O pipeline canônico é:

```bash
cd apps/app
flutter build web --release --no-web-resources-cdn --pwa-strategy=none
python ../../infra/scripts/finalize-flutter-web-build.py --build-dir build/web
cd ../..
python infra/scripts/check-flutter-web-contract.py
```

`--no-web-resources-cdn` obriga o empacotamento local do CanvasKit/WASM. `--pwa-strategy=none` desativa a política automática do SDK porque o projeto mantém `apps/app/web/sw.js` explicitamente.

Algumas versões do SDK ainda produzem um `flutter_service_worker.js` vazio mesmo com a estratégia desativada. O finalizador remove somente esse arquivo vazio; qualquer conteúdo não vazio bloqueia o build. O validator exige `"useLocalCanvasKit": true`, os arquivos locais do engine e a ausência do worker legado no artefato final.

O build Docker usa o mesmo pipeline e valida a revisão exata do SDK antes da compilação.

## Lockfiles dos clientes

São obrigatórios:

- `apps/web/package-lock.json` para o rollback React transitório;
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

1. lê `.flutter-version` e `.flutter-revision`;
2. restaura um cache separado por sistema, arquitetura e identidade do SDK;
3. quando necessário, clona a tag correspondente do repositório oficial Flutter;
4. compara o commit clonado com a revisão fixada;
5. adiciona o SDK ao `PATH`;
6. desativa analytics no SDK do runner;
7. prepara somente os artefatos Web necessários;
8. executa os gates do cliente e do artefato PWA.

A versão não é escolhida por action de terceiros nem por canal móvel. Atualizações exigem PR explícita, revisão do changelog, novo lockfile quando aplicável e execução completa dos gates.

## Contrato do service worker

`tests/quality/test_flutter_web_contract.py` executa o validator sobre os arquivos versionados. Depois do build, o mesmo validator examina o artefato.

São bloqueados:

- ausência de exclusão explícita de `/api/`;
- interceptação antes da verificação de API;
- ausência de filtro por método ou origem;
- armazenamento de respostas não bem-sucedidas ou não `basic`;
- ausência de limpeza dos caches antigos Flutter e React;
- ausência de `skipWaiting` ou `clients.claim`;
- espera indefinida pelo primeiro controle do worker;
- `flutter_service_worker.js` legado;
- divergência entre `web/sw.js` e o `sw.js` gerado;
- manifesto ou ícones incompletos;
- CanvasKit remoto ou arquivos locais do engine ausentes;
- origins remotas conhecidas em arquivos controlados pelo projeto.

## Política de dependências

- versões diretas permanecem fixadas;
- lockfiles são obrigatórios quando suportados;
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
- compilação Web;
- finalização do artefato;
- contrato do artefato Web/PWA;
- build da imagem;
- Caddy e headers;
- smoke ou restart.

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
- divergência de versão bloqueia o gate;
- o contrato source do Flutter Web/PWA é válido;
- o finalizador remove apenas worker legado vazio;
- configuração remota do engine é rejeitada.

Falhas intencionais permanecem confinadas aos diretórios temporários dos testes e nunca são commitadas no repositório real.

## Checks esperados para rulesets

Após estabilização, os rulesets de `develop` e `main` devem exigir:

- `Mandatory quality gates`;
- `Docker Compose integration` quando o workflow for aplicável.

A obrigatoriedade deve ser configurada somente depois que os nomes e triggers forem confirmados em PR real para evitar bloqueio administrativo do repositório.
