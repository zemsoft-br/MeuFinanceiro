# Instalação da fundação e avaliação segura

## Para quem é este guia

Este guia é destinado a quem deseja executar e avaliar a fundação do MeuFinanceiro no próprio computador, sem preparar um ambiente completo de contribuição.

O projeto ainda está em fase de fundação. **Não insira dados financeiros reais, credenciais bancárias, documentos pessoais ou informações de clientes.**

Para alterar código, executar a suíte completa ou abrir Pull Requests, consulte [Como contribuir](../../CONTRIBUTING.md) e o [runbook de quality gates](../runbooks/QUALITY_GATES.md).

## Estado atual

A instalação atual é feita a partir do código-fonte e constrói os containers localmente. Ainda não existe release estável, instalador gráfico ou distribuição por imagens publicadas.

A stack contém:

- cliente Flutter Web/PWA;
- API FastAPI;
- Worker;
- PostgreSQL;
- Caddy como única entrada HTTP local.

O PostgreSQL permanece em rede interna do Docker. Somente o Caddy publica uma porta no host, ligada a `127.0.0.1`.

## Escolha o ambiente

| Ambiente | Endereço padrão | Uso recomendado |
|---|---|---|
| Comum | `http://127.0.0.1:8080` | validar a fundação sem identificação demo |
| Demonstração | `http://127.0.0.1:8081` | avaliar a interface com isolamento e aviso explícito de dados fictícios |

Os dois ambientes usam projetos, volumes, credenciais e keyrings diferentes e podem ser executados simultaneamente.

A fixture demo atual contém somente os metadados determinísticos da fundação. Ela ainda não cria residência, membros, contas, categorias ou movimentações.

## Requisitos

### Todos os sistemas

- código-fonte do repositório;
- Docker Engine ou Docker Desktop em execução;
- Docker Compose v2;
- ao menos 2 GB de memória disponível para os containers;
- porta `8080` livre para o ambiente comum ou `8081` livre para o demo.

Confirme o Docker antes de continuar:

```text
docker version
docker compose version
```

O segundo comando deve informar Compose v2.

### Linux, macOS ou WSL 2

- shell compatível com os scripts do repositório;
- Python 3 disponível como `python3`.

O host não precisa ter Flutter instalado. O SDK fixado é usado dentro do build Docker.

### Windows

- Windows PowerShell;
- Docker Desktop configurado e iniciado.

O fluxo `dev-up.ps1` gera as credenciais e o keyring com APIs criptográficas do .NET e não depende de Python instalado no Windows.

## Obter o código

Enquanto não houver release estável, utilize a branch `develop`:

```text
git clone <URL_DO_REPOSITORIO>
cd MeuFinanceiro
git switch develop
git pull --ff-only
```

Execute os comandos seguintes sempre na raiz do repositório.

## Opção A — ambiente comum

Use este fluxo para validar a stack normal. O ambiente comum **não** deve exibir o aviso `Modo demonstração`.

### Linux, macOS ou WSL 2

```bash
./infra/scripts/dev-up.sh
```

### Windows PowerShell

```powershell
& .\infra\scripts\dev-up.ps1
```

Na primeira execução, o operador:

1. gera senhas administrativas e de runtime independentes;
2. cria `.env` e `.secrets/keyring.json`;
3. constrói os containers, incluindo o Flutter Web;
4. aplica as migrações;
5. inicia API, Worker, Web, PostgreSQL e Caddy;
6. executa o smoke test da stack.

Quando o processo concluir, abra:

```text
http://127.0.0.1:8080
```

### Confirmação esperada

- a interface Flutter abre sem o aviso `Modo demonstração`;
- `http://127.0.0.1:8080/api/v1/health/ready` responde com estado saudável;
- `http://127.0.0.1:8080/api/v1/demo/status` informa `"enabled": false` e `"loaded": false`.

### Parar sem apagar dados

Linux, macOS ou WSL 2:

```bash
./infra/scripts/dev-down.sh
```

Windows PowerShell:

```powershell
docker compose down
```

Esses comandos removem os containers e redes da execução, mas preservam o volume do PostgreSQL, `.env` e `.secrets`.

> Não acrescente `--volumes` ao comando de parada. Esse parâmetro remove o volume de dados e não faz parte do encerramento normal.

### Iniciar novamente

Execute outra vez o mesmo `dev-up` do seu sistema. A configuração e o volume existentes serão reutilizados.

## Opção B — ambiente demonstração

Use este fluxo para avaliar a interface com isolamento adicional. O aviso global `Modo demonstração` deve aparecer em todas as rotas.

### Linux, macOS ou WSL 2

```bash
bash infra/scripts/demo-up.sh up
```

### Windows PowerShell

```powershell
& .\infra\scripts\demo-up.ps1 -Action up
```

O operador cria `.demo/.env`, `.demo/secrets/keyring.json`, um projeto Compose próprio e um volume exclusivo. Em seguida, aplica as migrações, carrega a fixture e exige que a API confirme o modo demo.

Abra:

```text
http://127.0.0.1:8081
```

### Confirmação esperada

- a interface exibe `Modo demonstração`;
- o aviso informa que os dados são fictícios;
- `http://127.0.0.1:8081/api/v1/health/ready` responde com estado saudável;
- `http://127.0.0.1:8081/api/v1/demo/status` informa `"enabled": true` e `"loaded": true`.

### Consultar o estado

Linux, macOS ou WSL 2:

```bash
bash infra/scripts/demo-up.sh status
```

Windows PowerShell:

```powershell
& .\infra\scripts\demo-up.ps1 -Action status
```

### Parar sem apagar o volume demo

Linux, macOS ou WSL 2:

```bash
bash infra/scripts/demo-up.sh down
```

Windows PowerShell:

```powershell
& .\infra\scripts\demo-up.ps1 -Action down
```

### Apagar integralmente o ambiente demo

> **Atenção:** `purge` remove os containers, o volume, `.demo/.env` e o keyring do ambiente demonstração. Use somente quando desejar descartar todo o estado demo.

Linux, macOS ou WSL 2:

```bash
bash infra/scripts/demo-up.sh purge
```

Windows PowerShell:

```powershell
& .\infra\scripts\demo-up.ps1 -Action purge
```

A purga é limitada ao projeto `meufinanceiro-demo` e não deve remover o volume do ambiente comum.

## Diagnóstico inicial

### `Docker não encontrado`

Confirme que o Docker está instalado e disponível no terminal:

```text
docker version
```

No Windows e no macOS, confirme também que o Docker Desktop terminou de iniciar.

### `Docker Compose v2 não encontrado`

Execute:

```text
docker compose version
```

O projeto utiliza o subcomando `docker compose`. O binário legado `docker-compose` não substitui esse requisito.

### `Python 3 é necessário`

Esse erro se aplica aos operadores Unix. Instale Python 3 e confirme:

```text
python3 --version
```

O `dev-up.ps1` e o `demo-up.ps1` não exigem Python no host Windows.

### Execução de scripts bloqueada no PowerShell

Libere somente o processo atual e tente novamente:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Essa alteração termina quando a janela do PowerShell é fechada.

### Porta ocupada

Para o ambiente comum, altere `APP_HTTP_PORT` no arquivo `.env` e execute novamente o `dev-up`.

Para o demo, a primeira tentativa cria `.demo/.env`. Altere `APP_HTTP_PORT` nesse arquivo e execute novamente o comando `up`.

Mantenha a porta ligada a `127.0.0.1`. Este guia não autoriza exposição em `0.0.0.0`, LAN, domínio público ou internet.

### A interface não abre

Verifique os serviços, incluindo os one-shot:

```text
docker compose ps --all
```

No ambiente comum, consulte as últimas mensagens:

```text
docker compose logs --tail=200
```

Não publique logs sem revisar se contêm caminhos locais ou outras informações do host. Os operadores do projeto não imprimem senhas ou conteúdo do keyring.

Para diagnóstico técnico ampliado, consulte o [runbook do ambiente local](../runbooks/LOCAL_DEVELOPMENT.md) e o [runbook do modo demonstração](../runbooks/DEMO_MODE.md).

## Segurança

- não versione nem compartilhe `.env`, `.secrets`, `.demo` ou `.backups`;
- não copie senhas ou keyrings entre ambiente comum e demo;
- não insira credenciais Pluggy ou de qualquer integração externa;
- não altere a publicação do PostgreSQL;
- não exponha o Caddy publicamente com base neste guia;
- não utilize dados reais, mesmo no ambiente comum;
- faça backup validado antes de qualquer procedimento destrutivo futuro.

## Depois da instalação

Quando o ambiente comum estiver saudável, consulte o [runbook de backup e restauração verificável](../runbooks/BACKUP_AND_RESTORE.md). Ele cria um bundle coordenado de PostgreSQL, `.env` e keyring e prova a restauração em container descartável sem tocar na instalação.

O bundle contém senhas e chave mestra. Ele deve permanecer em armazenamento criptografado e nunca pode ser versionado ou anexado a issues.

Para avançar uma instalação comum baseada em código-fonte, consulte [Atualização segura e rollback controlado](../runbooks/SAFE_UPDATE_AND_ROLLBACK.md). O fluxo exige backup verificado e bloqueia rollback automático quando a revisão Alembic muda.

Restauração destrutiva real, acesso remoto e validação independente por outra pessoa permanecem em entregas separadas da issue #10.
