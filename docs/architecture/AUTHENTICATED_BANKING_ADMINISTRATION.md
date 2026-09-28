# Administração bancária autenticada

Status: **issue #86**.

## Objetivo

Expor a configuração do provider bancário somente ao operador administrador autenticado, sem iniciar conexão, sincronização ou chamada externa.

## Rotas

```text
POST  /api/v1/admin/banking/providers/{provider}/configuration
GET   /api/v1/admin/banking/providers/{provider}/configuration
PUT   /api/v1/admin/banking/providers/{provider}/credentials
PATCH /api/v1/admin/banking/providers/{provider}/state
```

Todas dependem de sessão bearer válida e papel `installation_admin`.

## Contexto confiável

`installation_id` é obtido exclusivamente do principal autenticado. O cliente não pode enviar installation ID, operator ID, session ID, residence ID, Item ID ou Account ID.

## Credenciais

Client ID e Client Secret usam `SecretStr` no request e são encaminhados diretamente ao serviço interno de administração. Nenhuma resposta inclui credencial, envelope cifrado, installation ID ou identificador externo do provider.

A troca de credenciais e as alterações de estado exigem `expected_revision`, mantendo concorrência otimista.

## Flags

- configurar ou trocar credenciais exige provider disponível;
- habilitar exige `APP_BANKING_ENABLED=true` e `APP_BANKING_PLUGGY_ENABLED=true`;
- desabilitar configuração conhecida continua permitido quando o provider fica indisponível;
- nenhuma alteração de estado cria transporte ou executa rede.

## Erros

```text
401 sessão ausente ou inválida
403 operador sem papel administrativo
404 provider ou configuração indisponível
409 feature desabilitada ou revisão divergente
503 falha sanitizada de persistência
```

As rotas usam `Cache-Control: no-store` e não incluem valores fornecidos pelo cliente nas mensagens de erro.

## Fora do escopo

- UI Flutter;
- Connect Token ou Widget;
- criação de Item;
- contas e transações;
- sincronização ou worker;
- chamadas reais à Pluggy;
- deploy, HML ou produção.
