# Contrato inicial `BankingProvider`

Status: **proposto**. Não existe implementação produtiva nem persistência associada.

## Objetivo

Isolar provedores de Open Finance do domínio do MeuFinanceiro. O sistema deve continuar funcional sem provedor bancário, e nenhum tipo do SDK Pluggy pode atravessar essa fronteira.

## Princípios

- PostgreSQL local permanece a fonte principal de verdade.
- Integração bancária é opcional e configurada por instalação.
- O provedor nunca inicia pagamentos.
- Consentimento, conexão e sincronização são conceitos distintos.
- Respostas externas são convertidas em DTOs neutros antes de qualquer regra de domínio.
- Identificadores externos são opacos.
- Dados confirmados, pendentes e inferidos não são misturados.
- Remoção de uma conexão não apaga automaticamente registros financeiros já importados.

## Capacidades

Cada conexão declara explicitamente capacidades observadas:

```text
identity
bank_accounts
credit_accounts
transactions
credit_card_bills
investments
loans
manual_refresh
webhooks
```

Ausência de capacidade não é erro. Cobertura pode variar por conector, plano, consentimento e instituição.

## Tipos de fronteira propostos

```python
class BankingProvider:
    provider_name: str

    def create_connection_intent(
        self, residence_id: str, actor_id: str
    ) -> ConnectionIntent: ...

    def get_connection(self, external_connection_id: str) -> ConnectionState: ...

    def list_accounts(self, external_connection_id: str) -> list[ExternalAccount]: ...

    def list_transactions(
        self,
        external_account_id: str,
        cursor: str | None,
        changed_since: datetime | None,
    ) -> ExternalPage[ExternalTransaction]: ...

    def list_credit_card_bills(
        self, external_account_id: str
    ) -> list[ExternalCreditCardBill]: ...

    def list_investments(
        self, external_connection_id: str
    ) -> list[ExternalInvestment]: ...

    def list_loans(self, external_connection_id: str) -> list[ExternalLoan]: ...

    def request_refresh(self, external_connection_id: str) -> RefreshRequest: ...

    def disconnect(self, external_connection_id: str) -> None: ...
```

O exemplo é documental. A interface definitiva será criada somente junto do primeiro caso de uso do domínio.

## Estado de conexão

Estados internos mínimos:

```text
PENDING_USER_ACTION
SYNCING
AVAILABLE
PARTIAL
REAUTHENTICATION_REQUIRED
TEMPORARILY_UNAVAILABLE
RATE_LIMITED
DISCONNECTED
FAILED
```

O adaptador mapeia estados específicos do provedor para esse conjunto sem descartar o código externo original usado em diagnóstico local.

## Transações

Uma transação externa deve preservar distinções:

- `CONFIRMED`: confirmada pela instituição;
- `PENDING`: ainda sujeita a mudança;
- `INFERRED`: criada pelo MeuFinanceiro a partir de regra local;
- `DELETED`: antes fornecida, depois removida pelo provedor.

A chave de deduplicação não pode depender somente de descrição, data e valor. A estratégia inicial deve combinar identificador externo quando disponível, conta externa, estado, data, valor e fingerprint de campos estáveis observados.

## Idempotência e cursores

- cada página importada recebe identificador idempotente local;
- cursores externos são tratados como opacos;
- repetir a mesma página não cria novos lançamentos;
- mudança de `PENDING` para `CONFIRMED` atualiza a representação importada, não duplica;
- exclusões externas geram reconciliação explícita;
- falha parcial não avança cursor global indevidamente.

## Retry e limites

- `401/403`: renovar API key uma vez; depois exigir reautenticação/configuração;
- `409` ou Item em atualização: não iniciar execução concorrente;
- `429`/limite operacional: respeitar janela informada e não usar retry agressivo;
- `5xx`/rede: backoff exponencial limitado com jitter;
- erros de credencial ou ação do usuário: nunca retry automático;
- sincronização manual deve ser limitada e informar última atualização.

A Pluggy documenta limites operacionais por produto no Open Finance. O adaptador não deve prometer atualização em tempo real.

## Dados que não devem ser persistidos

- senha bancária;
- código MFA;
- API key;
- Connect Token;
- `CLIENT_SECRET` em banco;
- resposta HTTP bruta;
- material de chave privada/certificado de conector;
- campos não utilizados “por precaução”.

Credenciais da Application pertencem ao mecanismo seguro de configuração da instalação e nunca ao domínio financeiro.

## Desacoplamento da Pluggy

Mapeamento esperado:

```text
Pluggy Item           -> ExternalConnection
Pluggy Account        -> ExternalAccount
Pluggy Transaction    -> ExternalTransaction
Pluggy Bill           -> ExternalCreditCardBill
Pluggy Investment     -> ExternalInvestment
Pluggy Loan           -> ExternalLoan
Connect Token         -> ConnectionIntent temporário
```

Nenhum objeto Pluggy é retornado pelo contrato neutro.

## Validação necessária antes da aceitação

- laboratório sandbox concluído;
- fluxo real Meu Pluggy comprovado;
- schemas sanitizados comparados;
- campos estáveis e instáveis registrados;
- expiração e revogação exercitadas;
- limites observados confrontados com a documentação;
- estratégia sem webhook avaliada;
- ameaça e privacidade revisadas.

Até essa validação, este documento permanece proposto.
