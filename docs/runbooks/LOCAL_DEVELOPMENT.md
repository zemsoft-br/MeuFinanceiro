# Ambiente local de desenvolvimento

## Objetivo

Inicializar a fundação do MeuFinanceiro por Docker Compose sem credenciais fixas e sem publicar o PostgreSQL no host.

## Requisitos

- Docker Engine ou Docker Desktop com Compose v2;
- ao menos 2 GB de memória disponível para os containers;
- portas locais configuráveis, com `8080` como padrão;
- Linux, macOS, WSL 2 ou Windows com PowerShell.

## Inicialização em Linux, macOS ou WSL

```bash
./infra/scripts/dev-up.sh
```

O script:

1. valida Docker e Compose;
2. cria `.env` com senha aleatória quando necessário;
3. constrói e inicia os serviços;
4. aguarda os health checks;
5. executa o smoke test Web + API + PostgreSQL.

## Inicialização em Windows PowerShell

```powershell
./infra/scripts/dev-up.ps1
```

## Endpoints

| Recurso | Endereço |
|---|---|
| Aplicação | `http://127.0.0.1:8080/` |
| Liveness da API | `http://127.0.0.1:8080/api/v1/health/live` |
| Readiness da API | `http://127.0.0.1:8080/api/v1/health/ready` |
| OpenAPI | `http://127.0.0.1:8080/api/v1/docs` |

Altere `APP_HTTP_PORT` em `.env` para usar outra porta.

## Serviços

| Serviço | Responsabilidade | Rede |
|---|---|---|
| `caddy` | entrada HTTP local e proxy reverso | edge |
| `web` | shell React + TypeScript provisório | edge |
| `api` | FastAPI e contrato OpenAPI | edge + backend |
| `worker` | processo inerte e health HTTP | backend |
| `postgres` | persistência local | backend interna |

O PostgreSQL não publica porta no host. Use `docker compose exec postgres psql` quando precisar de acesso administrativo local.

## Comandos operacionais

```bash
# Estado
docker compose ps

# Logs sanitizados
docker compose logs --tail=200

# Parar sem remover dados
./infra/scripts/dev-down.sh

# Parar e remover o volume local de banco — destrutivo
docker compose down --volumes

# Validar pré-requisitos
./infra/scripts/doctor.sh

# Executar novamente o smoke test
./tests/smoke/compose-smoke.sh
```

## Encerramento gracioso

`api`, `worker` e `web` usam processo init no Compose. Os serviços têm `stop_grace_period` explícito e tratam `SIGTERM` antes de receber encerramento forçado.

## Segurança da fundação

- `.env` não é versionado;
- o script gera senha aleatória local;
- PostgreSQL fica somente na rede interna;
- apenas Caddy publica porta, ligada a `127.0.0.1`;
- aplicações executam como usuários não-root;
- capabilities Linux são removidas dos serviços sem necessidade;
- `no-new-privileges` está habilitado;
- nenhuma integração externa ou telemetria é iniciada.

## Compatibilidade de arquitetura

As imagens escolhidas possuem distribuição oficial multi-plataforma para `amd64` e `arm64`. A primeira validação real em ambas as arquiteturas será registrada quando runners ou hosts das duas arquiteturas estiverem disponíveis.

## Interface do Google Stitch

O arquivo `apps/web/src/App.tsx` é deliberadamente provisório. A interface criada no Google Stitch deve substituir os componentes visuais sem alterar os endpoints de health nem incorporar regras financeiras no frontend.
