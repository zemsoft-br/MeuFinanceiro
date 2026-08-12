import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/auth/login_screen.dart';
import 'package:meufinanceiro_app/theme/app_theme.dart';

import '../../support/fake_auth_transport.dart';

void main() {
  testWidgets('invalid credentials are generic and password is cleared', (
    tester,
  ) async {
    final transport = FakeAuthTransport.response(
      statusCode: 401,
      body: '{"detail":"operator credentials are invalid"}',
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authTransportProvider.overrideWithValue(transport),
          authApiBaseUriProvider.overrideWithValue(
            Uri.parse('http://localhost/api/v1/'),
          ),
        ],
        child: MaterialApp(theme: buildAppTheme(), home: const LoginScreen()),
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

    expect(
      find.text('Não foi possível entrar com essas credenciais.'),
      findsOneWidget,
    );
    final passwordField = tester.widget<TextFormField>(
      find.byKey(LoginScreen.passwordFieldKey),
    );
    expect(passwordField.controller?.text, isEmpty);
    expect(find.textContaining('synthetic-password'), findsNothing);
  });

  testWidgets('password visibility toggle is accessible', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authTransportProvider.overrideWithValue(
            FakeAuthTransport.response(statusCode: 503, body: '{}'),
          ),
        ],
        child: MaterialApp(theme: buildAppTheme(), home: const LoginScreen()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byTooltip('Mostrar senha'), findsOneWidget);
    await tester.tap(find.byKey(LoginScreen.passwordVisibilityKey));
    await tester.pump();
    expect(find.byTooltip('Ocultar senha'), findsOneWidget);
  });

  testWidgets('login screen has no overflow at 320 px with text scaled 2x', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authTransportProvider.overrideWithValue(
            FakeAuthTransport.response(statusCode: 503, body: '{}'),
          ),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const MediaQuery(
            data: MediaQueryData(textScaler: TextScaler.linear(2)),
            child: LoginScreen(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Entrar no MeuFinanceiro'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
