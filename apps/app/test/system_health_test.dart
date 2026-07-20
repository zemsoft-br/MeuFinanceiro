import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/app/app.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/features/system_health/system_health_screen.dart';
import 'package:meufinanceiro_app/routing/app_router.dart';

import 'support/fake_health_transport.dart';

void main() {
  Future<void> pumpSystem(
    WidgetTester tester,
    FakeHealthTransport transport, {
    bool settle = true,
    AsyncValue<ApiHealthSnapshot>? healthOverride,
  }) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          initialLocationProvider.overrideWithValue('/sistema'),
          if (healthOverride != null)
            apiHealthProvider.overrideWithValue(healthOverride),
          healthTransportProvider.overrideWithValue(transport),
          healthClockProvider.overrideWithValue(
            () => DateTime.utc(2026, 7, 20, 1, 2, 3),
          ),
        ],
        child: const MeuFinanceiroApp(),
      ),
    );

    if (settle) {
      await tester.pumpAndSettle();
    } else {
      await tester.pump();
    }
  }

  testWidgets('renders checking before the health response completes',
      (tester) async {
    await pumpSystem(
      tester,
      operationalHealthTransport(),
      settle: false,
      healthOverride: const AsyncValue<ApiHealthSnapshot>.loading(),
    );

    expect(find.text('Verificando'), findsWidgets);
    expect(find.text('Verificando o ambiente'), findsOneWidget);
  });

  testWidgets('renders operational health details', (tester) async {
    await pumpSystem(tester, operationalHealthTransport());

    expect(find.text('Operacional'), findsWidgets);
    expect(find.text('API e persistência'), findsOneWidget);
    expect(find.text('ok'), findsWidgets);
    expect(find.text('01:02:03'), findsOneWidget);
  });

  testWidgets('renders degraded health without blocking navigation',
      (tester) async {
    await pumpSystem(tester, degradedHealthTransport());

    expect(find.text('Atenção'), findsWidgets);
    expect(find.text('Serviço parcialmente disponível'), findsOneWidget);
    expect(find.text('unavailable'), findsOneWidget);
  });

  testWidgets('renders unavailable health after timeout', (tester) async {
    await pumpSystem(tester, timeoutHealthTransport());

    expect(find.text('Indisponível'), findsWidgets);
    expect(find.text('API indisponível'), findsOneWidget);
    expect(find.text('não verificado'), findsWidgets);
  });

  testWidgets('refresh invalidates the provider and performs another check',
      (tester) async {
    final transport = operationalHealthTransport();
    await pumpSystem(tester, transport);

    await tester.tap(find.byKey(SystemHealthScreen.refreshKey));
    await tester.pumpAndSettle();

    expect(transport.callCount, 2);
  });
}
