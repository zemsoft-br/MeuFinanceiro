import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/reauthentication/pluggy_reauthentication_controller.dart';

import '../../../../support/fake_auth_transport.dart';
import '../../../../support/fake_pluggy_connect_launcher.dart';

const _sessionToken = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _connectToken = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB';
const _connectionId = '30000000-0000-4000-8000-000000000003';
const _itemId = 'synthetic-existing-item';

void main() {
  test('reauthentication HTTP failures map to stable sanitized phases', () async {
    const scenarios = {
      403: PluggyReauthenticationPhase.connectionUnavailable,
      404: PluggyReauthenticationPhase.connectionNotFound,
      409: PluggyReauthenticationPhase.connectionUnavailable,
      502: PluggyReauthenticationPhase.invalidProviderResponse,
      503: PluggyReauthenticationPhase.temporarilyUnavailable,
    };

    for (final scenario in scenarios.entries) {
      final launcher = FakePluggyConnectLauncher();
      final transport = FakeAuthTransport((uri, method, timeout, headers, body) async {
        if (uri.path.endsWith('/auth/session')) {
          return const AuthHttpResponse(statusCode: 200, body: _issuedSession);
        }
        if (uri.path.contains('/reauthentication-token')) {
          return AuthHttpResponse(
            statusCode: scenario.key,
            body: '{"detail":"provider detail must stay hidden"}',
          );
        }
        throw StateError('unexpected synthetic route');
      });
      final container = _container(transport, launcher);
      await _login(container);

      await container
          .read(pluggyReauthenticationControllerProvider.notifier)
          .start(_connectionId);

      final state = container.read(pluggyReauthenticationControllerProvider);
      expect(state.phase, scenario.value, reason: 'HTTP ${scenario.key}');
      expect(state.toString(), isNot(contains('provider detail')));
      expect(launcher.calls, isEmpty);
      container.dispose();
    }
  });

  test('provider error without Item never re-registers a connection', () async {
    final launcher = FakePluggyConnectLauncher();
    final transport = _happyTransport();
    final container = _container(transport, launcher);
    addTearDown(container.dispose);
    await _login(container);

    await container
        .read(pluggyReauthenticationControllerProvider.notifier)
        .start(_connectionId);
    launcher.emit(const PluggyConnectCallback.opened());
    launcher.emit(const PluggyConnectCallback.errorWithoutItem());
    await _flush();

    expect(
      container.read(pluggyReauthenticationControllerProvider).phase,
      PluggyReauthenticationPhase.genericFailure,
    );
    expect(
      transport.calls.where(
        (call) => call.uri.path.endsWith('/banking/pluggy/connections'),
      ),
      isEmpty,
    );
  });

  test('invalid callback payload never re-registers a connection', () async {
    final launcher = FakePluggyConnectLauncher();
    final transport = _happyTransport();
    final container = _container(transport, launcher);
    addTearDown(container.dispose);
    await _login(container);

    await container
        .read(pluggyReauthenticationControllerProvider.notifier)
        .start(_connectionId);
    launcher.emit(const PluggyConnectCallback.opened());
    launcher.emit(const PluggyConnectCallback.invalidPayload());
    await _flush();

    expect(
      container.read(pluggyReauthenticationControllerProvider).phase,
      PluggyReauthenticationPhase.invalidProviderResponse,
    );
    expect(
      transport.calls.where(
        (call) => call.uri.path.endsWith('/banking/pluggy/connections'),
      ),
      isEmpty,
    );
  });
}

ProviderContainer _container(
  FakeAuthTransport transport,
  FakePluggyConnectLauncher launcher,
) {
  final container = ProviderContainer(
    overrides: [
      authTransportProvider.overrideWithValue(transport),
      authApiBaseUriProvider.overrideWithValue(
        Uri.parse('http://localhost/api/v1/'),
      ),
      pluggyReauthenticationLauncherProvider.overrideWithValue(launcher),
      demoStatusProvider.overrideWithValue(AsyncValue.data(_demoStatus())),
    ],
  );
  container.listen(
    pluggyReauthenticationControllerProvider,
    (previous, next) {},
    fireImmediately: true,
  );
  return container;
}

Future<void> _login(ProviderContainer container) async {
  await container
      .read(operatorSessionControllerProvider.notifier)
      .login(login: 'admin', password: 'synthetic-password');
}

Future<void> _flush() async {
  for (var index = 0; index < 6; index += 1) {
    await Future<void>.delayed(Duration.zero);
  }
}

FakeAuthTransport _happyTransport() {
  return FakeAuthTransport((uri, method, timeout, headers, body) async {
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
