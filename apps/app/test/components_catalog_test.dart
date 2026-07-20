import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/app/app.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/features/components_catalog/components_catalog_screen.dart';
import 'package:meufinanceiro_app/routing/app_router.dart';

import 'support/fake_health_transport.dart';

void main() {
  Future<void> pumpCatalog(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1200, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          initialLocationProvider.overrideWithValue('/componentes'),
          healthTransportProvider.overrideWithValue(
            operationalHealthTransport(),
          ),
        ],
        child: const MeuFinanceiroApp(),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('shows loading, empty, error and unavailable states',
      (tester) async {
    await pumpCatalog(tester);

    expect(find.text('Carregando informações'), findsOneWidget);
    expect(find.text('Nenhum item cadastrado'), findsOneWidget);
    expect(find.text('Não foi possível concluir'), findsOneWidget);
    expect(find.text('Serviço indisponível'), findsOneWidget);
  });

  testWidgets('rejects an invalid demonstrative form', (tester) async {
    await pumpCatalog(tester);

    await tester.ensureVisible(
      find.byKey(ComponentsCatalogScreen.submitKey),
    );
    await tester.tap(find.byKey(ComponentsCatalogScreen.submitKey));
    await tester.pumpAndSettle();

    expect(find.text('Informe o nome da residência.'), findsOneWidget);
    expect(find.byKey(ComponentsCatalogScreen.successKey), findsNothing);
  });

  testWidgets('accepts a valid demonstrative form without persistence',
      (tester) async {
    await pumpCatalog(tester);

    await tester.enterText(
      find.byKey(ComponentsCatalogScreen.residenceFieldKey),
      'Residência Ipê',
    );
    await tester.ensureVisible(
      find.byKey(ComponentsCatalogScreen.submitKey),
    );
    await tester.tap(find.byKey(ComponentsCatalogScreen.submitKey));
    await tester.pumpAndSettle();

    expect(find.byKey(ComponentsCatalogScreen.successKey), findsOneWidget);
    expect(find.text('Validação concluída.'), findsOneWidget);
  });
}
