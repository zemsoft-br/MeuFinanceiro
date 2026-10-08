import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_project_screen.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_finance_backend.dart';

FinancialCoreApi _api(Map<String, Object?> response) {
  final transport = FakeAuthTransport(
    (uri, method, timeout, headers, body) async {
      return AuthHttpResponse(statusCode: 200, body: jsonEncode(response));
    },
  );
  return FinancialCoreApi(
    AuthenticatedApiClient(
      transport: transport,
      tokenVault: SessionTokenVault()..store(financeTestToken),
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () {},
    ),
  );
}

void main() {
  testWidgets('projects empty state is explicit and create remains available', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1366, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          financialCoreApiProvider.overrideWithValue(_api({'items': []})),
        ],
        child: const MaterialApp(
          home: Scaffold(body: FinancialProjectScreen()),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(FinancialProjectScreen.titleKey), findsOneWidget);
    expect(find.byKey(FinancialProjectScreen.emptyKey), findsOneWidget);
    expect(find.byKey(FinancialProjectScreen.noticeKey), findsOneWidget);
    final create = tester.widget<FilledButton>(
      find.byKey(FinancialProjectScreen.createKey),
    );
    expect(create.onPressed, isNotNull);
    expect(tester.takeException(), isNull);
  });
}
