import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_controller.dart';

import '../../../../support/fake_auth_transport.dart';
import '../../../../support/fake_pluggy_connect_launcher.dart';

const _sessionToken = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _connectToken = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB';

void main() {
  test('provider error without item never calls registration endpoint', () async {
    final harness = await _Harness.create();
    addTearDown(harness.dispose);

    await harness.controller.start();
    harness.launcher.emit(const PluggyConnectCallback.opened());
    harness.launcher.emit(const PluggyConnectCallback.errorWithoutItem());
    await _flush();

    expect(harness.state.phase, PluggyConnectPhase.genericFailure);
    expect(harness.registrationCalls, isEmpty);
  });

  test('invalid callback payload fails closed without registration', () async {
    final harness = await _Harness.create();
    addTearDown(harness.dispose);

    await harness.controller.start();
    harness.launcher.emit(const PluggyConnectCallback.opened());
    harness.launcher.emit(const PluggyConnectCallback.invalidPayload());
    await _flush();

    expect(harness.state.phase, PluggyConnectPhase.invalidProviderResponse);
    expect(harness.registrationCalls, isEmpty);
  });

  test('launcher failure is recoverable and does not register an item', () async {
    final harness = await _Harness.create(failOnLaunch: true);
    addTearDown(harness.dispose);

    await harness.controller.start();

    expect(harness.state.phase, PluggyConnectPhase.temporarilyUnavailable);
    expect(harness.launcher.calls, hasLength(1));
    expect(harness.registrationCalls, isEmpty);
  });

  test('connect-token transport failure is recoverable without opening widget', () async {
    final harness = await _Harness.create(failTokenTransport: true);
    addTearDown(harness.dispose);

    await harness.controller.start();

    expect(harness.state.phase, PluggyConnectPhase.temporarilyUnavailable);
    expect(harness.launcher.calls, isEmpty);
    expect(harness.registrationCalls, isEmpty);
  });

  test('401 during registration clears local auth and requires login again', () async {
    final harness = await _Harness.create(registrationStatus: 401);
    addTearDown(harness.dispose);

    await harness.controller.start();
    harness.launcher.emit(const PluggyConnectCallback.opened());
    harness.launcher.emit(
      const PluggyConnectCallback.itemAvailable('synthetic-item'),
    );
    await _flush();

    expect(harness.state.phase, PluggyConnectPhase.authenticationRequired);
    expect(
      harness.container.read(operatorSessionControllerProvider).phase,
      OperatorSessionPhase.expiredOrRevoked,
    );
    expect(harness.container.read(sessionTokenVaultProvider).hasToken, isFalse);
  });
}

class _Harness {
  _Harness({
    required this.container,
    required this.launcher,
    required this.transport,
  });

  final ProviderContainer container;
  final FakePluggyConnectLauncher launcher;
  final FakeAuthTransport transport;

  PluggyConnectController get controller =>
      container.read(pluggyConnectControllerProvider.notifier);

  PluggyConnectState get state => container.read(pluggyConnectControllerProvider);

  Iterable<AuthTransportCall> get registrationCalls => transport.calls.where(
        (call) => call.uri.path.endsWith('/banking/pluggy/connections'),
      );

  static Future<_Harness> create({
    int registrationStatus = 200,
    bool failOnLaunch = false,
    bool failTokenTransport = false,
  }) async {
    final launcher = FakePluggyConnectLauncher(failOnLaunch: failOnLaunch);
    final transport = FakeAuthTransport((uri, method, timeout, headers, body) async {
      if (uri.path.endsWith('/auth/session')) {
        return const AuthHttpResponse(statusCode: 200, body: _issuedSession);
      }
      if (uri.path.endsWith('/banking/pluggy/connect-token')) {
        if (failTokenTransport) {
          throw StateError('synthetic offline transport');
        }
        return const AuthHttpResponse(
          statusCode: 200,
          body: '{"accessToken":"$_connectToken"}',
        );
      }
      if (uri.path.endsWith('/banking/pluggy/connections')) {
        return AuthHttpResponse(
          statusCode: registrationStatus,
          body: registrationStatus == 200 ? _registeredConnection : '{}',
        );
      }
      throw StateError('unexpected synthetic route');
    });
    final container = ProviderContainer(
      overrides: [
        authTransportProvider.overrideWithValue(transport),
        authApiBaseUriProvider.overrideWithValue(
          Uri.parse('http://localhost/api/v1/'),
        ),
        pluggyConnectLauncherProvider.overrideWithValue(launcher),
        demoStatusProvider.overrideWithValue(
          AsyncValue.data(_demoStatus()),
        ),
      ],
    );
    container.listen(
      pluggyConnectControllerProvider,
      (previous, next) {},
      fireImmediately: true,
    );
    await container
        .read(operatorSessionControllerProvider.notifier)
        .login(login: 'admin', password: 'synthetic-password');
    return _Harness(container: container, launcher: launcher, transport: transport);
  }

  void dispose() => container.dispose();
}

Future<void> _flush() async {
  for (var index = 0; index < 6; index += 1) {
    await Future<void>.delayed(Duration.zero);
  }
}

DemoStatus _demoStatus() {
  return DemoStatus(
    enabled: false,
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
