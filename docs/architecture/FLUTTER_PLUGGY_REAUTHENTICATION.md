# Reautenticação Pluggy no Flutter Web/PWA

## Objetivo

O Flutter permite atualizar uma conexão Pluggy existente usando somente o UUID
local da conexão como entrada controlável pelo cliente.

Rota protegida:

```text
/app/integracoes/pluggy/conexoes/:connectionId/reautenticar
```

O path nunca contém Item ID Pluggy. A rota permanece dentro de `/app/*` e herda
a guarda de sessão descrita em `FLUTTER_OPERATOR_SESSION.md`.

## Contrato backend

O cliente chama:

```text
POST /api/v1/banking/pluggy/connections/{connectionId}/reauthentication-token
```

sem body e sem query parameters.

O backend resolve a conexão local sob RLS, busca novamente o Item na Pluggy,
comprova `id` e `clientUserId=residence:<primary_residence_id>` e só então
retorna:

```json
{
  "accessToken": "<ephemeral-connect-token>",
  "itemId": "<ephemeral-provider-item-id>"
}
```

O Flutter aceita exatamente esses dois campos. Ambos permanecem em memória e
são consumidos uma única vez para abrir o widget.

## Update mode do Pluggy Connect

A documentação oficial da Pluggy, verificada em 2026-08-07/08, exige para
update mode:

1. novo Connect Token criado server-side com o `itemId` do Item existente;
2. `connectToken` fornecido ao Connect;
3. o mesmo Item fornecido pela opção `updateItem`.

Referências:

- Pluggy — Updating an Item;
- Pluggy — Create Connect Token;
- Pluggy — Setup PluggyConnect Widget on your app.

O adapter Web continua carregando o script versionado somente após ação
explícita. As opções comuns permanecem:

```text
connectToken: <efêmero>
language: pt
countries: [BR]
includeSandbox: false
```

No modo update acrescenta-se somente:

```text
updateItem: <Item efêmero devolvido pelo backend>
```

Não são enviados `clientUserId`, `forceAskForCredentials`, webhook, OAuth
redirect, connector IDs ou products.

`forceAskForCredentials` permanece deliberadamente fora deste recorte. O
Connect decide se precisa solicitar MFA/credenciais conforme o estado do Item.

## Fronteira de confiança

```text
connectionId local
        |
        v
backend recompõe ownership
        |
        v
accessToken + itemId efêmeros
        |
        v
Pluggy Connect(updateItem)
        |
        | callback não confiável
        v
item.id deve coincidir com o Item usado no update
        |
        v
POST /api/v1/banking/pluggy/connections
        |
        v
backend recompõe ownership novamente
        |
        v
connectionId/status/requiresUserAction locais
```

O controller guarda o Item esperado somente em campo privado e temporário
enquanto o widget está ativo. Esse valor não faz parte do estado Riverpod e é
apagado em cancelamento, dispose, sucesso ou falha. Um callback com Item
diferente falha fechado antes do endpoint de registro.

Mesmo quando o callback coincide, ele não autoriza a operação. O registro
existente repete a validação server-side.

## Segredos e identificadores transitórios

`EphemeralPluggyUpdateMaterial` contém o Connect Token e Item ID apenas até a
abertura do launcher. `take()` é single-use e as representações dos wrappers são
redigidas.

É proibido colocar Connect Token ou Item ID em:

- estado Riverpod observável;
- localStorage/sessionStorage/IndexedDB;
- SQLite/SharedPreferences;
- cache PWA;
- URL/query/fragment;
- logs, analytics ou exception text;
- mensagens visuais.

O único identificador persistente usado pela UI é o UUID local da conexão.

## Demo, offline e retries

O modo demonstração é verificado antes do request de reautenticação e antes do
launcher. Nenhuma integração externa é iniciada em demo.

Falha de transporte/CDN vira estado recuperável. Não existe fila offline e não
há retry automático de mutações. Nova tentativa exige ação explícita do usuário.

## Ciclo de vida

`PluggyReauthenticationController` é auto-dispose e single-flight:

- impede dois fluxos simultâneos;
- serializa callbacks;
- ignora callbacks tardios após cancelamento/dispose;
- mantém geração monotônica;
- devolve foco à ação principal após fechamento;
- não inicia conexão automaticamente ao abrir a rota.

A chamada externa só começa após o usuário acionar **Atualizar conexão**.

## UX

A tela informa que:

- é uma atualização de conexão existente;
- a Pluggy pode pedir MFA ou novas credenciais;
- o MeuFinanceiro não armazena senha/MFA;
- internet é necessária;
- cancelar não remove a conexão existente.

Após sucesso, somente o `connectionId` local, estado local e
`requiresUserAction` podem aparecer.

## Fora do escopo

- visão geral/lista de conexões;
- descoberta de conexões pelo Flutter;
- `forceAskForCredentials`;
- `PATCH /items`;
- refresh sem interação;
- sincronização de contas/transações;
- worker, polling ou webhook;
- desconexão;
- Android/iOS/macOS;
- chamada Pluggy real;
- ativação de flags;
- deploy, HML ou produção.
