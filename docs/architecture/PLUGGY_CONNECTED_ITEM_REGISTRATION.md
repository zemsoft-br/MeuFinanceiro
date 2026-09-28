# Registro server-side de Item Pluggy concluído

Status: implementação da issue #95.

## Objetivo

O Connect Widget devolve um `itemId`, mas esse identificador é tratado apenas como um
ponteiro não confiável. O backend não usa o `itemId` como autorização e não persiste a
conexão antes de comprovar, diretamente na Pluggy, que o Item pertence à residência
autenticada.

O marcador de ownership é o mesmo criado na emissão do Connect Token:

```text
clientUserId = residence:<primary_residence_id>
```

## Endpoint

```text
POST /api/v1/banking/pluggy/connections
```

Body aceito:

```json
{
  "itemId": "<provider-item-id>"
}
```

O modelo usa `extra=forbid`, aceita somente o alias `itemId` e rejeita query
parameters. `installation_id`, `residence_id`, `clientUserId`, estado e capacidades
nunca são controlados pelo cliente.

Autorização:

```text
Bearer session
  -> installation_admin
  -> primary_residence_id obrigatório
```

## Fluxo de confiança

```text
itemId não confiável
    -> validação bounded
    -> credenciais Pluggy habilitadas em callback efêmero
    -> GET /items/{itemId}
    -> id retornado deve corresponder ao solicitado
    -> clientUserId deve existir e ser válido
    -> clientUserId deve ser exatamente residence:<residência autenticada>
    -> somente então register_connection
    -> replace_capabilities
```

Uma divergência de Item ou `clientUserId` falha fechado antes de qualquer persistência.
A mensagem pública não inclui Item ID, clientUserId, URL, payload do provider ou
credenciais.

## Persistência

Após a verificação server-side:

- `installation_id` e `residence_id` vêm da sessão;
- provider é fixo em `pluggy`;
- `external_connection_id` recebe o Item ID já verificado;
- estado Pluggy é convertido para `StoredConnectionStatus`;
- capacidades observadas são convertidas para `CapabilitySnapshot`;
- o store reutiliza a mesma conexão para o mesmo Item/residência;
- uma conexão já associada a outra residência falha com conflito sanitizado;
- a FK canônica de residência e o RLS permanecem como defesas adicionais.

A resposta HTTP contém somente:

```json
{
  "connectionId": "<uuid-local>",
  "status": "AVAILABLE",
  "requiresUserAction": false
}
```

O Item ID Pluggy e o `clientUserId` não são devolvidos.

## Credenciais e transporte

`PluggyConnectionRegistrationService` usa
`BankingIntegrationStore.use_enabled_credentials(provider="pluggy")`. As credenciais
só existem no callback da operação de verificação.

O transporte é criado por chamada, executa somente a leitura do Item e é fechado em
sucesso ou falha. Erros de transporte são convertidos para códigos estáveis e não
carregam diagnóstico bruto.

A persistência ocorre depois que o callback de credenciais terminou. Nenhuma API key,
Connect Token, credencial ou payload bruto é persistido.

## Runtime

O serviço só é composto quando:

```text
APP_BANKING_ENABLED=true
APP_BANKING_PLUGGY_ENABLED=true
```

As flags continuam `false` por padrão. A composição do serviço não lê credenciais e
não executa rede no startup.

## Fora do escopo

- Flutter/Connect Widget;
- criação de Item pelo backend;
- reautenticação/update de Item;
- OAuth redirect;
- webhooks;
- sincronização manual/worker;
- persistência de contas e transações;
- desconexão;
- chamadas Pluggy reais nos testes;
- credenciais reais;
- alteração das flags padrão;
- bootstrap real;
- deploy, HML ou produção.

O próximo recorte pode integrar o Connect Widget ao cliente e chamar esse endpoint
após o sucesso, ainda sem iniciar sincronização de dados financeiros.
