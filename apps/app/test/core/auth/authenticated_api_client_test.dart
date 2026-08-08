import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';

import '../../support/fake_auth_transport.dart';

const _token = 'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB';

void main() {
  test('401 clears bearer and reports invalid session', () async {
    final vault = SessionTokenVault()..store(_token);
    var invalidations = 0;
    final client = AuthenticatedApiClient(
      transport: FakeAuthTransport.response(statusCode: 401, body: '{}'),
      tokenVault: vault,
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () => invalidations += 1,
    );

    await expectLater(
      client.get('banking/example'),
      throwsA(
        isA<AuthenticatedApiException>()
            .having((error) => error.statusCode, 'statusCode', 401)
            .having(
              (error) => error.failure,
              'failure',
              AuthenticatedApiFailure.authenticationRequired,
            ),
      ),
    );

    expect(vault.hasToken, isFalse);
    expect(invalidations, 1);
  });

  test('local unauthorized callback cannot alter 401 semantics', () async {
    final vault = SessionTokenVault()..store(_token);
    final client = AuthenticatedApiClient(
      transport: FakeAuthTransport.response(statusCode: 401, body: '{}'),
      tokenVault: vault,
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () => throw StateError('synthetic callback failure'),
    );

    await expectLater(
      client.get('banking/example'),
      throwsA(
        isA<AuthenticatedApiException>().having(
          (error) => error.failure,
          'failure',
          AuthenticatedApiFailure.authenticationRequired,
        ),
      ),
    );
    expect(vault.hasToken, isFalse);
  });

  test('403 does not erase an otherwise valid session', () async {
    final vault = SessionTokenVault()..store(_token);
    final client = AuthenticatedApiClient(
      transport: FakeAuthTransport.response(statusCode: 403, body: '{}'),
      tokenVault: vault,
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () => fail('403 must not invalidate the bearer'),
    );

    await expectLater(
      client.get('banking/example'),
      throwsA(
        isA<AuthenticatedApiException>().having(
          (error) => error.failure,
          'failure',
          AuthenticatedApiFailure.forbidden,
        ),
      ),
    );
    expect(vault.hasToken, isTrue);
  });

  test('authenticated mutation sends one request and no scope fields', () async {
    final vault = SessionTokenVault()..store(_token);
    final transport = FakeAuthTransport.response(statusCode: 409, body: '{}');
    final client = AuthenticatedApiClient(
      transport: transport,
      tokenVault: vault,
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () {},
    );

    await expectLater(
      client.post(
        'banking/pluggy/connections',
        jsonBody: const {'itemId': 'item'},
      ),
      throwsA(isA<AuthenticatedApiException>()),
    );

    expect(transport.calls, hasLength(1));
    final call = transport.calls.single;
    expect(call.headers['Authorization'], 'Bearer $_token');
    expect(call.headers['Pragma'], 'no-cache');
    expect(jsonDecode(call.body!), {'itemId': 'item'});
    expect(call.body, isNot(contains('residence')));
    expect(call.body, isNot(contains('installation')));
    expect(client.toString(), isNot(contains(_token)));
  });

  test('authenticated client rejects paths that escape the API base', () async {
    final vault = SessionTokenVault()..store(_token);
    final transport = FakeAuthTransport.response(statusCode: 200, body: '{}');
    final client = AuthenticatedApiClient(
      transport: transport,
      tokenVault: vault,
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () {},
    );

    for (final path in [
      '../health/ready',
      './banking/example',
      '/api/v1/banking/example',
      r'banking\example',
      'https://evil.example/steal',
      'banking/example#fragment',
    ]) {
      await expectLater(
        client.get(path),
        throwsA(isA<FormatException>()),
      );
    }
    expect(transport.calls, isEmpty);
  });
}
