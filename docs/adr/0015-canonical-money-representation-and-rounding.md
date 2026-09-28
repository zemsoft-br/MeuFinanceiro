# ADR-0015 — Representação monetária e arredondamento canônicos

- Status: Accepted
- Data: 2026-08-11
- Decisores: mantenedores

## Contexto

O ADR-0010 e `docs/architecture/FINANCIAL_INVARIANTS.md` exigem uma decisão explícita de dinheiro antes da primeira funcionalidade financeira. O produto precisa representar BRL e moedas estrangeiras observadas em cartões/importações sem depender de `float`, sem arredondamento implícito e sem cristalizar formatos incompatíveis entre PostgreSQL, FastAPI e Flutter.

As observações bancárias já usam `Decimal`, porém esse uso é específico da integração e não constitui contrato do livro financeiro.

## Decisão

### Representação interna

O domínio financeiro usa um value object `Money` composto por:

```text
amount: Decimal
currency: código ASCII uppercase de três letras
```

`float` não é aceito nem convertido implicitamente.

O amount deve ser finito. O contrato de persistência para valores monetários futuros é:

```text
NUMERIC(24,8)
```

Isso permite até 16 dígitos inteiros e até 8 casas decimais. O value object valida esse limite antes da persistência.

Trailing zeroes não possuem significado de identidade e podem ser removidos na forma canônica. Zero negativo é normalizado para zero.

### Serialização

Contratos HTTP financeiros futuros devem serializar:

```json
{
  "amount": "123.45",
  "currency": "BRL"
}
```

`amount` é string decimal fixed-point, sem notação exponencial. JSON number não é autoridade financeira.

O Flutter deve consumir esse campo como representação decimal segura; `double` não deve ser usado como fonte de verdade para valores financeiros.

### Arredondamento

Construção, persistência, soma e subtração não arredondam silenciosamente.

Quando um caso de uso exige quantização, ele deve informar explicitamente:

- escala alvo;
- modo de arredondamento.

Modos iniciais permitidos:

```text
HALF_EVEN
HALF_UP
DOWN
```

Não existe modo default no value object.

A quantidade de casas padrão de uma moeda, regras fiscais, taxas cambiais ou regras específicas de instituição pertencem aos respectivos casos de uso e não ao `Money` genérico.

### Aritmética

Soma, subtração e comparação ordenada exigem moedas iguais. Operações cross-currency falham fechado.

Nenhuma taxa de câmbio é inferida. Conversões futuras devem registrar no mínimo taxa, instante/data de referência, fonte e política de arredondamento.

Valores negativos e zero são representáveis no value object. Cada agregado decide quando esses valores são válidos.

### Privacidade

`repr`/`str` do `Money` não exibem o amount. O valor permanece acessível apenas por atributo explícito ou serialização deliberada do caso de uso.

## Alternativas consideradas

### `float`/`double`

Rejeitada por erro binário de representação e inconsistência de arredondamento.

### Inteiro em centavos

Rejeitada como contrato geral porque o produto precisa preservar valores com mais de duas casas em câmbio, taxas, investimentos e fontes externas. Casos específicos podem derivar unidades mínimas quando necessário.

### `NUMERIC(18,2)`

Rejeitada por perder precisão útil de fontes externas e cálculos intermediários.

### Arredondamento automático para duas casas

Rejeitado. Nem toda moeda ou operação possui duas casas e arredondamento silencioso torna conciliação e auditoria não reproduzíveis.

### Catálogo ISO-4217 completo no núcleo

Adiado. O primeiro contrato exige somente código ASCII uppercase de três letras. Regras de minor units exigem issue própria antes de serem usadas como autoridade.

## Consequências positivas

- um único contrato monetário para contas, movimentos, cartões, dívidas e patrimônio;
- ausência de `float` no domínio;
- serialização estável entre Python e Flutter;
- precisão suficiente para dados externos sem perda silenciosa;
- arredondamento auditável e dependente do caso de uso;
- operações cross-currency não passam despercebidas.

## Consequências negativas e riscos

- APIs precisam representar amount como string;
- Flutter precisará de tratamento decimal explícito antes das primeiras telas financeiras;
- `NUMERIC(24,8)` consome mais espaço que valores em centavos;
- regras de minor units e câmbio continuam exigindo decisões próprias;
- aggregates devem declarar semântica de sinal em vez de delegá-la ao `Money`.

## Validação

O pacote `meufinanceiro-finance` materializa esta decisão com testes para:

- rejeição de float e valores não finitos;
- precisão/escala compatíveis com `NUMERIC(24,8)`;
- moeda ASCII uppercase;
- serialização fixed-point por string;
- soma/subtração e ordenação somente na mesma moeda;
- quantização com modo explícito;
- redaction de `repr`/`str`.

## Referências

- #124
- #125
- ADR-0010
- `docs/PRODUCT_SPECIFICATION.md`
- `docs/architecture/FINANCIAL_INVARIANTS.md`
- `docs/architecture/IMPLEMENTATION_SEQUENCE.md`
