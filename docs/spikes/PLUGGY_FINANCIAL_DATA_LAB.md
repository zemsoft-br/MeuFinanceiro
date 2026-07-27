# Laboratório Pluggy — transações, cartões e faturas

Status: implementação da issue #57. Este laboratório continua isolado do runtime do MeuFinanceiro e não cria schema, migration, webhook ou sincronização produtiva.

## Objetivo

Consultar a API Pluggy de forma read-only para inventariar:

- transações por conta;
- contas de cartão de crédito;
- faturas associadas aos cartões;
- estados `PENDING` e `POSTED`;
- presença de metadados de parcelas;
- paginação e intervalo temporal aproximado;
- campos candidatos a deduplicação e sincronização incremental.

O relatório não persiste valores financeiros, descrições, titulares, documentos, números de conta/cartão, identificadores externos, cursores ou datas financeiras completas.

## Contrato oficial verificado em 27/07/2026

- Cartões são retornados como `Account` com `type=CREDIT` e `subtype=CREDIT_CARD`.
- Transações são consultadas por conta em `GET /v2/transactions?accountId=...`.
- A paginação de transações é orientada por cursor por meio do campo `next`.
- A documentação informa páginas de até 500 transações e histórico de até 12 meses.
- Faturas são consultadas em `GET /bills?accountId=...`.
- Transações de fatura aberta ou parcelas futuras podem aparecer como `PENDING`.
- Transações vinculadas a uma fatura vencida podem aparecer como `POSTED` e possuir `billId`.
- O identificador de uma transação pode mudar quando dados materiais são alterados pelo provedor.
- Não existe identificador único garantido para agrupar todas as parcelas de uma mesma compra.
- Cobertura de faturas varia conforme instituição e tipo de conexão.

Fontes oficiais:

- https://docs.pluggy.ai/reference/accounts-list
- https://docs.pluggy.ai/reference/transactions-list-by-cursor
- https://docs.pluggy.ai/docs/transactions
- https://docs.pluggy.ai/reference/bills-list
- https://docs.pluggy.ai/docs/credit-card-bills
- https://docs.pluggy.ai/docs/credit-card-installments
- https://docs.pluggy.ai/docs/basic-concepts

## Segurança

1. Use somente dados do próprio mantenedor.
2. Nunca informe `CLIENT_ID`, `CLIENT_SECRET`, API key ou Item ID por argumento gravado em script ou histórico compartilhado.
3. Defina `PLUGGY_CLIENT_ID` e `PLUGGY_CLIENT_SECRET` apenas no processo local.
4. O Item ID é validado como UUID e usado somente em memória.
5. Account IDs, Transaction IDs, Bill IDs e cursores nunca são gravados no relatório.
6. O cursor retornado pela Pluggy só é aceito quando é relativo, aponta para `/v2/transactions` e permanece vinculado à mesma conta.
7. `--max-accounts` e `--max-pages` limitam o volume de chamadas.
8. Revise o JSON sanitizado antes de compartilhar.

## Execução segura no PowerShell

Use o Item que retornou contas na validação anterior:

```powershell
Set-Location "C:\Users\vinii\Desktop\GitHub\MeuFinanceiro"

$ItemId = Read-Host "Cole o ITEM_ID"
$ClientId = Read-Host "Cole somente o CLIENT_ID"
$Secret = Read-Host "Cole somente o CLIENT_SECRET" -AsSecureString
$Pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)

try {
    $env:PLUGGY_CLIENT_ID = $ClientId.Trim()
    $env:PLUGGY_CLIENT_SECRET =
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Pointer)

    py -3.13 tools/pluggy-spike/pluggy_financial.py `
        --item-id $ItemId.Trim() `
        --max-accounts 10 `
        --max-pages 5
}
finally {
    if ($Pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Pointer)
    }

    Remove-Item Env:PLUGGY_CLIENT_ID -ErrorAction SilentlyContinue
    Remove-Item Env:PLUGGY_CLIENT_SECRET -ErrorAction SilentlyContinue

    $ItemId = $null
    $ClientId = $null
    $Secret = $null
    $Pointer = [IntPtr]::Zero
}
```

Resultado esperado:

```text
Prova sanitizada gravada em .pluggy-spike\reports\financial-collection-<data>.json
```

## Limites locais

- `--max-accounts`: de 1 a 25; padrão 10.
- `--max-pages`: de 1 a 20 por conta; padrão 5.
- Quando o limite é atingido e ainda existe cursor, o relatório marca `truncated=true`.
- Contas sem ID válido são registradas como ignoradas, sem abortar toda a coleta.
- Payloads vazios são registrados com zero registros, sem serem tratados como falha.

## Conteúdo do relatório

O JSON registra somente:

- status sanitizado do Item;
- quantidade e schema das contas;
- quantidade de contas de cartão;
- ordinal local de cada conta, tipo e subtipo;
- quantidade de transações, páginas e presença de cursor;
- contagem de estados `PENDING` e `POSTED`;
- nomes de campos e caminhos aninhados;
- presença de metadados de parcelas e vínculo com fatura;
- quantidade e schema das faturas;
- buckets aproximados de amplitude temporal;
- presença de campos candidatos a deduplicação e atualização incremental;
- flags explícitas de privacidade.

O JSON não registra:

- Item ID, Account ID, Transaction ID ou Bill ID;
- cursor de paginação;
- valor, saldo, limite ou moeda;
- descrição, estabelecimento ou categoria;
- nome, documento, agência ou número de conta/cartão;
- data completa da transação ou fatura;
- resposta HTTP bruta;
- API key, Connect Token, Client ID ou Client Secret.

## Interpretação

- `credit_card_count=0` não é erro; o Item pode não possuir cartão ou o conector pode não fornecer essa capacidade.
- `bills.record_count=0` não prova ausência de cartão; a instituição pode não retornar faturas nesse fluxo.
- `PENDING` e `POSTED` devem permanecer estados distintos no futuro adaptador.
- `external_id_stability=MAY_CHANGE_AFTER_MATERIAL_UPDATE` impede usar somente o ID externo como garantia absoluta de continuidade.
- Deduplicação produtiva ainda deverá combinar identificador externo, conta externa, estado, datas, valor e fingerprint de campos estáveis observados, sem depender apenas de descrição/data/valor.

## Fora do escopo

- integração com backend principal;
- persistência de dados bancários;
- migration ou schema;
- webhooks produtivos;
- atualização ou exclusão de Items;
- iniciação de pagamentos ou DDA;
- deploy, HML ou produção.


## Capacidades indisponíveis por conta

Um `HTTP 404` retornado por uma consulta de transações ou faturas não encerra mais
toda a prova. O laboratório registra a capacidade como
`NOT_AVAILABLE_HTTP_404`, informa apenas o ordinal local da conta no terminal e
continua com as demais contas. Item ID, Account ID e corpo bruto do erro não são
impressos nem persistidos. Outros códigos HTTP continuam sendo tratados como falha.


## Validação contra falsos positivos

Credenciais, API key e Item ID continuam bloqueados por busca de substring. Valores sensíveis observados nos payloads financeiros são comparados por igualdade exata contra os valores escalares do relatório. Essa separação evita que um sufixo numérico ou fragmento de data seja confundido com uma contagem ou timestamp sanitizado, sem permitir que o valor bruto seja persistido.
