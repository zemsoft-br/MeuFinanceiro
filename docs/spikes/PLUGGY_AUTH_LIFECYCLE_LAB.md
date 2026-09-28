# Laboratório Pluggy — ciclo de autenticação, retry e rate limit

Status: implementação da issue #59. Este laboratório permanece isolado do runtime do MeuFinanceiro, executa somente autenticação e consulta read-only de conectores e não acessa, atualiza ou exclui Items.

## Objetivo

Validar de forma sanitizada:

- criação e renovação da API key;
- uma única renovação após HTTP 401/403;
- tratamento de HTTP 429 com `RateLimit-Reset` ou `Retry-After`;
- backoff exponencial limitado com jitter para HTTP 5xx, timeout e falhas de rede;
- ausência de retry automático para erros funcionais como HTTP 400 e 404;
- separação entre API key, Connect Token, Item e consentimento bancário.

## Contrato oficial verificado em 27/07/2026

- A API key é criada por `POST /auth` com `CLIENT_ID` e `CLIENT_SECRET`.
- A API key possui validade documentada de duas horas.
- O Connect Token possui validade documentada de 30 minutos e escopo reduzido para o frontend.
- Ao expirar, a API key deve ser recriada com as credenciais da Application.
- Em HTTP 429, a Pluggy documenta `RateLimit-Reset` como a quantidade de segundos restante até a liberação e `Retry-After` como janela padrão de retry.
- `RateLimit-Reset` é a janela mais precisa e deve ser preferida quando válida.
- Não é necessário nem seguro provocar rate limit real por volume para validar o cliente.

Fontes oficiais:

- https://docs.pluggy.ai/reference/auth
- https://docs.pluggy.ai/docs/authentication
- https://docs.pluggy.ai/docs/glossary
- https://docs.pluggy.ai/docs/rate-limits

## Política implementada

### HTTP 401/403

Uma chamada read-only autenticada pode renovar a API key no máximo uma vez. Se a chamada repetida também retornar 401/403, a operação termina sem novo ciclo de autenticação.

### HTTP 429

A ordem de decisão é:

1. usar `RateLimit-Reset` quando representar entre 1 e 60 segundos;
2. usar `Retry-After` quando representar entre 1 e 60 segundos;
3. encerrar sem retry quando não houver janela utilizável.

A prova não persiste o valor exato dos cabeçalhos. O relatório registra somente presença dos cabeçalhos e buckets aproximados de espera.

### HTTP 5xx e rede

São permitidas no máximo três tentativas. As esperas usam backoff exponencial limitado e jitter. O jitter é injetável nos testes para manter a prova determinística.

### Erros funcionais

HTTP 400 e 404 não são repetidos automaticamente. A resposta bruta não é exibida nem persistida.

## Execução segura no PowerShell

```powershell
Set-Location "C:\Users\vinii\Desktop\GitHub\MeuFinanceiro"

$ClientId = Read-Host "Cole somente o CLIENT_ID"
$Secret = Read-Host "Cole somente o CLIENT_SECRET" -AsSecureString
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)

try {
    $env:PLUGGY_CLIENT_ID = $ClientId.Trim()
    $env:PLUGGY_CLIENT_SECRET =
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)

    py -3.13 tools/pluggy-spike/pluggy_auth_lifecycle.py auth-lifecycle
}
finally {
    if ($Pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
    }

    Remove-Item Env:PLUGGY_CLIENT_ID -ErrorAction SilentlyContinue
    Remove-Item Env:PLUGGY_CLIENT_SECRET -ErrorAction SilentlyContinue

    $ClientId = $null
    $Secret = $null
    $Pointer = [IntPtr]::Zero
}
```

Saída padrão:

```text
.pluggy-spike\reports\auth-lifecycle-<timestamp>.json
```

## Prova opcional de expiração real

```powershell
py -3.13 tools/pluggy-spike/pluggy_auth_lifecycle.py auth-lifecycle `
    --observe-expiration
```

Esse modo mantém o processo local aberto por mais de duas horas, usa a mesma API key somente em memória e repete apenas a consulta read-only de conectores. A prova considera a expiração observada somente quando a chamada recebe 401/403, cria uma nova API key uma vez e conclui a repetição com sucesso.

O modo é opcional porque a validade de duas horas já é documentada. A execução sem `--observe-expiration` valida autenticação, chamada segura, sanitização e toda a política de erro por testes controlados, sem manter um processo longo.

## Conteúdo do relatório

O relatório registra somente:

- data UTC, sem horário de sessão;
- contagem de tentativas de autenticação e leitura;
- contagem de renovações;
- códigos HTTP observados em falhas;
- presença de `Retry-After` e `RateLimit-Reset`;
- buckets aproximados de espera;
- contagem e nomes de campos do payload de conectores;
- flags explícitas de privacidade.

O relatório não registra:

- API key;
- Connect Token;
- Client ID ou Client Secret;
- headers de autenticação;
- resposta HTTP bruta;
- Item ID, Account ID ou qualquer identificador bancário;
- dados financeiros;
- horário exato da autenticação ou da expiração.

## Conceitos distintos

```text
API key
→ autentica o backend da Application
→ validade documentada de duas horas
→ renovada por POST /auth

Connect Token
→ autentica o Pluggy Connect no frontend
→ validade documentada de 30 minutos
→ não substitui a API key para dados detalhados

Item
→ representa uma conexão com uma instituição
→ não é criado, atualizado ou excluído neste laboratório

Consentimento bancário
→ autorização do usuário na instituição
→ pode exigir reautorização própria
→ não é renovado pela criação de uma nova API key
```

## Fora do escopo

- criar, atualizar, excluir ou recriar Items;
- revogar ou renovar consentimento bancário;
- executar carga para provocar HTTP 429 real;
- consultar contas, transações, faturas, investimentos ou empréstimos;
- sincronização incremental ou polling produtivo;
- integração com o backend principal;
- schema, migration, deploy, HML ou produção;
- pagamentos, DDA ou API comercial paga.
