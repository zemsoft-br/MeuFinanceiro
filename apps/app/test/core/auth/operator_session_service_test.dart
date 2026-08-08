import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_service.dart';

import '../../support/fake_auth_transport.dart';

const _token = 'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC';

void main() {
  test('login request contains only login and password', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 200,
      body: _issuedSession,
    );
    final service = _service(transport);

    await service.login(login: ' admin ', password: 'synthetic-password');

    final call = transport.calls.single;
    expect(call.method, AuthHttpMethod.post);
    expect(call.uri.path, '/api/v1/auth/session');
    expect(jsonDecode(call.body!), {
      'login': 'admin',
      'password': 'synthetic-password',
    });
    expect(call.body, isNot(contains('installation_id')));
    expect(call.body, isNot(contains('residence_id')));
    expect(call.body, isNot(contains('operator_id')));
  });

  test('GET current session uses bearer and parses principal', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 200,
      body: _principal,
    );
    final service = _service(transport);

    final principal = await service.getCurrent(_token);

    expect(principal.login, 'admin');
    expect(transport.calls.single.method, AuthHttpMethod.get);
    expect(transport.calls.single.headers['Authorization'], 'Bearer $_token');
    expect(transport.calls.single.toString(), isNot(contains(_token)));
  });

  test('GET 401 is a stable expired-session failure', () async {
    final service = _service(
      FakeAuthTransport.response(statusCode: 401, body: '{}'),
    );

    await expectLater(
      service.getCurrent(_token),
      throwsA(isA<OperatorSessionExpired>()),
    );
  });
}

OperatorSessionService _service(FakeAuthTransport transport) {
  return OperatorSessionService(
    transport: transport,
    apiBaseUri: Uri.parse('http://localhost/api/v1/'),
    timeout: const Duration(seconds: 2),
  );
}

const _principal = '''
{
  "operator_id":"10000000-0000-4000-8000-000000000001",
  "installation_id":"20000000-0000-4000-8000-000000000002",
  "primary_residence_id":"30000000-0000-4000-8000-000000000003",
  "login":"admin",
  "role":"installation_admin",
  "expires_at":"2026-08-08T00:00:00Z"
}
''';

const _issuedSession = '''
{
  "access_token":"$_token",
  "token_type":"bearer",
  "expires_at":"2026-08-08T00:00:00Z",
  "operator":$_principal
}
''';
