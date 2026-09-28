# ADR-0014 — Residência primária derivada da associação do operador

- Status: Accepted
- Data: 2026-08-06
- Decisores: mantenedores

## Contexto

A persistência bancária aplica RLS por `residence_id`, mas esse identificador ainda não possuía entidade canônica ou associação com o operador autenticado. Aceitar um UUID fornecido pelo cliente criaria contexto órfão e permitiria que autorização e isolamento dependessem de um identificador não comprovado.

O produto começa com uma instalação por banco e um operador administrador local. Antes de implementar múltiplos membros, convites ou troca de residência, é necessário criar um contexto doméstico mínimo, legítimo e derivável da sessão.

## Decisão

- O schema `household` contém residências e associações entre residência e operador.
- O bootstrap inicial cria instalação, operador, residência primária e associação `owner` em uma única transação.
- Instalações anteriores podem executar um comando local idempotente que cria somente o contexto ausente.
- Uma associação primária deve estar ativa e apontar para residência ativa.
- Existe no máximo uma associação primária ativa por operador.
- `OperatorSessionPrincipal.primary_residence_id` é resolvido pela persistência; nunca é aceito em login ou payload do cliente.
- Sessões de instalações antigas sem associação continuam válidas para autenticação e recuperação, mas operações que exigem residência usam uma dependência fail-closed.
- A role de runtime possui SELECT, INSERT e UPDATE no schema household, mas não DELETE.
- Nenhuma rota bancária pode aceitar `residence_id` arbitrário. Futuros casos de uso devem usar o contexto derivado.

O schema household não recebe RLS neste recorte. A única leitura executável busca a associação do próprio operador autenticado sob `installation_id + operator_id`, e ainda não há endpoints de membros. Antes de introduzir múltiplos operadores ou seleção de residência, uma issue própria deverá definir políticas RLS, autorização por papel e mudança de contexto.

## Alternativas consideradas

### Usar installation ID como residence ID

Rejeitado. Mistura limites distintos, impede múltiplas residências futuras e torna os dados bancários semanticamente ambíguos.

### Gerar residence ID no cliente

Rejeitado. O servidor não conseguiria comprovar existência, associação ou autorização do identificador.

### Aceitar residence ID em cada rota

Rejeitado. Aumenta a superfície de IDOR e obriga cada handler a reconstruir a autorização.

### Implementar imediatamente membros e convites completos

Adiado. O recorte aumentaria significativamente schema, UX, autorização e recuperação antes de existir necessidade operacional.

## Consequências positivas

- o contexto bancário futuro deriva de uma entidade real;
- bootstrap novo produz instalação utilizável sem UUID órfão;
- instalações anteriores possuem correção explícita e idempotente;
- sessões carregam contexto confiável sem payload adicional;
- a evolução para múltiplos membros mantém separação entre instalação e residência.

## Consequências negativas e riscos

- instalações existentes precisam executar o comando de correção antes de operações por residência;
- a ausência de RLS household limita o recorte a um único operador;
- troca de residência primária e múltiplos membros exigirão novas decisões;
- as conexões bancárias existentes ainda não possuem FK para household até uma migração posterior.

## Validação

- migration e grants em PostgreSQL real;
- bootstrap atômico de quatro entidades;
- recuperação idempotente;
- unique parcial para associação primária;
- sessão com contexto derivado ou `None` legítimo;
- dependência HTTP fail-closed;
- role runtime sem DELETE;
- contrato estático que proíbe `residence_id` em payload bancário.

## Referências

- ADR-0012 — Persistência, segurança e feature flag da integração bancária.
- ADR-0013 — Autenticação local de operador e sessões opacas.
