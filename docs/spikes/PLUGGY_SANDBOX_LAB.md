# Laboratório Pluggy Sandbox

Status: implementação da issue #53. Este laboratório não integra a Pluggy ao runtime do MeuFinanceiro.

## Objetivo

Validar autenticação, Connect Token, Pluggy Connect e inventário dos schemas usando somente o conector fictício **Pluggy Bank**. Nenhum banco real, dado financeiro real, webhook público, schema produtivo ou SDK entra neste recorte.

## Fatos oficiais verificados em 26/07/2026

- `CLIENT_ID` e `CLIENT_SECRET` são trocados no backend por uma API key com validade documentada de duas horas.
- Connect Token é destinado ao frontend, tem escopo reduzido e validade documentada de 30 minutos.
- O plano gratuito pode impedir `POST /items`; a criação deve ocorrer pelo Pluggy Connect Widget.
- O widget oferece `includeSandbox=true`.
- Pluggy Bank usa usuários de teste. O fluxo de sucesso documentado usa `user-ok`, `password-ok` e, quando solicitado, MFA `123456`.
- Conectores devem ser consultados dinamicamente; seus metadados podem mudar.
- Limites do Open Finance variam por produto, CPF/CNPJ e instituição. Criar múltiplos Items para a mesma autorização pode consumir limites desnecessariamente.
- O repositório oficial do Meu Pluggy descreve um fluxo em que uma Development Application autoriza acesso por proxy às conexões mantidas pelo Meu Pluggy. Esse fluxo ainda precisa ser comprovado nesta conta.

Fontes oficiais:

- https://docs.pluggy.ai/reference/auth
- https://docs.pluggy.ai/reference/connect-token-create
- https://docs.pluggy.ai/docs/authentication
- https://docs.pluggy.ai/docs/environments-and-configurations
- https://docs.pluggy.ai/docs/create-your-first-item
- https://docs.pluggy.ai/reference/items
- https://docs.pluggy.ai/docs/rate-limits-of
- https://github.com/pluggyai/meu-pluggy

## Segurança

1. Nunca informe credenciais por argumento de linha de comando.
2. Defina-as apenas no processo local:
   - `PLUGGY_CLIENT_ID`
   - `PLUGGY_CLIENT_SECRET`
3. Não use `.env` neste laboratório.
4. Não anexe `.pluggy-spike/`, respostas brutas ou screenshots com caminhos pessoais.
5. O servidor local escuta somente `127.0.0.1`.
6. O Connect Token fica apenas em memória e expira rapidamente.
7. Revise o JSON sanitizado antes de compartilhar.

## Preparação da Application

No Dashboard Pluggy:

1. crie uma **Development Application**;
2. não publique as credenciais;
3. mantenha Pluggy Bank habilitado;
4. para o teste posterior do Meu Pluggy, habilite o conector correspondente e use o Preview/Demo oficial;
5. revogue e recrie a credencial se houver qualquer suspeita de exposição.

## Comandos

Windows PowerShell:

```powershell
$env:PLUGGY_CLIENT_ID = "<somente-local>"
$env:PLUGGY_CLIENT_SECRET = "<somente-local>"

py -3.13 tools/pluggy-spike/pluggy_spike.py probe
py -3.13 tools/pluggy-spike/pluggy_spike.py serve
```

Linux, macOS ou WSL:

```bash
export PLUGGY_CLIENT_ID='<somente-local>'
export PLUGGY_CLIENT_SECRET='<somente-local>'

python3.13 tools/pluggy-spike/pluggy_spike.py probe
python3.13 tools/pluggy-spike/pluggy_spike.py serve
```

O navegador abrirá uma página local. Use apenas Pluggy Bank:

```text
user: user-ok
password: password-ok
MFA: 123456
```

Após sucesso, o callback grava somente Item ID, status e horário em `.pluggy-spike/last-item.json`. Esse arquivo permanece local e ignorado pelo Git.

Para inventariar metadados, sem valores:

```powershell
$item = (Get-Content .pluggy-spike/last-item.json | ConvertFrom-Json).item_id
py -3.13 tools/pluggy-spike/pluggy_spike.py collect --item-id $item
```

O relatório contém somente contagens, nomes de campos, estados e fingerprint efêmero. Ele não contém resposta bruta, saldo, descrição, número de conta, nome do titular, documento ou token.

## Cenários do sandbox

Executar e registrar separadamente:

1. login bem-sucedido;
2. MFA bem-sucedido;
3. credencial inválida;
4. indisponibilidade simulada oferecida pelo Pluggy Bank;
5. repetição com `avoidDuplicates=true`;
6. coleta de contas, investimentos e empréstimos quando o usuário sandbox escolhido oferecer esses produtos.

## Perguntas ainda não confirmadas

Estas perguntas dependem da Application e do conector Meu Pluggy real:

- o “Conector 200” ainda mantém esse identificador e nome no contrato atual;
- quais produtos ficam disponíveis após o trial;
- frequência real de atualização do proxy Meu Pluggy;
- histórico efetivo por produto;
- comportamento de cartões, faturas, transações pendentes e parcelas futuras;
- disponibilidade de investimentos e empréstimos;
- expiração, revogação e reconexão;
- campos estáveis para deduplicação;
- possibilidade segura de sincronização manual sem webhooks.

Não transformar essas hipóteses em contrato produtivo antes da prova real.
