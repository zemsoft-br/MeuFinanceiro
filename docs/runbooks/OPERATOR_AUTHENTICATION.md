# Autenticação local do operador

## Objetivo

Criar e operar o primeiro administrador e sua residência primária sem senha em argumentos, arquivos versionados ou variáveis de ambiente.

## Bootstrap novo

Com a stack migrada e saudável, execute em terminal interativo:

```bash
docker compose exec api python -m app.operator_cli bootstrap \
  --login admin \
  --residence-name "Residência principal"
```

A senha e a confirmação são solicitadas por `getpass`. O comando recusa entrada redirecionada e falha quando a instalação já possui operador.

A transação cria:

- installation;
- operador `installation_admin`;
- residência ativa;
- associação primária `owner`.

A saída contém somente IDs, login e nome da residência. Nunca registra senha, hash ou token.

## Instalação antiga sem residência

Após executar a migration `0005`, uma instalação que já possuía operador pode criar o contexto household ausente com:

```bash
docker compose exec api python -m app.operator_cli ensure-primary-residence \
  --residence-name "Residência principal"
```

O comando é idempotente: se a associação primária ativa já existe, retorna o contexto existente e não altera o nome nem cria duplicata.

## Sessão HTTP

```text
POST   /api/v1/auth/session
GET    /api/v1/auth/session
DELETE /api/v1/auth/session
```

O login retorna um bearer token opaco uma única vez. O cliente deve mantê-lo apenas durante a sessão e enviá-lo como:

```http
Authorization: Bearer <token>
```

O banco armazena somente SHA-256 do token. A sessão expira após oito horas e pode ser revogada por logout. Respostas sob `/api/v1/auth/` usam `Cache-Control: no-store`.

A resposta de sessão inclui `primary_residence_id` derivado da associação ativa. Instalações antigas ainda não corrigidas recebem `null`; operações futuras que exigem residência falham fechado até o comando de correção ser executado.

## Segurança

- não compartilhe token em issue, chat, log ou bundle de diagnóstico;
- não coloque senha em shell history, `.env` ou Compose;
- não invente ou forneça residence ID por payload;
- acesso fora do loopback exige TLS e controles remotos adicionais;
- erros de login são deliberadamente genéricos;
- cinco falhas conhecidas bloqueiam temporariamente o operador por quinze minutos;
- health e status demo continuam públicos;
- a role runtime não possui DELETE nos schemas identity e household.

## Recuperação atual

Não existe recuperação automática de senha nesta fase. Preserve o backup coordenado do banco e keyring e trate perda de acesso como operação administrativa que exige um recorte próprio, revisão e trilha auditável.
