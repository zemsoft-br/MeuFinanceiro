# Modelo de persistência da integração bancária

Status: **contrato arquitetural aceito pela issue #64**. Este documento descreve o
schema futuro, mas não cria migration, modelo SQLAlchemy, endpoint ou integração com
provider.

## Objetivo

Traduzir o ADR-0012 em um contrato verificável para as próximas issues de:

1. interface executável `BankingProvider`;
2. migration do schema `integrations`;
3. configuração administrativa do provider;
4. adaptador Pluggy read-only;
5. sincronização manual e reconciliação.

## Fronteiras

```text
keyring externo
  protege
provider_configuration.credential_envelopes

PostgreSQL
  mantém configuração operacional
  mantém conexões e capacidades por residência
  mantém cursores e execuções idempotentes
  mantém observações externas minimizadas

BankingProvider
  converte payloads externos em DTOs neutros
  nunca retorna cliente HTTP, token ou payload bruto

Domínio financeiro
  decide importação, conciliação e confirmação
  continua funcional sem provider
```

## Estados da configuração

```text
disabled -> configured -> enabled
    ^          |            |
    |----------|------------|
```

### `disabled`

- estado padrão quando não existe configuração;
- nenhuma autenticação externa;
- nenhum adaptador instanciado;
- nenhum job de sincronização enfileirado;
- health principal permanece saudável;
- interface financeira manual permanece disponível.

### `configured`

- envelopes obrigatórios existem e validam localmente;
- configuração ainda não autoriza chamada externa;
- pode ser usada para revisão, teste de integridade e rotação;
- não cria conexão nem Connect Token.

### `enabled`

- ativação administrativa explícita;
- permite fluxos externos autorizados por capacidade;
- tarefas revalidam o estado imediatamente antes da chamada;
- falha de decriptação ou configuração incompleta torna o provider indisponível sem
  alterar dados financeiros locais.

## Schema conceitual

O schema futuro chama-se `integrations`. Nenhum objeto deste documento existe até a
migration específica ser criada e revisada.

### `integrations.provider_configurations`

Escopo: instalação.

| Campo conceitual | Regra |
|---|---|
| `id` | UUID interno gerado antes da cifragem |
| `installation_id` | identificador estável da instalação |
| `provider` | slug neutro em allowlist |
| `state` | `disabled`, `configured` ou `enabled` |
| `client_id_envelope` | JSON versionado do ADR-0005 |
| `client_secret_envelope` | JSON versionado do ADR-0005 |
| `configuration_revision` | incremento otimista |
| `created_at` | timestamp do banco |
| `updated_at` | timestamp do banco |
| `enabled_at` | opcional |
| `disabled_at` | opcional |

Invariantes:

- `UNIQUE (installation_id, provider)`;
- envelopes são obrigatórios para `configured` e `enabled`;
- `disabled` pode preservar envelopes para pausa reversível;
- remoção de envelopes é ação administrativa separada;
- ciphertext nunca é devolvido por endpoints comuns;
- alteração usa compare-and-swap por `configuration_revision`;
- ativação e desativação geram auditoria sanitizada.

AAD:

```text
meufinanceiro:v1:installation:{installation_id}:provider:{provider}:
configuration:{id}:field:client_id

meufinanceiro:v1:installation:{installation_id}:provider:{provider}:
configuration:{id}:field:client_secret
```

### `integrations.connections`

Escopo: residência.

| Campo conceitual | Regra |
|---|---|
| `id` | UUID interno |
| `installation_id` | defesa contra associação cruzada |
| `residence_id` | coluna direta e protegida por RLS |
| `provider` | slug neutro |
| `provider_configuration_id` | configuração da instalação |
| `external_connection_id` | identificador operacional sensível |
| `status` | estado neutro do `BankingProvider` |
| `requires_user_action` | booleano derivado do estado |
| `last_successful_sync_at` | opcional |
| `last_attempt_at` | opcional |
| `next_refresh_allowed_at` | opcional |
| `consent_expires_at` | opcional quando fornecido |
| `provider_reason_code` | código limitado, sem mensagem livre |
| `disconnected_at` | opcional |
| `created_at` | timestamp do banco |
| `updated_at` | timestamp do banco |

Invariantes:

- `UNIQUE (installation_id, provider, external_connection_id)`;
- uma conexão externa não pertence silenciosamente a duas residências;
- `residence_id` não é alterado por endpoint comum;
- reconexão reutiliza a linha quando o provider reutiliza o Item;
- `DISCONNECTED` bloqueia novas sincronizações;
- desconexão não remove observações ou lançamentos importados;
- código externo não se torna regra de domínio.

### `integrations.connection_capabilities`

Escopo: residência e conexão.

| Campo conceitual | Regra |
|---|---|
| `id` | UUID interno |
| `residence_id` | RLS direta |
| `connection_id` | FK da mesma residência |
| `capability` | allowlist neutra |
| `state` | `SUPPORTED`, `NOT_AVAILABLE`, `REQUIRES_USER_ACTION`, `NOT_OBSERVED` ou `UNKNOWN` |
| `source` | contrato, observação ou resposta operacional |
| `provider_reason_code` | opcional e limitado |
| `observed_at` | timestamp do banco |
| `updated_at` | timestamp do banco |

Invariantes:

- `UNIQUE (connection_id, capability)`;
- ausência de registros não vira automaticamente `NOT_AVAILABLE`;
- estado pode regredir para `UNKNOWN` ou `REQUIRES_USER_ACTION`;
- capacidades não são assumidas globalmente pelo provider.

### `integrations.sync_runs`

Escopo: residência e conexão.

| Campo conceitual | Regra |
|---|---|
| `id` | UUID interno |
| `residence_id` | RLS direta |
| `connection_id` | conexão da mesma residência |
| `idempotency_key` | única por operação lógica |
| `trigger` | manual, recovery ou futuro webhook |
| `status` | requested, running, partial, succeeded, failed ou cancelled |
| `started_at` | opcional |
| `finished_at` | opcional |
| `attempt_count` | inteiro limitado |
| `error_category` | enum neutro |
| `provider_reason_code` | opcional e limitado |
| `http_status` | opcional quando necessário |
| `retry_window_bucket` | bucket, nunca header bruto |
| `records_seen` | contagem |
| `records_applied` | contagem |
| `created_at` | timestamp do banco |

Invariantes:

- `UNIQUE (connection_id, idempotency_key)`;
- somente uma execução externa ativa por conexão;
- estado do provider é revalidado antes da chamada;
- `disabled` impede enqueue e execução;
- falha parcial não avança todos os cursores;
- payload, URL completa e mensagem livre do provider são proibidos;
- retry segue o contrato limitado do `BankingProvider`.

### `integrations.sync_cursors`

Escopo: residência, conexão e recurso.

| Campo conceitual | Regra |
|---|---|
| `id` | UUID interno |
| `residence_id` | RLS direta |
| `connection_id` | conexão da mesma residência |
| `external_account_id` | opcional conforme recurso |
| `resource` | transactions, bills ou outro recurso permitido |
| `cursor` | valor opaco sensível |
| `source_window` | janela lógica, sem payload |
| `committed_at` | após persistência integral da página |
| `updated_at` | timestamp do banco |

Invariantes:

- unicidade por conexão, conta e recurso;
- cursor nunca é aceito de input do cliente;
- cursor nunca aparece em log ou resposta pública;
- atualização ocorre na mesma transação da página aplicada;
- falha de página preserva o cursor anterior;
- cursor de uma conta não pode ser usado em outra.

### `integrations.external_accounts`

Escopo: residência e conexão.

| Campo conceitual | Regra |
|---|---|
| `id` | UUID interno |
| `residence_id` | RLS direta |
| `connection_id` | conexão da mesma residência |
| `external_account_id` | identificador sensível |
| `type` | tipo neutro |
| `subtype` | subtipo neutro |
| `currency` | código normalizado |
| `name` | opcional e minimizado |
| `number_mask` | opcional, nunca número completo |
| `status` | ativo, indisponível ou desconectado |
| `first_seen_at` | timestamp do banco |
| `last_seen_at` | timestamp do banco |

Invariantes:

- `UNIQUE (connection_id, external_account_id)`;
- número completo, agência completa e documento do titular não são necessários;
- conta externa não é automaticamente uma conta financeira confirmada pelo usuário;
- vínculo com o domínio ocorre por processo explícito de importação/conciliação.

### `integrations.external_observations`

Escopo: residência, conta e recurso externo.

Este objeto guarda somente a representação normalizada mínima antes da decisão do
domínio. A migration será criada apenas junto do primeiro recurso importado.

Campos mínimos futuros:

```text
id
residence_id
connection_id
external_account_id
resource_type
external_resource_id opcional
status
provider_updated_at opcional
effective_date
amount
currency
stable_fingerprint
first_seen_at
last_seen_at
deleted_at opcional
normalized_payload_version
```

`normalized_payload_version` identifica o DTO neutro, não o payload HTTP. Campos como
descrição, categoria, fatura e parcela entram somente quando exigidos pelo caso de
uso e passam por minimização específica.

### `integrations.audit_events`

Escopo: instalação ou residência, conforme a ação.

Eventos permitidos:

```text
provider_configured
provider_enabled
provider_disabled
credentials_replaced
credential_rewrap_started
credential_rewrap_completed
connection_linked
reauthentication_requested
connection_disconnected
sync_requested
sync_completed
sync_failed
retention_cleanup_completed
```

Conteúdo permitido:

- IDs internos;
- provider slug;
- ator interno;
- residência quando aplicável;
- categoria e resultado;
- contagens;
- `key_id` de origem e destino durante rewrap;
- timestamp do banco.

Conteúdo proibido:

- envelopes;
- plaintext;
- external IDs;
- cursor;
- valores financeiros;
- descrição de transação;
- token;
- payload ou mensagem livre do provider.

## Contrato de RLS

Todas as tabelas com `residence_id` devem:

1. habilitar RLS;
2. forçar RLS para a role de runtime quando suportado pelo contrato de migrations;
3. possuir política baseada no `residence_id` da própria linha;
4. rejeitar operação sem contexto transacional de residência;
5. validar FKs compostas ou constraints equivalentes para impedir associação cruzada;
6. ser testadas com duas residências e a mesma role de runtime;
7. impedir leitura, update e delete cruzados;
8. manter jobs administrativos separados dos handlers comuns.

A role de migration cria políticas e grants. API e Worker não recebem
`BYPASSRLS`, `SUPERUSER`, `CREATEDB` ou `CREATEROLE`.

## Contrato de configuração e ativação

A futura API administrativa deve separar comandos:

```text
store_credentials
validate_envelopes
set_configured
set_enabled
set_disabled
remove_credentials
```

Regras:

- `store_credentials` cifra antes de abrir a transação de escrita final;
- nenhum endpoint retorna o valor armazenado;
- update substitui o envelope inteiro;
- validação local prova decriptação e formato, não autenticação externa;
- teste externo futuro é comando separado e explícito;
- ativação exige revisão atual da configuração;
- desativação cancela novos trabalhos, mas não apaga histórico;
- remoção de credenciais exige provider desabilitado e confirmação administrativa.

## Rewrap transacional

### Preparação

- criar backup coordenado;
- validar keyring;
- confirmar nova chave ativa;
- contar envelopes por `key_id`;
- registrar plano sem valores.

### Lote

Para cada configuração reservada:

1. carregar ID, provider, revisão e envelopes;
2. reconstruir o AAD canônico;
3. decriptar com chave histórica;
4. cifrar com chave ativa;
5. atualizar somente se a revisão não mudou;
6. incrementar `configuration_revision`;
7. confirmar a transação;
8. limpar plaintext e buffers alcançáveis pelo chamador;
9. registrar somente resultado e contagem.

### Verificação

- zero envelopes referenciam a chave antiga;
- todos os envelopes podem ser autenticados com seu AAD;
- nenhuma configuração mudou semanticamente;
- falhas permanecem listadas por ID interno;
- restart carrega o keyring atual;
- chave antiga continua presente até operação posterior.

### Remoção da chave histórica

Não é parte automática do rewrap. Exige:

- backup novo validado;
- contagem zero por `key_id` no banco restaurável;
- validação de restore;
- confirmação administrativa explícita;
- atualização atômica do keyring;
- restart e smoke de integridade.

## Retenção e limpeza

| Classe | Regra padrão |
|---|---|
| tokens efêmeros e credenciais bancárias | nunca persistir |
| credenciais da Application | até substituição ou remoção explícita |
| identificadores de conexão | enquanto houver histórico ou auditoria necessária |
| cursor ativo | manter somente a versão confirmada |
| execução de sincronização | 90 dias |
| auditoria administrativa/segurança | 365 dias |
| observação importada | política do domínio financeiro |

A limpeza:

- usa job idempotente;
- registra somente contagens;
- não remove conexão referenciada por observação ou lançamento;
- não remove auditoria necessária para provar desconexão ou troca de credencial;
- não reduz retenção abaixo do limite configurado sem ação administrativa;
- nunca usa cascade destrutivo para dados financeiros confirmados.

## Backup e restore

Manifesto sanitizado:

```text
backup_format_version
database_revision
envelope_version
referenced_key_ids
created_at
application_version
```

`referenced_key_ids` não contém material de chave. O pacote protegido de secrets e o
backup do banco precisam representar o mesmo ponto operacional.

Gate de restore:

1. banco restaura em ambiente isolado;
2. keyring restaura com permissões corretas;
3. revisão Alembic corresponde ao manifesto;
4. todos os `key_id` referenciados existem;
5. envelopes autenticam com AAD reconstruído;
6. nenhum plaintext é impresso;
7. provider permanece `disabled` no ambiente de validação;
8. nenhuma chamada externa é executada.

## Observabilidade

Métricas permitidas:

```text
banking_provider_state{provider}
banking_connections_total{provider,status}
banking_sync_runs_total{provider,result}
banking_sync_duration_bucket{provider}
banking_capability_total{provider,capability,state}
banking_rewrap_remaining_total{provider,key_id}
```

Labels proibidos:

- residência;
- external ID;
- conta;
- cursor;
- documento;
- descrição;
- valor;
- token;
- código externo de alta cardinalidade.

Logs usam `provider`, IDs internos, categoria neutra, contagens e duração. O filtro de
redaction da fundação permanece obrigatório.

## Threat model complementar

| Ameaça | Controle |
|---|---|
| envelope copiado entre registros | AAD com instalação, provider, registro e campo |
| credencial ativa sem intenção | estados `configured` e `enabled` separados |
| associação da conexão à residência errada | unicidade global e RLS direta |
| vazamento por logs | allowlist e redaction central |
| dump sem keyring | ciphertext sem chave no banco |
| keyring sem banco | ausência de envelopes e contexto |
| cursor trocado entre contas | vínculo por conexão, conta e recurso |
| retry após desativação | revalidação antes da chamada |
| remoção prematura de chave | contagem zero, restore e confirmação separada |
| desconexão apagando histórico | estado e retenção separados de dados locais |
| payload bruto usado como cache | proibição estrutural e teste contratual |

## Próximas issues obrigatórias

### Interface executável

- protocolo Python neutro;
- DTOs tipados;
- provider fake;
- testes de capacidades e estados;
- nenhum SDK Pluggy.

### Migration do schema `integrations`

- tabelas iniciais de configuração, conexão e capacidades;
- envelopes JSON validados;
- constraints e grants;
- RLS com duas residências;
- upgrade e downgrade em PostgreSQL real;
- sem dados financeiros ainda.

### Configuração administrativa

- comandos separados para armazenar, ativar e desativar;
- autorização de operador da instalação;
- envelope e AAD;
- auditoria sanitizada;
- sem autenticação externa automática.

### Adaptador Pluggy mínimo

- autenticação server-side;
- API key somente em memória;
- leitura de conexão e capacidades;
- contas e transações read-only em recortes posteriores;
- feature flag e provider registry fail-closed.

## Fora do escopo deste contrato

- migration;
- modelos SQLAlchemy;
- endpoints;
- telas Flutter;
- SDK Pluggy;
- chamadas externas;
- Item real;
- sincronização;
- webhook;
- deploy;
- HML ou produção;
- pagamentos, DDA ou transferências.