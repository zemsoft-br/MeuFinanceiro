# Cliente Flutter

Base canônica do cliente MeuFinanceiro.

## Estado

Nesta etapa, o projeto comprova somente:

- toolchain fixada;
- composição Riverpod;
- roteamento GoRouter;
- análise, testes e build Web reproduzíveis.

O shell React permanece como runtime ativo até as entregas de paridade e Docker/PWA da issue #24.

## Comandos

```bash
flutter pub get --enforce-lockfile
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter build web --release
```

Use exatamente a versão registrada em `/.flutter-version`.
