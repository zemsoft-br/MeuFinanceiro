# Pluggy Spike

Laboratório descartável das issues #53, #55, #57, #59 e #61.

- Python 3.13, somente standard library.
- Não faz parte da API, worker, Flutter ou Compose.
- Não usa SDK.
- Não lê `.env`.
- Não cria Item diretamente.
- Usa Pluggy Connect em servidor `127.0.0.1`.
- Mantém API key, Connect Token e identificadores somente em memória ou na pasta
  local ignorada `.pluggy-spike/`.
- Nunca grava respostas brutas, credenciais ou dados financeiros em relatórios.
- Não atualiza, exclui ou recria Items.

Documentação:

- `docs/spikes/PLUGGY_SANDBOX_LAB.md`;
- `docs/spikes/PLUGGY_FINANCIAL_DATA_LAB.md`;
- `docs/spikes/PLUGGY_AUTH_LIFECYCLE_LAB.md`;
- `docs/spikes/PLUGGY_FINAL_REPORT.md`;
- `docs/architecture/BANKING_PROVIDER_CONTRACT.md`.

A spike foi concluída tecnicamente. Qualquer integração produtiva deve começar por
issue própria de persistência e segurança, sem reutilizar os scripts como runtime.
