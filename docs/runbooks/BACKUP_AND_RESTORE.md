# Backup coordenado e restauração verificável

## Objetivo

Criar um ponto de recuperação coordenado da instalação comum e provar que o dump PostgreSQL pode ser restaurado sem alterar o volume, os containers, a configuração ou o keyring em uso.

Este runbook cobre a **fundação local**. Ele não autoriza operação em produção e não substitui uma política de retenção, criptografia ou recuperação de desastre.

## Conteúdo sensível

O bundle contém:

- dump completo do PostgreSQL;
- cópia de `.env`, incluindo senhas administrativas e de runtime;
- cópia de `.secrets/keyring.json`, incluindo a chave mestra;
- manifesto sanitizado com hashes e metadados.

> **O bundle é altamente sensível.** Mantenha-o somente em armazenamento criptografado, fora do checkout, e nunca o anexe a issues, Pull Requests, logs, artifacts ou serviços públicos.

Perder o keyring correspondente pode tornar credenciais e tokens cifrados irrecuperáveis. Banco e keyring precisam pertencer ao mesmo ponto de recuperação.

## Escopo atual

O fluxo opera somente o ambiente comum iniciado por `dev-up`.

Não são cobertos:

- ambiente demo, que é descartável;
- restauração destrutiva sobre a instalação comum;
- upload para nuvem;
- agendamento ou retenção;
- criptografia própria do bundle;
- atualização ou rollback;
- HML ou produção.

A verificação restaura o dump em um container PostgreSQL temporário, sem portas publicadas e sem rede Docker externa. Ao terminar, o container é removido.

## Pré-requisitos

- ambiente comum inicializado e PostgreSQL saudável;
- Docker e Docker Compose v2;
- `.env` e `.secrets/keyring.json` existentes;
- Python 3 no fluxo Unix;
- PowerShell no Windows;
- destino com espaço suficiente para o dump.

Confirme o estado:

```text
docker compose ps --all
```

O serviço `postgres` deve aparecer como `healthy`.

## Criar um backup no Linux, macOS ou WSL 2

```bash
bash infra/scripts/backup-create.sh --acknowledge-sensitive
```

O destino padrão é `.backups/`. Para usar outro diretório:

```bash
bash infra/scripts/backup-create.sh \
  --acknowledge-sensitive \
  --output-dir /caminho/em/armazenamento-criptografado
```

O comando imprime somente o caminho final do bundle em stdout. Avisos são enviados a stderr. Conteúdo de `.env`, keyring e dump não é exibido.

## Criar um backup no Windows PowerShell

```powershell
& .\infra\scripts\backup-create.ps1 -AcknowledgeSensitive
```

Destino alternativo:

```powershell
& .\infra\scripts\backup-create.ps1 `
  -AcknowledgeSensitive `
  -OutputDirectory 'D:\BackupsCriptografados\MeuFinanceiro'
```

O dump é criado dentro do container PostgreSQL e transferido por `docker cp`. Ele não passa pelo redirecionamento textual do Windows PowerShell, evitando corrupção do formato binário custom.

## Estrutura do bundle

Exemplo:

```text
meufinanceiro-20260723T120000Z-0123abcd/
  database.dump
  installation.env
  keyring.json
  manifest.json
```

`manifest.json` contém apenas:

- formato e versão do contrato;
- identificador e horário UTC;
- nome do banco e revisão Alembic;
- imagem PostgreSQL e formato do dump;
- versão, ID ativo e quantidade de chaves do keyring;
- tamanho e SHA-256 de cada arquivo;
- marcação de conteúdo sensível.

Senha, URL de banco e material criptográfico nunca pertencem ao manifesto.

## Verificar a restauração no Linux, macOS ou WSL 2

```bash
bash infra/scripts/backup-verify.sh \
  /caminho/do/meufinanceiro-20260723T120000Z-0123abcd
```

O verificador:

1. valida contrato, arquivos, tamanhos e SHA-256;
2. valida a estrutura mínima do keyring sem mostrar chaves;
3. cria um container `postgres:18.4-alpine` com nome e senha aleatórios;
4. usa `--network none` e não publica portas;
5. restaura `database.dump` com `pg_restore --exit-on-error`;
6. compara a revisão Alembic restaurada com o manifesto;
7. confirma a existência do schema `infra`;
8. remove o container temporário, inclusive quando ocorre falha.

## Verificar a restauração no Windows PowerShell

```powershell
& .\infra\scripts\backup-verify.ps1 `
  'D:\BackupsCriptografados\MeuFinanceiro\meufinanceiro-20260723T120000Z-0123abcd'
```

O contrato verificado é o mesmo do operador Unix.

## O que a verificação não faz

A prova descartável não:

- altera `.env` ou `.secrets` do checkout;
- acessa o volume `postgres_data` da instalação;
- inicia API, Worker, Web ou Caddy;
- publica PostgreSQL em `127.0.0.1` ou `0.0.0.0`;
- altera o ambiente demo;
- comprova decriptação de envelopes funcionais ainda inexistentes;
- restaura dados sobre uma instalação real.

Uma restauração destrutiva real exigirá uma entrega separada, com confirmação explícita, backup prévio e rollback documentado.

## Consistência operacional

A criação do bundle:

- recusa PostgreSQL ausente ou não saudável;
- copia `.env` e keyring no mesmo fluxo do dump;
- grava primeiro em diretório temporário;
- publica o diretório final somente após gerar e validar o manifesto;
- recusa sobrescrita;
- remove dump temporário do container e diretório parcial em falhas.

O `pg_dump` produz um snapshot consistente do banco no instante da execução. Nesta fundação, ainda não existem operações financeiras de usuário. Quando houver módulos mutáveis, o procedimento poderá exigir janela de manutenção ou coordenação adicional.

## Armazenamento e retenção

O repositório não implementa criptografia do bundle. O operador deve:

1. criar o backup diretamente em volume, pasta ou mídia criptografada, quando possível;
2. restringir permissões ao usuário responsável;
3. manter pelo menos uma cópia fora do host principal;
4. verificar periodicamente uma amostra com `backup-verify`;
5. excluir cópias antigas conforme uma política definida;
6. nunca sincronizar o bundle para destino público ou sem criptografia.

`.backups/` é ignorado pelo Git apenas como proteção contra commit acidental. Isso não transforma o diretório em armazenamento seguro.

## Falhas comuns

### `PostgreSQL não está saudável; backup recusado`

Consulte:

```text
docker compose ps --all
docker compose logs --tail=200 postgres
```

Corrija a causa antes de tentar novamente. O script não cria backup parcial de banco indisponível.

### `Revisão Alembic não encontrada`

A instalação pode estar sem migração aplicada ou inconsistente. Não force o backup como ponto de recuperação válido. Consulte [Persistência, migrações e fila](PERSISTENCE_AND_TASK_QUEUE.md).

### `Integridade inválida`

O bundle foi alterado, truncado ou copiado incorretamente. Não use esse bundle para recuperação. Preserve-o para diagnóstico somente em local seguro e escolha outra cópia validada.

### Falha durante `pg_restore`

O container temporário é removido automaticamente. Verifique se o dump foi criado com a versão suportada e se todos os hashes continuam válidos.

## Evidência de CI

O `Container Quality`:

1. inicia a stack comum descartável;
2. cria um bundle em diretório temporário do runner;
3. verifica a restauração em PostgreSQL sem portas;
4. confirma que não restou container de verificação;
5. remove o bundle sem publicá-lo como artifact.

Essa prova usa apenas credenciais aleatórias de CI e dados sintéticos da fundação.
