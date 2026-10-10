import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_project_link_dialog.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_finance_backend.dart';

const _projectId = 'a4000000-0000-4000-8000-000000000001';
const _movementId = 'a5000000-0000-4000-8000-000000000001';
const _linkId = 'a6000000-0000-4000-8000-000000000001';
const _stamp = '2026-10-08T17:00:00Z';

FinancialAccount _account({bool archived = false}) => FinancialAccount(
  accountId: 'a7000000-0000-4000-8000-000000000001',
  ownerOperatorId: financeTestOwnerId,
  visibilityScope: FinancialVisibilityScope.household,
  accountType: FinancialAccountType.checking,
  customTypeName: null,
  name: 'Conta casa',
  currency: 'BRL',
  status: archived
      ? FinancialAccountStatus.archived
      : FinancialAccountStatus.active,
  createdAt: DateTime.parse(_stamp),
  updatedAt: DateTime.parse(_stamp),
  archivedAt: archived ? DateTime.parse(_stamp) : null,
);

FinancialMovement _movement() => FinancialMovement(
  movementId: _movementId,
  accountId: _account().accountId,
  money: FinancialMoneyWire(amount: '-125', currency: 'BRL'),
  resultEffect: FinancialResultEffect.expense,
  role: FinancialMovementRole.standard,
  effectiveDate: '2026-10-08',
  competenceDate: '2026-10-08',
  description: 'Material',
  reversalOfId: null,
  reversalReason: null,
  createdAt: DateTime.parse(_stamp),
);

Map<String, Object?> _project() => {
  'id': _projectId,
  'ownerOperatorId': financeTestOwnerId,
  'visibilityScope': 'HOUSEHOLD',
  'title': 'Reforma',
  'description': null,
  'currency': 'BRL',
  'planned': {'amount': '500', 'currency': 'BRL'},
  'targetDate': null,
  'version': 1,
  'createdAt': _stamp,
  'updatedAt': _stamp,
  'canEdit': true,
};

Map<String, Object?> _link() => {
  'id': _linkId,
  'movementId': _movementId,
  'projectId': _projectId,
  'supersedesId': null,
  'revision': 1,
  'actorOperatorId': financeTestOwnerId,
  'createdAt': _stamp,
};

FinancialCoreApi _api(FakeAuthTransport transport) => FinancialCoreApi(
  AuthenticatedApiClient(
    transport: transport,
    tokenVault: SessionTokenVault()..store(financeTestToken),
    apiBaseUri: Uri.parse('http://localhost/api/v1/'),
    timeout: const Duration(seconds: 2),
    onUnauthorized: () {},
  ),
);

Future<void> _open(
  WidgetTester tester,
  FakeAuthTransport transport, {
  bool archived = false,
  required ValueChanged<FinancialProjectLinkInput?> onResult,
}) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [financialCoreApiProvider.overrideWithValue(_api(transport))],
      child: MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () async {
                final result = await showDialog<FinancialProjectLinkInput>(
                  context: context,
                  builder: (_) => FinancialProjectLinkDialog(
                    account: _account(archived: archived),
                    movement: _movement(),
                  ),
                );
                onResult(result);
              },
              child: const Text('Abrir vínculo'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('Abrir vínculo'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('opening a statement editor makes two reads, never N+1', (
    tester,
  ) async {
    final transport = FakeAuthTransport((
      uri,
      method,
      timeout,
      headers,
      body,
    ) async {
      final response = uri.path.endsWith('/projects')
          ? {
              'items': [_project()],
            }
          : {'link': null};
      return AuthHttpResponse(statusCode: 200, body: jsonEncode(response));
    });
    FinancialProjectLinkInput? result;
    await _open(tester, transport, onResult: (value) => result = value);
    expect(transport.calls.length, 2);
    expect(transport.calls.map((call) => call.method).toSet(), {
      AuthHttpMethod.get,
    });
    expect(find.byKey(FinancialProjectLinkDialog.dialogKey), findsOneWidget);
    await tester.tap(find.byKey(FinancialProjectLinkDialog.projectKey));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Reforma').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(FinancialProjectLinkDialog.saveKey));
    await tester.pumpAndSettle();
    expect(result?.projectId, _projectId);
    expect(result?.expectedPredecessorId, isNull);
    expect(transport.calls.length, 2);
  });

  testWidgets('an archived account may only unlink its historical expense', (
    tester,
  ) async {
    final transport = FakeAuthTransport((
      uri,
      method,
      timeout,
      headers,
      body,
    ) async {
      final response = uri.path.endsWith('/projects')
          ? {
              'items': [_project()],
            }
          : {'link': _link()};
      return AuthHttpResponse(statusCode: 200, body: jsonEncode(response));
    });
    FinancialProjectLinkInput? result;
    await _open(
      tester,
      transport,
      archived: true,
      onResult: (value) => result = value,
    );
    expect(find.byKey(FinancialProjectLinkDialog.projectKey), findsNothing);
    expect(find.byKey(FinancialProjectLinkDialog.historyKey), findsOneWidget);
    await tester.tap(find.byKey(FinancialProjectLinkDialog.unlinkKey));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(FinancialProjectLinkDialog.saveKey));
    await tester.pumpAndSettle();
    expect(result?.projectId, isNull);
    expect(result?.expectedPredecessorId, _linkId);
  });
}
