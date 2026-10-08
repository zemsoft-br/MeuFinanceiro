import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_finance_backend.dart';

const _projectId = 'c4000000-0000-4000-8000-000000000001';
const _movementId = 'c5000000-0000-4000-8000-000000000001';
const _linkId = 'c6000000-0000-4000-8000-000000000001';
const _moment = '2026-10-08T17:00:00Z';

Map<String, Object?> _project({
  String amount = '500',
  String currency = 'BRL',
}) => {
  'id': _projectId,
  'ownerOperatorId': financeTestOwnerId,
  'visibilityScope': 'HOUSEHOLD',
  'title': 'Reforma',
  'description': null,
  'currency': currency,
  'planned': {'amount': amount, 'currency': currency},
  'targetDate': null,
  'version': 1,
  'createdAt': _moment,
  'updatedAt': _moment,
  'canEdit': true,
};

Map<String, Object?> _link({String? projectId = _projectId}) => {
  'id': _linkId,
  'movementId': _movementId,
  'projectId': projectId,
  'supersedesId': null,
  'revision': 1,
  'actorOperatorId': financeTestOwnerId,
  'createdAt': _moment,
};

Map<String, Object?> _summary() => {
  'project': _project(),
  'realized': {'amount': '125', 'currency': 'BRL'},
  'remaining': {'amount': '375', 'currency': 'BRL'},
  'excess': {'amount': '0', 'currency': 'BRL'},
  'progressPercent': '25.00',
  'progressStatus': 'UNDER',
  'expenseCount': 1,
  'expenses': [
    {
      'movementId': _movementId,
      'description': 'Material de obra',
      'effectiveDate': '2026-10-08',
      'originalAmount': {'amount': '125', 'currency': 'BRL'},
      'realized': {'amount': '125', 'currency': 'BRL'},
      'reversed': false,
    },
  ],
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

void main() {
  group('project inputs', () {
    test('amount stays decimal text and scope remains explicit', () {
      final input = FinancialProjectCreateInput(
        title: ' Reforma ', visibilityScope: FinancialVisibilityScope.household,
        currency: 'BRL', plannedAmount: '500.00',
      );
      expect(input.title, 'Reforma');
      expect(input.toJson()['plannedAmount'], '500.00');
      expect(input.toJson()['visibilityScope'], 'HOUSEHOLD');
      expect(
        input.withIdempotencyKey(input.idempotencyKey).idempotencyKey,
        input.idempotencyKey,
      );
      expect(
        () => FinancialProjectCreateInput(
          title: 'Reforma', visibilityScope: FinancialVisibilityScope.shared,
          currency: 'BRL', plannedAmount: '500',
        ),
        throwsFormatException,
      );
      expect(
        () => FinancialProjectCreateInput(
          title: 'Reforma',
          visibilityScope: FinancialVisibilityScope.personal,
          currency: 'BRL', plannedAmount: '-1',
        ),
        throwsFormatException,
      );
    });

    test('unlinked without predecessor is rejected', () {
      expect(() => FinancialProjectLinkInput(), throwsFormatException);
      final command = FinancialProjectLinkInput(projectId: _projectId);
      expect(command.toJson()['expectedPredecessorId'], isNull);
      expect(command.toJson()['projectId'], _projectId);
    });
  });

  test('server summary and link are strict and never recomputed on client', () async {
    final transport = FakeAuthTransport((uri, method, timeout, headers, body) async {
      final result = switch (uri.path) {
        '/api/v1/finance/projects' => {'items': [_project()]},
        '/api/v1/finance/projects/$_projectId/summary' => _summary(),
        '/api/v1/finance/movements/$_movementId/project-link' =>
          {'link': _link()},
        '/api/v1/finance/movements/$_movementId/project-link/revisions' =>
          {'items': [_link()]},
        _ => _project(),
      };
      return AuthHttpResponse(statusCode: 200, body: jsonEncode(result));
    });
    final api = _api(transport);
    expect((await api.listProjects()).single.title, 'Reforma');
    final summary = await api.getProjectSummary(_projectId);
    expect(summary.realized.amount, '125');
    expect(summary.remaining.amount, '375');
    expect(summary.progressPercent, '25.00');
    expect(summary.expenses.single.movementId, _movementId);
    expect(summary.expenses.single.description, 'Material de obra');
    expect(summary.expenses.single.effectiveDate, '2026-10-08');
    expect((await api.getProjectLink(_movementId))?.projectId, _projectId);
    expect((await api.getProjectLinkHistory(_movementId)).length, 1);
    expect(transport.calls.every((call) => call.method == AuthHttpMethod.get), isTrue);
  });

  test('an invalid server money shape fails closed', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 200,
      body: jsonEncode({'items': [_project(amount: '-500')]}),
    );
    await expectLater(_api(transport).listProjects(), throwsFormatException);
  });

  test('link write preserves explicit idempotency and predecessor material', () async {
    final transport = FakeAuthTransport((uri, method, timeout, headers, body) async {
      return AuthHttpResponse(statusCode: 201, body: jsonEncode(_link()));
    });
    final input = FinancialProjectLinkInput(projectId: _projectId);
    final link = await _api(transport).reviseProjectLink(_movementId, input);
    expect(link.revision, 1);
    final sent = jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
    expect(sent['idempotencyKey'], input.idempotencyKey);
    expect(sent['projectId'], _projectId);
    expect(sent['expectedPredecessorId'], isNull);
    expect(transport.calls.single.method, AuthHttpMethod.post);
  });
}
