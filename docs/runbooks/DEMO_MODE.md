# Modo demonstração isolado

## Objetivo

O modo demonstração permite validar o MeuFinanceiro sem inserir dados reais, sem configurar integrações externas e sem reutilizar o banco, o volume, o `.env` ou o keyring do ambiente local comum.

Esta primeira versão implementa somente a fundação executável da fixture `residencia-ipe-v1`. Ela não cria residência, membros, contas, categorias ou movimentações. Cada módulo futuro expandirá a mesma fixture depois que seu domínio estiver aprovado.

## Contrato determinístico

| Campo | Valor |
|---|---|
| `fixture_id` | `residencia-ipe-v1` |
| `fixture_version` | `1` |
| `reference_date` | `2026-11-01` |
| `timezone` | `America/Sao_Paulo` |
| `currency` | `BRL` |
| `scope` | `foundation_only` |
| `contract_checksum` | `34a7628233ff6c4f5eac6469b8e80fdedd5d65d80f825b4ecf72a069235a21a1` |

O checksum representa os campos canônicos acima. Se os metadados persistidos divergirem, a carga e a leitura falham explicitamente em vez de corrigirem o registro silenciosamente.

## Isolamento

O ambiente demo usa:

- Compose project `meufinanceiro-demo`;
- banco `meufinanceiro_demo`;
- role administrativa `meufinanceiro_demo_admin`;
- role de runtime `meufinanceiro_demo_app`;
- porta HTTP `127.0.0.1:8081`;
- volume Docker próprio do projeto;
- `.demo/.env` exclusivo;
- `.demo/secrets/keyring.json` exclusivo;
- `APP_DEMO_MODE=true`.

O ambiente comum permanece com `APP_DEMO_MODE=false` e porta padrão `8080`.

## Operação no Linux/macOS/WSL

```bash
bash infra/scripts/demo-up.sh up
bash infra/scripts/demo-up.sh status
bash infra/scripts/demo-up.sh reset
bash infra/scripts/demo-up.sh load
bash infra/scripts/demo-up.sh down
bash infra/scripts/demo-up.sh purge
```

## Operação no Windows PowerShell

```powershell
& .\infra\scripts\demo-up.ps1 -Action up
& .\infra\scripts\demo-up.ps1 -Action status
& .\infra\scripts\demo-up.ps1 -Action reset
& .\infra\scripts\demo-up.ps1 -Action load
& .\infra\scripts\demo-up.ps1 -Action down
& .\infra\scripts\demo-up.ps1 -Action purge
```

`up` gera credenciais e keyring automaticamente, aplica as migrações, carrega a fixture e exige que a API confirme `enabled=true` e `loaded=true`.

`down` encerra os containers sem apagar o volume. `purge` remove containers, volume, `.demo/.env` e keyring. A remoção dos dados é, portanto, explícita.

## Comandos de fixture

A CLI operacional também pode ser executada diretamente no serviço isolado:

```bash
docker compose \
  --project-name meufinanceiro-demo \
  --env-file .demo/.env \
  --profile demo \
  run --rm demo-fixture \
  python -m meufinanceiro_persistence.demo_cli status
```

Comandos disponíveis:

- `load`: cria o registro canônico quando ausente e retorna o mesmo registro nas execuções seguintes;
- `status`: informa o contrato e o estado carregado;
- `reset`: remove somente o registro da fixture demo e pode ser repetido com segurança.

Todos os comandos recusam execução quando `APP_DEMO_MODE` não está habilitado.

## Endpoint somente leitura

```text
GET /api/v1/demo/status
```

O endpoint nunca aceita escrita e não retorna senha, URL de banco, keyring ou material criptográfico.

No ambiente comum:

```json
{
  "enabled": false,
  "loaded": false,
  "fixture_id": "residencia-ipe-v1",
  "fixture_version": 1,
  "reference_date": "2026-11-01",
  "timezone": "America/Sao_Paulo",
  "currency": "BRL",
  "scope": "foundation_only",
  "contract_checksum": "34a7628233ff6c4f5eac6469b8e80fdedd5d65d80f825b4ecf72a069235a21a1",
  "loaded_at": null
}
```

No ambiente demo carregado, `enabled` e `loaded` são `true`, e `loaded_at` contém o instante da primeira carga. Uma segunda carga preserva esse instante, comprovando idempotência.

## Persistência

A migração `0002_demo_fixture` cria somente `infra.demo_fixture`.

A tabela contém metadados da fixture e não antecipa entidades funcionais. O reset usa a chave estável `residencia-ipe-v1` e não apaga `infra.task_queue`, efeitos da fila ou dados futuros que não estejam explicitamente associados à fixture demo.

## Testes

A suíte cobre:

- status antes da carga;
- carga em banco vazio;
- segunda carga sem duplicidade;
- reset e segundo reset;
- recusa fora do modo demo;
- conflito entre metadados persistidos e contrato canônico;
- preservação da fila normal;
- downgrade simétrico;
- contrato OpenAPI somente leitura;
- ambiente comum com demo desabilitado;
- ambiente demo simultâneo ao ambiente comum;
- ciclo de reset e carga via Docker Compose.

## Regras para expansão

Ao implementar um novo módulo:

1. reutilizar `residencia-ipe-v1` e os identificadores estáveis do contrato;
2. derivar datas de `2026-11-01`, nunca de `now()` direto;
3. adicionar dados somente depois do schema e das regras do módulo serem aprovados;
4. manter carga e reset idempotentes e limitados aos dados marcados como demo;
5. não usar dumps reais, dados anonimizados ou marcas sem licença;
6. atualizar o checksum apenas por mudança versionada do contrato;
7. adicionar testes de isolamento, autorização e invariantes do módulo.

## Segurança

- nunca copiar `.env`, keyring ou volume do ambiente comum;
- nunca inserir credenciais Pluggy ou de outra integração;
- nunca utilizar dados do mantenedor, familiares, clientes ou instituições reais;
- nunca habilitar o modo demo em HML ou produção por inferência deste runbook;
- nenhum deploy é autorizado por esta funcionalidade.
