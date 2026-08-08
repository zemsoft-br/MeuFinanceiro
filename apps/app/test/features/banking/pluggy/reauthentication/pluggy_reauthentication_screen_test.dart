import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/reauthentication/pluggy_reauthentication_controller.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/reauthentication/pluggy_reauthentication_screen.dart';
import 'package:meufinanceiro_app/theme/app_theme.dart';

import '../../../../support/fake_auth_transport.dart';
import '../../../../support/fake_pluggy_connect_launcher.dart';

const _sessionToken = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _connectToken = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB';
const _connectionId = '30000000-0000-4000-8000-000000000003';
const _itemId = 'provider-item-must-stay-hidden';

void main() {
  testWidgets('screen remains usable at 320 px with text scaled 2x', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await _pumpScreen(
      tester,
      launcher: FakePluggyConnectLauncher(),
      mediaQuery: const MediaQueryData(textScaler: TextScaler.linear(2)),
    );

    expect(find.byKey(PluggyReauthenticationScreen.titleKey), findsOneWidget);
    expect(find.byKey(PluggyReauthenticationScreen.actionButtonKey), findsOneWidget);
    expect(find.textContaining('MFA'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('cancel returns focus and preserves existing connection', (
    tester,
  ) async {
    final launcher = FakePluggyConnectLauncher();
    await _pumpScreen(tester, launcher: launcher);

    await tester.tap(find.byKey(PluggyReauthenticationScreen.actionButtonKey));
    await tester.pump();
    expect(launcher.calls, hasLength(1));
    expect(launcher.calls.single.updateItem, _itemId);

    launcher.emit(const PluggyConnectCallback.opened());
    await tester.pump();
    launcher.emit(const PluggyConnectCallback.closed());
    await tester.pumpAndSettle();

    expect(find.textContaining('conexão existente foi preservada'), findsOneWidget);
    final button = tester.widget<FilledButton>(
      find.byKey(PluggyReauthenticationScreen.actionButtonKey),
    );
    expect(button.focusNode?.hasFocus, isTrue);
    expect(find.byKey(PluggyReauthenticationScreen.localConnectionKey), findsNothing);
  });

  testWidgets('success shows local result without provider material', (
    tester,
  ) async {
    final launcher = FakePluggyConnectLauncher();
    await _pumpScreen(tester, launcher: launcher);

    await tester.tap(find.byKey(PluggyReauthenticationScreen.actionButtonKey));
    await tester.pump();
    launcher.emit(const PluggyConnectCallback.opened());
    launcher.emit(const PluggyConnectCallback.itemAvailable(_itemId));
    await _pumpCallbacks(tester);

    expect(
      find.text('A conexão foi atualizada e validada pelo MeuFinanceiro.'),
      findsOneWidget,
    );
    expect(find.byKey(PluggyReauthenticationScreen.localConnectionKey), findsOneWidget);
    expect(find.text(_connectionId), findsOneWidget);
    expect(find.textContaining(_itemId), findsNothing);
    expect(find.textContaining(_connectToken), findsNothing);
    expect(find.textContaining(_sessionToken), findsNothing);
  });

  testWidgets('demo mode disables reauthentication before provider access', (
    tester,
  ) async {
    final launcher = FakePluggyConnectLauncher();
    await _pumpScreen(tester, launcher: launcher, demoEnabled: true);

    final button = tester.widget<FilledButton>(
      find.byKey(PluggyReauthenticationScreen.actionButtonKey),
    );
    expect(button.onPressed, isNull);
    expect(
      find.text('Integrações externas ficam indisponíveis no modo demonstração.'),
      findsOneWidget,
    );
    expect(launcher.calls, isEmpty);
  });
}

Future<void> _pumpScreen(
  WidgetTester tester, {
  required FakePluggyConnectLauncher launcher,
  bool demoEnabled = false,
  MediaQueryData? mediaQuery,
}) async {
  final transport = FakeAuthTransport((uri, method, timeout, headers, body) async {
    if (uri.path.endsWith('/auth/session')) {
      return const AuthHttpResponse(statusCode: 200, body: _issuedSession);
    }
    if (uri.path.contains('/reauthentication-token')) {
      return const AuthHttpResponse(
        statusCode: 200,
        body: '{"accessToken":"$_connectToken","itemId":"$_itemId"}',
      );
    }
    if (uri.path.endsWith('/banking/pluggy/connections')) {
      return const AuthHttpResponse(statusCode: 200, body: _registeredConnection);
    }
    throw StateError('unexpected synthetic route');
  });

  Widget home = const Scaffold(
    body: SingleChildScrollView(
      child: PluggyReauthenticationScreen(connectionId: _connectionId),
    ),
  );
  if (mediaQuery != null) {
    home = MediaQuery(data: mediaQuery, child: home);
  }

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        authTransportProvider.overrideWithValue(transport),
        authApiBaseUriProvider.overrideWithValue(
          Uri.parse('http://localhost/api/v1/'),
        ),
        pluggyReauthenticationLauncherProvider.overrideWithValue(launcher),
        demoStatusProvider.overrideWithValue(
          AsyncValue.data(_demoStatus(enabled: demoEnabled)),
        ),
      ],
      child: MaterialApp(theme: buildAppTheme(), home: home),
    ),
  );
  await tester.pumpAndSettle();

  final container = ProviderScope.containerOf(
    tester.element(find.byType(PluggyReauthenticationScreen)),
  );
  await container
      .read(operatorSessionControllerProvider.notifier)
      .login(login: 'admin', password: 'synthetic-password');
  await tester.pumpAndSettle();
}

Future<void> _pumpCallbacks(WidgetTester tester) async {
  for (var index = 0; index < 6; index += 1) {
    await tester.pump();
  }
}

DemoStatus _demoStatus({required bool enabled}) {
  return DemoStatus(
    enabled: enabled,
    loaded: false,
    fixtureId: DemoStatus.canonicalFixtureId,
    fixtureVersion: DemoStatus.canonicalFixtureVersion,
    referenceDate: DateTime(2026, 11, 1),
    timezone: DemoStatus.canonicalTimezone,
    currency: DemoStatus.canonicalCurrency,
    scope: DemoStatus.canonicalScope,
    contractChecksum: DemoStatus.canonicalContractChecksum,
    loadedAt: null,
  );
}

const _issuedSession = '''
{
  "access_token":"$_sessionToken",
  "token_type":"bearer",
  "expires_at":"2027-08-08T00:00:00Z",
  "operator":{
    "operator_id":"10000000-0000-4000-8000-000000000001",
    "installation_id":"20000000-0000-4000-8000-000000000002",
    "primary_residence_id":"30000000-0000-4000-8000-000000000003",
    "login":"admin",
    "role":"installation_admin",
    "expires_at":"2027-08-08T00:00:00Z"
  }
}
''';

const _registeredConnection = '''
{
  "connectionId":"$_connectionId",
  "status":"AVAILABLE",
  "requiresUserAction":false
}
''';
