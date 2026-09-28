# Changelog

Este arquivo registra as mudanças relevantes das versões publicáveis do MeuFinanceiro.

## [0.1.0-alpha.1] - 2026-09-28

### Primeiro Alpha

- Ambiente local e autohospedado distribuído com Docker Compose, com cliente Flutter Web/PWA.
- Autenticação local e modo demonstração para avaliação do produto sem depender de integração bancária.
- Núcleo financeiro com contas, saldos derivados e extrato.
- Receitas e despesas manuais.
- Transferências entre contas compatíveis, incluindo reversão de transferências.
- Reversão de movimentações manuais suportadas.
- Backend com autoridade de sessão e residência para operações financeiras.
- APIs semânticas de movimentação, proteção de idempotência e valores monetários representados por strings decimais nos contratos aplicáveis.
- Backup e restauração verificável da instalação local.
- Atualização segura com rollback controlado.
- Diagnósticos sanitizados para suporte e troubleshooting.
- Fundações bancárias neutras em relação ao provider, incluindo contratos e adaptadores read-only relacionados à Pluggy e Open Finance.
- Lifecycle local de consentimento e disconnect com preservação de histórico.
- Proteção contra writes derivados do provider depois do disconnect.
- Bridge de banking para ledger e mecanismos de observação e reconciliação já presentes no backend.

### Limitações deste Alpha

- Esta versão é uma prerelease Alpha e não deve ser tratada como versão de produção.
- Ainda não utilize o MeuFinanceiro com dados financeiros reais.
- As integrações bancárias existentes são fundações técnicas e não constituem uma experiência completa de Open Finance pronta para produção.
- Operação real com Pluggy não faz parte do marco validado desta release.
- Homologação, produção e deploy não fazem parte da validação deste marco.
- Funcionalidades previstas no roadmap não devem ser consideradas disponíveis apenas por constarem na documentação de produto.
- Este marco não declara como concluídos módulos completos de importações, cartões, orçamento, empréstimos ou investimentos.
