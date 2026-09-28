# Diagnóstico sanitizado e troubleshooting

## Objetivo

Este runbook orienta a coleta de evidências técnicas da fundação sem copiar `.env`, keyring, dumps, senhas, tokens ou URLs de banco com credenciais.

Os operadores são somente leitura. Eles não executam build, restart, migração, backup, restauração, remoção de volume ou upload automático.

## Antes de compartilhar qualquer arquivo

Mesmo com as proteções automáticas:

1. extraia o bundle;
2. abra todos os arquivos de texto e JSON;
3. confirme que não há nomes, caminhos ou informações do host que você não deseja divulgar;
4. nunca anexe `.env`, `.secrets`, `.backups`, `.updates`, dumps ou keyrings;
5. compartilhe somente o bundle final, nunca o diretório temporário de uma execução interrompida.

## Doctor — verificação rápida

O `doctor` imprime estados estáveis:

- `OK`: verificação aprovada;
- `WARN`: condição útil para diagnóstico, mas não bloqueia o comando;
- `FAIL`: pré-requisito obrigatório ausente ou indisponível.

O código de saída é diferente de zero somente quando existe ao menos um `FAIL`.

### Linux, macOS ou WSL 2

```bash
bash infra/scripts/doctor.sh
```

Endpoint alternativo:

```bash
MEUFINANCEIRO_BASE_URL=http://127.0.0.1:8090 \
  bash infra/scripts/doctor.sh
```

### Windows PowerShell

```powershell
& .\infra\scripts\doctor.ps1
```

Endpoint alternativo:

```powershell
& .\infra\scripts\doctor.ps1 `
  -BaseUrl 'http://127.0.0.1:8090'
```

O doctor valida:

- Git, Docker e Compose v2;
- acesso ao Docker Engine;
- checkout, branch e alterações rastreadas;
- presença de `compose.yaml`, `.env` e keyring sem ler seus conteúdos;
- resolução do contrato Compose;
- existência de serviços em execução;
- readiness HTTP local.

## Gerar bundle diagnóstico

### Linux, macOS ou WSL 2

```bash
bash infra/scripts/diagnostics-export.sh
```

Diretório e endpoint alternativos:

```bash
bash infra/scripts/diagnostics-export.sh \
  --output-dir /caminho/privado/diagnosticos \
  --base-url http://127.0.0.1:8090
```

O resultado é:

```text
meufinanceiro-diagnostics-<utc>-<random>.tar.gz
```

### Windows PowerShell

```powershell
& .\infra\scripts\diagnostics-export.ps1
```

Diretório e endpoint alternativos:

```powershell
& .\infra\scripts\diagnostics-export.ps1 `
  -OutputDirectory 'D:\Diagnosticos\MeuFinanceiro' `
  -BaseUrl 'http://127.0.0.1:8090'
```

O resultado é:

```text
meufinanceiro-diagnostics-<utc>-<random>.zip
```

## Conteúdo permitido

O bundle contém somente evidência operacional sanitizada:

- `manifest.json`: formato, horário, lista de arquivos e garantias de privacidade;
- `README.txt`: instruções de revisão;
- `versions.txt`: versões de ferramentas;
- `host.txt`: sistema, arquitetura e espaço em disco sem hostname ou usuário;
- `git.txt`: commit, branch e alterações rastreadas com caminhos relativos ao repositório;
- `config-presence.txt`: presença e hashes de `.env` e keyring, sem conteúdo;
- `doctor.txt`: resultado do doctor;
- `compose-ps.json`: serviço, estado, health, exit code, imagem e portas;
- `health.json`: resposta sanitizada do readiness;
- `schema-revision.txt`: revisão Alembic atual, quando acessível;
- `logs.txt`: últimas 200 linhas dos serviços da fundação com redaction defensiva.

O bundle não contém:

- `.env` ou suas variáveis completas;
- `keyring.json` ou material criptográfico;
- dumps, SQL, certificados ou chaves privadas;
- payloads financeiros;
- upload automático;
- saída integral de `docker inspect` ou `docker info`.

## Problemas comuns

### Docker Desktop aberto, mas engine indisponível

Sintoma no Windows:

```text
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
```

Confirme:

```powershell
docker context show
docker version
docker info
docker compose version
```

O contexto esperado é normalmente `desktop-linux`. `docker version` precisa exibir Client e Server. Não execute os operadores enquanto o Server estiver ausente.

### Docker Compose v2 ausente

Confirme:

```text
docker compose version
```

O binário legado `docker-compose` não substitui o subcomando usado pelo projeto.

### Porta local ocupada

A instalação comum usa `127.0.0.1:8080` e o demo usa `127.0.0.1:8081` por padrão.

Verificação no Windows:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8080
```

Verificação em Linux, macOS ou WSL:

```bash
ss -ltn 'sport = :8080'
```

Altere apenas `APP_HTTP_PORT` no arquivo do ambiente correspondente. Não troque o bind para `0.0.0.0` como solução de porta.

### Serviço one-shot aparece como `Exited (0)`

`db-bootstrap` e `migrate` devem encerrar após concluir. `Exited (0)` é saudável para esses serviços.

Use:

```text
docker compose ps --all
```

Investigue somente quando o exit code for diferente de zero.

### API responde HTTP 503

Consulte:

```text
http://127.0.0.1:8080/api/v1/health/ready
```

A resposta separa processo, banco e schema. Causas frequentes:

- `database=unavailable`: PostgreSQL ainda não está saudável ou a role de runtime não conecta;
- `schema=outdated`: migração não chegou ao head esperado;
- keyring/configuração inválida: API e Worker recusam readiness.

Colete o bundle antes de tentar qualquer correção. Não execute downgrade Alembic.

### Migração ou bootstrap falhou

Consulte apenas os serviços envolvidos:

```text
docker compose logs --tail=200 migrate db-bootstrap postgres
```

Não edite manualmente `alembic_version`, não recrie a role com privilégios amplos e não remova o volume. O bundle diagnóstico inclui o exit code dos one-shots e a revisão atual.

### Volume PostgreSQL não encontrado

O volume deve estar montado em `/var/lib/postgresql` dentro do container PostgreSQL. O nome concreto depende do projeto Compose e não deve ser presumido.

Confirme o estado sem remover nada:

```text
docker compose ps --all
docker volume ls
```

Não use `docker volume rm`, `docker compose down --volumes` ou prune como troubleshooting.

### `.env` ou keyring ausente

Na instalação comum, ambos são criados pelo `dev-up`. No demo, ficam sob `.demo/`.

Não copie arquivos entre ambientes. Não regenere credenciais sobre uma instalação com dados sem seguir os runbooks de backup e key management.

### Permissão ou ACL bloqueia leitura

No Linux, verifique somente metadados:

```bash
ls -ld . .secrets
ls -l .env .secrets/keyring.json
```

No Windows:

```powershell
Get-Acl .env
Get-Acl .secrets\keyring.json
```

Não inclua o conteúdo dos arquivos em screenshots ou tickets. Ajustes de permissão devem manter acesso restrito ao usuário da instalação.

### Checkout com alterações rastreadas

O doctor gera `WARN`. Atualização segura recusa esse estado.

Confirme:

```text
git status --short
```

Não descarte alterações automaticamente. Revise, faça commit em branch própria ou preserve o trabalho antes de atualizar.

### Atualização exige recuperação coordenada

O estado:

```text
ROLLBACK_REQUIRES_COORDINATED_RESTORE
```

significa que o schema mudou ou ficou incerto. Preserve `.updates/` e o bundle de backup indicado. Não execute downgrade, não inicie versões aleatórias do código e não restaure dados sem autorização específica.

Consulte [Atualização segura e rollback controlado](SAFE_UPDATE_AND_ROLLBACK.md).

## O que nunca usar como correção genérica

```text
docker compose down --volumes
docker volume rm
docker system prune --volumes
alembic downgrade
rm -rf .secrets .backups .updates
```

Esses comandos podem destruir dados, credenciais ou evidências. Procedimentos destrutivos exigem escopo separado e autorização explícita.

## Relação com outros runbooks

- [Instalação da fundação](../guides/INSTALLATION.md)
- [Ambiente local](LOCAL_DEVELOPMENT.md)
- [Persistência, migrações e fila](PERSISTENCE_AND_TASK_QUEUE.md)
- [Backup e restauração verificável](BACKUP_AND_RESTORE.md)
- [Atualização segura e rollback controlado](SAFE_UPDATE_AND_ROLLBACK.md)
- [Gerenciamento do keyring](KEY_MANAGEMENT.md)
