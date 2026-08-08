import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_api.dart';

import '../../../../support/fake_auth_transport.dart';

const _sessionToken = 'SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS';
const _connectToken = 'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC';

void main() {
  test('connect token response is strict and the secret wrapper is redacted', () async {
    final api = _api(
      FakeAuthTransport.response(
        statusCode: 200,
        body: '{"accessToken":"$_connectToken"}',
      ),
    );

    final token = await api.issueToken();

    expect(token.toString(), isNot(contains(_connectToken)));
    expect(token.take(), _connectToken);
    expect(() => token.take(), throwsA(isA<StateError>()));
  });

  test('connect token response rejects extra fields fail closed', () async {
    final api = _api(
      FakeAuthTransport.response(
        statusCode: 200,
        body: '{"accessToken":"$_connectToken","clientUserId":"unsafe"}',
      ),
    );

    await expectLater(api.issueToken(), throwsA(isA<FormatException>()));
  });

  test('registration sends only transient itemId and accepts local result', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 200,
      body: '''
      {
        "connectionId":"30000000-0000-4000-8000-000000000003",
        "status":"AVAILABLE",
        "requiresUserAction":false
      }
      ''',
    );
    final api = _api(transport);

    final result = await api.registerItem('synthetic-item-1');

    expect(result.connectionId, '30000000-0000-4000-8000-000000000003');
    expect(result.status, 'AVAILABLE');
    expect(result.requiresUserAction, isFalse);
    expect(transport.calls, hasLength(1));
    expect(transport.calls.single.uri.path, '/api/v1/banking/pluggy/connections');
    expect(jsonDecode(transport.calls.single.body!), {'itemId': 'synthetic-item-1'});
    expect(transport.calls.single.body, isNot(contains('residence')));
    expect(transport.calls.single.body, isNot(contains('installation')));
    expect(transport.calls.single.body, isNot(contains('clientUserId')));
  });

  test('registration rejects unknown status and extra provider payload', () async {
    for (final body in [
      '''
      {
        "connectionId":"30000000-0000-4000-8000-000000000003",
        "status":"PROVIDER_SAYS_OK",
        "requiresUserAction":false
      }
      ''',
      '''
      {
        "connectionId":"30000000-0000-4000-8000-000000000003",
        "status":"AVAILABLE",
        "requiresUserAction":false,
        "itemId":"must-not-cross"
      }
      ''',
    ]) {
      final api = _api(FakeAuthTransport.response(statusCode: 200, body: body));
      await expectLater(
        api.registerItem('synthetic-item-1'),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test('registration rejects unsafe item identifiers before transport', () async {
    final transport = FakeAuthTransport.response(statusCode: 200, body: '{}');
    final api = _api(transport);

    for (final value in [
      '',
      ' item ',
      'item/child',
      r'item\child',
      'item?query',
      'item#fragment',
    ]) {
      await expectLater(api.registerItem(value), throwsA(isA<FormatException>()));
    }
    expect(transport.calls, isEmpty);
  });
}

PluggyConnectApi _api(FakeAuthTransport transport) {
  final vault = SessionTokenVault()..store(_sessionToken);
  return PluggyConnectApi(
    AuthenticatedApiClient(
      transport: transport,
      tokenVault: vault,
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () {},
    ),
  );
}
