# Autenticação local do operador

## Objetivo

Criar e operar o primeiro administrador da instalação sem senha em argumentos, arquivos versionados ou variáveis de ambiente.

## Bootstrap

Com a stack migrada e saudável, execute em terminal interativo:

```bash
docker compose exec api python -m app.operator_cli bootstrap --login admin
```

A senha e a confirmação são solicitadas por `getpass`. O comando recusa entrada redirecionada e falha quando a instalação já possui operador.

A saída contém somente:

- installation ID;
- operator ID;
- login normalizado.

Nunca registra senha, hash ou token.

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

## Segurança

- não compartilhe token em issue, chat, log ou bundle de diagnóstico;
- não coloque senha em shell history, `.env` ou Compose;
- acesso fora do loopback exige TLS e controles remotos adicionais;
- erros de login são deliberadamente genéricos;
- cinco falhas conhecidas bloqueiam temporariamente o operador por quinze minutos;
- health e status demo continuam públicos;
- endpoints administrativos bancários ainda não fazem parte deste recorte.

## Recuperação atual

Não existe recuperação automática de senha nesta fase. Preserve o backup coordenado do banco e keyring e trate perda de acesso como operação administrativa que exige um recorte próprio, revisão e trilha auditável.
