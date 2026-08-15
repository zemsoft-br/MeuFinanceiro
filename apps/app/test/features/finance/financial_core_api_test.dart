import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_auth_transport.dart';

const _token = 'FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF';
const _accountId = '40000000-0000-4000-8000-000000000004';
const _ownerId = '30000000-0000-4000-8000-000000000003';
const _openingId = '50000000-0000-4000-8000-000000000005';
const _movementId = '60000000-0000-4000-8000-000000000006';
const _reversalId = '70000000-0000-4000-8000-000000000007';

void main() {
  test('lists accounts through strict authenticated wire contract', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 200,
      body: _accountsResponse,
    );
    final accounts = await _api(transport).listAccounts();

    expect(transport.calls, hasLength(1));
    expect(transport.calls.single.method, AuthHttpMethod.get);
    expect(transport.calls.single.uri.path, '/api/v1/finance/accounts');
    expect(accounts, hasLength(1));
    expect(accounts.single.accountId, _accountId);
    expect(accounts.single.ownerOperatorId, _ownerId);
    expect(accounts.single.accountType, FinancialAccountType.checking);
    expect(accounts.single.visibilityScope, FinancialVisibilityScope.personal);
  });

  test('account response rejects extra and missing keys', () async {
    for (final body in [
      _accountsResponse.replaceFirst(
        '"archivedAt":null',
        '"archivedAt":null,"balance":"100"',
      ),
      _accountsResponse.replaceFirst('"ownerOperatorId":"$_ownerId",', ''),
    ]) {
      await expectLater(
        _api(
          FakeAuthTransport.response(statusCode: 200, body: body),
        ).listAccounts(),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test(
    'opening balance preserves decimal string and rejects JSON number',
    () async {
      final valid = await _api(
        FakeAuthTransport.response(statusCode: 200, body: _openingResponse),
      ).getOpeningBalance(_accountId);
      expect(valid, isNotNull);
      expect(valid!.money.amount, '1234.50000000');

      final numeric = _openingResponse.replaceFirst(
        '"amount":"1234.50000000"',
        '"amount":1234.5',
      );
      await expectLater(
        _api(
          FakeAuthTransport.response(statusCode: 200, body: numeric),
        ).getOpeningBalance(_accountId),
        throwsA(isA<FormatException>()),
      );
    },
  );

  test('explicit null opening balance remains null', () async {
    final result = await _api(
      FakeAuthTransport.response(
        statusCode: 200,
        body: '{"openingBalance":null}',
      ),
    ).getOpeningBalance(_accountId);
    expect(result, isNull);
  });

  test(
    'movement parser preserves original and reversal as separate events',
    () async {
      final movements = await _api(
        FakeAuthTransport.response(statusCode: 200, body: _movementsResponse),
      ).listMovements(_accountId);

      expect(movements, hasLength(2));
      expect(movements[0].role, FinancialMovementRole.standard);
      expect(movements[0].money.amount, '-75.25');
      expect(movements[1].role, FinancialMovementRole.reversal);
      expect(movements[1].reversalOfId, _movementId);
      expect(movements[1].reversalReason, 'Lançamento incorreto');
    },
  );

  test(
    'create account body contains no client-controlled scope or balance',
    () async {
      final transport = FakeAuthTransport.response(
        statusCode: 201,
        body: _accountObject,
      );
      await _api(transport).createAccount(
        const FinancialAccountCreateInput(
          name: 'Conta principal',
          accountType: FinancialAccountType.checking,
          currency: 'BRL',
          visibilityScope: FinancialVisibilityScope.personal,
        ),
      );

      final body =
          jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
      expect(body.keys.toSet(), {
        'name',
        'accountType',
        'customTypeName',
        'currency',
        'visibilityScope',
      });
      for (final forbidden in [
        'ownerOperatorId',
        'residenceId',
        'installationId',
        'operatorId',
        'balance',
        'status',
      ]) {
        expect(body, isNot(contains(forbidden)));
      }
    },
  );

  test('CUSTOM input requires customTypeName and non-CUSTOM forbids it', () {
    expect(
      () => const FinancialAccountCreateInput(
        name: 'Outro',
        accountType: FinancialAccountType.custom,
        currency: 'BRL',
        visibilityScope: FinancialVisibilityScope.personal,
      ).toJson(),
      throwsA(isA<FormatException>()),
    );
    expect(
      () => const FinancialAccountCreateInput(
        name: 'Conta',
        accountType: FinancialAccountType.checking,
        currency: 'BRL',
        visibilityScope: FinancialVisibilityScope.personal,
        customTypeName: 'Não permitido',
      ).toJson(),
      throwsA(isA<FormatException>()),
    );
  });

  test(
    'opening create keeps amount as JSON string without floating point',
    () async {
      final transport = FakeAuthTransport.response(
        statusCode: 201,
        body: _openingObject,
      );
      await _api(transport).createOpeningBalance(
        _accountId,
        FinancialOpeningBalanceCreateInput(
          amount: '-12.34000000',
          currency: 'BRL',
          effectiveDate: '2026-08-01',
        ),
      );
      final body =
          jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
      expect(body['amount'], '-12.34000000');
      expect(body['amount'], isA<String>());
    },
  );

  test(
    'wire validation rejects invalid ids currency enum timestamp and date',
    () async {
      for (final body in [
        _accountsResponse.replaceFirst(_accountId, 'not-a-resource-id'),
        _accountsResponse.replaceFirst('"currency":"BRL"', '"currency":"brl"'),
        _accountsResponse.replaceFirst(
          '"status":"ACTIVE"',
          '"status":"UNKNOWN"',
        ),
        _accountsResponse.replaceFirst(
          '"createdAt":"2026-08-13T12:00:00Z"',
          '"createdAt":"2026-08-13T12:00:00"',
        ),
      ]) {
        await expectLater(
          _api(
            FakeAuthTransport.response(statusCode: 200, body: body),
          ).listAccounts(),
          throwsA(isA<FormatException>()),
        );
      }
      expect(
        () => FinancialOpeningBalanceCreateInput(
          amount: '1.00',
          currency: 'BRL',
          effectiveDate: '2026-02-30',
        ),
        throwsA(isA<FormatException>()),
      );
    },
  );

  test('FinancialMoneyWire preserves high precision and redacts repr', () {
    final money = FinancialMoneyWire(
      amount: '9999999999999999.12345678',
      currency: 'BRL',
    );
    expect(money.amount, '9999999999999999.12345678');
    expect(money.toJson()['amount'], isA<String>());
    expect(money.toString(), isNot(contains(money.amount)));
  });
}

FinancialCoreApi _api(FakeAuthTransport transport) {
  final vault = SessionTokenVault()..store(_token);
  return FinancialCoreApi(
    AuthenticatedApiClient(
      transport: transport,
      tokenVault: vault,
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () {},
    ),
  );
}

const _accountObject =
    '''
{
  "accountId":"$_accountId",
  "ownerOperatorId":"$_ownerId",
  "visibilityScope":"PERSONAL",
  "accountType":"CHECKING",
  "customTypeName":null,
  "name":"Conta principal",
  "currency":"BRL",
  "status":"ACTIVE",
  "createdAt":"2026-08-13T12:00:00Z",
  "updatedAt":"2026-08-13T12:00:00Z",
  "archivedAt":null
}
''';

const _accountsResponse = '''{"accounts":[$_accountObject]}''';

const _openingObject =
    '''
{
  "openingBalanceId":"$_openingId",
  "accountId":"$_accountId",
  "money":{"amount":"1234.50000000","currency":"BRL"},
  "effectiveDate":"2026-08-01",
  "createdAt":"2026-08-13T12:00:00Z"
}
''';

const _openingResponse = '''{"openingBalance":$_openingObject}''';

const _movementsResponse =
    '''
{
  "movements":[
    {
      "movementId":"$_movementId",
      "accountId":"$_accountId",
      "money":{"amount":"-75.25","currency":"BRL"},
      "resultEffect":"EXPENSE",
      "role":"STANDARD",
      "effectiveDate":"2026-08-12",
      "competenceDate":"2026-08-12",
      "description":"Mercado",
      "reversalOfId":null,
      "reversalReason":null,
      "createdAt":"2026-08-13T12:00:00Z"
    },
    {
      "movementId":"$_reversalId",
      "accountId":"$_accountId",
      "money":{"amount":"75.25","currency":"BRL"},
      "resultEffect":"EXPENSE",
      "role":"REVERSAL",
      "effectiveDate":"2026-08-13",
      "competenceDate":"2026-08-13",
      "description":null,
      "reversalOfId":"$_movementId",
      "reversalReason":"Lançamento incorreto",
      "createdAt":"2026-08-13T12:00:00Z"
    }
  ]
}
''';
