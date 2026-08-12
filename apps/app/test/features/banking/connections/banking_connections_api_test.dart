import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/banking/connections/banking_connections_api.dart';

import '../../../support/fake_auth_transport.dart';

const _token = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _connectionId = '30000000-0000-4000-8000-000000000003';

void main() {
  test(
    'lists only strict local connection metadata through authenticated GET',
    () async {
      final transport = FakeAuthTransport.response(
        statusCode: 200,
        body: _singleConnectionResponse,
      );
      final api = _api(transport);

      final connections = await api.listConnections();

      expect(transport.calls, hasLength(1));
      expect(transport.calls.single.method, AuthHttpMethod.get);
      expect(transport.calls.single.uri.path, '/api/v1/banking/connections');
      expect(transport.calls.single.uri.query, isEmpty);
      expect(transport.calls.single.body, isNull);
      expect(connections, hasLength(1));
      expect(connections.single.connectionId, _connectionId);
      expect(connections.single.provider, 'pluggy');
      expect(
        connections.single.status,
        BankingConnectionStatus.reauthenticationRequired,
      );
      expect(connections.single.requiresUserAction, isTrue);
      expect(connections.single.reauthenticationAvailable, isTrue);
      expect(connections.single.updatedAt.isUtc, isTrue);
      expect(connections.single.toString(), isNot(contains(_connectionId)));
    },
  );

  test('empty list is accepted without creating synthetic entries', () async {
    final connections = await _api(
      FakeAuthTransport.response(statusCode: 200, body: '{"connections":[]}'),
    ).listConnections();

    expect(connections, isEmpty);
  });

  test('root and connection objects reject unexpected fields', () async {
    for (final body in [
      '{"connections":[],"extra":true}',
      _singleConnectionResponse.replaceFirst(
        '"reauthenticationAvailable":true',
        '"reauthenticationAvailable":true,"itemId":"forbidden-provider-item"',
      ),
      _singleConnectionResponse.replaceFirst(
        '"reauthenticationAvailable":true',
        '"reauthenticationAvailable":true,"providerReasonCode":"DETAIL"',
      ),
    ]) {
      await expectLater(
        _api(
          FakeAuthTransport.response(statusCode: 200, body: body),
        ).listConnections(),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test('invalid UUID provider status and timestamps fail closed', () async {
    final invalidBodies = [
      _singleConnectionResponse.replaceFirst(_connectionId, 'provider-item'),
      _singleConnectionResponse.replaceFirst(
        '"provider":"pluggy"',
        '"provider":"Pluggy"',
      ),
      _singleConnectionResponse.replaceFirst(
        '"status":"REAUTHENTICATION_REQUIRED"',
        '"status":"UNKNOWN_PROVIDER_STATE"',
      ),
      _singleConnectionResponse.replaceFirst(
        '"updatedAt":"2026-08-08T00:00:00Z"',
        '"updatedAt":"2026-08-08T00:00:00"',
      ),
      _singleConnectionResponse.replaceFirst(
        '"lastAttemptAt":"2026-08-08T00:00:00Z"',
        '"lastAttemptAt":42',
      ),
    ];

    for (final body in invalidBodies) {
      await expectLater(
        _api(
          FakeAuthTransport.response(statusCode: 200, body: body),
        ).listConnections(),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test('all known local statuses are accepted explicitly', () async {
    for (final status in BankingConnectionStatus.values) {
      final body = _singleConnectionResponse.replaceFirst(
        'REAUTHENTICATION_REQUIRED',
        status.wireValue,
      );
      final result = await _api(
        FakeAuthTransport.response(statusCode: 200, body: body),
      ).listConnections();
      expect(result.single.status, status);
    }
  });
}

BankingConnectionsApi _api(FakeAuthTransport transport) {
  final vault = SessionTokenVault()..store(_token);
  return BankingConnectionsApi(
    AuthenticatedApiClient(
      transport: transport,
      tokenVault: vault,
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () {},
    ),
  );
}

const _singleConnectionResponse =
    '''
{
  "connections":[
    {
      "connectionId":"$_connectionId",
      "provider":"pluggy",
      "status":"REAUTHENTICATION_REQUIRED",
      "requiresUserAction":true,
      "lastSuccessfulSyncAt":null,
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
