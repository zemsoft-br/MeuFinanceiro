import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/banking/connections/banking_connections_screen.dart';
import 'package:meufinanceiro_app/theme/app_theme.dart';

import '../../../support/fake_auth_transport.dart';

const _token = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _activeConnectionId = '30000000-0000-4000-8000-000000000003';
const _disconnectedConnectionId = '40000000-0000-4000-8000-000000000004';

void main() {
  testWidgets(
    'renders only local metadata and gates reauthentication by backend flag',
    (tester) async {
      await _pumpScreen(tester, body: _connectionsResponse);

      expect(find.byKey(BankingConnectionsScreen.titleKey), findsOneWidget);
      expect(find.text('Pluggy · Open Finance'), findsNWidgets(2));
      expect(find.text('Disponível'), findsOneWidget);
      expect(find.text('Desconectada'), findsOneWidget);
      expect(
        find.byKey(
          BankingConnectionsScreen.reauthenticationButtonKey(
            _activeConnectionId,
          ),
        ),
        findsOneWidget,
      );
      expect(
        find.byKey(
          BankingConnectionsScreen.reauthenticationButtonKey(
            _disconnectedConnectionId,
          ),
        ),
        findsNothing,
      );
      expect(find.text(_activeConnectionId), findsNothing);
      expect(find.text(_disconnectedConnectionId), findsNothing);
      expect(find.textContaining('itemId'), findsNothing);
      expect(find.textContaining('clientUserId'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('empty state remains usable and offers connect action', (
    tester,
  ) async {
    await _pumpScreen(tester, body: '{"connections":[]}');

    expect(find.byKey(BankingConnectionsScreen.emptyKey), findsOneWidget);
    expect(find.text('Nenhuma instituição conectada'), findsOneWidget);
    expect(find.text('Conectar instituição'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('missing primary residence is explicit and disables refresh', (
    tester,
  ) async {
    await _pumpScreen(tester, statusCode: 409, body: '{}');

    expect(find.text('Residência principal necessária'), findsOneWidget);
    final refresh = tester.widget<OutlinedButton>(
      find.byKey(BankingConnectionsScreen.refreshButtonKey),
    );
    expect(refresh.onPressed, isNull);
    expect(find.text('Tentar novamente'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('overview remains usable at 320 px with text scaled 2x', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await _pumpScreen(
      tester,
      body: _connectionsResponse,
      mediaQuery: const MediaQueryData(textScaler: TextScaler.linear(2)),
    );

    expect(find.byKey(BankingConnectionsScreen.titleKey), findsOneWidget);
    expect(find.byKey(BankingConnectionsScreen.listKey), findsOneWidget);
    expect(find.text('Conectar instituição'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

Future<void> _pumpScreen(
  WidgetTester tester, {
  required String body,
  int statusCode = 200,
  MediaQueryData? mediaQuery,
}) async {
  final vault = SessionTokenVault()..store(_token);
  final transport = FakeAuthTransport.response(
    statusCode: statusCode,
    body: body,
  );

  Widget home = const Scaffold(
    body: SingleChildScrollView(child: BankingConnectionsScreen()),
  );
  if (mediaQuery != null) {
    home = MediaQuery(data: mediaQuery, child: home);
  }

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sessionTokenVaultProvider.overrideWithValue(vault),
        authTransportProvider.overrideWithValue(transport),
        authApiBaseUriProvider.overrideWithValue(
          Uri.parse('http://localhost/api/v1/'),
        ),
      ],
      child: MaterialApp(theme: buildAppTheme(), home: home),
    ),
  );
  await tester.pumpAndSettle();
}

const _connectionsResponse =
    '''
{
  "connections":[
    {
      "connectionId":"$_activeConnectionId",
      "provider":"pluggy",
      "status":"AVAILABLE",
      "requiresUserAction":false,
      "lastSuccessfulSyncAt":"2026-08-08T00:00:00Z",
      "lastAttemptAt":"2026-08-08T00:00:00Z",
      "nextRefreshAllowedAt":null,
      "consentExpiresAt":null,
      "disconnectedAt":null,
      "updatedAt":"2026-08-08T00:00:00Z",
      "reauthenticationAvailable":true
    },
    {
      "connectionId":"$_disconnectedConnectionId",
      "provider":"pluggy",
      "status":"DISCONNECTED",
      "requiresUserAction":false,
      "lastSuccessfulSyncAt":null,
      "lastAttemptAt":"2026-08-07T00:00:00Z",
      "nextRefreshAllowedAt":null,
      "consentExpiresAt":null,
      "disconnectedAt":"2026-08-08T00:00:00Z",
      "updatedAt":"2026-08-08T00:00:00Z",
      "reauthenticationAvailable":false
    }
  ]
}
''';
