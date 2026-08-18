# Modo demonstração isolado

## Objetivo

O modo demonstração permite validar o MeuFinanceiro com dados totalmente sintéticos, sem configurar integrações externas e sem reutilizar banco, volume, `.env` ou keyring do ambiente local comum.

A fixture `residencia-ipe-v1` está na versão 2 e cobre a fundação financeira da Fase 1: identidade/residência, contas, categorias, saldo de abertura e Movements append-only.

## Contrato determinístico

| Campo | Valor |
|---|---|
| `fixture_id` | `residencia-ipe-v1` |
| `fixture_version` | `2` |
| `reference_date` | `2026-11-01` |
| `timezone` | `America/Sao_Paulo` |
| `currency` | `BRL` |
| `scope` | `finance_phase1` |
| `contract_checksum` | `a819b4913e35cabff3f20617b3e7837a6042b0c9243031a65b3f53fa7086d091` |

A versão 1 (`foundation_only`) não é atualizada silenciosamente. Se um volume antigo contiver metadados incompatíveis, faça `purge` no ambiente demo isolado e recrie a fixture.

## Conteúdo sintético v2

A carga usa IDs UUIDv4 estáveis e datas derivadas da referência de 1º de novembro de 2026.

Identidade:

- operador com login `demo`;
- residência `Residência Ipê`;
- membership ativa e primária do operador.

Contas:

- `Conta Corrente Ipê`: CHECKING, PERSONAL, BRL;
- `Carteira da Casa`: CASH, HOUSEHOLD, BRL.

Categorias:

- `Moradia`;
- `Alimentação`.

Saldo de abertura:

- `Conta Corrente Ipê`: R$ 2.500,00 em 31/10/2026;
- `Carteira da Casa`: **sem registro de saldo de abertura**, para preservar a diferença entre “não informado” e zero explícito.

Movements da conta corrente:

- +R$ 4.500,00 — receita demonstrativa;
- -R$ 1.600,00 — despesa demonstrativa;
- -R$ 420,75 — despesa demonstrativa;
- -R$ 90,00 — despesa demonstrativa a estornar;
- +R$ 90,00 — REVERSAL integral do Movement anterior.

O efeito líquido dos Movements é R$ 2.479,25. Com o saldo de abertura, o saldo derivável da conta é R$ 4.979,25. **Nenhum campo de saldo corrente é persistido.**

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
- `.demo/secrets/operator_password.txt` exclusivo;
- `APP_DEMO_MODE=true`.

A carga e o status usam a role de runtime e respeitam RLS/guards normais. O reset funcional usa a conexão administrativa **somente no serviço isolado `demo-fixture`**, porque o ledger não concede DELETE à runtime.

Nenhum grant de UPDATE/DELETE é adicionado a `finance.movements` para atender o modo demo.

## Credencial do operador demo

O login é fixo:

```text
demo
```

A senha não é fixa nem versionada no repositório. Ela é **gerada automaticamente** na primeira preparação do ambiente demo usando CSPRNG e armazenada apenas em:

```text
.demo/secrets/operator_password.txt
```

O arquivo recebe permissões privadas equivalentes aos demais secrets locais. O Compose o monta em `demo-fixture` como **Docker secret** somente leitura em:

```text
/run/secrets/demo_operator_password
```

Você **não precisa definir `DEMO_OPERATOR_PASSWORD`** para usar `demo-up.sh` ou `demo-up.ps1`. A variável continua aceita internamente pelo CLI somente como compatibilidade para testes e tooling legado; arquivo e variável ao mesmo tempo são rejeitados para evitar fonte ambígua.

A mesma senha é reutilizada enquanto o diretório `.demo` existir. O comando `purge` remove o arquivo junto com todo o estado demo; uma preparação futura gera outra credencial.

Se existir um **ambiente demo antigo** cuja `.demo/.env` ainda contenha `DEMO_OPERATOR_PASSWORD=<valor>`, os scripts preservam essa credencial no primeiro uso do fluxo novo: movem o valor para `.demo/secrets/operator_password.txt`, aplicam as permissões privadas e **remove a linha `DEMO_OPERATOR_PASSWORD=`** do `.env`. Isso evita invalidar o hash Argon2id já materializado no banco e elimina o segredo legado do arquivo de configuração.

Na primeira carga, a senha é armazenada no banco apenas como hash Argon2id. Cargas seguintes verificam a mesma credencial sem reescrever o operador.

Após `up`, o script mostra localmente no terminal:

```text
Login demo: demo
Senha demo: <senha-gerada-localmente>
```

A senha não é enviada à API, não é persistida em logs do serviço e não é adicionada ao `.demo/.env`.

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

`up` gera as credenciais do banco demo, o keyring local e a credencial privada do operador demo quando ainda não existirem; aplica as migrações, carrega a fixture e exige que a API confirme `enabled=true` e `loaded=true`.

`down` encerra os containers sem apagar o volume. `purge` remove containers, volume, `.demo/.env`, keyring e `.demo/secrets/operator_password.txt`. A remoção dos dados e da credencial é explícita.

## Lifecycle da fixture

### `load`

Em uma transação:

1. valida metadata v2;
2. materializa/verifica instalação, operador, residência e membership;
3. define contexto financeiro de instalação/residência/operador;
4. materializa/verifica categorias e contas;
5. materializa/verifica o opening balance;
6. materializa/verifica Movements STANDARD;
7. materializa/verifica a REVERSAL.

As inserções funcionais usam `ON CONFLICT DO NOTHING` seguido de verificação exata. Divergência falha explicitamente; nenhum registro append-only é atualizado.

Uma segunda carga preserva `loaded_at` e não duplica dados.

### `status`

`loaded=true` só é retornado quando metadata **e todo o conjunto funcional esperado** estão consistentes. Metadata isolada não é suficiente.

Telemetria normal de autenticação do operador, como último login e tentativas, não faz parte da igualdade estável da fixture.

### `reset`

O reset remove o escopo da instalação demo em ordem de dependência, incluindo sessões e Movements criados durante a própria demonstração. Dados de outra instalação e `infra.task_queue` são preservados.

O reset pode ser repetido com segurança.

## Endpoint somente leitura

```text
GET /api/v1/demo/status
```

O endpoint não aceita mutações e retorna apenas metadata operacional da fixture.

No ambiente comum:

```json
{
  "enabled": false,
  "loaded": false,
  "fixture_id": "residencia-ipe-v1",
  "fixture_version": 2,
  "reference_date": "2026-11-01",
  "timezone": "America/Sao_Paulo",
  "currency": "BRL",
  "scope": "finance_phase1",
  "contract_checksum": "a819b4913e35cabff3f20617b3e7837a6042b0c9243031a65b3f53fa7086d091",
  "loaded_at": null
}
```

## Integrações externas

A fixture v2 não chama nem popula Pluggy ou qualquer provider externo. Não há importação, sincronização, webhook ou iniciação de pagamento.

## Testes esperados

A suíte da #175 e os contratos de qualidade do modo demo devem validar:

- metadata v2/checksum;
- carga em banco vazio;
- segunda carga idempotente e `loaded_at` preservado;
- IDs estáveis;
- identidade/residência completas;
- hash de autenticação válido;
- duas contas, categorias, opening balance e cinco Movements exatos;
- STANDARD + REVERSAL como eventos separados;
- saldo derivável de R$ 4.979,25 sem coluna de saldo;
- conta cash sem opening balance;
- tolerância à telemetria mutável de autenticação;
- conflito em drift funcional;
- reset administrativo limitado à instalação demo;
- segundo reset idempotente;
- preservação da fila normal;
- contrato HTTP v2 somente leitura;
- scripts Linux/PowerShell gerando e reutilizando credencial privada local, sem segredo manual;
- migração transparente de `DEMO_OPERATOR_PASSWORD` legado para o secret file privado;
- montagem da senha como Docker secret somente leitura;
- fallback de `DEMO_OPERATOR_PASSWORD` restrito ao CLI de compatibilidade/testes;
- `purge` removendo a credencial gerada;
- ausência de provider externo.

## Regras para próximas expansões

1. reutilizar `residencia-ipe-v1` e identificadores estáveis;
2. derivar datas de `2026-11-01`;
3. adicionar dados somente depois do schema/invariantes do módulo serem aprovados;
4. manter carga/status/reset idempotentes e isolados;
5. não usar dumps reais ou dados anonimizados;
6. versionar metadata/checksum em mudança incompatível;
7. não enfraquecer RLS, grants ou append-only por conveniência da demo.

## Segurança

- nunca copiar `.env`, keyring, senha de operador ou volume do ambiente comum;
- nunca inserir credenciais de integração externa;
- nunca utilizar dados do mantenedor, familiares, clientes ou instituições reais;
- nunca habilitar o modo demo em HML ou produção por inferência deste runbook;
- nenhum deploy é autorizado por esta funcionalidade.
