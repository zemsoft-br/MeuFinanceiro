import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_finance_backend.dart';

const _token = 'FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF';
const _accountId = '40000000-0000-4000-8000-000000000004';
const _destinationAccountId = '41000000-0000-4000-8000-000000000041';
const _ownerId = '30000000-0000-4000-8000-000000000003';
const _transferId = '80000000-0000-4000-8000-000000000008';
const _sourceMovementId = '81000000-0000-4000-8000-000000000081';
const _destinationMovementId = '82000000-0000-4000-8000-000000000082';
const _reversalTransferId = '83000000-0000-4000-8000-000000000083';
const _reversalSourceMovementId = '84000000-0000-4000-8000-000000000084';
const _reversalDestinationMovementId = '85000000-0000-4000-8000-000000000085';
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
          '/api/v1/finance/accounts/$_accountId' => const AuthHttpResponse(
            statusCode: 200,
            body: _accountObject,
          ),
          '/api/v1/finance/accounts/$_accountId/opening-balance' =>
            const AuthHttpResponse(
              statusCode: 200,
              body: '{"openingBalance":null}',
            ),
          '/api/v1/finance/accounts/$_accountId/balance' => AuthHttpResponse(
            statusCode: 200,
            body: _balanceObject(reversed),
          ),
          '/api/v1/finance/accounts/$_accountId/statement' => AuthHttpResponse(
            statusCode: 200,
            body: _statementObject(reversed),
          ),
          '/api/v1/finance/accounts/$_accountId/transfers' => AuthHttpResponse(
            statusCode: 200,
            body: _transfersObject(reversed),
          ),
          '/api/v1/finance/accounts' => const AuthHttpResponse(
            statusCode: 200,
            body: _accountsObject,
          ),
          '/api/v1/finance/categories' => const AuthHttpResponse(
            statusCode: 200,
            body: '{"categories":[]}',
          ),
          '/api/v1/finance/accounts/$_accountId/movement-allocations' =>
            const AuthHttpResponse(
              statusCode: 200,
              body: '{"accountId":"$_accountId","movementAllocations":[]}',
            ),
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
  group('detail load: categories and bulk allocations', () {
    test(
      'reads categories and bulk allocations once, joined by movementId',
      () async {
        final backend = _classificationBackend(
          movements: [
            FakeMovementSpec(id: financeTestMovementId(1)),
            FakeMovementSpec(
              id: financeTestMovementId(2),
              amount: '300',
              effect: 'INCOME',
              description: 'Salário',
            ),
            FakeMovementSpec(id: financeTestMovementId(3)),
          ],
          allocations: {
            financeTestMovementId(1): fakeAllocationJson(
              setId: financeTestAllocationSetId(1),
              movementId: financeTestMovementId(1),
              shares: [(financeTestCategoryId(1), '-75.25')],
            ),
            financeTestMovementId(2): fakeAllocationJson(
              setId: financeTestAllocationSetId(2),
              movementId: financeTestMovementId(2),
              shares: [
                (financeTestCategoryId(1), '100'),
                (financeTestCategoryId(2), '100'),
                (financeTestCategoryId(3), '100'),
              ],
            ),
          },
        );
        final container = await _loaded(backend);

        final state = container.read(_detailProvider);
        expect(state.phase, FinancialLoadPhase.loaded);
        expect(state.currentAllocations.keys.toSet(), {
          financeTestMovementId(1),
          financeTestMovementId(2),
        });
        expect(
          state.currentAllocations[financeTestMovementId(2)]!.allocations,
          hasLength(3),
        );
        expect(backend.categoryReads, 1);
        expect(backend.bulkReads, 1);
        expect(backend.singleAllocationReads, 0);
        final labels = {
          for (final movement in state.movements)
            movement.movementId: financialMovementClassificationLabel(
              movement: movement,
              allocation: state.currentAllocations[movement.movementId],
              index: state.categoryIndex,
            ),
        };
        expect(labels, {
          financeTestMovementId(1): 'Moradia',
          financeTestMovementId(2): '3 categorias',
          financeTestMovementId(3): 'Sem categoria',
        });
      },
    );

    test('request count is fixed: 0 or 20 movements cost the same', () async {
      final empty = _classificationBackend(movements: []);
      await _loaded(empty);
      final many = _classificationBackend(
        movements: [
          for (var i = 1; i <= 20; i++)
            FakeMovementSpec(id: financeTestMovementId(i)),
        ],
        allocations: {
          for (var i = 1; i <= 20; i += 2)
            financeTestMovementId(i): fakeAllocationJson(
              setId: financeTestAllocationSetId(i),
              movementId: financeTestMovementId(i),
              shares: [(financeTestCategoryId(1), '-75.25')],
            ),
        },
      );
      final container = await _loaded(many);

      expect(empty.calls.length, many.calls.length);
      expect(many.bulkReads, 1);
      expect(many.categoryReads, 1);
      expect(many.singleAllocationReads, 0);
      expect(container.read(_detailProvider).currentAllocations, hasLength(10));
    });

    test('refresh replaces the current map with the persisted truth', () async {
      final backend = _classificationBackend(
        movements: [
          FakeMovementSpec(id: financeTestMovementId(1)),
          FakeMovementSpec(id: financeTestMovementId(2)),
        ],
        allocations: {
          financeTestMovementId(1): fakeAllocationJson(
            setId: financeTestAllocationSetId(1),
            movementId: financeTestMovementId(1),
            shares: [(financeTestCategoryId(1), '-75.25')],
          ),
        },
      );
      final container = await _loaded(backend);
      expect(container.read(_detailProvider).currentAllocations.keys, [
        financeTestMovementId(1),
      ]);

      backend.allocations
        ..clear()
        ..[financeTestMovementId(2)] = fakeAllocationJson(
          setId: financeTestAllocationSetId(2),
          movementId: financeTestMovementId(2),
          shares: [(financeTestCategoryId(2), '-75.25')],
        );
      await container.read(_detailProvider.notifier).refresh();

      final state = container.read(_detailProvider);
      expect(state.phase, FinancialLoadPhase.loaded);
      expect(state.currentAllocations.keys, [financeTestMovementId(2)]);
      expect(backend.bulkReads, 2);
    });

    test('a stale load never overwrites newer state', () async {
      final backend = _classificationBackend(
        movements: [
          FakeMovementSpec(id: financeTestMovementId(1)),
          FakeMovementSpec(id: financeTestMovementId(2)),
        ],
        allocations: {
          financeTestMovementId(1): fakeAllocationJson(
            setId: financeTestAllocationSetId(1),
            movementId: financeTestMovementId(1),
            shares: [(financeTestCategoryId(1), '-75.25')],
          ),
        },
      );
      final container = await _loaded(backend);
      final controller = container.read(_detailProvider.notifier);

      // A refresh starts, snapshots the old truth and is held open...
      final gate = Completer<void>();
      backend.nextBulkGate = gate;
      final staleRefresh = controller.refresh();
      while (backend.bulkReads < 2) {
        await Future<void>.delayed(Duration.zero);
      }
      // ...the server moves on, and a newer forced load finishes first.
      backend.allocations[financeTestMovementId(2)] = fakeAllocationJson(
        setId: financeTestAllocationSetId(2),
        movementId: financeTestMovementId(2),
        shares: [(financeTestCategoryId(2), '-75.25')],
      );
      final created = await controller.createManualEntry(
        FinancialManualEntryKind.income,
        FinancialManualEntryCreateInput(
          amount: '10',
          currency: 'BRL',
          effectiveDate: '2026-09-10',
          competenceDate: '2026-09-10',
          description: 'Extra',
        ),
      );
      expect(created, isTrue);
      expect(container.read(_detailProvider).currentAllocations.keys.toSet(), {
        financeTestMovementId(1),
        financeTestMovementId(2),
      });

      gate.complete();
      await staleRefresh;

      final state = container.read(_detailProvider);
      expect(state.phase, FinancialLoadPhase.loaded);
      expect(state.currentAllocations.keys.toSet(), {
        financeTestMovementId(1),
        financeTestMovementId(2),
      });
    });

    test(
      'DISABLED categories keep resolving history and leave the picker',
      () async {
        final backend = _classificationBackend(
          allocations: {
            financeTestMovementId(1): fakeAllocationJson(
              setId: financeTestAllocationSetId(1),
              movementId: financeTestMovementId(1),
              shares: [(financeTestCategoryId(5), '-75.25')],
            ),
          },
        );
        final container = await _loaded(backend);

        final state = container.read(_detailProvider);
        expect(state.phase, FinancialLoadPhase.loaded);
        final disabled = state.categoryIndex.byId(financeTestCategoryId(5))!;
        expect(disabled.status, FinancialCategoryStatus.disabled);
        expect(
          financialMovementClassificationLabel(
            movement: state.movements.single,
            allocation: state.currentAllocations[financeTestMovementId(1)],
            index: state.categoryIndex,
          ),
          'Antiga',
        );
        expect(
          eligibleFinancialCategories(
            index: state.categoryIndex,
            account: state.account!,
          ).map((item) => item.categoryId),
          isNot(contains(financeTestCategoryId(5))),
        );
      },
    );

    test(
      'an allocation naming an unknown category is an invalid response',
      () async {
        final backend = _classificationBackend(
          allocations: {
            financeTestMovementId(1): fakeAllocationJson(
              setId: financeTestAllocationSetId(1),
              movementId: financeTestMovementId(1),
              shares: [(financeTestCategoryId(77), '-75.25')],
            ),
          },
        );
        final container = await _loaded(backend);

        expect(
          container.read(_detailProvider).phase,
          FinancialLoadPhase.invalidResponse,
        );
      },
    );

    test('inconsistent category trees are invalid responses', () async {
      for (final categories in [
        [
          fakeCategoryJson(
            id: financeTestCategoryId(1),
            name: 'Órfã',
            parentId: financeTestCategoryId(42),
          ),
        ],
        [
          fakeCategoryJson(
            id: financeTestCategoryId(1),
            name: 'A',
            parentId: financeTestCategoryId(2),
          ),
          fakeCategoryJson(
            id: financeTestCategoryId(2),
            name: 'B',
            parentId: financeTestCategoryId(1),
          ),
        ],
      ]) {
        final container = await _loaded(
          FakeFinanceBackend(categories: categories),
        );
        expect(
          container.read(_detailProvider).phase,
          FinancialLoadPhase.invalidResponse,
        );
      }
    });

    test(
      'a valid hierarchy deeper than 8 loads and resolves its path',
      () async {
        final backend = FakeFinanceBackend(
          categories: [
            for (var i = 1; i <= 12; i++)
              fakeCategoryJson(
                id: financeTestCategoryId(i),
                name: 'N$i',
                parentId: i == 1 ? null : financeTestCategoryId(i - 1),
              ),
          ],
          allocations: {
            financeTestMovementId(1): fakeAllocationJson(
              setId: financeTestAllocationSetId(1),
              movementId: financeTestMovementId(1),
              shares: [(financeTestCategoryId(12), '-75.25')],
            ),
          },
        );
        final container = await _loaded(backend);

        final state = container.read(_detailProvider);
        expect(state.phase, FinancialLoadPhase.loaded);
        expect(
          state.categoryIndex.pathLabel(financeTestCategoryId(12)),
          List.generate(12, (i) => 'N${i + 1}').join(' > '),
        );
        expect(
          financialMovementClassificationLabel(
            movement: state.movements.single,
            allocation: state.currentAllocations[financeTestMovementId(1)],
            index: state.categoryIndex,
          ),
          endsWith('N11 > N12'),
        );
      },
    );
  });

  group('simple classification', () {
    test(
      'changes nothing before 201 and sends exactly the Movement money',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        final controller = container.read(_detailProvider.notifier);
        final gate = Completer<void>();
        backend.allocationPostGate = gate;
        final callsBefore = backend.calls.length;

        final pending = controller.classifyMovement(
          movementId: financeTestMovementId(1),
          categoryId: financeTestCategoryId(1),
        );
        while (backend.allocationPosts < 1) {
          await Future<void>.delayed(Duration.zero);
        }

        var state = container.read(_detailProvider);
        expect(state.classificationMutationInFlight, isTrue);
        expect(state.currentAllocations, isEmpty);

        gate.complete();
        expect(await pending, FinancialMutationOutcome.success);

        state = container.read(_detailProvider);
        expect(state.classificationMutationInFlight, isFalse);
        expect(
          state
              .currentAllocations[financeTestMovementId(1)]!
              .allocations
              .single
              .categoryId,
          financeTestCategoryId(1),
        );
        // Exactly one POST, and no reload of ledger data after it.
        expect(backend.calls.length, callsBefore + 1);
        expect(backend.allocationPosts, 1);
        final body = backend.postedBodies.single;
        expect(body.keys.toSet(), {'idempotencyKey', 'allocations'});
        expect(body['allocations'], [
          {
            'categoryId': financeTestCategoryId(1),
            'amount': '-75.25',
            'currency': 'BRL',
          },
        ]);
      },
    );

    test(
      'income keeps its positive amount and expense keeps its sign',
      () async {
        final backend = _classificationBackend(
          movements: [
            FakeMovementSpec(id: financeTestMovementId(1), amount: '-0.10'),
            FakeMovementSpec(
              id: financeTestMovementId(2),
              amount: '1234.56',
              effect: 'INCOME',
              description: 'Salário',
            ),
          ],
        );
        final container = await _loaded(backend);
        final controller = container.read(_detailProvider.notifier);

        expect(
          await controller.classifyMovement(
            movementId: financeTestMovementId(1),
            categoryId: financeTestCategoryId(1),
          ),
          FinancialMutationOutcome.success,
        );
        expect(
          await controller.classifyMovement(
            movementId: financeTestMovementId(2),
            categoryId: financeTestCategoryId(2),
          ),
          FinancialMutationOutcome.success,
        );

        expect(
          backend.postedBodies.map(
            (body) => (body['allocations'] as List).single['amount'],
          ),
          ['-0.10', '1234.56'],
        );
      },
    );

    test(
      'non-owners, ineligible movements and categories never start a request',
      () async {
        Future<void> expectBlocked(
          FakeFinanceBackend backend, {
          String operatorId = financeTestOwnerId,
          String movementId = '',
          String? categoryId,
        }) async {
          final container = await _loaded(backend, operatorId: operatorId);
          final outcome = await container
              .read(_detailProvider.notifier)
              .classifyMovement(
                movementId: movementId.isEmpty
                    ? financeTestMovementId(1)
                    : movementId,
                categoryId: categoryId ?? financeTestCategoryId(1),
              );
          expect(outcome, FinancialMutationOutcome.notAllowed);
          expect(backend.allocationPosts, 0);
        }

        // Not the account owner (read-only member).
        await expectBlocked(
          _classificationBackend(accountScope: 'HOUSEHOLD'),
          operatorId: financeTestOtherOperatorId,
        );
        // NEUTRAL and REVERSAL are never directly classifiable.
        final kinds = _classificationBackend(
          movements: [
            FakeMovementSpec(
              id: financeTestMovementId(1),
              effect: 'NEUTRAL',
              description: 'Transferência',
            ),
            FakeMovementSpec(
              id: financeTestMovementId(2),
              effect: 'EXPENSE',
              role: 'REVERSAL',
              amount: '75.25',
              description: null,
            ),
          ],
        );
        await expectBlocked(kinds, movementId: financeTestMovementId(1));
        await expectBlocked(kinds, movementId: financeTestMovementId(2));
        // Already classified: no new first classification.
        await expectBlocked(
          _classificationBackend(
            allocations: {
              financeTestMovementId(1): fakeAllocationJson(
                setId: financeTestAllocationSetId(1),
                movementId: financeTestMovementId(1),
                shares: [(financeTestCategoryId(1), '-75.25')],
              ),
            },
          ),
          categoryId: financeTestCategoryId(2),
        );
        // Unknown movement, disabled category, other owner's PERSONAL, unknown id.
        await expectBlocked(
          _classificationBackend(),
          movementId: financeTestMovementId(55),
        );
        await expectBlocked(
          _classificationBackend(),
          categoryId: financeTestCategoryId(5),
        );
        await expectBlocked(
          _classificationBackend(),
          categoryId: financeTestCategoryId(4),
        );
        await expectBlocked(
          _classificationBackend(),
          categoryId: financeTestCategoryId(88),
        );
        // Archived account.
        await expectBlocked(_classificationBackend(accountStatus: 'ARCHIVED'));
      },
    );

    test(
      'HOUSEHOLD and SHARED accounts only accept HOUSEHOLD categories',
      () async {
        for (final scope in ['HOUSEHOLD', 'SHARED']) {
          final backend = _classificationBackend(accountScope: scope);
          final container = await _loaded(backend);
          final controller = container.read(_detailProvider.notifier);

          expect(
            await controller.classifyMovement(
              movementId: financeTestMovementId(1),
              categoryId: financeTestCategoryId(3),
            ),
            FinancialMutationOutcome.notAllowed,
            reason: '$scope account must refuse a PERSONAL category',
          );
          expect(backend.allocationPosts, 0);
          expect(
            await controller.classifyMovement(
              movementId: financeTestMovementId(1),
              categoryId: financeTestCategoryId(1),
            ),
            FinancialMutationOutcome.success,
          );
        }
      },
    );

    test(
      '409 refetches persisted truth, never retries and never fakes success',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        final controller = container.read(_detailProvider.notifier);
        // Another writer classifies the same Movement first.
        backend.allocationPostStatus = 409;
        backend.onAllocationPost = (movementId) {
          backend.allocations[movementId] = fakeAllocationJson(
            setId: financeTestAllocationSetId(9),
            movementId: movementId,
            shares: [(financeTestCategoryId(2), '-75.25')],
          );
        };
        final statementReads = backend.statementReads;

        final outcome = await controller.classifyMovement(
          movementId: financeTestMovementId(1),
          categoryId: financeTestCategoryId(1),
        );

        expect(outcome, FinancialMutationOutcome.conflictReconciled);
        expect(backend.allocationPosts, 1, reason: 'no automatic retry');
        expect(backend.categoryReads, 2);
        expect(backend.bulkReads, 2);
        expect(
          backend.statementReads,
          statementReads,
          reason: 'ledger untouched',
        );
        final state = container.read(_detailProvider);
        expect(state.classificationMutationInFlight, isFalse);
        final current = state.currentAllocations[financeTestMovementId(1)]!;
        expect(current.allocationSetId, financeTestAllocationSetId(9));
        expect(current.allocations.single.categoryId, financeTestCategoryId(2));
      },
    );

    test(
      '409 reconciliation also resolves categories created by the other writer',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        backend.allocationPostStatus = 409;
        backend.onAllocationPost = (movementId) {
          backend.categories.add(
            fakeCategoryJson(
              id: financeTestCategoryId(60),
              name: 'Nova alheia',
            ),
          );
          backend.allocations[movementId] = fakeAllocationJson(
            setId: financeTestAllocationSetId(9),
            movementId: movementId,
            shares: [(financeTestCategoryId(60), '-75.25')],
          );
        };

        final outcome = await container
            .read(_detailProvider.notifier)
            .classifyMovement(
              movementId: financeTestMovementId(1),
              categoryId: financeTestCategoryId(1),
            );

        expect(outcome, FinancialMutationOutcome.conflictReconciled);
        final state = container.read(_detailProvider);
        expect(state.phase, FinancialLoadPhase.loaded);
        expect(state.categoryIndex.byId(financeTestCategoryId(60)), isNotNull);
      },
    );

    test(
      '409 whose refetch fails keeps a visible warning instead of silence',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        backend.allocationPostStatus = 409;
        backend.onAllocationPost = (_) {
          backend.allocations[financeTestMovementId(1)] = 'not json';
        };

        final outcome = await container
            .read(_detailProvider.notifier)
            .classifyMovement(
              movementId: financeTestMovementId(1),
              categoryId: financeTestCategoryId(1),
            );

        expect(outcome, FinancialMutationOutcome.invalidResponse);
        final state = container.read(_detailProvider);
        expect(state.refreshFailure, FinancialRefreshFailure.invalidResponse);
        expect(state.classificationMutationInFlight, isFalse);
        expect(backend.allocationPosts, 1);
      },
    );

    test(
      '422 is a rejection that leaves state untouched and is not retried',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        backend.allocationPostStatus = 422;
        final reads = backend.calls.length;

        final outcome = await container
            .read(_detailProvider.notifier)
            .classifyMovement(
              movementId: financeTestMovementId(1),
              categoryId: financeTestCategoryId(1),
            );

        expect(outcome, FinancialMutationOutcome.rejected);
        final state = container.read(_detailProvider);
        expect(state.currentAllocations, isEmpty);
        expect(state.classificationMutationInFlight, isFalse);
        expect(state.classificationTrusted, isTrue);
        expect(backend.allocationPosts, 1);
        expect(backend.calls.length, reads + 1, reason: 'no retry, no refetch');
      },
    );

    test(
      'an unknown outcome keeps the key so an identical retry is idempotent',
      () async {
        final backend = _classificationBackend(
          movements: [
            FakeMovementSpec(id: financeTestMovementId(1)),
            FakeMovementSpec(id: financeTestMovementId(2)),
          ],
        );
        final container = await _loaded(backend);
        final controller = container.read(_detailProvider.notifier);
        backend.allocationPostStatus = 503;

        final first = await controller.classifyMovement(
          movementId: financeTestMovementId(1),
          categoryId: financeTestCategoryId(1),
        );
        expect(first, FinancialMutationOutcome.unknownOutcomeReconciled);
        expect(container.read(_detailProvider).currentAllocations, isEmpty);
        expect(backend.allocationPosts, 1, reason: 'no automatic retry');

        backend.allocationPostStatus = null;
        final retry = await controller.classifyMovement(
          movementId: financeTestMovementId(1),
          categoryId: financeTestCategoryId(1),
        );
        expect(retry, FinancialMutationOutcome.success);
        expect(backend.postedKeys[1], backend.postedKeys[0]);

        // A different logical attempt, or the next one after success, is new.
        await controller.classifyMovement(
          movementId: financeTestMovementId(2),
          categoryId: financeTestCategoryId(1),
        );
        expect(backend.postedKeys[2], isNot(backend.postedKeys[0]));
      },
    );

    test(
      'a different category after an unknown outcome is a new attempt',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        final controller = container.read(_detailProvider.notifier);
        backend.allocationPostStatus = 503;
        await controller.classifyMovement(
          movementId: financeTestMovementId(1),
          categoryId: financeTestCategoryId(1),
        );
        backend.allocationPostStatus = null;

        await controller.classifyMovement(
          movementId: financeTestMovementId(1),
          categoryId: financeTestCategoryId(2),
        );

        expect(backend.postedKeys[1], isNot(backend.postedKeys[0]));
      },
    );

    test(
      'a 2xx that cannot be validated is reconciled, never incorporated',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        backend.allocationPostBody = (movementId, body) => fakeAllocationJson(
          setId: financeTestAllocationSetId(1),
          movementId: movementId,
          shares: [(financeTestCategoryId(1), '-1')],
        );
        final reads = backend.bulkReads;

        final outcome = await container
            .read(_detailProvider.notifier)
            .classifyMovement(
              movementId: financeTestMovementId(1),
              categoryId: financeTestCategoryId(1),
            );

        expect(outcome, FinancialMutationOutcome.unknownOutcomeReconciled);
        final state = container.read(_detailProvider);
        expect(
          state.currentAllocations,
          isEmpty,
          reason: 'the body is not trusted',
        );
        expect(state.classificationTrusted, isTrue);
        expect(state.classificationMutationInFlight, isFalse);
        expect(backend.allocationPosts, 1);
        expect(backend.bulkReads, reads + 1);
      },
    );

    test('lost access is reported as a blocked session phase', () async {
      final backend = _classificationBackend();
      final container = await _loaded(backend);
      backend.allocationPostStatus = 403;

      final outcome = await container
          .read(_detailProvider.notifier)
          .classifyMovement(
            movementId: financeTestMovementId(1),
            categoryId: financeTestCategoryId(1),
          );

      expect(outcome, FinancialMutationOutcome.accessBlocked);
      expect(
        container.read(_detailProvider).phase,
        FinancialLoadPhase.forbidden,
      );
    });

    test('a second submission while one is in flight is refused', () async {
      final backend = _classificationBackend();
      final container = await _loaded(backend);
      final controller = container.read(_detailProvider.notifier);
      final gate = Completer<void>();
      backend.allocationPostGate = gate;

      final first = controller.classifyMovement(
        movementId: financeTestMovementId(1),
        categoryId: financeTestCategoryId(1),
      );
      while (backend.allocationPosts < 1) {
        await Future<void>.delayed(Duration.zero);
      }
      final second = await controller.classifyMovement(
        movementId: financeTestMovementId(1),
        categoryId: financeTestCategoryId(1),
      );
      gate.complete();

      expect(second, FinancialMutationOutcome.notAllowed);
      expect(await first, FinancialMutationOutcome.success);
      expect(backend.allocationPosts, 1);
    });
  });

  group('inline category creation', () {
    test(
      'adds only the backend-confirmed category and it can be used',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        final controller = container.read(_detailProvider.notifier);
        final before = container.read(_detailProvider).categories.length;

        final result = await controller.createCategory(
          FinancialCategoryCreateInput(
            name: 'Mercado',
            visibilityScope: FinancialVisibilityScope.household,
            parentId: financeTestCategoryId(1),
          ),
        );

        expect(result.outcome, FinancialMutationOutcome.success);
        final created = result.category!;
        final state = container.read(_detailProvider);
        expect(state.categories.length, before + 1);
        expect(
          state.categoryIndex.pathLabel(created.categoryId),
          'Moradia > Mercado',
        );
        expect(backend.categoryReads, 1, reason: 'no reload of the detail');
        expect(backend.statementReads, 1);

        expect(
          await controller.classifyMovement(
            movementId: financeTestMovementId(1),
            categoryId: created.categoryId,
          ),
          FinancialMutationOutcome.success,
        );
      },
    );

    test('failures never add a category', () async {
      for (final configure in <void Function(FakeFinanceBackend)>[
        (backend) => backend.categoryPostStatus = 422,
        (backend) => backend.categoryPostStatus = 503,
        (backend) => backend.categoryPostBody = (body) => fakeCategoryJson(
          id: financeTestCategoryId(700),
          name: body['name'] as String,
          scope: 'PERSONAL',
        ),
      ]) {
        final backend = _classificationBackend();
        configure(backend);
        final container = await _loaded(backend);
        final before = container.read(_detailProvider).categories.length;

        final result = await container
            .read(_detailProvider.notifier)
            .createCategory(
              FinancialCategoryCreateInput(
                name: 'Nova',
                visibilityScope: FinancialVisibilityScope.household,
              ),
            );

        expect(result.outcome, isNot(FinancialMutationOutcome.success));
        expect(result.category, isNull);
        final state = container.read(_detailProvider);
        expect(state.categories.length, before);
        expect(state.classificationMutationInFlight, isFalse);
      }
    });

    test('creation context is filtered before any request', () async {
      final backend = _classificationBackend(accountScope: 'HOUSEHOLD');
      final container = await _loaded(backend);
      final controller = container.read(_detailProvider.notifier);

      // PERSONAL category from a HOUSEHOLD account context.
      final personal = await controller.createCategory(
        FinancialCategoryCreateInput(
          name: 'Minha',
          visibilityScope: FinancialVisibilityScope.personal,
        ),
      );
      // Parents must be active, same scope and owned by the operator.
      final disabledParent = await controller.createCategory(
        FinancialCategoryCreateInput(
          name: 'Filha',
          visibilityScope: FinancialVisibilityScope.household,
          parentId: financeTestCategoryId(5),
        ),
      );
      final foreignParent = await controller.createCategory(
        FinancialCategoryCreateInput(
          name: 'Filha',
          visibilityScope: FinancialVisibilityScope.household,
          parentId: financeTestCategoryId(6),
        ),
      );
      final unknownParent = await controller.createCategory(
        FinancialCategoryCreateInput(
          name: 'Filha',
          visibilityScope: FinancialVisibilityScope.household,
          parentId: financeTestCategoryId(99),
        ),
      );

      for (final result in [
        personal,
        disabledParent,
        foreignParent,
        unknownParent,
      ]) {
        expect(result.outcome, FinancialMutationOutcome.notAllowed);
      }
      expect(
        backend.calls.where((call) => call.method == AuthHttpMethod.post),
        isEmpty,
      );
    });
  });
  group('classification trust (fail closed)', () {
    Future<FinancialMutationOutcome> classify(
      ProviderContainer container, {
      int movement = 1,
      int category = 1,
    }) => container
        .read(_detailProvider.notifier)
        .classifyMovement(
          movementId: financeTestMovementId(movement),
          categoryId: financeTestCategoryId(category),
        );

    FakeFinanceBackend conflictingBackend({
      List<FakeMovementSpec>? movements,
      void Function(FakeFinanceBackend backend)? breakReconciliation,
    }) {
      final backend = _classificationBackend(movements: movements);
      backend.allocationPostStatus = 409;
      backend.onAllocationPost = (movementId) {
        backend.allocations[movementId] = fakeAllocationJson(
          setId: financeTestAllocationSetId(9),
          movementId: movementId,
          shares: [(financeTestCategoryId(2), '-75.25')],
        );
        breakReconciliation?.call(backend);
      };
      return backend;
    }

    test('a reconciled 409 keeps the classification trusted', () async {
      final backend = conflictingBackend();
      final container = await _loaded(backend);

      expect(
        await classify(container),
        FinancialMutationOutcome.conflictReconciled,
      );
      expect(container.read(_detailProvider).classificationTrusted, isTrue);
    });

    test(
      '409 + failed reconciliation marks the state untrusted but keeps what was known',
      () async {
        for (final breakIt in <void Function(FakeFinanceBackend)>[
          (backend) => backend.categoryReadStatus = 503,
          (backend) => backend.bulkReadStatus = 503,
          (backend) => backend.bulkReadStatus = 500,
        ]) {
          final backend = conflictingBackend(breakReconciliation: breakIt);
          final container = await _loaded(backend);
          final before = container.read(_detailProvider);

          final outcome = await classify(container);

          expect(outcome, FinancialMutationOutcome.temporarilyUnavailable);
          final state = container.read(_detailProvider);
          expect(state.classificationTrusted, isFalse);
          expect(
            state.phase,
            FinancialLoadPhase.loaded,
            reason: 'ledger stays visible',
          );
          expect(state.balance, same(before.balance));
          expect(state.statement, same(before.statement));
          expect(state.currentAllocations, before.currentAllocations);
          expect(state.categories, before.categories);
          expect(state.classificationMutationInFlight, isFalse);
          expect(backend.allocationPosts, 1);
        }
      },
    );

    test(
      '409 + unusable reconciliation payload is invalid and untrusted',
      () async {
        final backend = conflictingBackend(
          breakReconciliation: (backend) =>
              backend.allocations[financeTestMovementId(1)] = 'not json',
        );
        final container = await _loaded(backend);

        expect(
          await classify(container),
          FinancialMutationOutcome.invalidResponse,
        );
        expect(container.read(_detailProvider).classificationTrusted, isFalse);
      },
    );

    test(
      'an untrusted state sends no classification and no category POST',
      () async {
        final backend = conflictingBackend(
          breakReconciliation: (backend) => backend.bulkReadStatus = 503,
          movements: [
            FakeMovementSpec(id: financeTestMovementId(1)),
            FakeMovementSpec(id: financeTestMovementId(2)),
          ],
        );
        final container = await _loaded(backend);
        await classify(container);
        expect(container.read(_detailProvider).classificationTrusted, isFalse);
        final posts = backend.allocationPosts;
        backend.allocationPostStatus = null;

        expect(
          await classify(container, movement: 2),
          FinancialMutationOutcome.notAllowed,
        );
        final category = await container
            .read(_detailProvider.notifier)
            .createCategory(
              FinancialCategoryCreateInput(
                name: 'Nova',
                visibilityScope: FinancialVisibilityScope.household,
              ),
            );
        expect(category.outcome, FinancialMutationOutcome.notAllowed);
        expect(backend.allocationPosts, posts);
        expect(backend.categoryPosts, 0);
      },
    );

    test('a successful refresh restores trust and eligibility', () async {
      final backend = conflictingBackend(
        breakReconciliation: (backend) => backend.categoryReadStatus = 503,
        movements: [
          FakeMovementSpec(id: financeTestMovementId(1)),
          FakeMovementSpec(id: financeTestMovementId(2)),
        ],
      );
      final container = await _loaded(backend);
      await classify(container);
      expect(container.read(_detailProvider).classificationTrusted, isFalse);

      // Still failing: refresh does not restore trust.
      await container.read(_detailProvider.notifier).refresh();
      expect(container.read(_detailProvider).classificationTrusted, isFalse);

      backend.categoryReadStatus = null;
      backend.allocationPostStatus = null;
      await container.read(_detailProvider.notifier).refresh();

      final state = container.read(_detailProvider);
      expect(state.classificationTrusted, isTrue);
      expect(
        state.currentAllocations[financeTestMovementId(1)]!.allocationSetId,
        financeTestAllocationSetId(9),
      );
      expect(
        await classify(container, movement: 2),
        FinancialMutationOutcome.success,
      );
    });

    test(
      '404 reconciles once, never retries and shows the new truth',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        backend.allocationPostStatus = 404;
        backend.onAllocationPost = (_) {
          // The category was disabled behind the client's back.
          backend.categories[0] = fakeCategoryJson(
            id: financeTestCategoryId(1),
            name: 'Moradia',
            status: 'DISABLED',
          );
        };
        final categoryReads = backend.categoryReads;
        final bulkReads = backend.bulkReads;
        final statementReads = backend.statementReads;

        final outcome = await classify(container);

        expect(outcome, FinancialMutationOutcome.rejected);
        expect(backend.allocationPosts, 1, reason: 'no automatic retry');
        expect(backend.categoryReads, categoryReads + 1);
        expect(backend.bulkReads, bulkReads + 1);
        expect(
          backend.statementReads,
          statementReads,
          reason: 'ledger untouched',
        );
        final state = container.read(_detailProvider);
        expect(state.classificationTrusted, isTrue);
        expect(state.currentAllocations, isEmpty, reason: 'no fake success');
        expect(
          state.categoryIndex.byId(financeTestCategoryId(1))!.status,
          FinancialCategoryStatus.disabled,
        );
        expect(
          await classify(container),
          FinancialMutationOutcome.notAllowed,
          reason: 'the disabled category left the picker',
        );
      },
    );

    test(
      '404 + failed reconciliation is untrusted and blocks new mutations',
      () async {
        final backend = _classificationBackend(
          movements: [
            FakeMovementSpec(id: financeTestMovementId(1)),
            FakeMovementSpec(id: financeTestMovementId(2)),
          ],
        );
        final container = await _loaded(backend);
        backend.allocationPostStatus = 404;
        backend.onAllocationPost = (_) => backend.bulkReadStatus = 503;

        final outcome = await classify(container);

        expect(outcome, FinancialMutationOutcome.rejected);
        expect(container.read(_detailProvider).classificationTrusted, isFalse);
        expect(backend.allocationPosts, 1);
        backend.allocationPostStatus = null;
        expect(
          await classify(container, movement: 2),
          FinancialMutationOutcome.notAllowed,
        );
        expect(backend.allocationPosts, 1);
      },
    );

    test(
      'an unknown 5xx outcome stays trusted so the same key can be replayed',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        backend.allocationPostStatus = 503;

        await classify(container);

        expect(container.read(_detailProvider).classificationTrusted, isTrue);
      },
    );
  });

  group('ambiguous classification outcome', () {
    FakeFinanceBackend ambiguousBackend({
      required bool persisted,
      bool transportFailure = false,
      List<FakeMovementSpec>? movements,
      void Function(FakeFinanceBackend backend)? breakReconciliation,
    }) {
      final backend = _classificationBackend(movements: movements);
      if (transportFailure) {
        backend.allocationPostThrows = true;
      } else {
        backend.allocationPostStatus = 503;
      }
      backend.onAllocationPost = (movementId) {
        if (persisted) {
          backend.allocations[movementId] = fakeAllocationJson(
            setId: financeTestAllocationSetId(7),
            movementId: movementId,
            shares: [(financeTestCategoryId(1), '-75.25')],
          );
        }
        breakReconciliation?.call(backend);
      };
      return backend;
    }

    void heal(FakeFinanceBackend backend) {
      backend.allocationPostStatus = null;
      backend.allocationPostThrows = false;
      backend.categoryReadStatus = null;
      backend.bulkReadStatus = null;
    }

    Future<FinancialMutationOutcome> classify(
      ProviderContainer container, {
      int movement = 1,
      int category = 1,
    }) => container
        .read(_detailProvider.notifier)
        .classifyMovement(
          movementId: financeTestMovementId(movement),
          categoryId: financeTestCategoryId(category),
        );

    for (final transport in [true, false]) {
      final cause = transport ? 'timeout/transport failure' : '5xx';

      test(
        '$cause + persisted write: reconciled once, trusted, no new POST',
        () async {
          final backend = ambiguousBackend(
            persisted: true,
            transportFailure: transport,
          );
          final container = await _loaded(backend);
          final categoryReads = backend.categoryReads;
          final bulkReads = backend.bulkReads;
          final statementReads = backend.statementReads;

          final outcome = await classify(container);

          expect(outcome, FinancialMutationOutcome.unknownOutcomeReconciled);
          expect(backend.allocationPosts, 1, reason: 'no automatic retry');
          expect(backend.categoryReads, categoryReads + 1);
          expect(backend.bulkReads, bulkReads + 1);
          expect(
            backend.statementReads,
            statementReads,
            reason: 'ledger untouched',
          );
          final state = container.read(_detailProvider);
          expect(state.classificationTrusted, isTrue);
          expect(state.classificationMutationInFlight, isFalse);
          expect(state.refreshFailure, FinancialRefreshFailure.none);
          final current = state.currentAllocations[financeTestMovementId(1)]!;
          expect(current.allocationSetId, financeTestAllocationSetId(7));
          expect(
            current.allocations.single.categoryId,
            financeTestCategoryId(1),
          );
          // Decided by the returned truth: nothing left to classify.
          expect(
            await classify(container),
            FinancialMutationOutcome.notAllowed,
          );
          expect(backend.allocationPosts, 1);
        },
      );
    }

    test(
      'timeout + nothing persisted: trusted again; the same attempt replays with the same key',
      () async {
        final backend = ambiguousBackend(
          persisted: false,
          transportFailure: true,
        );
        final container = await _loaded(backend);

        final first = await classify(container);

        expect(first, FinancialMutationOutcome.unknownOutcomeReconciled);
        expect(backend.allocationPosts, 1, reason: 'no automatic retry');
        var state = container.read(_detailProvider);
        expect(state.classificationTrusted, isTrue);
        expect(state.currentAllocations, isEmpty);

        // Still failing: an explicit retry is another ambiguous attempt, same key.
        expect(
          await classify(container),
          FinancialMutationOutcome.unknownOutcomeReconciled,
        );
        expect(backend.allocationPosts, 2);

        heal(backend);
        expect(await classify(container), FinancialMutationOutcome.success);
        expect(backend.allocationPosts, 3);
        expect(
          backend.postedKeys.toSet(),
          hasLength(1),
          reason: 'one logical attempt',
        );
        state = container.read(_detailProvider);
        expect(state.currentAllocations, hasLength(1));
      },
    );

    test(
      'a changed category is a new logical attempt with a new key',
      () async {
        final backend = ambiguousBackend(persisted: false);
        final container = await _loaded(backend);
        await classify(container);
        heal(backend);

        await classify(container, category: 2);

        expect(backend.postedKeys, hasLength(2));
        expect(backend.postedKeys[1], isNot(backend.postedKeys[0]));
      },
    );

    test('a changed amount is a new logical attempt with a new key', () async {
      final backend = ambiguousBackend(persisted: false);
      final container = await _loaded(backend);
      await classify(container);
      heal(backend);
      // Same Movement, different canonical money after a refresh.
      backend.movements = [
        FakeMovementSpec(id: financeTestMovementId(1), amount: '-80.00'),
      ];
      await container.read(_detailProvider.notifier).refresh();

      await classify(container);

      expect(backend.postedKeys, hasLength(2));
      expect(backend.postedKeys[1], isNot(backend.postedKeys[0]));
      expect(
        (backend.postedBodies[1]['allocations'] as List).single['amount'],
        '-80.00',
      );
    });

    test(
      'timeout + failed reconciliation: untrusted, nothing mutable, key kept',
      () async {
        final backend = ambiguousBackend(
          persisted: false,
          transportFailure: true,
          breakReconciliation: (b) => b.bulkReadStatus = 503,
        );
        final container = await _loaded(backend);
        final before = container.read(_detailProvider);

        final outcome = await classify(container);

        expect(outcome, FinancialMutationOutcome.temporarilyUnavailable);
        var state = container.read(_detailProvider);
        expect(state.classificationTrusted, isFalse);
        expect(
          state.phase,
          FinancialLoadPhase.loaded,
          reason: 'ledger stays visible',
        );
        expect(state.currentAllocations, before.currentAllocations);
        expect(backend.allocationPosts, 1);
        // No new mutation of any kind while untrusted.
        expect(await classify(container), FinancialMutationOutcome.notAllowed);
        expect(
          await classify(container, category: 2),
          FinancialMutationOutcome.notAllowed,
        );
        final category = await container
            .read(_detailProvider.notifier)
            .createCategory(
              FinancialCategoryCreateInput(
                name: 'Nova',
                visibilityScope: FinancialVisibilityScope.household,
              ),
            );
        expect(category.outcome, FinancialMutationOutcome.notAllowed);
        expect(backend.allocationPosts, 1);
        expect(backend.categoryPosts, 0);

        // A later canonical read restores trust; the pending key survived.
        heal(backend);
        await container.read(_detailProvider.notifier).refresh();
        state = container.read(_detailProvider);
        expect(state.classificationTrusted, isTrue);
        expect(await classify(container), FinancialMutationOutcome.success);
        expect(backend.postedKeys, hasLength(2));
        expect(backend.postedKeys[1], backend.postedKeys[0]);
      },
    );

    test(
      '5xx + unusable reconciliation payload: invalid and untrusted',
      () async {
        final backend = ambiguousBackend(
          persisted: false,
          breakReconciliation: (b) =>
              b.allocations[financeTestMovementId(1)] = 'not json',
        );
        final container = await _loaded(backend);

        final outcome = await classify(container);

        expect(outcome, FinancialMutationOutcome.invalidResponse);
        final state = container.read(_detailProvider);
        expect(state.classificationTrusted, isFalse);
        expect(state.refreshFailure, FinancialRefreshFailure.invalidResponse);
        expect(backend.allocationPosts, 1);
      },
    );

    test(
      'a refresh after an untrusted ambiguous write follows the persisted truth',
      () async {
        final backend = ambiguousBackend(
          persisted: true,
          breakReconciliation: (b) => b.bulkReadStatus = 503,
        );
        final container = await _loaded(backend);
        await classify(container);
        expect(container.read(_detailProvider).classificationTrusted, isFalse);

        heal(backend);
        await container.read(_detailProvider.notifier).refresh();

        final state = container.read(_detailProvider);
        expect(state.classificationTrusted, isTrue);
        expect(
          state.currentAllocations[financeTestMovementId(1)]!.allocationSetId,
          financeTestAllocationSetId(7),
        );
        expect(await classify(container), FinancialMutationOutcome.notAllowed);
        expect(backend.allocationPosts, 1);
      },
    );

    test(
      'lost access during the ambiguous outcome is not reconciled',
      () async {
        final backend = _classificationBackend();
        final container = await _loaded(backend);
        backend.allocationPostStatus = 403;
        final reads = backend.bulkReads;

        final outcome = await classify(container);

        expect(outcome, FinancialMutationOutcome.accessBlocked);
        expect(backend.bulkReads, reads);
      },
    );
  });

  group('category creation with unknown outcome', () {
    FinancialCategoryCreateInput input({
      String name = 'Mercado',
      FinancialVisibilityScope scope = FinancialVisibilityScope.household,
      String? parentId,
    }) => FinancialCategoryCreateInput(
      name: name,
      visibilityScope: scope,
      parentId: parentId,
    );

    void serverCreates(
      FakeFinanceBackend backend,
      int n, {
      String name = 'Mercado',
      String scope = 'HOUSEHOLD',
      String? parentId,
      String owner = financeTestOwnerId,
    }) => backend.categories.add(
      fakeCategoryJson(
        id: financeTestCategoryId(n),
        name: name,
        scope: scope,
        parentId: parentId,
        owner: owner,
      ),
    );

    Future<FinancialCategoryCreateResult> create(
      ProviderContainer container, [
      FinancialCategoryCreateInput? value,
    ]) => container
        .read(_detailProvider.notifier)
        .createCategory(value ?? input());

    test(
      'a transport failure after the send is reconciled, never re-POSTed',
      () async {
        final backend = _classificationBackend();
        backend.categoryPostThrows = true;
        backend.onCategoryPost = (_) => serverCreates(backend, 700);
        final container = await _loaded(backend);
        final reads = backend.categoryReads;

        final result = await create(container);

        expect(
          result.outcome,
          FinancialMutationOutcome.unknownOutcomeReconciled,
        );
        expect(backend.categoryPosts, 1, reason: 'no automatic retry');
        expect(backend.categoryReads, reads + 1);
        expect(
          result.category,
          isNull,
          reason: 'the lost id is never inferred',
        );
        expect(result.matches.map((item) => item.categoryId), [
          financeTestCategoryId(700),
        ]);
        final state = container.read(_detailProvider);
        expect(state.categoryCreationUnknown, isFalse);
        expect(
          state.categories.map((item) => item.categoryId),
          contains(financeTestCategoryId(700)),
        );
      },
    );

    test('a 5xx after the send is reconciled, never re-POSTed', () async {
      final backend = _classificationBackend();
      backend.categoryPostStatus = 503;
      backend.onCategoryPost = (_) => serverCreates(backend, 700);
      final container = await _loaded(backend);
      final reads = backend.categoryReads;

      final result = await create(container);

      expect(result.outcome, FinancialMutationOutcome.unknownOutcomeReconciled);
      expect(backend.categoryPosts, 1);
      expect(backend.categoryReads, reads + 1);
      expect(result.matches, hasLength(1));
    });

    test(
      'an unusable 201 body is just as ambiguous and is reconciled too',
      () async {
        final backend = _classificationBackend();
        backend.categoryPostBody = (body) => 'not json';
        backend.onCategoryPost = (_) => serverCreates(backend, 700);
        final container = await _loaded(backend);

        final result = await create(container);

        expect(
          result.outcome,
          FinancialMutationOutcome.unknownOutcomeReconciled,
        );
        expect(backend.categoryPosts, 1);
        expect(result.category, isNull);
      },
    );

    test(
      'reconciliation without a compatible newcomer reports no match',
      () async {
        final backend = _classificationBackend();
        backend.categoryPostStatus = 503; // the server never saw it
        final container = await _loaded(backend);
        final before = container.read(_detailProvider).categories.length;

        final result = await create(container);

        expect(
          result.outcome,
          FinancialMutationOutcome.unknownOutcomeReconciled,
        );
        expect(result.matches, isEmpty);
        expect(container.read(_detailProvider).categories.length, before);
        // Not claimed as failed either: the user may simply try again.
        expect(
          container.read(_detailProvider).categoryCreationUnknown,
          isFalse,
        );
      },
    );

    test('several compatible newcomers are reported, never chosen', () async {
      final backend = _classificationBackend();
      backend.categoryPostStatus = 503;
      backend.onCategoryPost = (_) {
        serverCreates(backend, 700);
        serverCreates(backend, 701);
      };
      final container = await _loaded(backend);

      final result = await create(container);

      expect(result.matches, hasLength(2));
      expect(result.category, isNull);
      expect(result.outcome, FinancialMutationOutcome.unknownOutcomeReconciled);
    });

    test(
      'matching needs name, scope, parent and operator, not just the name',
      () async {
        final backend = _classificationBackend();
        backend.categoryPostStatus = 503;
        backend.onCategoryPost = (_) {
          // Same name, but: another scope, another parent, another owner.
          serverCreates(backend, 700, scope: 'PERSONAL');
          serverCreates(backend, 701, parentId: financeTestCategoryId(1));
          serverCreates(backend, 702, owner: financeTestOtherOperatorId);
        };
        final container = await _loaded(backend);

        final result = await create(container);

        expect(result.matches, isEmpty);
        expect(
          container.read(_detailProvider).categories.length,
          9,
          reason: 'the canonical list still replaced the local one',
        );
      },
    );

    test(
      'a category that already existed before the request is not a match',
      () async {
        final backend = _classificationBackend();
        backend.categories.add(
          fakeCategoryJson(id: financeTestCategoryId(710), name: 'Mercado'),
        );
        backend.categoryPostStatus = 503;
        final container = await _loaded(backend);

        final result = await create(container);

        expect(result.matches, isEmpty);
      },
    );

    test(
      'a failed reconciliation blocks resubmission while the outcome is unknown',
      () async {
        final backend = _classificationBackend();
        backend.categoryPostStatus = 503;
        backend.onCategoryPost = (_) => backend.categoryReadStatus = 503;
        final container = await _loaded(backend);

        final first = await create(container);

        expect(first.outcome, FinancialMutationOutcome.temporarilyUnavailable);
        expect(container.read(_detailProvider).categoryCreationUnknown, isTrue);
        expect(backend.categoryPosts, 1);

        final blocked = await create(container);
        expect(blocked.outcome, FinancialMutationOutcome.notAllowed);
        final blockedAgain = await create(container, input(name: 'Outra'));
        expect(blockedAgain.outcome, FinancialMutationOutcome.notAllowed);
        expect(backend.categoryPosts, 1, reason: 'no blind second POST');
      },
    );

    test('a later successful refresh unblocks creation', () async {
      final backend = _classificationBackend();
      backend.categoryPostStatus = 503;
      backend.onCategoryPost = (_) => backend.categoryReadStatus = 503;
      final container = await _loaded(backend);
      await create(container);
      expect(container.read(_detailProvider).categoryCreationUnknown, isTrue);

      // Refresh still failing keeps the block.
      await container.read(_detailProvider.notifier).refresh();
      expect(container.read(_detailProvider).categoryCreationUnknown, isTrue);

      backend.categoryReadStatus = null;
      backend.categoryPostStatus = null;
      await container.read(_detailProvider.notifier).refresh();

      expect(container.read(_detailProvider).categoryCreationUnknown, isFalse);
      final created = await create(container);
      expect(created.outcome, FinancialMutationOutcome.success);
      expect(backend.categoryPosts, 2, reason: 'only the user-triggered one');
    });

    test(
      'reconcileCategories also unblocks, and only after a successful read',
      () async {
        final backend = _classificationBackend();
        backend.categoryPostStatus = 503;
        backend.onCategoryPost = (_) => backend.categoryReadStatus = 503;
        final container = await _loaded(backend);
        await create(container);
        final controller = container.read(_detailProvider.notifier);

        expect(
          await controller.reconcileCategories(),
          FinancialMutationOutcome.temporarilyUnavailable,
        );
        expect(container.read(_detailProvider).categoryCreationUnknown, isTrue);

        backend.categoryReadStatus = null;
        expect(
          await controller.reconcileCategories(),
          FinancialMutationOutcome.success,
        );
        expect(
          container.read(_detailProvider).categoryCreationUnknown,
          isFalse,
        );
      },
    );

    test('definitive rejections are not unknown outcomes', () async {
      final backend = _classificationBackend();
      backend.categoryPostStatus = 422;
      final container = await _loaded(backend);
      final reads = backend.categoryReads;

      final result = await create(container);

      expect(result.outcome, FinancialMutationOutcome.rejected);
      expect(backend.categoryReads, reads, reason: 'nothing to reconcile');
      expect(container.read(_detailProvider).categoryCreationUnknown, isFalse);
    });
  });
}

final _detailProvider = financialAccountDetailControllerProvider(
  financeTestAccountId,
);

FakeFinanceBackend _classificationBackend({
  String accountScope = 'PERSONAL',
  String accountStatus = 'ACTIVE',
  List<FakeMovementSpec>? movements,
  Map<String, String>? allocations,
}) => FakeFinanceBackend(
  accountScope: accountScope,
  accountStatus: accountStatus,
  movements: movements,
  allocations: allocations,
  categories: [
    fakeCategoryJson(id: financeTestCategoryId(1), name: 'Moradia'),
    fakeCategoryJson(
      id: financeTestCategoryId(2),
      name: 'Energia',
      parentId: financeTestCategoryId(1),
    ),
    fakeCategoryJson(
      id: financeTestCategoryId(3),
      name: 'Pessoal',
      scope: 'PERSONAL',
    ),
    fakeCategoryJson(
      id: financeTestCategoryId(4),
      name: 'Do outro',
      scope: 'PERSONAL',
      owner: financeTestOtherOperatorId,
    ),
    fakeCategoryJson(
      id: financeTestCategoryId(5),
      name: 'Antiga',
      status: 'DISABLED',
    ),
    fakeCategoryJson(
      id: financeTestCategoryId(6),
      name: 'Da outra pessoa',
      owner: financeTestOtherOperatorId,
    ),
  ],
);

Future<ProviderContainer> _loaded(
  FakeFinanceBackend backend, {
  String operatorId = financeTestOwnerId,
}) async {
  final container = financeTestContainer(backend, operatorId: operatorId);
  addTearDown(container.dispose);
  container.listen(_detailProvider, (previous, next) {}, fireImmediately: true);
  await container.read(_detailProvider.notifier).load();
  return container;
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
  "ownerOperatorId":"$_ownerId",
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
