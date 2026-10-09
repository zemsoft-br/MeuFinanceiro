import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_project_controller.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_finance_backend.dart';

const _projectId = 'b4000000-0000-4000-8000-000000000001';
const _time = '2026-10-08T17:00:00Z';

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
  'createdAt': _time,
  'updatedAt': _time,
  'canEdit': true,
};

Map<String, Object?> _summary() => {
  'project': _project(),
  'realized': {'amount': '0', 'currency': 'BRL'},
  'remaining': {'amount': '500', 'currency': 'BRL'},
  'excess': {'amount': '0', 'currency': 'BRL'},
  'progressPercent': '0.00',
  'progressStatus': 'UNDER',
  'expenseCount': 0,
  'expenses': <Object?>[],
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

FinancialProjectCreateInput _input() => FinancialProjectCreateInput(
  title: 'Reforma',
  visibilityScope: FinancialVisibilityScope.household,
  currency: 'BRL',
  plannedAmount: '500',
);

void main() {
  test(
    'POST 201 without canonical read is UNKNOWN; explicit retry reuses key',
    () async {
      var created = false;
      var failCanonicalRead = true;
      final sentKeys = <String>[];
      final transport = FakeAuthTransport((
        uri,
        method,
        timeout,
        headers,
        body,
      ) async {
        if (uri.path.endsWith('/finance/projects') &&
            method == AuthHttpMethod.post) {
          final payload = jsonDecode(body!) as Map<String, dynamic>;
          sentKeys.add(payload['idempotencyKey'] as String);
          created = true;
          return AuthHttpResponse(
            statusCode: 201,
            body: jsonEncode(_project()),
          );
        }
        if (uri.path.endsWith('/finance/projects') &&
            method == AuthHttpMethod.get) {
          if (created && failCanonicalRead) {
            return const AuthHttpResponse(statusCode: 503, body: '{}');
          }
          return AuthHttpResponse(
            statusCode: 200,
            body: jsonEncode({
              'items': created ? [_project()] : [],
            }),
          );
        }
        if (uri.path.endsWith('/finance/projects/$_projectId/summary')) {
          return AuthHttpResponse(
            statusCode: 200,
            body: jsonEncode(_summary()),
          );
        }
        throw StateError('unexpected project route: $method ${uri.path}');
      });
      final container = ProviderContainer(
        overrides: [
          financialCoreApiProvider.overrideWithValue(_api(transport)),
        ],
      );
      addTearDown(container.dispose);
      container.listen(financialProjectsControllerProvider, (_, _) {});
      final controller = container.read(
        financialProjectsControllerProvider.notifier,
      );

      expect(await controller.load(), isTrue);
      expect(
        container.read(financialProjectsControllerProvider).phase,
        FinancialLoadPhase.empty,
      );
      final first = await controller.create(_input());
      expect(first, FinancialProjectWriteOutcome.unknown);
      expect(sentKeys, hasLength(1));
      expect(
        container.read(financialProjectsControllerProvider).trusted,
        isFalse,
      );
      expect(container.read(financialProjectsControllerProvider).busy, isFalse);
      // No automatic second POST; the operator first restores canonical reads.
      failCanonicalRead = false;
      expect(await controller.refresh(), isTrue);
      expect(
        container.read(financialProjectsControllerProvider).trusted,
        isTrue,
      );
      final retry = await controller.create(_input());
      expect(retry, FinancialProjectWriteOutcome.confirmed);
      expect(sentKeys, hasLength(2));
      expect(sentKeys[0], sentKeys[1]);
      expect(
        container.read(financialProjectsControllerProvider).selectedId,
        _projectId,
      );
      expect(
        transport.calls.where((call) => call.method == AuthHttpMethod.post),
        hasLength(2),
      );
    },
  );

  test(
    'PUT 200 superseded by another writer is UNKNOWN, not confirmed',
    () async {
      var updated = false;
      final otherProject = {
        ..._project(),
        'version': 3,
        'title': 'Outro autor',
      };
      final ours = {..._project(), 'version': 2, 'title': 'Meu plano'};
      final transport = FakeAuthTransport((
        uri,
        method,
        timeout,
        headers,
        body,
      ) async {
        if (uri.path.endsWith('/finance/projects/$_projectId') &&
            method == AuthHttpMethod.put) {
          updated = true;
          return AuthHttpResponse(statusCode: 200, body: jsonEncode(ours));
        }
        if (uri.path.endsWith('/finance/projects') &&
            method == AuthHttpMethod.get) {
          return AuthHttpResponse(
            statusCode: 200,
            body: jsonEncode({
              'items': [updated ? otherProject : _project()],
            }),
          );
        }
        if (uri.path.endsWith('/finance/projects/$_projectId/summary')) {
          return AuthHttpResponse(
            statusCode: 200,
            body: jsonEncode({
              ..._summary(),
              'project': updated ? otherProject : _project(),
            }),
          );
        }
        throw StateError('unexpected route: $method ${uri.path}');
      });
      final container = ProviderContainer(
        overrides: [
          financialCoreApiProvider.overrideWithValue(_api(transport)),
        ],
      );
      addTearDown(container.dispose);
      container.listen(financialProjectsControllerProvider, (_, _) {});
      final controller = container.read(
        financialProjectsControllerProvider.notifier,
      );
      expect(await controller.load(), isTrue);
      final outcome = await controller.replace(
        _projectId,
        FinancialProjectReplaceInput(
          expectedVersion: 1,
          title: 'Meu plano',
          currency: 'BRL',
          plannedAmount: '500',
        ),
      );
      expect(updated, isTrue);
      expect(outcome, FinancialProjectWriteOutcome.unknown);
      final state = container.read(financialProjectsControllerProvider);
      expect(state.projects.single.version, 3);
      expect(state.summary?.project.version, 3);
    },
  );

  test(
    'POST 201 but canonical list omits created project cannot confirm',
    () async {
      var posted = false;
      final transport = FakeAuthTransport((
        uri,
        method,
        timeout,
        headers,
        body,
      ) async {
        if (uri.path.endsWith('/finance/projects') &&
            method == AuthHttpMethod.post) {
          posted = true;
          return AuthHttpResponse(
            statusCode: 201,
            body: jsonEncode(_project()),
          );
        }
        if (uri.path.endsWith('/finance/projects')) {
          return AuthHttpResponse(
            statusCode: 200,
            body: jsonEncode({'items': <Object?>[]}),
          );
        }
        throw StateError('unexpected route: ${uri.path}');
      });
      final container = ProviderContainer(
        overrides: [
          financialCoreApiProvider.overrideWithValue(_api(transport)),
        ],
      );
      addTearDown(container.dispose);
      container.listen(financialProjectsControllerProvider, (_, _) {});
      final controller = container.read(
        financialProjectsControllerProvider.notifier,
      );

      expect(await controller.load(), isTrue);
      expect(
        await controller.create(_input()),
        FinancialProjectWriteOutcome.unknown,
      );
      expect(posted, isTrue);
      expect(
        container.read(financialProjectsControllerProvider).trusted,
        isFalse,
      );
      expect(
        await controller.create(_input()),
        FinancialProjectWriteOutcome.notAllowed,
      );
      expect(
        transport.calls.where((call) => call.method == AuthHttpMethod.post),
        hasLength(1),
      );
    },
  );
}
