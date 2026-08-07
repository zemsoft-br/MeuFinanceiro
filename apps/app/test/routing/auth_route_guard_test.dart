import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';
import 'package:meufinanceiro_app/routing/auth_route_guard.dart';

void main() {
  test('protected deep link redirects signed-out user to login', () {
    final redirect = AuthRouteGuard.redirectForProtectedRoute(
      session: const OperatorSessionState.signedOut(),
      location: Uri.parse('/app/integracoes/pluggy/conectar?step=1'),
    );

    final uri = Uri.parse(redirect!);
    expect(uri.path, '/login');
    expect(
      uri.queryParameters['redirect'],
      '/app/integracoes/pluggy/conectar?step=1',
    );
  });

  test('authenticated session may continue to protected route', () {
    final principal = OperatorPrincipal.fromPayload(const {
      'operator_id': '10000000-0000-4000-8000-000000000001',
      'installation_id': '20000000-0000-4000-8000-000000000002',
      'primary_residence_id': '30000000-0000-4000-8000-000000000003',
      'login': 'admin',
      'role': 'installation_admin',
      'expires_at': '2026-08-08T00:00:00Z',
    });

    expect(
      AuthRouteGuard.redirectForProtectedRoute(
        session: OperatorSessionState.authenticated(principal),
        location: Uri.parse('/app/integracoes/pluggy/conectar'),
      ),
      isNull,
    );
  });

  test('external and recursive redirects are rejected', () {
    expect(
      AuthRouteGuard.sanitizeRedirect('https://evil.example/steal'),
      isNull,
    );
    expect(AuthRouteGuard.sanitizeRedirect('//evil.example/steal'), isNull);
    expect(AuthRouteGuard.sanitizeRedirect('/login'), isNull);
    expect(
      AuthRouteGuard.sanitizeRedirect('/app/integracoes/pluggy/conectar'),
      '/app/integracoes/pluggy/conectar',
    );
  });
}
