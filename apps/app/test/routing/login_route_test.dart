import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/app/app.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/auth/login_screen.dart';
import 'package:meufinanceiro_app/routing/app_router.dart';

import '../support/fake_auth_transport.dart';

void main() {
  testWidgets('opens canonical login route without the application shell', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          initialLocationProvider.overrideWithValue('/login'),
          authTransportProvider.overrideWithValue(
            FakeAuthTransport.response(statusCode: 503, body: '{}'),
          ),
        ],
        child: const MeuFinanceiroApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Entrar no MeuFinanceiro'), findsOneWidget);
    expect(find.byKey(LoginScreen.loginFieldKey), findsOneWidget);
    expect(find.byKey(LoginScreen.passwordFieldKey), findsOneWidget);
    expect(find.byKey(LoginScreen.submitButtonKey), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
