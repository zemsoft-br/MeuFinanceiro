import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

import '../../support/fake_auth_transport.dart';

const _token = 'FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF';
const _accountId = '40000000-0000-4000-8000-000000000004';
const _destinationAccountId = '41000000-0000-4000-8000-000000000041';
const _ownerId = '30000000-0000-4000-8000-000000000003';
const _transferId = '80000000-0000-4000-8000-000000000008';
const _sourceMovementId = '81000000-0000-4000-8000-000000000081';
const _destinationMovementId = '82000000-0000-4000-8000-000000000082';
const _reversalTransferId = '83000000-0000-4000-8000-000000000083';
const _reversalSourceMovementId = '84000000-0000-4000-8000-000000000084';
const _reversalDestinationMovementId =
    '85000000-0000-4000-8000-000000000085';
const _idempotencyKey = '90000000-0000-4000-8000-000000000009';

void main() {
  test(
    'loads transfer relations and reverses aggregate instead of a leg',
    () async {
    var reversed = false;
    final transport = FakeAuthTransport((
      uri,
      method,
      timeout,
      headers,
      body,
    ) async {
      final path = uri.path;
      if (method == AuthHttpMethod.post &&
          path == '/api/v1/finance/transfers/$_transferId/reversal') {
        final payload = jsonDecode(body!) as Map<String, dynamic>;
        expect(payload, isNot(contains('amount')));
        expect(payload['idempotencyKey'], _idempotencyKey);
        reversed = true;
        return const AuthHttpResponse(
          statusCode: 201,
          body: _reversalTransferObject,
        );
      }
      if (method != AuthHttpMethod.get) {
        return const AuthHttpResponse(statusCode: 405, body: '{}');
      }
      return switch (path) {
        '/api/v1/finance/accounts/$_accountId' =>
          const AuthHttpResponse(statusCode: 200, body: _accountObject),
        '/api/v1/finance/accounts/$_accountId/opening-balance' =>
          const AuthHttpResponse(
            statusCode: 200,
            body: '{"openingBalance":null}',
          ),
        '/api/v1/finance/accounts/$_accountId/balance' =>
          AuthHttpResponse(statusCode: 200, body: _balanceObject(reversed)),
        '/api/v1/finance/accounts/$_accountId/statement' =>
          AuthHttpResponse(statusCode: 200, body: _statementObject(reversed)),
        '/api/v1/finance/accounts/$_accountId/transfers' =>
          AuthHttpResponse(statusCode: 200, body: _transfersObject(reversed)),
        '/api/v1/finance/accounts' =>
          const AuthHttpResponse(statusCode: 200, body: _accountsObject),
        _ => const AuthHttpResponse(statusCode: 404, body: '{}'),
      };
    });
    final container = _container(transport);
    addTearDown(container.dispose);
    final provider = financialAccountDetailControllerProvider(_accountId);
    container.listen(provider, (previous, next) {}, fireImmediately: true);
    final controller = container.read(provider.notifier);

    await controller.load();

    var state = container.read(provider);
    expect(state.phase, FinancialLoadPhase.loaded);
    expect(state.transfers, hasLength(1));
    expect(state.transfers.single.transferId, _transferId);

    final didReverse = await controller.reverseTransfer(
      _transferId,
      FinancialTransferReversalInput(
        idempotencyKey: _idempotencyKey,
        effectiveDate: '2026-11-06',
        competenceDate: '2026-11-06',
        reason: 'Correção',
      ),
    );

    expect(didReverse, isTrue);
    state = container.read(provider);
    expect(state.phase, FinancialLoadPhase.loaded);
    expect(state.transfers, hasLength(2));
    expect(state.transfers.last.role, FinancialTransferRole.reversal);
    expect(state.transfers.last.reversalOfId, _transferId);
    expect(
      transport.calls
          .where(
            (call) =>
                call.method == AuthHttpMethod.post &&
                call.uri.path ==
                    '/api/v1/finance/transfers/$_transferId/reversal',
          )
          .length,
      1,
    );
    },
  );
}

ProviderContainer _container(FakeAuthTransport transport) {
  final container = ProviderContainer(
    overrides: [
      authTransportProvider.overrideWithValue(transport),
      authApiBaseUriProvider.overrideWithValue(
        Uri.parse('http://localhost/api/v1/'),
      ),
      authRequestTimeoutProvider.overrideWithValue(const Duration(seconds: 2)),
    ],
  );
  container.read(sessionTokenVaultProvider).store(_token);
  return container;
}

const _accountObject =
    '''
{
  "accountId":"$_accountId",
  "ownerOperatorId":"$_ownerId",
  "visibilityScope":"PERSONAL",
  "accountType":"CHECKING",
  "customTypeName":null,
  "name":"Conta Corrente",
  "currency":"BRL",
  "status":"ACTIVE",
  "createdAt":"2026-11-01T12:00:00Z",
  "updatedAt":"2026-11-01T12:00:00Z",
  "archivedAt":null
}
''';

const _destinationAccountObject =
    '''
{
  "accountId":"$_destinationAccountId",
  "ownerOperatorId":null,
  "visibilityScope":"HOUSEHOLD",
  "accountType":"CASH",
  "customTypeName":null,
  "name":"Carteira",
  "currency":"BRL",
  "status":"ACTIVE",
  "createdAt":"2026-11-01T12:00:00Z",
  "updatedAt":"2026-11-01T12:00:00Z",
  "archivedAt":null
}
''';

const _accountsObject =
    '''
{"accounts":[$_accountObject,$_destinationAccountObject]}
''';

String _balanceObject(bool reversed) =>
    '''
{
  "accountId":"$_accountId",
  "currency":"BRL",
  "openingBalance":null,
  "movementNet":{"amount":"${reversed ? '0' : '-10'}","currency":"BRL"},
  "currentBalance":{"amount":"${reversed ? '0' : '-10'}","currency":"BRL"},
  "movementCount":${reversed ? 2 : 1},
  "calculatedAt":"2026-11-06T12:00:00Z"
}
''';

String _statementObject(bool reversed) =>
    '''
{
  "accountId":"$_accountId",
  "currency":"BRL",
  "openingBalance":null,
  "entries":[
    {
      "movement":{
        "movementId":"$_sourceMovementId",
        "accountId":"$_accountId",
        "money":{"amount":"-10","currency":"BRL"},
        "resultEffect":"NEUTRAL",
        "role":"STANDARD",
        "effectiveDate":"2026-11-05",
        "competenceDate":"2026-11-05",
        "description":"Transferência",
        "reversalOfId":null,
        "reversalReason":null,
        "createdAt":"2026-11-05T12:00:00Z"
      },
      "balanceAfter":{"amount":"-10","currency":"BRL"}
    }
    ${reversed ? _reversalStatementEntry : ''}
  ],
  "closingBalance":{"amount":"${reversed ? '0' : '-10'}","currency":"BRL"},
  "calculatedAt":"2026-11-06T12:00:00Z"
}
''';

const _reversalStatementEntry =
    ''',
    {
      "movement":{
        "movementId":"$_reversalDestinationMovementId",
        "accountId":"$_accountId",
        "money":{"amount":"10","currency":"BRL"},
        "resultEffect":"NEUTRAL",
        "role":"REVERSAL",
        "effectiveDate":"2026-11-06",
        "competenceDate":"2026-11-06",
        "description":null,
        "reversalOfId":"$_sourceMovementId",
        "reversalReason":"Correção",
        "createdAt":"2026-11-06T12:00:00Z"
      },
      "balanceAfter":{"amount":"0","currency":"BRL"}
    }''';

String _transfersObject(bool reversed) =>
    '''
{
  "transfers":[
    $_standardTransferObject
    ${reversed ? ',$_reversalTransferObject' : ''}
  ]
}
''';

const _standardTransferObject =
    '''
{
  "transferId":"$_transferId",
  "sourceAccountId":"$_accountId",
  "destinationAccountId":"$_destinationAccountId",
  "currency":"BRL",
  "sourceMovementId":"$_sourceMovementId",
  "destinationMovementId":"$_destinationMovementId",
  "role":"STANDARD",
  "reversalOfId":null,
  "createdAt":"2026-11-05T12:00:00Z"
}
''';

const _reversalTransferObject =
    '''
{
  "transferId":"$_reversalTransferId",
  "sourceAccountId":"$_destinationAccountId",
  "destinationAccountId":"$_accountId",
  "currency":"BRL",
  "sourceMovementId":"$_reversalSourceMovementId",
  "destinationMovementId":"$_reversalDestinationMovementId",
  "role":"REVERSAL",
  "reversalOfId":"$_transferId",
  "createdAt":"2026-11-06T12:00:00Z"
}
''';
