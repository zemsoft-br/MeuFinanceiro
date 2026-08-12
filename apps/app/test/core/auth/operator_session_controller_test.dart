import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';

import '../../support/fake_auth_transport.dart';

const _token = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

void main() {
  test('successful login stores bearer only in the in-memory vault', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 200,
      body: _validSession,
    );
    final container = _container(transport);
    addTearDown(container.dispose);

    await container
        .read(operatorSessionControllerProvider.notifier)
        .login(login: 'admin', password: 'synthetic-password');

    final state = container.read(operatorSessionControllerProvider);
    expect(state.phase, OperatorSessionPhase.authenticated);
    expect(state.principal?.login, 'admin');
    expect(container.read(sessionTokenVaultProvider).hasToken, isTrue);
    expect(state.toString(), isNot(contains(_token)));
    expect(transport.calls.single.body, contains('synthetic-password'));
    expect(
      transport.calls.single.toString(),
      isNot(contains('synthetic-password')),
    );
  });

  test('invalid credentials do not retain password or bearer', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 401,
      body: '{"detail":"operator credentials are invalid"}',
    );
    final container = _container(transport);
    addTearDown(container.dispose);

    await container
        .read(operatorSessionControllerProvider.notifier)
        .login(login: 'admin', password: 'wrong-synthetic-password');

    expect(
      container.read(operatorSessionControllerProvider).phase,
      OperatorSessionPhase.invalidCredentials,
    );
    expect(container.read(sessionTokenVaultProvider).hasToken, isFalse);
  });

  test('second submit is ignored while authentication is active', () async {
    final response = Completer<AuthHttpResponse>();
    final transport = FakeAuthTransport(
      (uri, method, timeout, headers, body) => response.future,
    );
    final container = _container(transport);
    addTearDown(container.dispose);
    final controller = container.read(
      operatorSessionControllerProvider.notifier,
    );

    final first = controller.login(login: 'admin', password: 'first-password');
    final second = controller.login(
      login: 'admin',
      password: 'second-password',
    );
    await second;

    expect(transport.calls, hasLength(1));
    response.complete(
      const AuthHttpResponse(statusCode: 200, body: _validSession),
    );
    await first;
    expect(
      container.read(operatorSessionControllerProvider).phase,
      OperatorSessionPhase.authenticated,
    );
  });

  test('late login response cannot restore a session after logout', () async {
    final loginResponse = Completer<AuthHttpResponse>();
    final transport = FakeAuthTransport((uri, method, timeout, headers, body) {
      if (method == AuthHttpMethod.post) {
        return loginResponse.future;
      }
      return Future.value(const AuthHttpResponse(statusCode: 204, body: ''));
    });
    final container = _container(transport);
    addTearDown(container.dispose);
    final controller = container.read(
      operatorSessionControllerProvider.notifier,
    );

    final login = controller.login(
      login: 'admin',
      password: 'synthetic-password',
    );
    await Future<void>.delayed(Duration.zero);
    await controller.logout();

    loginResponse.complete(
      const AuthHttpResponse(statusCode: 200, body: _validSession),
    );
    await login;

    expect(
      container.read(operatorSessionControllerProvider).phase,
      OperatorSessionPhase.signedOut,
    );
    expect(container.read(sessionTokenVaultProvider).hasToken, isFalse);
  });

  test('logout clears bearer before the revoke request completes', () async {
    final logoutResponse = Completer<AuthHttpResponse>();
    final transport = FakeAuthTransport((
      uri,
      method,
      timeout,
      headers,
      body,
    ) async {
      if (method == AuthHttpMethod.post) {
        return const AuthHttpResponse(statusCode: 200, body: _validSession);
      }
      return logoutResponse.future;
    });
    final container = _container(transport);
    addTearDown(container.dispose);
    final controller = container.read(
      operatorSessionControllerProvider.notifier,
    );

    await controller.login(login: 'admin', password: 'synthetic-password');
    expect(container.read(sessionTokenVaultProvider).hasToken, isTrue);

    final logout = controller.logout();
    await Future<void>.delayed(Duration.zero);
    expect(container.read(sessionTokenVaultProvider).hasToken, isFalse);
    expect(
      container.read(operatorSessionControllerProvider).phase,
      OperatorSessionPhase.signingOut,
    );

    logoutResponse.complete(const AuthHttpResponse(statusCode: 204, body: ''));
    await logout;
    expect(
      container.read(operatorSessionControllerProvider).phase,
      OperatorSessionPhase.signedOut,
    );
  });
}

ProviderContainer _container(FakeAuthTransport transport) {
  return ProviderContainer(
    overrides: [
      authTransportProvider.overrideWithValue(transport),
      authApiBaseUriProvider.overrideWithValue(
        Uri.parse('http://localhost/api/v1/'),
      ),
      authRequestTimeoutProvider.overrideWithValue(const Duration(seconds: 2)),
    ],
  );
}

const _validSession =
    '''
{
  "access_token":"$_token",
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
