# ADR-0002 — Modelo local como fonte de verdade e integrações por adaptadores

- Status: Accepted
- Data: 2026-07-19
- Decisores: mantenedores

## Contexto

O produto receberá dados manuais, arquivos e integrações Open Finance. A disponibilidade e a qualidade de provedores variam por instituição, plano e tempo.

Acoplar o domínio diretamente à Pluggy impediria uso offline, dificultaria importações alternativas e aumentaria o risco de perda funcional quando uma conexão expirasse.

## Decisão

O modelo financeiro normalizado no PostgreSQL será a fonte de verdade do produto.

Pluggy, OFX, CSV, PDF, QIF e provedores futuros serão adaptadores que geram observações, candidatos, críticas e conciliações. Eles não sobrescrevem silenciosamente decisões confirmadas pelo usuário.

O sistema armazenará a origem e os campos necessários à auditoria e deduplicação, sem exigir retenção integral do payload bruto de APIs externas.

## Alternativas consideradas

### Pluggy como fonte principal

Rejeitada por criar dependência operacional e funcional de um serviço externo opcional.

### Armazenar somente extratos brutos e calcular tudo sob demanda

Rejeitada porque dificulta edição local, conciliação, projeções, autorização e evolução de formatos.

### Plugins arbitrários dentro do backend

Rejeitada na fundação por risco de segurança, compatibilidade e acesso irrestrito aos dados.

## Consequências positivas

- funcionamento sem integração bancária;
- histórico preservável após desconexão;
- importadores compartilham o mesmo ciclo de validação;
- novos provedores não alteram o núcleo;
- usuário controla conflitos entre fontes.

## Consequências negativas e riscos

- exige modelo de deduplicação e conciliação robusto;
- normalização pode perder campos não previstos;
- mudanças do domínio exigem migrações locais;
- adaptadores precisam acompanhar mudanças externas.

## Validação

A arquitetura deve provar que uma residência consegue operar completamente com dados manuais e arquivos antes da integração Pluggy ser necessária.
