# Ambiente local de desenvolvimento

## Objetivo

Inicializar a fundação do MeuFinanceiro por Docker Compose sem credenciais fixas, sem publicar o PostgreSQL no host, com keyring exclusivo por instalação, migrações reproduzíveis, role de runtime sem privilégios administrativos e cliente Flutter Web/PWA servido localmente.

## Requisitos

- Docker Engine ou Docker Desktop com Compose v2;
- ao menos 2 GB de memória disponível para os containers;
- portas locais configuráveis, com `8080` como padrão;
- Linux, macOS, WSL 2 ou Windows com PowerShell;
- Python 3 para o script Unix de geração e validação do keyring.

O host não precisa ter Flutter instalado para iniciar a stack. O SDK fixado é usado dentro do estágio de build Docker do serviço `web`.

## Inicialização em Linux, macOS ou WSL

```bash
./infra/scripts/dev-up.sh
```

O script:

1. valida Docker, Compose e Python;
2. cria `.env` com senhas administrativas e de runtime independentes;
3. cria e valida `.secrets/keyring.json` sem imprimir o material;
4. constrói os serviços, incluindo o build Flutter Web pinado;
5. aguarda PostgreSQL, bootstrap da role e migração Alembic;
6. inicia API, Worker, Web e Caddy;
7. executa smoke de Flutter Web, PWA, health, idempotência e processamento da fila.

## Inicialização em Windows PowerShell

```powershell
./infra/scripts/dev-up.ps1
```

O PowerShell gera as duas senhas e o keyring com o gerador criptográfico do .NET, tenta restringir as ACLs de `.env` e `.secrets` e comprova que a página servida contém o bootstrap Flutter.

## Endpoints

| Recurso | Endereço |
|---|---|
| Aplicação | `http://127.0.0.1:8080/` |
| Componentes | `http://127.0.0.1:8080/componentes` |
| Sistema | `http://127.0.0.1:8080/sistema` |
| Manifesto PWA | `http://127.0.0.1:8080/manifest.json` |
| Service worker | `http://127.0.0.1:8080/sw.js` |
| Liveness da API | `http://127.0.0.1:8080/api/v1/health/live` |
| Readiness da API | `http://127.0.0.1:8080/api/v1/health/ready` |
| OpenAPI | `http://127.0.0.1:8080/api/v1/docs` |

Altere `APP_HTTP_PORT` em `.env` para usar outra porta. O health do Worker permanece somente na rede `backend`.

## Serviços

| Serviço | Responsabilidade | Rede |
|---|---|---|
| `caddy` | entrada HTTP local e proxy reverso para `/api/` | edge |
| `web` | build Flutter Web estático servido por Caddy não-root | edge |
| `api` | FastAPI, OpenAPI, criptografia e persistência | edge + backend |
| `worker` | consumidor da fila persistente | backend |
| `db-bootstrap` | reconciliação one-shot da role de runtime | backend |
| `migrate` | aplicação one-shot das migrações Alembic | backend |
| `postgres` | fonte local de verdade e fila | backend interna |

`db-bootstrap` e `migrate` encerram com código zero após concluir. O PostgreSQL não publica porta no host. Use `docker compose exec postgres psql` quando precisar de acesso administrativo local.

O frontend não possui seleção de runtime. `apps/app` é a única fonte do cliente e `infra/web/Dockerfile` sempre produz o artefato Flutter Web servido pelo serviço `web`.

## Comandos operacionais

```bash
# Estado, incluindo serviços one-shot
docker compose ps --all

# Logs sanitizados
docker compose logs --tail=200

# Reconstruir apenas o Flutter Web
docker compose build web
docker compose up --detach --wait web caddy

# Aplicar migrações pendentes
docker compose run --rm migrate

# Validar o keyring sem mostrar material
python3 infra/scripts/manage-secrets.py validate

# Rotacionar após backup validado
python3 infra/scripts/manage-secrets.py rotate

# Parar sem remover dados
./infra/scripts/dev-down.sh

# Parar e remover o volume local de banco — destrutivo
docker compose down --volumes

# Validar pré-requisitos
./infra/scripts/doctor.sh

# Executar novamente o smoke test
./tests/smoke/compose-smoke.sh
```

Consulte [Persistência, migrações e fila](PERSISTENCE_AND_TASK_QUEUE.md) para leases, retry e diagnóstico. Consulte [Gerenciamento do keyring](KEY_MANAGEMENT.md) antes de rotacionar ou restaurar.

## Encerramento gracioso

`api`, `worker` e `web` usam processo init no Compose. Os serviços têm `stop_grace_period` explícito. O runtime Web recebe `SIGTERM` por meio do init, e o Caddy encerra os listeners sem executar como root. O Worker deixa de reservar novas tarefas ao receber `SIGTERM`, conclui o handler em andamento dentro do período de graça e fecha o health server e o pool. Se houver interrupção forçada, o lease expirado permite recuperação posterior.

## Segurança da fundação

- `.env` e `.secrets` não são versionados;
- cada instalação gera duas senhas e uma chave mestra exclusivas;
- API e Worker usam role sem `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION` ou `BYPASSRLS`;
- a credencial administrativa fica limitada ao PostgreSQL, bootstrap e migração;
- o keyring fica fora do PostgreSQL e é montado read-only somente em API e Worker;
- configuração ausente, keyring inválido, banco indisponível ou schema desatualizado impedem readiness;
- PostgreSQL fica somente na rede interna;
- apenas Caddy publica porta, ligada a `127.0.0.1`;
- aplicações executam como usuários não-root;
- capabilities Linux são removidas dos serviços sem necessidade;
- `no-new-privileges` está habilitado;
- o build Flutter não depende de CDN no runtime;
- o service worker ignora integralmente `/api/` e não armazena dados financeiros;
- nenhuma integração externa ou telemetria é iniciada.

## Compatibilidade de arquitetura

As imagens escolhidas possuem distribuição oficial multi-plataforma para `amd64` e `arm64`. A primeira validação real em ambas as arquiteturas será registrada quando runners ou hosts das duas arquiteturas estiverem disponíveis.

## Interface do Google Stitch

As referências do Google Stitch orientam a identidade visual, mas não participam do runtime. O cliente Flutter não carrega HTML, Tailwind, Google Fonts ou scripts remotos dos protótipos.
