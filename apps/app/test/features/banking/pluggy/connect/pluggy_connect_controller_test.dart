import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_controller.dart';

import '../../../../support/fake_auth_transport.dart';
import '../../../../support/fake_pluggy_connect_launcher.dart';

const _sessionToken = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _connectToken = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB';

void main() {
  test(
    'opens one widget and registers only the transient item pointer',
    () async {
      final launcher = FakePluggyConnectLauncher();
      final transport = _happyTransport();
      final container = _container(transport, launcher: launcher);
      addTearDown(container.dispose);
      await _login(container);

      final controller = container.read(
        pluggyConnectControllerProvider.notifier,
      );
      await controller.start();
      await controller.start();

      expect(launcher.calls, hasLength(1));
      expect(launcher.calls.single.connectToken, _connectToken);
      expect(launcher.calls.single.toString(), isNot(contains(_connectToken)));
      expect(
        container.read(pluggyConnectControllerProvider).toString(),
        isNot(contains(_connectToken)),
      );

      launcher.emit(const PluggyConnectCallback.opened());
      launcher.emit(
        const PluggyConnectCallback.itemAvailable('synthetic-provider-item'),
      );
      await _flushCallbacks();

      final state = container.read(pluggyConnectControllerProvider);
      expect(state.phase, PluggyConnectPhase.connected);
      expect(state.connectionId, '30000000-0000-4000-8000-000000000003');
      expect(state.connectionStatus, 'AVAILABLE');
      expect(state.requiresUserAction, isFalse);

      final registrationCalls = transport.calls.where(
        (call) => call.uri.path.endsWith('/banking/pluggy/connections'),
      );
      expect(registrationCalls, hasLength(1));
      expect(
        registrationCalls.single.body,
        '{"itemId":"synthetic-provider-item"}',
      );
      expect(registrationCalls.single.body, isNot(contains('residence')));
      expect(registrationCalls.single.body, isNot(contains('installation')));
      expect(registrationCalls.single.body, isNot(contains('clientUserId')));
    },
  );

  test('demo mode never requests token or opens provider widget', () async {
    final launcher = FakePluggyConnectLauncher();
    final transport = _happyTransport();
    final container = _container(
      transport,
      launcher: launcher,
      demoEnabled: true,
    );
    addTearDown(container.dispose);
    await _login(container);

    await container.read(pluggyConnectControllerProvider.notifier).start();

    expect(
      container.read(pluggyConnectControllerProvider).phase,
      PluggyConnectPhase.demoUnavailable,
    );
    expect(launcher.calls, isEmpty);
    expect(
      transport.calls.where(
        (call) => call.uri.path.endsWith('/banking/pluggy/connect-token'),
      ),
      isEmpty,
    );
  });

  test('callbacks are serialized while registration is in flight', () async {
    final launcher = FakePluggyConnectLauncher();
    final firstRegistration = Completer<AuthHttpResponse>();
    var registrations = 0;
    final transport = FakeAuthTransport((uri, method, timeout, headers, body) {
      if (uri.path.endsWith('/auth/session')) {
        return Future.value(
          const AuthHttpResponse(statusCode: 200, body: _issuedSession),
        );
      }
      if (uri.path.endsWith('/banking/pluggy/connect-token')) {
        return Future.value(
          const AuthHttpResponse(
            statusCode: 200,
            body: '{"accessToken":"$_connectToken"}',
          ),
        );
      }
      if (uri.path.endsWith('/banking/pluggy/connections')) {
        registrations += 1;
        if (registrations == 1) {
          return firstRegistration.future;
        }
        return Future.value(
          const AuthHttpResponse(statusCode: 200, body: _registeredConnection),
        );
      }
      throw StateError('unexpected synthetic route');
    });
    final container = _container(transport, launcher: launcher);
    addTearDown(container.dispose);
    await _login(container);
    await container.read(pluggyConnectControllerProvider.notifier).start();

    launcher.emit(const PluggyConnectCallback.opened());
    launcher.emit(const PluggyConnectCallback.itemAvailable('item-one'));
    launcher.emit(const PluggyConnectCallback.itemAvailable('item-two'));
    await _flushCallbacks();

    expect(registrations, 1);
    firstRegistration.complete(
      const AuthHttpResponse(statusCode: 200, body: _registeredConnection),
    );
    await _flushCallbacks();

    expect(registrations, 2);
    expect(
      container.read(pluggyConnectControllerProvider).phase,
      PluggyConnectPhase.connected,
    );
  });

  test('late callback after screen cancellation is ignored', () async {
    final launcher = FakePluggyConnectLauncher();
    final transport = _happyTransport();
    final container = _container(transport, launcher: launcher);
    addTearDown(container.dispose);
    await _login(container);
    final controller = container.read(pluggyConnectControllerProvider.notifier);
    await controller.start();

    controller.cancelFromScreen();
    launcher.emit(const PluggyConnectCallback.itemAvailable('late-item'));
    await _flushCallbacks();

    expect(
      container.read(pluggyConnectControllerProvider).phase,
      PluggyConnectPhase.idle,
    );
    expect(
      transport.calls.where(
        (call) => call.uri.path.endsWith('/banking/pluggy/connections'),
      ),
      isEmpty,
    );
  });

  test('connect-token HTTP failures map to stable local states', () async {
    const scenarios = {
      404: PluggyConnectPhase.providerUnavailable,
      409: PluggyConnectPhase.configurationRequired,
      502: PluggyConnectPhase.invalidProviderResponse,
      503: PluggyConnectPhase.temporarilyUnavailable,
    };

    for (final scenario in scenarios.entries) {
      final launcher = FakePluggyConnectLauncher();
      final transport = FakeAuthTransport((
        uri,
        method,
        timeout,
        headers,
        body,
      ) {
        if (uri.path.endsWith('/auth/session')) {
          return Future.value(
            const AuthHttpResponse(statusCode: 200, body: _issuedSession),
          );
        }
        return Future.value(
          AuthHttpResponse(statusCode: scenario.key, body: '{}'),
        );
      });
      final container = _container(transport, launcher: launcher);
      await _login(container);

      await container.read(pluggyConnectControllerProvider.notifier).start();

      expect(
        container.read(pluggyConnectControllerProvider).phase,
        scenario.value,
        reason: 'HTTP ${scenario.key}',
      );
      expect(launcher.calls, isEmpty);
      container.dispose();
    }
  });

  test(
    'registration HTTP failures map without exposing provider payload',
    () async {
      const scenarios = {
        403: PluggyConnectPhase.connectionConflict,
        404: PluggyConnectPhase.invalidProviderResponse,
        409: PluggyConnectPhase.connectionConflict,
        502: PluggyConnectPhase.invalidProviderResponse,
        503: PluggyConnectPhase.temporarilyUnavailable,
      };

      for (final scenario in scenarios.entries) {
        final launcher = FakePluggyConnectLauncher();
        final transport = FakeAuthTransport((
          uri,
          method,
          timeout,
          headers,
          body,
        ) {
          if (uri.path.endsWith('/auth/session')) {
            return Future.value(
              const AuthHttpResponse(statusCode: 200, body: _issuedSession),
            );
          }
          if (uri.path.endsWith('/banking/pluggy/connect-token')) {
            return Future.value(
              const AuthHttpResponse(
                statusCode: 200,
                body: '{"accessToken":"$_connectToken"}',
              ),
            );
          }
          return Future.value(
            AuthHttpResponse(
              statusCode: scenario.key,
              body: '{"detail":"synthetic provider detail must be ignored"}',
            ),
          );
        });
        final container = _container(transport, launcher: launcher);
        await _login(container);
        await container.read(pluggyConnectControllerProvider.notifier).start();
        launcher.emit(const PluggyConnectCallback.opened());
        launcher.emit(
          const PluggyConnectCallback.itemAvailable('synthetic-item'),
        );
        await _flushCallbacks();

        final state = container.read(pluggyConnectControllerProvider);
        expect(state.phase, scenario.value, reason: 'HTTP ${scenario.key}');
        expect(state.toString(), isNot(contains('synthetic provider detail')));
        expect(state.toString(), isNot(contains('synthetic-item')));
        container.dispose();
      }
    },
  );
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
      pluggyConnectLauncherProvider.overrideWithValue(launcher),
      demoStatusProvider.overrideWithValue(
        AsyncValue.data(_demoStatus(enabled: demoEnabled)),
      ),
    ],
  );
  container.listen(
    pluggyConnectControllerProvider,
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

Future<void> _flushCallbacks() async {
  for (var index = 0; index < 5; index += 1) {
    await Future<void>.delayed(Duration.zero);
  }
}

FakeAuthTransport _happyTransport() {
  return FakeAuthTransport((uri, method, timeout, headers, body) async {
    if (uri.path.endsWith('/auth/session')) {
      return const AuthHttpResponse(statusCode: 200, body: _issuedSession);
    }
    if (uri.path.endsWith('/banking/pluggy/connect-token')) {
      expect(body, isNull);
      return const AuthHttpResponse(
        statusCode: 200,
        body: '{"accessToken":"$_connectToken"}',
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
