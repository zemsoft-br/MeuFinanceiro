import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';
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
  test(
    'opens update mode once and re-registers only the verified callback item',
    () async {
      final launcher = FakePluggyConnectLauncher();
      final transport = _happyTransport();
      final container = _container(transport, launcher: launcher);
      addTearDown(container.dispose);
      await _login(container);

      final controller = container.read(
        pluggyReauthenticationControllerProvider.notifier,
      );
      await controller.start(_connectionId);
      await controller.start(_connectionId);

      expect(launcher.calls, hasLength(1));
      expect(launcher.calls.single.connectToken, _connectToken);
      expect(launcher.calls.single.updateItem, _itemId);
      expect(launcher.calls.single.toString(), isNot(contains(_connectToken)));
      expect(launcher.calls.single.toString(), isNot(contains(_itemId)));
      expect(
        container.read(pluggyReauthenticationControllerProvider).toString(),
        isNot(contains(_itemId)),
      );

      launcher.emit(const PluggyConnectCallback.opened());
      launcher.emit(const PluggyConnectCallback.itemAvailable(_itemId));
      await _flush();

      final state = container.read(pluggyReauthenticationControllerProvider);
      expect(state.phase, PluggyReauthenticationPhase.updated);
      expect(state.connectionId, _connectionId);

      final registrations = transport.calls.where(
        (call) => call.uri.path.endsWith('/banking/pluggy/connections'),
      );
      expect(registrations, hasLength(1));
      expect(registrations.single.body, '{"itemId":"$_itemId"}');
    },
  );

  test('callback Item must match backend-issued update Item', () async {
    final launcher = FakePluggyConnectLauncher();
    final transport = _happyTransport();
    final container = _container(transport, launcher: launcher);
    addTearDown(container.dispose);
    await _login(container);

    await container
        .read(pluggyReauthenticationControllerProvider.notifier)
        .start(_connectionId);
    launcher.emit(const PluggyConnectCallback.opened());
    launcher.emit(
      const PluggyConnectCallback.itemAvailable('different-provider-item'),
    );
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

  test(
    'invalid local connection ID fails before any banking request',
    () async {
      final launcher = FakePluggyConnectLauncher();
      final transport = _happyTransport();
      final container = _container(transport, launcher: launcher);
      addTearDown(container.dispose);
      await _login(container);
      final callsBefore = transport.calls.length;

      await container
          .read(pluggyReauthenticationControllerProvider.notifier)
          .start('provider-item-from-url');

      expect(
        container.read(pluggyReauthenticationControllerProvider).phase,
        PluggyReauthenticationPhase.invalidConnectionId,
      );
      expect(transport.calls, hasLength(callsBefore));
      expect(launcher.calls, isEmpty);
    },
  );

  test(
    'demo mode never requests reauthentication material or launcher',
    () async {
      final launcher = FakePluggyConnectLauncher();
      final transport = _happyTransport();
      final container = _container(
        transport,
        launcher: launcher,
        demoEnabled: true,
      );
      addTearDown(container.dispose);
      await _login(container);

      await container
          .read(pluggyReauthenticationControllerProvider.notifier)
          .start(_connectionId);

      expect(
        container.read(pluggyReauthenticationControllerProvider).phase,
        PluggyReauthenticationPhase.demoUnavailable,
      );
      expect(
        transport.calls.where(
          (call) => call.uri.path.contains('/reauthentication-token'),
        ),
        isEmpty,
      );
      expect(launcher.calls, isEmpty);
    },
  );

  test('late callback after cancellation is ignored', () async {
    final launcher = FakePluggyConnectLauncher();
    final transport = _happyTransport();
    final container = _container(transport, launcher: launcher);
    addTearDown(container.dispose);
    await _login(container);
    final controller = container.read(
      pluggyReauthenticationControllerProvider.notifier,
    );
    await controller.start(_connectionId);

    controller.cancelFromScreen();
    launcher.emit(const PluggyConnectCallback.itemAvailable(_itemId));
    await _flush();

    expect(
      container.read(pluggyReauthenticationControllerProvider).phase,
      PluggyReauthenticationPhase.idle,
    );
    expect(
      transport.calls.where(
        (call) => call.uri.path.endsWith('/banking/pluggy/connections'),
      ),
      isEmpty,
    );
  });

  test('401 while requesting material invalidates the local session', () async {
    final launcher = FakePluggyConnectLauncher();
    final transport = FakeAuthTransport((
      uri,
      method,
      timeout,
      headers,
      body,
    ) async {
      if (uri.path.endsWith('/auth/session')) {
        return const AuthHttpResponse(statusCode: 200, body: _issuedSession);
      }
      if (uri.path.contains('/reauthentication-token')) {
        return const AuthHttpResponse(statusCode: 401, body: '{}');
      }
      throw StateError('unexpected synthetic route');
    });
    final container = _container(transport, launcher: launcher);
    addTearDown(container.dispose);
    await _login(container);

    await container
        .read(pluggyReauthenticationControllerProvider.notifier)
        .start(_connectionId);

    expect(
      container.read(pluggyReauthenticationControllerProvider).phase,
      PluggyReauthenticationPhase.authenticationRequired,
    );
    expect(
      container.read(operatorSessionControllerProvider).phase,
      OperatorSessionPhase.expiredOrRevoked,
    );
    expect(container.read(sessionTokenVaultProvider).hasToken, isFalse);
  });
}

ProviderContainer _container(
  FakeAuthTransport transport, {
  required FakePluggyConnectLauncher launcher,
  bool demoEnabled = false,
}) {
  final container = ProviderContainer(
    overrides: [
      authTransportProvider.overrideWithValue(transport),
      authApiBaseUriProvider.overrideWithValue(
        Uri.parse('http://localhost/api/v1/'),
      ),
      authRequestTimeoutProvider.overrideWithValue(const Duration(seconds: 2)),
      pluggyReauthenticationLauncherProvider.overrideWithValue(launcher),
      demoStatusProvider.overrideWithValue(
        AsyncValue.data(_demoStatus(enabled: demoEnabled)),
      ),
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
  expect(
    container.read(operatorSessionControllerProvider).isAuthenticated,
    isTrue,
  );
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
      expect(body, isNull);
      return const AuthHttpResponse(
        statusCode: 200,
        body: '{"accessToken":"$_connectToken","itemId":"$_itemId"}',
      );
    }
    if (uri.path.endsWith('/banking/pluggy/connections')) {
      return const AuthHttpResponse(
        statusCode: 200,
        body: _registeredConnection,
      );
    }
    throw StateError('unexpected synthetic route');
  });
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

const _issuedSession =
    '''
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

const _registeredConnection =
    '''
{
  "connectionId":"$_connectionId",
  "status":"AVAILABLE",
  "requiresUserAction":false
}
''';
