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
const _destinationAccountId = '41000000-0000-4000-8000-000000000041';
const _transferId = '80000000-0000-4000-8000-000000000008';
const _sourceTransferMovementId = '81000000-0000-4000-8000-000000000081';
const _destinationTransferMovementId = '82000000-0000-4000-8000-000000000082';
const _reversalTransferId = '83000000-0000-4000-8000-000000000083';
const _reversalSourceTransferMovementId =
    '84000000-0000-4000-8000-000000000084';
const _reversalDestinationTransferMovementId =
    '85000000-0000-4000-8000-000000000085';
const _idempotencyKey = '90000000-0000-4000-8000-000000000009';
const _categoryId = 'a1000000-0000-4000-8000-0000000000a1';
const _childCategoryId = 'b2000000-0000-4000-8000-0000000000b2';
const _disabledCategoryId = 'c3000000-0000-4000-8000-0000000000c3';
const _personalCategoryId = 'd4000000-0000-4000-8000-0000000000d4';
const _allocationSetId = 'e5000000-0000-4000-8000-0000000000e5';
const _otherAllocationSetId = 'e6000000-0000-4000-8000-0000000000e6';
const _otherMovementId = '61000000-0000-4000-8000-000000000061';

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

  test('manual income uses semantic endpoint and string money', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 201,
      body: _incomeMovementObject,
    );
    final movement = await _api(transport).createManualEntry(
      _accountId,
      FinancialManualEntryKind.income,
      FinancialManualEntryCreateInput(
        idempotencyKey: _idempotencyKey,
        amount: '125.50',
        currency: 'BRL',
        effectiveDate: '2026-09-20',
        competenceDate: '2026-09-20',
        description: 'Receita manual',
      ),
    );

    expect(
      transport.calls.single.uri.path,
      '/api/v1/finance/accounts/$_accountId/income',
    );
    final body =
        jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
    expect(body.keys.toSet(), {
      'idempotencyKey',
      'amount',
      'currency',
      'effectiveDate',
      'competenceDate',
      'description',
    });
    expect(body['idempotencyKey'], _idempotencyKey);
    expect(body['amount'], '125.50');
    expect(body['amount'], isA<String>());
    expect(movement.resultEffect, FinancialResultEffect.income);
  });

  test('manual inputs reject zero negative and invalid idempotency', () {
    for (final amount in ['0', '0.00', '-1.00']) {
      expect(
        () => FinancialManualEntryCreateInput(
          idempotencyKey: _idempotencyKey,
          amount: amount,
          currency: 'BRL',
          effectiveDate: '2026-09-20',
          competenceDate: '2026-09-20',
          description: 'Teste',
        ),
        throwsA(isA<FormatException>()),
      );
    }
    expect(
      () => FinancialManualEntryCreateInput(
        idempotencyKey: 'not-a-uuid',
        amount: '1.00',
        currency: 'BRL',
        effectiveDate: '2026-09-20',
        competenceDate: '2026-09-20',
        description: 'Teste',
      ),
      throwsA(isA<FormatException>()),
    );

    final generated = FinancialManualEntryCreateInput(
      amount: '1.00',
      currency: 'BRL',
      effectiveDate: '2026-09-20',
      competenceDate: '2026-09-20',
      description: 'Teste',
    ).idempotencyKey;
    expect(
      generated,
      matches(
        RegExp(
          r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ),
      ),
    );
  });

  test('movement reversal never sends caller-controlled amount', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 201,
      body: _reversalMovementObject,
    );
    final movement = await _api(transport).reverseMovement(
      _movementId,
      FinancialMovementReversalInput(
        idempotencyKey: _idempotencyKey,
        effectiveDate: '2026-09-20',
        competenceDate: '2026-09-20',
        reason: 'Correção',
      ),
    );

    expect(
      transport.calls.single.uri.path,
      '/api/v1/finance/movements/$_movementId/reversal',
    );
    final body =
        jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
    expect(body, isNot(contains('amount')));
    expect(body.keys.toSet(), {
      'idempotencyKey',
      'effectiveDate',
      'competenceDate',
      'reason',
    });
    expect(movement.role, FinancialMovementRole.reversal);
    expect(movement.reversalOfId, _movementId);
  });

  test(
    'transfer uses semantic aggregate endpoint and preserves string money',
    () async {
      final transport = FakeAuthTransport.response(
        statusCode: 201,
        body: _transferObject,
      );
      final transfer = await _api(transport).createTransfer(
        FinancialTransferCreateInput(
          idempotencyKey: _idempotencyKey,
          sourceAccountId: _accountId,
          destinationAccountId: _destinationAccountId,
          amount: '80.25',
          currency: 'BRL',
          effectiveDate: '2026-09-20',
          competenceDate: '2026-09-20',
          description: 'Reserva',
        ),
      );

      expect(transport.calls.single.uri.path, '/api/v1/finance/transfers');
      final body =
          jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
      expect(body['amount'], '80.25');
      expect(body['amount'], isA<String>());
      expect(transfer.transferId, _transferId);
      expect(transfer.role, FinancialTransferRole.standard);
    },
  );

  test('lists account transfer relations through strict read model', () async {
    final transport = FakeAuthTransport.response(
      statusCode: 200,
      body: _transfersResponse,
    );
    final transfers = await _api(transport).listTransfers(_accountId);

    expect(transport.calls.single.method, AuthHttpMethod.get);
    expect(
      transport.calls.single.uri.path,
      '/api/v1/finance/accounts/$_accountId/transfers',
    );
    expect(transfers, hasLength(2));
    expect(transfers.first.transferId, _transferId);
    expect(transfers.first.role, FinancialTransferRole.standard);
    expect(transfers.last.role, FinancialTransferRole.reversal);
    expect(transfers.last.reversalOfId, _transferId);
  });

  test(
    'transfer reversal uses aggregate endpoint and sends no amount',
    () async {
      final transport = FakeAuthTransport.response(
        statusCode: 201,
        body: _transferReversalObject,
      );
      final transfer = await _api(transport).reverseTransfer(
        _transferId,
        FinancialTransferReversalInput(
          idempotencyKey: _idempotencyKey,
          effectiveDate: '2026-09-21',
          competenceDate: '2026-09-21',
          reason: 'Correção da transferência',
        ),
      );

      expect(
        transport.calls.single.uri.path,
        '/api/v1/finance/transfers/$_transferId/reversal',
      );
      final body =
          jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
      expect(body, isNot(contains('amount')));
      expect(body.keys.toSet(), {
        'idempotencyKey',
        'effectiveDate',
        'competenceDate',
        'reason',
      });
      expect(transfer.role, FinancialTransferRole.reversal);
      expect(transfer.reversalOfId, _transferId);
    },
  );

  test('balance and statement are parsed as backend-derived values', () async {
    final balance = await _api(
      FakeAuthTransport.response(statusCode: 200, body: _balanceObject),
    ).getBalance(_accountId);
    expect(balance.currentBalance.amount, '1159.25');
    expect(balance.movementCount, 1);

    final statement = await _api(
      FakeAuthTransport.response(statusCode: 200, body: _statementObject),
    ).getStatement(_accountId);
    expect(statement.entries, hasLength(1));
    expect(statement.entries.single.movement.movementId, _movementId);
    expect(statement.entries.single.balanceAfter.amount, '1159.25');
    expect(statement.closingBalance.amount, '1159.25');
  });

  test('derived money parser rejects numeric JSON values', () async {
    final numeric = _balanceObject.replaceFirst(
      '"amount":"1159.25"',
      '"amount":1159.25',
    );
    await expectLater(
      _api(
        FakeAuthTransport.response(statusCode: 200, body: numeric),
      ).getBalance(_accountId),
      throwsA(isA<FormatException>()),
    );
  });
  group('categories', () {
    test(
      'lists ACTIVE, DISABLED, PERSONAL, HOUSEHOLD and parent links',
      () async {
        final transport = FakeAuthTransport.response(
          statusCode: 200,
          body: _categoriesResponse,
        );

        final categories = await _api(transport).listCategories();

        expect(transport.calls, hasLength(1));
        expect(transport.calls.single.method, AuthHttpMethod.get);
        expect(transport.calls.single.uri.path, '/api/v1/finance/categories');
        expect(categories.map((item) => item.categoryId), [
          _categoryId,
          _childCategoryId,
          _disabledCategoryId,
          _personalCategoryId,
        ]);
        expect(
          categories[0].visibilityScope,
          FinancialVisibilityScope.household,
        );
        expect(categories[0].parentId, isNull);
        expect(categories[0].status, FinancialCategoryStatus.active);
        expect(categories[1].parentId, _categoryId);
        expect(categories[2].status, FinancialCategoryStatus.disabled);
        expect(categories[2].disabledAt, isNotNull);
        expect(categories[2].isActive, isFalse);
        expect(
          categories[3].visibilityScope,
          FinancialVisibilityScope.personal,
        );
        expect(categories[3].ownerOperatorId, _ownerId);
      },
    );

    test(
      'an empty list is valid and a disabled category stays parseable',
      () async {
        final empty = await _api(
          FakeAuthTransport.response(
            statusCode: 200,
            body: '{"categories":[]}',
          ),
        ).listCategories();
        expect(empty, isEmpty);

        final disabledOnly = await _api(
          FakeAuthTransport.response(
            statusCode: 200,
            body:
                '{"categories":[${_categoryObject(id: _disabledCategoryId, name: "Antiga", status: "DISABLED", disabledAt: "2026-09-02T12:00:00Z")}]}',
          ),
        ).listCategories();
        expect(disabledOnly.single.name, 'Antiga');
        expect(disabledOnly.single.status, FinancialCategoryStatus.disabled);
      },
    );

    test('rejects structurally invalid category responses', () async {
      final valid = _categoryObject(id: _categoryId, name: 'Casa');
      final invalidBodies = <String, String>{
        'extra root field': '{"categories":[$valid],"total":1}',
        'extra category field':
            '{"categories":[${valid.replaceFirst('"disabledAt":null', '"disabledAt":null,"color":"red"')}]}',
        'missing field':
            '{"categories":[${valid.replaceFirst('"parentId":null,', '')}]}',
        'invalid timestamp':
            '{"categories":[${valid.replaceFirst('2026-09-01T12:00:00Z', 'yesterday')}]}',
        'timestamp without timezone':
            '{"categories":[${valid.replaceFirst('2026-09-01T12:00:00Z', '2026-09-01T12:00:00')}]}',
        'invalid category uuid':
            '{"categories":[${valid.replaceFirst(_categoryId, 'not-a-uuid')}]}',
        'non v4 category id':
            '{"categories":[${valid.replaceFirst(_categoryId, '11111111-1111-1111-8111-111111111111')}]}',
        'invalid owner uuid':
            '{"categories":[${valid.replaceFirst(_ownerId, 'nope')}]}',
        'SHARED category':
            '{"categories":[${valid.replaceFirst('"HOUSEHOLD"', '"SHARED"')}]}',
        'unknown status':
            '{"categories":[${valid.replaceFirst('"ACTIVE"', '"ARCHIVED"')}]}',
        'active with disabledAt':
            '{"categories":[${valid.replaceFirst('"disabledAt":null', '"disabledAt":"2026-09-02T12:00:00Z"')}]}',
        'disabled without disabledAt':
            '{"categories":[${valid.replaceFirst('"ACTIVE"', '"DISABLED"')}]}',
        'own parent':
            '{"categories":[${valid.replaceFirst('"parentId":null', '"parentId":"$_categoryId"')}]}',
        'updated before created':
            '{"categories":[${valid.replaceFirst('"updatedAt":"2026-09-01T12:00:00Z"', '"updatedAt":"2026-08-01T12:00:00Z"')}]}',
        'duplicate identity': '{"categories":[$valid,$valid]}',
        'name with surrounding space':
            '{"categories":[${valid.replaceFirst('"Casa"', '" Casa "')}]}',
        'not a list': '{"categories":{}}',
      };
      for (final entry in invalidBodies.entries) {
        expect(
          () => jsonDecode(entry.value),
          returnsNormally,
          reason: '${entry.key} must be well-formed JSON',
        );
        await expectLater(
          _api(
            FakeAuthTransport.response(statusCode: 200, body: entry.value),
          ).listCategories(),
          throwsA(isA<FormatException>()),
          reason: entry.key,
        );
      }
    });

    test('create sends only name, scope and optional parent', () async {
      final transport = FakeAuthTransport.response(
        statusCode: 201,
        body: _categoryObject(
          id: _childCategoryId,
          name: 'Mercado',
          parentId: _categoryId,
        ),
      );

      final created = await _api(transport).createCategory(
        FinancialCategoryCreateInput(
          name: '  Mercado  ',
          visibilityScope: FinancialVisibilityScope.household,
          parentId: _categoryId,
        ),
      );

      expect(transport.calls.single.method, AuthHttpMethod.post);
      expect(transport.calls.single.uri.path, '/api/v1/finance/categories');
      final body =
          jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
      expect(body, {
        'name': 'Mercado',
        'visibilityScope': 'HOUSEHOLD',
        'parentId': _categoryId,
      });
      expect(created.categoryId, _childCategoryId);

      final rootTransport = FakeAuthTransport.response(
        statusCode: 201,
        body: _categoryObject(id: _categoryId, name: 'Casa'),
      );
      await _api(rootTransport).createCategory(
        FinancialCategoryCreateInput(
          name: 'Casa',
          visibilityScope: FinancialVisibilityScope.household,
        ),
      );
      final rootBody =
          jsonDecode(rootTransport.calls.single.body!) as Map<String, dynamic>;
      expect(rootBody.keys.toSet(), {'name', 'visibilityScope'});
    });

    test(
      'create refuses SHARED, blank names and mismatching responses',
      () async {
        expect(
          () => FinancialCategoryCreateInput(
            name: 'Casa',
            visibilityScope: FinancialVisibilityScope.shared,
          ),
          throwsFormatException,
        );
        expect(
          () => FinancialCategoryCreateInput(
            name: '   ',
            visibilityScope: FinancialVisibilityScope.household,
          ),
          throwsFormatException,
        );
        expect(
          () => FinancialCategoryCreateInput(
            name: 'Casa',
            visibilityScope: FinancialVisibilityScope.household,
            parentId: 'not-a-uuid',
          ),
          throwsFormatException,
        );
        for (final body in [
          _categoryObject(id: _categoryId, name: 'Outro nome'),
          _categoryObject(id: _categoryId, name: 'Casa', scope: 'PERSONAL'),
          _categoryObject(
            id: _categoryId,
            name: 'Casa',
            status: 'DISABLED',
            disabledAt: '2026-09-02T12:00:00Z',
          ),
          _categoryObject(
            id: _categoryId,
            name: 'Casa',
            parentId: _childCategoryId,
          ),
        ]) {
          await expectLater(
            _api(
              FakeAuthTransport.response(statusCode: 201, body: body),
            ).createCategory(
              FinancialCategoryCreateInput(
                name: 'Casa',
                visibilityScope: FinancialVisibilityScope.household,
              ),
            ),
            throwsA(isA<FormatException>()),
          );
        }
      },
    );
  });

  group('current movement allocations (bulk)', () {
    test('one GET returns the current allocations keyed by movement', () async {
      final transport = FakeAuthTransport.response(
        statusCode: 200,
        body: _allocationsResponse([
          _allocationObject(),
          _allocationObject(
            setId: _otherAllocationSetId,
            movementId: _otherMovementId,
            shares: [(_categoryId, '-50'), (_childCategoryId, '-25.25')],
          ),
        ]),
      );

      final allocations = await _api(
        transport,
      ).listCurrentMovementAllocations(_accountId);

      expect(transport.calls, hasLength(1));
      expect(transport.calls.single.method, AuthHttpMethod.get);
      expect(
        transport.calls.single.uri.path,
        '/api/v1/finance/accounts/$_accountId/movement-allocations',
      );
      expect(allocations.map((item) => item.movementId), [
        _movementId,
        _otherMovementId,
      ]);
      expect(allocations[0].allocations.single.money.amount, '-75.25');
      expect(allocations[0].revision, 1);
      expect(allocations[0].supersedesId, isNull);
      expect(allocations[1].allocations, hasLength(2));
      expect(allocations[1].allocations[1].money.amount, '-25.25');
      expect(allocations[1].currency, 'BRL');
    });

    test('empty and revised current allocations are valid', () async {
      final empty = await _api(
        FakeAuthTransport.response(
          statusCode: 200,
          body: _allocationsResponse(const []),
        ),
      ).listCurrentMovementAllocations(_accountId);
      expect(empty, isEmpty);

      final revised = await _api(
        FakeAuthTransport.response(
          statusCode: 200,
          body: _allocationsResponse([
            _allocationObject(
              setId: _otherAllocationSetId,
              revision: 2,
              supersedesId: _allocationSetId,
            ),
          ]),
        ),
      ).listCurrentMovementAllocations(_accountId);
      expect(revised.single.revision, 2);
      expect(revised.single.supersedesId, _allocationSetId);
    });

    test('rejects duplicates, wrong account and inconsistent shapes', () async {
      final valid = _allocationObject();
      final invalidBodies = <String, String>{
        'duplicate current movement': _allocationsResponse([
          valid,
          _allocationObject(setId: _otherAllocationSetId),
        ]),
        'other account': _allocationsResponse([valid]).replaceFirst(
          '"accountId":"$_accountId"',
          '"accountId":"$_destinationAccountId"',
        ),
        'numeric amount': valid.replaceFirst(
          '"amount":"-75.25"',
          '"amount":-75.25',
        ),
        'invalid money text': valid.replaceFirst('"-75.25"', '"1e3"'),
        'extra root key': _allocationsResponse([valid]).replaceFirst(
          '"movementAllocations"',
          '"history":[],"movementAllocations"',
        ),
        'extra allocation key': valid.replaceFirst(
          '"revision":1,',
          '"revision":1,"category":"x",',
        ),
        'extra share key': valid.replaceFirst(
          '"money":',
          '"percent":"100","money":',
        ),
        'revision zero': valid.replaceFirst('"revision":1', '"revision":0'),
        'revision as double': valid.replaceFirst(
          '"revision":1',
          '"revision":1.0',
        ),
        'revision 1 with predecessor': valid.replaceFirst(
          '"supersedesId":null',
          '"supersedesId":"$_otherAllocationSetId"',
        ),
        'revision 2 without predecessor': valid.replaceFirst(
          '"revision":1',
          '"revision":2',
        ),
        'self superseding': _allocationObject(
          revision: 2,
          supersedesId: _allocationSetId,
        ),
        'empty shares': _allocationObject(shares: const []),
        'duplicate category': _allocationObject(
          shares: [(_categoryId, '-10'), (_categoryId, '-65.25')],
        ),
        'mixed currency': _allocationObject(
          shares: [(_categoryId, '-10'), (_childCategoryId, '-65.25')],
        ).replaceFirst('"currency":"BRL"}}]', '"currency":"USD"}}]'),
        'invalid movement id': valid.replaceFirst(_movementId, 'bad'),
        'invalid timestamp': valid.replaceFirst('2026-09-20T05:30:00Z', 'soon'),
      };
      for (final entry in invalidBodies.entries) {
        final body = entry.value.trimLeft().startsWith('{"accountId"')
            ? entry.value
            : _allocationsResponse([entry.value]);
        expect(
          () => jsonDecode(body),
          returnsNormally,
          reason: '${entry.key} must be well-formed JSON',
        );
        await expectLater(
          _api(
            FakeAuthTransport.response(statusCode: 200, body: body),
          ).listCurrentMovementAllocations(_accountId),
          throwsA(isA<FormatException>()),
          reason: entry.key,
        );
      }
    });
  });

  group('create movement allocation', () {
    test(
      'sends the movement only in the path and one exact string share',
      () async {
        final transport = FakeAuthTransport.response(
          statusCode: 201,
          body: _allocationObject(),
        );

        final created = await _api(transport).createMovementAllocation(
          _movementId,
          FinancialMovementAllocationCreateInput.single(
            categoryId: _categoryId,
            movementMoney: FinancialMoneyWire(
              amount: '-75.25',
              currency: 'BRL',
            ),
            idempotencyKey: _idempotencyKey,
          ),
        );

        expect(transport.calls, hasLength(1));
        expect(transport.calls.single.method, AuthHttpMethod.post);
        expect(
          transport.calls.single.uri.path,
          '/api/v1/finance/movements/$_movementId/allocation',
        );
        final raw = transport.calls.single.body!;
        final body = jsonDecode(raw) as Map<String, dynamic>;
        expect(body.keys.toSet(), {'idempotencyKey', 'allocations'});
        expect(body['idempotencyKey'], _idempotencyKey);
        final shares = body['allocations'] as List<dynamic>;
        expect(shares, hasLength(1));
        final share = shares.single as Map<String, dynamic>;
        expect(share, {
          'categoryId': _categoryId,
          'amount': '-75.25',
          'currency': 'BRL',
        });
        expect(share['amount'], isA<String>());
        expect(raw, isNot(contains(_movementId)));
        expect(created.allocationSetId, _allocationSetId);
        expect(created.movementId, _movementId);
      },
    );

    test('single share reuses the Movement money text verbatim', () {
      final negative = FinancialMovementAllocationCreateInput.single(
        categoryId: _categoryId,
        movementMoney: FinancialMoneyWire(amount: '-75.250', currency: 'BRL'),
      );
      final positive = FinancialMovementAllocationCreateInput.single(
        categoryId: _categoryId,
        movementMoney: FinancialMoneyWire(amount: '300', currency: 'BRL'),
      );

      expect(negative.allocations.single.amount, '-75.250');
      expect(positive.allocations.single.amount, '300');
      expect(
        (negative.toJson()['allocations'] as List).single,
        containsPair('amount', '-75.250'),
      );
    });

    test('every attempt gets a canonical v4 idempotency key unless supplied', () {
      FinancialMovementAllocationCreateInput build() =>
          FinancialMovementAllocationCreateInput.single(
            categoryId: _categoryId,
            movementMoney: FinancialMoneyWire(amount: '-1', currency: 'BRL'),
          );
      final first = build();
      final second = build();

      expect(first.idempotencyKey, isNot(second.idempotencyKey));
      expect(
        RegExp(
          r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ).hasMatch(first.idempotencyKey),
        isTrue,
      );
      expect(
        () => FinancialMovementAllocationCreateInput.single(
          categoryId: _categoryId,
          movementMoney: FinancialMoneyWire(amount: '-1', currency: 'BRL'),
          idempotencyKey: 'not-a-uuid',
        ),
        throwsFormatException,
      );
    });

    test(
      'input refuses zero, duplicate, mixed-currency and invalid shares',
      () {
        FinancialAllocationShareInput share(
          String category,
          String amount, [
          String currency = 'BRL',
        ]) => FinancialAllocationShareInput(
          categoryId: category,
          amount: amount,
          currency: currency,
        );

        expect(() => share(_categoryId, '0'), throwsFormatException);
        expect(() => share(_categoryId, '-0.00'), throwsFormatException);
        expect(() => share(_categoryId, '1e3'), throwsFormatException);
        expect(() => share(_categoryId, '1,5'), throwsFormatException);
        expect(() => share('bad', '1'), throwsFormatException);
        expect(() => share(_categoryId, '1', 'brl'), throwsFormatException);
        expect(
          () => FinancialMovementAllocationCreateInput(allocations: const []),
          throwsFormatException,
        );
        expect(
          () => FinancialMovementAllocationCreateInput(
            allocations: [share(_categoryId, '-1'), share(_categoryId, '-2')],
          ),
          throwsFormatException,
        );
        expect(
          () => FinancialMovementAllocationCreateInput(
            allocations: [
              share(_categoryId, '-1'),
              share(_childCategoryId, '-2', 'USD'),
            ],
          ),
          throwsFormatException,
        );
      },
    );

    test(
      'rejects a confirmed response that does not match the request',
      () async {
        final bodies = <String>[
          _allocationObject(movementId: _otherMovementId),
          _allocationObject(shares: [(_childCategoryId, '-75.25')]),
          _allocationObject(shares: [(_categoryId, '-75.26')]),
          _allocationObject(revision: 2, supersedesId: _otherAllocationSetId),
          _allocationObject(
            shares: [(_categoryId, '-40'), (_childCategoryId, '-35.25')],
          ),
        ];
        for (final body in bodies) {
          await expectLater(
            _api(
              FakeAuthTransport.response(statusCode: 201, body: body),
            ).createMovementAllocation(
              _movementId,
              FinancialMovementAllocationCreateInput.single(
                categoryId: _categoryId,
                movementMoney: FinancialMoneyWire(
                  amount: '-75.25',
                  currency: 'BRL',
                ),
              ),
            ),
            throwsA(isA<FormatException>()),
          );
        }
      },
    );

    test('accepts the canonical decimal echo of the same amount', () async {
      final created =
          await _api(
            FakeAuthTransport.response(
              statusCode: 201,
              body: _allocationObject(shares: [(_categoryId, '-75.25000000')]),
            ),
          ).createMovementAllocation(
            _movementId,
            FinancialMovementAllocationCreateInput.single(
              categoryId: _categoryId,
              movementMoney: FinancialMoneyWire(
                amount: '-75.25',
                currency: 'BRL',
              ),
            ),
          );
      expect(created.allocations.single.money.amount, '-75.25000000');
    });

    test('backend rejections surface as authenticated API failures', () async {
      for (final status in [404, 409, 422]) {
        await expectLater(
          _api(
            FakeAuthTransport.response(statusCode: status, body: '{}'),
          ).createMovementAllocation(
            _movementId,
            FinancialMovementAllocationCreateInput.single(
              categoryId: _categoryId,
              movementMoney: FinancialMoneyWire(
                amount: '-75.25',
                currency: 'BRL',
              ),
            ),
          ),
          throwsA(
            isA<AuthenticatedApiException>().having(
              (error) => error.statusCode,
              'statusCode',
              status,
            ),
          ),
        );
      }
    });
  });
}

String _categoryObject({
  required String id,
  required String name,
  String scope = 'HOUSEHOLD',
  String? parentId,
  String status = 'ACTIVE',
  String? disabledAt,
}) =>
    '''
{
  "categoryId":"$id",
  "ownerOperatorId":"$_ownerId",
  "visibilityScope":"$scope",
  "parentId":${parentId == null ? 'null' : '"$parentId"'},
  "name":"$name",
  "status":"$status",
  "createdAt":"2026-09-01T12:00:00Z",
  "updatedAt":"2026-09-01T12:00:00Z",
  "disabledAt":${disabledAt == null ? 'null' : '"$disabledAt"'}
}
''';

final _categoriesResponse =
    '''
{"categories":[
  ${_categoryObject(id: _categoryId, name: 'Moradia')},
  ${_categoryObject(id: _childCategoryId, name: 'Energia', parentId: _categoryId)},
  ${_categoryObject(id: _disabledCategoryId, name: 'Antiga', status: 'DISABLED', disabledAt: '2026-09-02T12:00:00Z')},
  ${_categoryObject(id: _personalCategoryId, name: 'Meus gastos', scope: 'PERSONAL')}
]}
''';

String _allocationObject({
  String setId = _allocationSetId,
  String movementId = _movementId,
  int revision = 1,
  String? supersedesId,
  List<(String, String)> shares = const [(_categoryId, '-75.25')],
}) =>
    '''
{
  "allocationSetId":"$setId",
  "movementId":"$movementId",
  "revision":$revision,
  "supersedesId":${supersedesId == null ? 'null' : '"$supersedesId"'},
  "allocations":[${shares.map((share) => '{"categoryId":"${share.$1}","money":{"amount":"${share.$2}","currency":"BRL"}}').join(',')}],
  "createdAt":"2026-09-20T05:30:00Z"
}
''';

String _allocationsResponse(List<String> allocations) =>
    '{"accountId":"$_accountId","movementAllocations":[${allocations.join(',')}]}';

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

const _incomeMovementObject =
    '''
{
  "movementId":"60000000-0000-4000-8000-000000000006",
  "accountId":"$_accountId",
  "money":{"amount":"125.50","currency":"BRL"},
  "resultEffect":"INCOME",
  "role":"STANDARD",
  "effectiveDate":"2026-09-20",
  "competenceDate":"2026-09-20",
  "description":"Receita manual",
  "reversalOfId":null,
  "reversalReason":null,
  "createdAt":"2026-09-20T05:00:00Z"
}
''';

const _reversalMovementObject =
    '''
{
  "movementId":"$_reversalId",
  "accountId":"$_accountId",
  "money":{"amount":"75.25","currency":"BRL"},
  "resultEffect":"EXPENSE",
  "role":"REVERSAL",
  "effectiveDate":"2026-09-20",
  "competenceDate":"2026-09-20",
  "description":null,
  "reversalOfId":"$_movementId",
  "reversalReason":"Correção",
  "createdAt":"2026-09-20T05:10:00Z"
}
''';

const _transferObject =
    '''
{
  "transferId":"$_transferId",
  "sourceAccountId":"$_accountId",
  "destinationAccountId":"$_destinationAccountId",
  "currency":"BRL",
  "sourceMovementId":"$_sourceTransferMovementId",
  "destinationMovementId":"$_destinationTransferMovementId",
  "role":"STANDARD",
  "reversalOfId":null,
  "createdAt":"2026-09-20T05:20:00Z"
}
''';

const _transferReversalObject =
    '''
{
  "transferId":"$_reversalTransferId",
  "sourceAccountId":"$_destinationAccountId",
  "destinationAccountId":"$_accountId",
  "currency":"BRL",
  "sourceMovementId":"$_reversalSourceTransferMovementId",
  "destinationMovementId":"$_reversalDestinationTransferMovementId",
  "role":"REVERSAL",
  "reversalOfId":"$_transferId",
  "createdAt":"2026-09-21T05:20:00Z"
}
''';

const _transfersResponse =
    '''
{
  "transfers":[
    $_transferObject,
    $_transferReversalObject
  ]
}
''';

const _balanceObject =
    '''
{
  "accountId":"$_accountId",
  "currency":"BRL",
  "openingBalance":{"amount":"1234.50","currency":"BRL"},
  "movementNet":{"amount":"-75.25","currency":"BRL"},
  "currentBalance":{"amount":"1159.25","currency":"BRL"},
  "movementCount":1,
  "calculatedAt":"2026-09-20T05:30:00Z"
}
''';

const _statementObject =
    '''
{
  "accountId":"$_accountId",
  "currency":"BRL",
  "openingBalance":{"amount":"1234.50","currency":"BRL"},
  "entries":[
    {
      "movement":{
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
      "balanceAfter":{"amount":"1159.25","currency":"BRL"}
    }
  ],
  "closingBalance":{"amount":"1159.25","currency":"BRL"},
  "calculatedAt":"2026-09-20T05:30:00Z"
}
''';
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
