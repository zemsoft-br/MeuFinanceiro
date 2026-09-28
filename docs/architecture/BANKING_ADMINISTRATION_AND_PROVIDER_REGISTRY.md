# Administração bancária interna e registry de providers

Status: **implementação inicial da issue #70**.

Este documento descreve a composição fail-closed adicionada entre o contrato neutro
`BankingProvider`, a persistência cifrada da issue #68 e os futuros adaptadores
externos.

## Objetivo do recorte

O recorte cria duas fronteiras:

```text
BankingProviderRegistry
BankingAdministrationService
```

O registry pertence ao pacote neutro `meufinanceiro-banking`. O serviço
administrativo pertence à aplicação API e coordena somente a configuração persistida.
Nenhum deles executa autenticação externa, HTTP, sincronização ou leitura de dados
financeiros.

## Registry fail-closed

`BankingProviderRegistry` inicia vazio. Um provider somente existe para o runtime
quando uma factory é registrada explicitamente durante a composição da aplicação.

O registry:

- valida o slug do provider;
- rejeita registros duplicados;
- pode ser congelado após o bootstrap;
- rejeita qualquer novo registro depois do congelamento;
- falha fechado quando o provider não está registrado;
- valida estruturalmente o objeto retornado pela factory;
- confirma que `provider.provider_name` corresponde ao nome registrado;
- remove a cadeia causal de falhas da factory;
- não importa persistência, FastAPI, HTTP ou SDK externo.

A factory somente é executada por `create()`. Consultar registro ou administrar a
configuração não instancia o provider.

## Composição padrão da API

O startup da API cria:

```text
BankingProviderRegistry().freeze()
```

Portanto, a composição padrão contém zero providers e não permite registro posterior.
O runtime continua totalmente funcional para lançamentos manuais e demais módulos.

Nenhum adaptador Pluggy é registrado nesta issue.

## Kill switch global

A configuração:

```text
APP_BANKING_ENABLED=false
```

é desabilitada por padrão.

O kill switch global não substitui o estado persistido do provider. A operação externa
futura exigirá simultaneamente:

1. feature flag global habilitada;
2. provider registrado;
3. configuração persistida em estado `enabled`;
4. autorização da residência e do ator para a operação específica.

Nesta issue, somente as duas primeiras condições são usadas para autorizar a transição
administrativa para `enabled`. Nenhuma operação externa existe.

## Serviço administrativo interno

`BankingAdministrationService` fornece casos de uso internos para:

```text
configure_provider
get_provider_configuration
replace_provider_credentials
set_provider_state
```

Regras:

- configurar credenciais exige provider registrado;
- substituir credenciais exige provider registrado;
- alterar para `configured` exige provider registrado;
- alterar para `enabled` exige provider registrado e feature flag global habilitada;
- alterar para `disabled` continua permitido mesmo se o adaptador não estiver mais
  registrado;
- consultar metadados permanece permitido para diagnóstico e desativação segura;
- compare-and-swap continua delegado ao `BankingIntegrationStore`;
- records públicos continuam sem envelopes cifrados.

Permitir a desativação sem adaptador é deliberado. Remover ou quebrar um adaptador não
pode impedir o operador de colocar a integração em estado seguro.

## Erros administrativos

A aplicação expõe somente categorias estáveis:

```text
PROVIDER_UNAVAILABLE
FEATURE_DISABLED
CONFIGURATION_NOT_FOUND
CONFIGURATION_CONFLICT
PERSISTENCE_FAILURE
```

Mensagens do banco, credenciais, envelopes, identificadores externos e diagnósticos de
factory não são propagados. As exceções administrativas removem a cadeia causal dos
erros traduzidos.

## Ausência de endpoint HTTP

Nenhuma rota FastAPI é criada neste recorte.

A configuração global pertence a um fluxo administrativo da instalação. O projeto
ainda não possui o contrato completo de autenticação e autorização do operador para
essa superfície. Expor headers improvisados, tokens estáticos ou endpoints sem actor
context violaria o ADR-0012.

O serviço interno poderá ser chamado por uma rota futura somente depois de existir:

- identidade autenticada;
- papel administrativo da instalação;
- autorização explícita;
- auditoria sanitizada;
- proteção contra replay e CSRF conforme o cliente escolhido.

## Segurança e privacidade

Este recorte preserva:

- integração desabilitada por padrão;
- retenção zero de API key e Connect Token;
- ausência de senha bancária e MFA;
- ausência de payload HTTP bruto;
- ausência de SDK Pluggy;
- ausência de chamadas externas;
- credenciais persistidas somente pelo store cifrado existente;
- nenhuma exposição de envelopes pela API pública do serviço.

## Build de container

A imagem da API passa a copiar e instalar o pacote interno
`meufinanceiro-banking`, antes da instalação de `meufinanceiro-api`.

Isso não adiciona dependência externa de runtime. O pacote neutro continua usando
somente a biblioteca padrão do Python.

## Fora do escopo

Continuam pendentes:

- endpoint administrativo autenticado;
- adaptador Pluggy read-only;
- autenticação da Application e API key efêmera;
- Connect Token e widget;
- conexões externas reais;
- contas e transações;
- worker e sincronização;
- auditoria administrativa persistida;
- Flutter;
- deploy, HML e produção.
