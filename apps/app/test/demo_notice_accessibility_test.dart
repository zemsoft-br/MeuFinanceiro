import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/app/app_shell.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';

void main() {
  testWidgets('remains readable at 320 px with enlarged text', (tester) async {
    tester.view.physicalSize = const Size(320, 700);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiHealthProvider.overrideWithValue(
            AsyncData<ApiHealthSnapshot>(_operationalHealth),
          ),
          demoStatusProvider.overrideWithValue(
            AsyncData<DemoStatus>(_enabledDemo),
          ),
        ],
        child: MaterialApp(
          home: MediaQuery(
            data: const MediaQueryData(textScaler: TextScaler.linear(2)),
            child: const AppShell(
              currentLocation: '/',
              child: SizedBox(height: 200),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(AppShell.demoNoticeKey), findsOneWidget);
    expect(find.text('Modo demonstração'), findsOneWidget);
    expect(
      find.text('Dados fictícios — não use informações reais.'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('announces the demo warning once with complete semantics', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    addTearDown(semantics.dispose);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiHealthProvider.overrideWithValue(
            AsyncData<ApiHealthSnapshot>(_operationalHealth),
          ),
          demoStatusProvider.overrideWithValue(
            AsyncData<DemoStatus>(_enabledDemo),
          ),
        ],
        child: const MaterialApp(
          home: AppShell(currentLocation: '/', child: SizedBox(height: 200)),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.bySemanticsLabel(
        'Modo demonstração. Os dados exibidos são inteiramente fictícios.',
      ),
      findsOneWidget,
    );
  });
}

final _operationalHealth = ApiHealthSnapshot(
  availability: ApiAvailability.operational,
  readiness: null,
  checkedAt: DateTime.utc(2026, 7, 23),
);

final _enabledDemo = DemoStatus(
  enabled: true,
  loaded: true,
  fixtureId: DemoStatus.canonicalFixtureId,
  fixtureVersion: DemoStatus.canonicalFixtureVersion,
  referenceDate: DateTime(2026, 11),
  timezone: DemoStatus.canonicalTimezone,
  currency: DemoStatus.canonicalCurrency,
  scope: DemoStatus.canonicalScope,
  contractChecksum: DemoStatus.canonicalContractChecksum,
  loadedAt: DateTime.utc(2026, 11, 1, 12),
);
