# Cliente Flutter

Base canônica do cliente MeuFinanceiro.

## Estado

A Fase B da migração reconstrói em Flutter os contratos do shell React sem
alterar o runtime servido pelo Docker Compose.

O cliente contém:

- rotas nomeadas `/`, `/componentes` e `/sistema`;
- shell responsivo com sidebar desktop, drawer e navegação inferior móvel;
- tema e tokens locais, sem fontes ou assets remotos;
- catálogo de componentes, formulário demonstrativo e estados comuns;
- health check testável com timeout e classificação operacional, degradada e
  indisponível;
- dependências de plataforma atrás de interfaces;
- testes de rota, widget, foco, semântica, responsividade e health.

O shell React permanece como runtime ativo até as entregas de Docker/PWA e a
validação de paridade operacional da issue #24.

## Organização

```text
lib/
  app/        composição e shell
  core/       contratos e serviços independentes de UI
  features/   páginas e estados por experiência
  platform/   adaptadores condicionais de plataforma
  routing/    rotas e destinos canônicos
  theme/      tokens, tema e componentes-base
```

## Comandos

```bash
flutter pub get --enforce-lockfile
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter build web --release
```

Use exatamente a versão registrada em `/.flutter-version`.
