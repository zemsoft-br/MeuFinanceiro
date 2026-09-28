import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';

const _token = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';

void main() {
  test('parses canonical session without exposing bearer in repr', () {
    final issued = IssuedOperatorSession.fromJson(_validSession);

    expect(issued.accessToken, _token);
    expect(issued.principal.login, 'admin');
    expect(issued.principal.isInstallationAdmin, isTrue);
    expect(
      issued.principal.primaryResidenceId,
      '30000000-0000-4000-8000-000000000003',
    );
    expect(issued.toString(), isNot(contains(_token)));
    expect(issued.principal.toString(), isNot(contains('admin')));
  });

  test('rejects unexpected session fields fail closed', () {
    final payload = _validSession.replaceFirst(
      '"token_type":"bearer"',
      '"token_type":"bearer","refresh_token":"unsafe"',
    );

    expect(
      () => IssuedOperatorSession.fromJson(payload),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects unsupported role and inconsistent expiration', () {
    expect(
      () => IssuedOperatorSession.fromJson(
        _validSession.replaceFirst('installation_admin', 'member'),
      ),
      throwsA(isA<FormatException>()),
    );

    expect(
      () => IssuedOperatorSession.fromJson(
        _validSession.replaceFirst(
          '"expires_at":"2026-08-08T00:00:00Z"',
          '"expires_at":"2026-08-08T01:00:00Z"',
        ),
      ),
      throwsA(isA<FormatException>()),
    );
  });
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
