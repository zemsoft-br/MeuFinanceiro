import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/app/app.dart';
import 'package:meufinanceiro_app/app/app_shell.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/features/home/home_screen.dart';
import 'package:meufinanceiro_app/routing/app_router.dart';

import 'support/fake_demo_transport.dart';
import 'support/fake_health_transport.dart';

void main() {
  testWidgets('boots through ProviderScope, GoRouter and responsive shell', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final transport = operationalHealthTransport();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          healthTransportProvider.overrideWithValue(transport),
          healthClockProvider.overrideWithValue(
            () => DateTime.utc(2026, 7, 20, 1),
          ),
          demoStatusTransportProvider.overrideWithValue(disabledDemoTransport()),
          demoStatusEndpointProvider.overrideWithValue(
            Uri.parse('http://localhost/api/v1/demo/status'),
          ),
          initialLocationProvider.overrideWithValue('/'),
        ],
        child: const MeuFinanceiroApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(HomeScreen.titleKey), findsOneWidget);
    expect(find.byKey(AppShell.desktopSidebarKey), findsOneWidget);
    expect(find.byKey(AppShell.mobileNavigationKey), findsNothing);
    expect(find.byKey(AppShell.demoNoticeKey), findsNothing);
    expect(find.text('Operacional'), findsWidgets);
    expect(transport.callCount, 1);
    expect(tester.takeException(), isNull);
  });
}
