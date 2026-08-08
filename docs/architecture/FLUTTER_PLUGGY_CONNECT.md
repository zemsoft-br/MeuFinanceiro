# Pluggy Connect no Flutter Web/PWA

## Objetivo

O cliente Flutter Web/PWA abre o Pluggy Connect sem transformar o navegador em
fronteira de autorização e sem persistir identificadores transitórios do
provider.

A rota canônica de **nova conexão** é:

```text
/app/integracoes/pluggy/conectar
```

Ela é protegida pelo namespace `/app/*` e depende da sessão local descrita em
`FLUTTER_OPERATOR_SESSION.md`.

A experiência reconstrói semanticamente a referência Stitch
`conectar_institui_o_assistente`; nenhum HTML do protótipo é incorporado ao
runtime Flutter.

A reautenticação/update de uma conexão existente usa o mesmo adapter em modo
controlado e está especificada separadamente em
`FLUTTER_PLUGGY_REAUTHENTICATION.md`.

## Referências oficiais verificadas

Verificação realizada em 2026-08-07:

- Pluggy — Environments and Configurations:
  `https://docs.pluggy.ai/docs/environments-and-configurations`
- Pluggy — Setup Pluggy Connect Widget on your app:
  `https://docs.pluggy.ai/docs/setup-pluggyconnect-widget-on-your-app`
- Pluggy Quickstart HTML:
  `https://github.com/pluggyai/quickstart/tree/master/frontend/html`
- pacote Flutter oficial avaliado:
  `https://pub.dev/packages/flutter_pluggy_connect`

O Quickstart Web oficial usa nesta data o asset versionado:

```text
https://cdn.pluggy.ai/pluggy-connect/v2.8.2/pluggy-connect.js
```

A versão fica fixa no adaptador Web. Não existe configuração de URL por query,
ambiente, payload da API ou estado do usuário.

## Por que o runtime Web usa adaptador JavaScript

A versão `3.0.1` do pacote `flutter_pluggy_connect` avaliada para este recorte
não declara Web entre as plataformas suportadas. Por isso ele não é dependência
do target Web do MeuFinanceiro.

A integração fica atrás de `PluggyConnectLauncher`. A implementação Web usa a
API JavaScript oficial do Connect, isolada em `lib/platform/pluggy/`.

Nenhum tipo JavaScript ou payload Pluggy atravessa essa porta. A apresentação
recebe apenas eventos normalizados e, quando disponível, um `itemId` transitório
já validado sintaticamente.

## Dependência externa lazy

A biblioteca Pluggy não participa do startup do MeuFinanceiro:

- não existe `<script>` Pluggy em `web/index.html`;
- `web/app_bootstrap.js` não conhece a Pluggy;
- o adaptador injeta o script somente após ação explícita do usuário;
- a carga do script é single-flight;
- falha de CDN é reduzida a erro local sanitizado;
- o núcleo do app, navegação e funcionamento offline não dependem dessa CDN.

O service worker do MeuFinanceiro ignora requests cross-origin, portanto os
recursos externos da Pluggy não entram no cache do shell.

## Fronteira de confiança da nova conexão

O fluxo é:

```text
sessão autenticada
        |
        v
POST /api/v1/banking/pluggy/connect-token
        |
        | accessToken efêmero
        v
Pluggy Connect Web
        |
        | callback não confiável
        v
extrair somente item.id
        |
        v
POST /api/v1/banking/pluggy/connections
{"itemId":"..."}
        |
        | backend busca o Item na Pluggy e comprova ownership
        v
connectionId + status + requiresUserAction locais
```

O callback nunca é evidência de autorização. Status, connector, capacidades,
`clientUserId`, instituição, contas e qualquer dado financeiro do callback são
descartados.

O backend continua sendo a única fronteira que comprova a associação do Item à
residência autenticada.

## Configuração do widget na nova conexão

O modo de criação usa:

```text
connectToken: <efêmero>
language: pt
countries: [BR]
includeSandbox: false
```

O fluxo de nova conexão **não** fornece `updateItem`. O adapter aceita essa
propriedade somente quando o fluxo separado de reautenticação recebeu o Item
transitório diretamente do backend autenticado.

Não são enviados pelo Flutter em nenhum dos dois modos:

- `clientUserId`;
- residência ou instalação;
- `forceAskForCredentials` neste recorte;
- webhook URL;
- OAuth redirect customizado;
- connector IDs arbitrários;
- products arbitrários;
- CPF/CNPJ;
- credenciais bancárias ou MFA.

O `clientUserId` canônico continua sendo definido e validado pelo backend.

## Callbacks

`onSuccess` é reduzido a `item.id`.

`onError` pode carregar `data.item` em fluxos nos quais já existe um Item
pendente. Quando esse ponteiro estiver presente e válido, ele também pode ser
enviado ao endpoint de registro; o backend permanece responsável por verificar
o Item.

A documentação oficial alerta que `onSuccess` não é garantido em todos os
fluxos. Autorizações que evoluem posteriormente serão complementadas por
webhooks/sincronização em recortes futuros; este cliente não implementa polling
automático.

`onClose` sem Item finaliza o fluxo local sem registrar conexão.

## Segredos e identificadores transitórios

### Connect Token

O token retornado pelo backend:

- fica em wrapper efêmero em memória;
- é consumido uma única vez para abrir o launcher;
- é descartado após a tentativa de abertura;
- não entra no estado Riverpod observável;
- não entra em storage, URL, cache, log, exception ou texto de widget;
- nunca é reutilizado automaticamente; novo retry solicita novo token.

### Item ID

Na criação, o Item ID:

- existe somente no callback normalizado e durante o POST de registro;
- não aparece na UI;
- não é gravado em storage/cache;
- não entra em `toString`/diagnóstico;
- é descartado depois do registro.

No update, ele também existe temporariamente entre a resposta autenticada e a
abertura do launcher; as regras de não persistência e redaction são as mesmas.

Após sucesso, a UI mantém somente o `connectionId` local, o status local e o
booleano `requiresUserAction` retornados pelo backend.

## Concorrência e ciclo de vida

`PluggyConnectController` é single-flight e auto-dispose:

- duas ações simultâneas não abrem dois widgets;
- callbacks são serializados em uma fila local;
- um callback tardio não restaura estado depois que a tela deixa de observar o
  provider;
- o controller mantém uma geração monotônica para invalidar trabalho antigo;
- não existe retry automático dos POSTs de token ou registro.

O controller de reautenticação preserva as mesmas garantias e ainda exige que o
Item do callback seja exatamente o Item transitório entregue pelo backend para
o update atual.

O retorno de foco ao botão é sinalizado pela camada de estado após o fechamento
do widget.

## Demo e offline

O status de demonstração é verificado antes de emitir material Pluggy. Em demo:

- nenhum POST bancário é iniciado;
- o script Pluggy não é carregado;
- a UI informa que integrações externas estão indisponíveis.

Falha de transporte/CDN é um estado recuperável e exige nova ação explícita do
usuário. Não existe fila offline para conexão bancária.

## Respostas aceitas

### Connect Token de criação

O cliente aceita estritamente:

```json
{"accessToken":"..."}
```

### Reautenticação

O modo update aceita estritamente:

```json
{"accessToken":"...","itemId":"..."}
```

Os dois campos são efêmeros e existem somente para inicializar o widget.

### Registro

O cliente aceita estritamente:

```json
{
  "connectionId":"<UUID local>",
  "status":"<enum local conhecido>",
  "requiresUserAction":false
}
```

O Item ID não faz parte do resultado permanente.

## Fora do escopo

- SDK Connect para Android/iOS/macOS;
- lista de conexões existentes;
- `forceAskForCredentials`;
- OAuth redirect customizado;
- webhooks no cliente;
- polling automático;
- sincronização de contas/transações;
- desconexão;
- persistência offline;
- dados financeiros no Flutter;
- ativação de flags;
- chamada Pluggy real em teste;
- deploy, homologação ou produção.
