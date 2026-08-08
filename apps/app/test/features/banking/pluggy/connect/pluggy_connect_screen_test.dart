import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_controller.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_screen.dart';
import 'package:meufinanceiro_app/theme/app_theme.dart';

import '../../../../support/fake_auth_transport.dart';
import '../../../../support/fake_pluggy_connect_launcher.dart';

const _sessionToken = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _connectToken = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB';

void main() {
  testWidgets('screen remains usable at 320 px with text scaled 2x', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final launcher = FakePluggyConnectLauncher();
    await _pumpScreen(
      tester,
      launcher: launcher,
      mediaQuery: const MediaQueryData(textScaler: TextScaler.linear(2)),
    );

    expect(find.byKey(PluggyConnectScreen.titleKey), findsOneWidget);
    expect(find.byKey(PluggyConnectScreen.connectButtonKey), findsOneWidget);
    expect(find.textContaining('Senha bancária'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('closing provider flow returns focus and records no connection', (
    tester,
  ) async {
    final launcher = FakePluggyConnectLauncher();
    await _pumpScreen(tester, launcher: launcher);

    await tester.tap(find.byKey(PluggyConnectScreen.connectButtonKey));
    await tester.pump();
    expect(launcher.calls, hasLength(1));

    launcher.emit(const PluggyConnectCallback.opened());
    await tester.pump();
    launcher.emit(const PluggyConnectCallback.closed());
    await tester.pumpAndSettle();

    expect(find.textContaining('Conexão cancelada'), findsOneWidget);
    final button = tester.widget<FilledButton>(
      find.byKey(PluggyConnectScreen.connectButtonKey),
    );
    expect(button.focusNode?.hasFocus, isTrue);
    expect(find.byKey(PluggyConnectScreen.localConnectionKey), findsNothing);
  });

  testWidgets('success shows only local connection result, never provider item', (
    tester,
  ) async {
    final launcher = FakePluggyConnectLauncher();
    await _pumpScreen(tester, launcher: launcher);

    await tester.tap(find.byKey(PluggyConnectScreen.connectButtonKey));
    await tester.pump();
    launcher.emit(const PluggyConnectCallback.opened());
    launcher.emit(
      const PluggyConnectCallback.itemAvailable('provider-item-must-stay-hidden'),
    );
    await _pumpCallbacks(tester);

    expect(
      find.text('Instituição conectada e validada pelo MeuFinanceiro.'),
      findsOneWidget,
    );
    expect(find.byKey(PluggyConnectScreen.localConnectionKey), findsOneWidget);
    expect(
      find.text('30000000-0000-4000-8000-000000000003'),
      findsOneWidget,
    );
    expect(find.textContaining('provider-item-must-stay-hidden'), findsNothing);
    expect(find.textContaining(_connectToken), findsNothing);
    expect(find.textContaining(_sessionToken), findsNothing);
  });

  testWidgets('demo mode explicitly disables external integration', (
    tester,
  ) async {
    final launcher = FakePluggyConnectLauncher();
    await _pumpScreen(tester, launcher: launcher, demoEnabled: true);

    final button = tester.widget<FilledButton>(
      find.byKey(PluggyConnectScreen.connectButtonKey),
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
    if (uri.path.endsWith('/banking/pluggy/connect-token')) {
      return const AuthHttpResponse(
        statusCode: 200,
        body: '{"accessToken":"$_connectToken"}',
      );
    }
    if (uri.path.endsWith('/banking/pluggy/connections')) {
      return const AuthHttpResponse(statusCode: 200, body: _registeredConnection);
    }
    throw StateError('unexpected synthetic route');
  });

  Widget home = const Scaffold(
    body: SingleChildScrollView(child: PluggyConnectScreen()),
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
        pluggyConnectLauncherProvider.overrideWithValue(launcher),
        demoStatusProvider.overrideWithValue(
          AsyncValue.data(_demoStatus(enabled: demoEnabled)),
        ),
      ],
      child: MaterialApp(theme: buildAppTheme(), home: home),
    ),
  );
  await tester.pumpAndSettle();

  final container = ProviderScope.containerOf(
    tester.element(find.byType(PluggyConnectScreen)),
  );
  await container
      .read(operatorSessionControllerProvider.notifier)
      .login(login: 'admin', password: 'synthetic-password');
  await tester.pumpAndSettle();
}

Future<void> _pumpCallbacks(WidgetTester tester) async {
  for (var index = 0; index < 5; index += 1) {
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
  "expires_at":"2026-08-08T00:00:00Z",
  "operator":{
    "operator_id":"10000000-0000-4000-8000-000000000001",
    "installation_id":"20000000-0000-4000-8000-000000000002",
    "primary_residence_id":"30000000-0000-4000-8000-000000000003",
    "login":"admin",
    "role":"installation_admin",
    "expires_at":"2026-08-08T00:00:00Z"
  }
}
''';

const _registeredConnection = '''
{
  "connectionId":"30000000-0000-4000-8000-000000000003",
  "status":"AVAILABLE",
  "requiresUserAction":false
}
''';
