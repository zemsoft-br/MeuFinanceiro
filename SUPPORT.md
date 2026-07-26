# Suporte

## Dúvidas de uso e instalação

Durante a fase de fundação, use uma issue somente quando houver um problema reproduzível ou uma melhoria claramente descrita pelos formulários disponíveis.

Antes de abrir:

1. consulte o `README.md` e os documentos em `docs/`;
2. execute o `doctor` correspondente ao seu sistema;
3. consulte o [runbook de diagnóstico sanitizado e troubleshooting](docs/runbooks/DIAGNOSTICS_AND_TROUBLESHOOTING.md);
4. procure issues abertas equivalentes;
5. remova credenciais, dados pessoais e informações financeiras da evidência.

Quando a análise exigir logs ou estado da stack, prefira o bundle produzido por:

```text
infra/scripts/diagnostics-export.sh
infra/scripts/diagnostics-export.ps1
```

Extraia e revise todos os arquivos antes de compartilhar. O bundle não deve ser enviado automaticamente e não substitui backup.

O projeto não oferece suporte privado garantido nem atendimento com prazo de resposta.

## Bugs

Use o formulário **Relatório de problema** e inclua versão, ambiente, reprodução, comportamento esperado e impacto. Anexe evidência somente depois de confirmar que o arquivo não contém `.env`, keyring, dumps, senhas, tokens, caminhos privados ou dados financeiros.

## Propostas

Use o formulário **Proposta ou spike técnico** para funcionalidades, integrações e decisões que ainda precisam de refinamento.

## Vulnerabilidades

Não abra issue pública. Siga `SECURITY.md` e utilize o canal privado de security advisories do GitHub quando disponível.

## Dados que nunca devem ser publicados

- credenciais Pluggy;
- tokens e chaves;
- `.env`, keyring ou bundles de backup;
- arquivos OFX, CSV, PDF ou QIF reais;
- CPF, e-mail, nomes completos ou dados bancários;
- dumps de banco;
- logs sem sanitização;
- capturas com saldos, transações ou identificadores reais.
