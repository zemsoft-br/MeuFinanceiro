import 'dart:ui' show Tristate;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/app/app.dart';
import 'package:meufinanceiro_app/app/app_shell.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/features/components_catalog/components_catalog_screen.dart';
import 'package:meufinanceiro_app/features/home/home_screen.dart';
import 'package:meufinanceiro_app/features/not_found/not_found_screen.dart';
import 'package:meufinanceiro_app/features/system_health/system_health_screen.dart';
import 'package:meufinanceiro_app/routing/app_router.dart';

import 'support/fake_health_transport.dart';

void main() {
  Future<FakeHealthTransport> pumpApp(
    WidgetTester tester, {
    required String location,
    required Size size,
    FakeHealthTransport? transport,
    bool settle = true,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final selectedTransport = transport ?? operationalHealthTransport();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          initialLocationProvider.overrideWithValue(location),
          healthTransportProvider.overrideWithValue(selectedTransport),
          healthClockProvider.overrideWithValue(
            () => DateTime.utc(2026, 7, 20, 1, 2, 3),
          ),
          healthTimeoutProvider.overrideWithValue(
            const Duration(milliseconds: 100),
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
    return selectedTransport;
  }

  group('routing', () {
    testWidgets('supports the three canonical deep links', (tester) async {
      for (final scenario in [
        ('/', HomeScreen.titleKey),
        ('/componentes', ComponentsCatalogScreen.titleKey),
        ('/sistema', SystemHealthScreen.titleKey),
      ]) {
        await pumpApp(
          tester,
          location: scenario.$1,
          size: const Size(1200, 900),
          // The components catalog showcases an indeterminate loading
          // state, whose animation never settles.
          settle: scenario.$1 != '/componentes',
        );
        expect(find.byKey(scenario.$2), findsOneWidget);
      }
    });

    testWidgets('renders an explicit unknown-route state', (tester) async {
      await pumpApp(
        tester,
        location: '/rota-inexistente',
        size: const Size(1200, 900),
      );

      expect(find.text('Página não encontrada'), findsOneWidget);
      expect(find.byKey(NotFoundScreen.titleKey), findsOneWidget);
      expect(find.text('/rota-inexistente'), findsOneWidget);
    });

    testWidgets('does not mark a mobile destination on an unknown route', (
      tester,
    ) async {
      await pumpApp(
        tester,
        location: '/rota-inexistente',
        size: const Size(390, 844),
      );

      expect(find.byKey(AppShell.mobileNavigationKey), findsNothing);
      expect(find.byKey(NotFoundScreen.titleKey), findsOneWidget);
    });

    testWidgets('marks the active desktop navigation item', (tester) async {
      await pumpApp(
        tester,
        location: '/componentes',
        size: const Size(1200, 900),
        // The components catalog showcases an indeterminate loading
        // state, whose animation never settles.
        settle: false,
      );

      final selected = tester.getSemantics(
        find.byKey(const Key('navigation-components')),
      );
      expect(selected.flagsCollection.isSelected, Tristate.isTrue);
    });
  });

  group('responsive shell', () {
    testWidgets('uses desktop sidebar without mobile controls', (tester) async {
      await pumpApp(tester, location: '/', size: const Size(1200, 900));

      expect(find.byKey(AppShell.desktopSidebarKey), findsOneWidget);
      expect(find.byKey(AppShell.mobileMenuButtonKey), findsNothing);
      expect(find.byKey(AppShell.mobileNavigationKey), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('uses mobile navigation and opens the accessible drawer', (
      tester,
    ) async {
      await pumpApp(tester, location: '/', size: const Size(390, 844));

      expect(find.byKey(AppShell.desktopSidebarKey), findsNothing);
      expect(find.byKey(AppShell.mobileMenuButtonKey), findsOneWidget);
      expect(find.byKey(AppShell.mobileNavigationKey), findsOneWidget);

      await tester.tap(find.byKey(AppShell.mobileMenuButtonKey));
      await tester.pumpAndSettle();

      expect(find.byKey(AppShell.mobileDrawerKey), findsOneWidget);
      expect(
        find.text(
          'Shell Flutter em migração. O runtime React permanece ativo.',
        ),
        findsOneWidget,
      );
      expect(
        Focus.of(tester.element(find.byTooltip('Fechar menu'))).hasFocus,
        isTrue,
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('mobile bottom navigation changes the active route', (
      tester,
    ) async {
      await pumpApp(tester, location: '/', size: const Size(390, 844));

      final mobileNavigation = find.byKey(AppShell.mobileNavigationKey);
      await tester.tap(
        find.descendant(of: mobileNavigation, matching: find.text('Sistema')),
      );
      await tester.pumpAndSettle();

      expect(find.byKey(SystemHealthScreen.titleKey), findsOneWidget);
    });

    testWidgets('drawer navigation moves focus to the new main content', (
      tester,
    ) async {
      await pumpApp(tester, location: '/', size: const Size(390, 844));

      await tester.tap(find.byKey(AppShell.mobileMenuButtonKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('navigation-system')));
      await tester.pumpAndSettle();

      final mainContent = tester.widget<Focus>(
        find.byKey(AppShell.mainContentKey),
      );
      expect(find.byKey(SystemHealthScreen.titleKey), findsOneWidget);
      expect(mainContent.focusNode?.hasFocus, isTrue);
    });

    testWidgets('drawer brand closes the menu and focuses the home content', (
      tester,
    ) async {
      await pumpApp(tester, location: '/sistema', size: const Size(390, 844));

      await tester.tap(find.byKey(AppShell.mobileMenuButtonKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(AppShell.mobileDrawerBrandKey));
      await tester.pumpAndSettle();

      final mainContent = tester.widget<Focus>(
        find.byKey(AppShell.mainContentKey),
      );
      expect(find.byKey(HomeScreen.titleKey), findsOneWidget);
      expect(find.byKey(AppShell.mobileDrawerKey), findsNothing);
      expect(mainContent.focusNode?.hasFocus, isTrue);
    });

    testWidgets('backdrop dismisses the mobile drawer and restores focus', (
      tester,
    ) async {
      await pumpApp(tester, location: '/', size: const Size(390, 844));

      await tester.tap(find.byKey(AppShell.mobileMenuButtonKey));
      await tester.pumpAndSettle();
      await tester.tapAt(const Offset(370, 420));
      await tester.pumpAndSettle();

      final menuButton = tester.widget<IconButton>(
        find.byKey(AppShell.mobileMenuButtonKey),
      );
      expect(find.byKey(AppShell.mobileDrawerKey), findsNothing);
      expect(menuButton.focusNode?.hasFocus, isTrue);
    });

    testWidgets('close control dismisses the mobile drawer', (tester) async {
      await pumpApp(tester, location: '/', size: const Size(390, 844));

      await tester.tap(find.byKey(AppShell.mobileMenuButtonKey));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Fechar menu'));
      await tester.pumpAndSettle();

      expect(
        find.text(
          'Shell Flutter em migração. O runtime React permanece ativo.',
        ),
        findsNothing,
      );
    });

    testWidgets('Escape closes the mobile drawer and restores menu focus', (
      tester,
    ) async {
      await pumpApp(tester, location: '/', size: const Size(390, 844));

      await tester.tap(find.byKey(AppShell.mobileMenuButtonKey));
      await tester.pumpAndSettle();
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pumpAndSettle();

      final menuButton = tester.widget<IconButton>(
        find.byKey(AppShell.mobileMenuButtonKey),
      );
      expect(menuButton.focusNode?.hasFocus, isTrue);
      expect(tester.takeException(), isNull);
    });

    testWidgets('does not overflow horizontally on desktop or mobile', (
      tester,
    ) async {
      for (final size in [const Size(1440, 1000), const Size(320, 700)]) {
        await pumpApp(tester, location: '/', size: size);
        expect(tester.takeException(), isNull);
      }
    });
  });
}
