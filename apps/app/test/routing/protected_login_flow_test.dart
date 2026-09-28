import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/auth/login_screen.dart';
import 'package:meufinanceiro_app/routing/auth_route_guard.dart';
import 'package:meufinanceiro_app/theme/app_theme.dart';

import '../support/fake_auth_transport.dart';

const _token = 'DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD';

void main() {
  testWidgets('successful login resumes a sanitized protected deep link', (
    tester,
  ) async {
    final router = GoRouter(
      initialLocation: '/login?redirect=%2Fprotected',
      routes: [
        GoRoute(
          path: '/login',
          builder: (context, state) => LoginScreen(
            redirectTo: AuthRouteGuard.sanitizeRedirect(
              state.uri.queryParameters['redirect'],
            ),
          ),
        ),
        GoRoute(
          path: '/protected',
          builder: (context, state) => const Scaffold(
            body: Center(child: Text('Protected destination')),
          ),
        ),
      ],
    );
    addTearDown(router.dispose);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authTransportProvider.overrideWithValue(
            FakeAuthTransport.response(statusCode: 200, body: _issuedSession),
          ),
          authApiBaseUriProvider.overrideWithValue(
            Uri.parse('http://localhost/api/v1/'),
          ),
        ],
        child: MaterialApp.router(theme: buildAppTheme(), routerConfig: router),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(LoginScreen.loginFieldKey), 'admin');
    await tester.enterText(
      find.byKey(LoginScreen.passwordFieldKey),
      'synthetic-password',
    );
    await tester.tap(find.byKey(LoginScreen.submitButtonKey));
    await tester.pumpAndSettle();

    expect(find.text('Protected destination'), findsOneWidget);
    expect(find.textContaining(_token), findsNothing);
  });
}

const _issuedSession =
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
