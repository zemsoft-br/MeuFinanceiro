# ADR-0009 — Stitch como referência visual e arquitetura de informação canônica

- Status: Proposed
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O Google Stitch produziu uma cobertura visual ampla do MeuFinanceiro. A exportação contém 68 artefatos, telas duplicadas, estados apresentados como páginas, shells concorrentes, três variações de Design System, assets externos e HTML sem implementação funcional suficiente.

O ADR-0008 define Flutter como cliente canônico multiplataforma e preserva os contratos de PWA, acessibilidade e cache seguro validados pela PR #21. Falta definir como o material visual se relaciona com o código Flutter e quais rotas e experiências devem existir.

## Decisão

1. O Stitch é referência de UX e cobertura, não fonte de código ou arquitetura.
2. Nenhum HTML, Tailwind CDN, Google Font ou imagem remota do protótipo será copiado diretamente para o cliente Flutter.
3. A aplicação possuirá uma única base Flutter e um único shell funcional.
4. Estados vazio, erro, loading, API indisponível e demonstração serão estados condicionais.
5. Web/PWA, mobile e desktop usarão as mesmas rotas e contratos de produto quando o alvo oferecer a experiência.
6. O inventário em `docs/design/STITCH_SCREEN_INVENTORY.csv` define a classificação dos artefatos.
7. `docs/architecture/INFORMATION_ARCHITECTURE.md` define a proposta canônica de navegação.
8. Pluggy reutiliza Importações e Conciliação.
9. Empréstimos, patrimônio e administração usam o Design System global.
10. Regras do domínio e autorização prevalecem sobre qualquer representação visual.
11. `go_router`, definido no ADR-0008, implementará as rotas; os arquivos do Stitch não geram rotas automaticamente.

## Alternativas consideradas

### Copiar os HTMLs para Flutter

Rejeitada. Os HTMLs dependem de CDN, assets externos, interações estáticas e semântica incompleta. A conversão mecânica produziria widgets sem contrato de domínio, acessibilidade ou responsividade confiável.

### Manter uma rota por tela exportada

Rejeitada. Criaria duplicações, estados artificiais e aplicações mobile paralelas.

### Continuar corrigindo o Stitch até convergir

Rejeitada como estratégia principal. O Stitch é eficiente para exploração, mas não é autoridade sobre a estrutura do repositório.

### Ignorar os protótipos

Rejeitada. A cobertura funcional e visual reduz trabalho de descoberta quando usada de forma controlada.

## Consequências positivas

- uma única arquitetura de informação;
- menos duplicação;
- implementação local-first;
- separação clara entre design e regra;
- issues futuras podem citar referências canônicas;
- responsividade tratada como propriedade da mesma aplicação Flutter;
- referências visuais independentes da tecnologia geradora do protótipo.

## Consequências negativas e riscos

- exige reconstrução manual dos componentes em Flutter;
- algumas decisões visuais precisam ser reinterpretadas;
- o inventário deve ser atualizado quando uma referência mudar;
- rotas podem evoluir conforme o domínio real;
- a distância entre protótipo e produto precisa ser comunicada;
- acessibilidade e comportamento Web precisam ser revalidados no Flutter.

## Validação

- 68 artefatos classificados;
- rotas comparadas com a especificação e roadmap;
- dependências externas identificadas;
- duplicações de Dashboard, onboarding, metas e mobile consolidadas;
- revisão com o ADR-0008 antes de aceitar;
- nenhuma referência depende da permanência do shell React transitório.

## Referências

- ADR-0002 — Fonte local de verdade e adaptadores
- ADR-0008 — Flutter como cliente canônico multiplataforma
- `docs/design/STITCH_AUDIT.md`
- `docs/design/STITCH_SCREEN_INVENTORY.csv`
- `docs/design/STITCH_SOURCE_ARCHIVE.md`
- `docs/architecture/INFORMATION_ARCHITECTURE.md`
- Issue #22
