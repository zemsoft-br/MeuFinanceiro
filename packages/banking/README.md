# Banking

Pacote Python independente que materializa a fronteira neutra de integrações bancárias do MeuFinanceiro.

## Conteúdo

- `BankingProvider`: protocolo estrutural síncrono;
- enums e DTOs imutáveis;
- `BankingProviderError`: erro sanitizado e sem payload externo;
- `FakeBankingProvider`: implementação determinística exclusiva para testes.

## Restrições

Este pacote:

- usa apenas a biblioteca padrão do Python 3.13;
- não importa SDK, cliente HTTP, FastAPI, SQLAlchemy ou Pydantic;
- não contém API key, Connect Token, senha bancária ou MFA;
- não executa rede, persistência ou sincronização produtiva;
- não é instanciado pela API ou pelo worker neste recorte.

A implementação de um adaptador real deve converter dados externos para estes DTOs e impedir que tipos, sessões, tokens ou payloads do provider atravessem a fronteira.
