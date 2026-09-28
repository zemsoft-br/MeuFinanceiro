# Uso efêmero de credenciais bancárias habilitadas

Status: **implementação inicial da issue #78**.

## Objetivo

Permitir que um caso de uso interno execute uma operação com as credenciais da
Application somente quando a configuração do provider estiver explicitamente
`enabled`.

O contrato é baseado em callback:

```text
BankingIntegrationStore.use_enabled_credentials(..., operation)
    -> lê configuração e envelopes em transação
    -> encerra a transação
    -> decripta com AAD contextual
    -> cria material efêmero redigido
    -> executa operation(material)
    -> descarta referências locais no finally
```

O método não registra provider, não autentica na Pluggy e não executa rede.

## Estado obrigatório

A configuração deve existir e possuir estado:

```text
enabled
```

Os estados abaixo falham antes da decriptação e antes do callback:

```text
configured
disabled
```

A presença de envelopes nunca implica autorização operacional.

## Leitura transacional

A leitura define `app.current_installation_id` com `SET LOCAL` e seleciona, dentro da
mesma transação:

- ID da configuração;
- provider;
- estado;
- revisão;
- envelope de Client ID;
- envelope de Client Secret.

A transação é encerrada antes do callback. Portanto, uma chamada externa futura não
manterá conexão PostgreSQL ou locks enquanto aguarda o provider.

## Decriptação

Cada campo usa o AAD canônico do ADR-0012:

```text
meufinanceiro:v1:installation:{installation_id}:provider:{provider}:
configuration:{configuration_id}:field:{field_name}
```

Os campos permitidos continuam restritos a:

```text
client_id
client_secret
```

Mover um envelope entre campos, configurações ou instalações falha na autenticação do
AES-GCM.

## Material efêmero

`EnabledProviderCredentials` contém:

- configuration ID;
- provider;
- revision;
- Client ID;
- Client Secret.

O tipo:

- é imutável;
- usa slots;
- possui `repr` redigido;
- não possui campos de envelope;
- não implementa serialização;
- não é persistido pelo store.

O plaintext permanece acessível ao callback porque uma futura factory precisará criar
a sessão autenticada. O callback é uma fronteira interna confiável e deve retornar
somente resultado sanitizado. O store remove suas referências locais no bloco
`finally`; Python não oferece garantia de sobrescrita imediata de strings imutáveis.

## Falhas

| Situação | Resultado |
|---|---|
| configuração ausente | `ConfigurationNotFoundError` |
| estado não habilitado | `ProviderNotEnabledError` |
| banco indisponível | `BankingPersistenceError` sanitizado |
| envelope inválido | `BankingPersistenceError` sanitizado |
| chave ausente | `BankingPersistenceError` sanitizado |
| AAD divergente | `BankingPersistenceError` sanitizado |
| plaintext inválido | `BankingPersistenceError` sanitizado |
| exceção do callback | propagada sem alteração pelo store |

Erros de leitura e decriptação não incluem plaintext, envelope, instalação,
configuration ID ou cadeia causal criptográfica.

## Runtime preservado

O recorte não:

- instala o adapter Pluggy na API;
- registra provider;
- altera `APP_BANKING_ENABLED=false`;
- carrega credenciais no startup;
- cria endpoint;
- executa chamadas externas;
- cria migration ou altera schema;
- executa deploy, HML ou produção.

## Próximo recorte

Uma issue posterior poderá criar um executor contextual que:

1. chama `use_enabled_credentials`;
2. cria `PluggyGatewayHttpTransport` dentro do callback;
3. compõe gateway e adapter;
4. executa uma operação read-only;
5. fecha o transporte no `finally`;
6. retorna somente DTOs neutros ou diagnóstico sanitizado.

Esse executor continuará sem sincronização automática e sem ativação no startup.
