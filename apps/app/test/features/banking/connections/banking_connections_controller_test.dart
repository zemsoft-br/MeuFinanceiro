import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/banking/connections/banking_connections_controller.dart';

import '../../../support/fake_auth_transport.dart';

const _token = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _connectionId = '30000000-0000-4000-8000-000000000003';

void main() {
  test('load is single-flight and produces local connections', () async {
    final response = Completer<AuthHttpResponse>();
    final transport = FakeAuthTransport(
      (uri, method, timeout, headers, body) => response.future,
    );
    final container = _container(transport);
    addTearDown(container.dispose);
    final controller = container.read(
      bankingConnectionsControllerProvider.notifier,
    );

    final first = controller.load();
    final second = controller.load();
    expect(transport.calls, hasLength(1));
    expect(
      container.read(bankingConnectionsControllerProvider).phase,
      BankingConnectionsPhase.loading,
    );

    response.complete(
      const AuthHttpResponse(statusCode: 200, body: _singleConnectionResponse),
    );
    await Future.wait([first, second]);

    final state = container.read(bankingConnectionsControllerProvider);
    expect(state.phase, BankingConnectionsPhase.loaded);
    expect(state.connections, hasLength(1));
    expect(state.connections.single.connectionId, _connectionId);
  });

  test('failed explicit refresh preserves already loaded local metadata', () async {
    var calls = 0;
    final transport = FakeAuthTransport((uri, method, timeout, headers, body) async {
      calls += 1;
      if (calls == 1) {
        return const AuthHttpResponse(
          statusCode: 200,
          body: _singleConnectionResponse,
        );
      }
      return const AuthHttpResponse(statusCode: 503, body: '{}');
    });
    final container = _container(transport);
    addTearDown(container.dispose);
    final controller = container.read(
      bankingConnectionsControllerProvider.notifier,
    );

    await controller.load();
    await controller.refresh();

    final state = container.read(bankingConnectionsControllerProvider);
    expect(state.phase, BankingConnectionsPhase.loaded);
    expect(state.connections, hasLength(1));
    expect(
      state.refreshFailure,
      BankingConnectionsRefreshFailure.temporarilyUnavailable,
    );
    expect(transport.calls, hasLength(2));
  });

  test('malformed refresh preserves data with invalid response notice', () async {
    var calls = 0;
    final transport = FakeAuthTransport((uri, method, timeout, headers, body) async {
      calls += 1;
      return AuthHttpResponse(
        statusCode: 200,
        body: calls == 1 ? _singleConnectionResponse : '{"connections":{},"x":1}',
      );
    });
    final container = _container(transport);
    addTearDown(container.dispose);
    final controller = container.read(
      bankingConnectionsControllerProvider.notifier,
    );

    await controller.load();
    await controller.refresh();

    final state = container.read(bankingConnectionsControllerProvider);
    expect(state.phase, BankingConnectionsPhase.loaded);
    expect(state.connections, hasLength(1));
    expect(
      state.refreshFailure,
      BankingConnectionsRefreshFailure.invalidResponse,
    );
  });

  test('401 clears bearer and invalidates local session state', () async {
    final container = _container(
      FakeAuthTransport.response(statusCode: 401, body: '{}'),
    );
    addTearDown(container.dispose);

    await container.read(bankingConnectionsControllerProvider.notifier).load();

    expect(
      container.read(bankingConnectionsControllerProvider).phase,
      BankingConnectionsPhase.authenticationRequired,
    );
    expect(container.read(sessionTokenVaultProvider).hasToken, isFalse);
    expect(
      container.read(operatorSessionControllerProvider).phase,
      OperatorSessionPhase.expiredOrRevoked,
    );
  });

  test('409 maps to explicit primary residence requirement', () async {
    final container = _container(
      FakeAuthTransport.response(statusCode: 409, body: '{}'),
    );
    addTearDown(container.dispose);

    await container.read(bankingConnectionsControllerProvider.notifier).load();

    expect(
      container.read(bankingConnectionsControllerProvider).phase,
      BankingConnectionsPhase.primaryResidenceRequired,
    );
    expect(container.read(sessionTokenVaultProvider).hasToken, isTrue);
  });

  test('403 and malformed initial responses map to sanitized states', () async {
    final forbidden = _container(
      FakeAuthTransport.response(statusCode: 403, body: '{}'),
    );
    addTearDown(forbidden.dispose);
    await forbidden.read(bankingConnectionsControllerProvider.notifier).load();
    expect(
      forbidden.read(bankingConnectionsControllerProvider).phase,
      BankingConnectionsPhase.forbidden,
    );

    final invalid = _container(
      FakeAuthTransport.response(statusCode: 200, body: '{"connections":{}}'),
    );
    addTearDown(invalid.dispose);
    await invalid.read(bankingConnectionsControllerProvider.notifier).load();
    expect(
      invalid.read(bankingConnectionsControllerProvider).phase,
      BankingConnectionsPhase.invalidResponse,
    );
  });
}

ProviderContainer _container(FakeAuthTransport transport) {
  final container = ProviderContainer(
    overrides: [
      authTransportProvider.overrideWithValue(transport),
      authApiBaseUriProvider.overrideWithValue(
        Uri.parse('http://localhost/api/v1/'),
      ),
      authRequestTimeoutProvider.overrideWithValue(const Duration(seconds: 2)),
    ],
  );
  container.read(sessionTokenVaultProvider).store(_token);
  container.listen(
    bankingConnectionsControllerProvider,
    (previous, next) {},
    fireImmediately: true,
  );
  return container;
}

const _singleConnectionResponse = '''
{
  "connections":[
    {
      "connectionId":"$_connectionId",
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
    }
  ]
}
''';
