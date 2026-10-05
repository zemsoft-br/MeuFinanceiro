import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_account_detail_screen.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

import '../../support/fake_finance_backend.dart';

/// Issue #245 final vertical gate on the client: category -> manual expense ->
/// unclassified -> simple classification -> split revision -> stale conflict.
/// Every step also proves that the economic Movement and the balance are
/// untouched by classification.

final _detail = financialAccountDetailControllerProvider(financeTestAccountId);

FakeFinanceBackend _backend({
  List<FakeMovementSpec>? movements,
  Map<String, String>? allocations,
}) => FakeFinanceBackend(
  movements: movements ?? [],
  allocations: allocations,
  categories: [
    fakeCategoryJson(id: financeTestCategoryId(1), name: 'Mercado'),
    fakeCategoryJson(id: financeTestCategoryId(2), name: 'Transporte'),
    fakeCategoryJson(id: financeTestCategoryId(3), name: 'Lazer'),
  ],
);

Future<ProviderContainer> _loaded(FakeFinanceBackend backend) async {
  final container = financeTestContainer(backend);
  addTearDown(container.dispose);
  container.listen(_detail, (previous, next) {}, fireImmediately: true);
  await container.read(_detail.notifier).load();
  return container;
}

/// Everything economic about a Movement, plus the balance and the statement.
Map<String, Object?> _economic(FinancialAccountDetailState state, String id) {
  final movement = state.movements.firstWhere((item) => item.movementId == id);
  final balance = state.balance!;
  return {
    'movementId': movement.movementId,
    'accountId': movement.accountId,
    'amount': movement.money.amount,
    'currency': movement.money.currency,
    'resultEffect': movement.resultEffect.name,
    'role': movement.role.name,
    'effectiveDate': movement.effectiveDate,
    'competenceDate': movement.competenceDate,
    'balance': [
      balance.currentBalance.amount,
      balance.movementNet.amount,
      balance.movementCount,
    ],
    'statement': [
      for (final entry in state.statement!.entries)
        [entry.movement.movementId, entry.balanceAfter.amount],
    ],
  };
}

FinancialAllocationShareInput _share(int category, String amount) =>
    FinancialAllocationShareInput(
      categoryId: financeTestCategoryId(category),
      amount: amount,
      currency: 'BRL',
    );

void main() {
  test(
    'vertical flow: category, expense, classify, split, stale conflict',
    () async {
      final backend = _backend();
      final container = await _loaded(backend);
      final controller = container.read(_detail.notifier);

      // categories are listed from the API (no Demo data) and one can be created
      expect(container.read(_detail).categories, hasLength(3));
      final created = await controller.createCategory(
        FinancialCategoryCreateInput(
          name: 'Casa',
          visibilityScope: FinancialVisibilityScope.household,
        ),
      );
      expect(created.outcome, FinancialMutationOutcome.success);
      expect(container.read(_detail).categories, hasLength(4));

      // manual expense: reloads the ledger once, appears as "Sem categoria"
      expect(
        await controller.createManualEntry(
          FinancialManualEntryKind.expense,
          FinancialManualEntryCreateInput(
            amount: '75.25',
            currency: 'BRL',
            effectiveDate: '2026-09-20',
            competenceDate: '2026-09-20',
            description: 'Mercado do mês',
          ),
        ),
        isTrue,
      );
      var state = container.read(_detail);
      final movementId = state.movements.single.movementId;
      expect(state.currentAllocations, isEmpty);
      expect(
        financialMovementClassificationLabel(
          movement: state.movements.single,
          allocation: null,
          index: state.categoryIndex,
        ),
        'Sem categoria',
      );
      final economic = _economic(state, movementId);
      final statementReads = backend.statementReads;
      final callsBeforeClassification = backend.calls.length;

      // simple classification: 100% in one category
      expect(
        await controller.classifyMovement(
          movementId: movementId,
          categoryId: financeTestCategoryId(1),
        ),
        FinancialMutationOutcome.success,
      );
      state = container.read(_detail);
      final first = state.currentAllocations[movementId]!;
      expect(first.revision, 1);
      expect(first.allocations.single.money.amount, '-75.25');
      expect(
        financialMovementClassificationLabel(
          movement: state.movements.single,
          allocation: first,
          index: state.categoryIndex,
        ),
        'Mercado',
      );
      expect(_economic(state, movementId), economic);

      // split revision: a NEW current revision, never an in-place edit
      expect(
        await controller.reviseMovementClassification(
          movementId: movementId,
          supersedesId: first.allocationSetId,
          shares: [_share(1, '-50.00'), _share(2, '-25.25')],
        ),
        FinancialMutationOutcome.success,
      );
      state = container.read(_detail);
      final second = state.currentAllocations[movementId]!;
      expect(second.revision, first.revision + 1);
      expect(second.supersedesId, first.allocationSetId);
      expect(second.allocations, hasLength(2));
      expect(
        financialMovementClassificationLabel(
          movement: state.movements.single,
          allocation: second,
          index: state.categoryIndex,
        ),
        '2 categorias',
      );
      expect(_economic(state, movementId), economic);
      expect(
        backend.statementReads,
        statementReads,
        reason: 'ledger not reloaded',
      );
      // classification costs exactly its two POSTs: nothing else on the wire
      expect(backend.calls.length, callsBeforeClassification + 2);

      // stale predecessor: writer B appends R3 while writer A still edits R2
      backend.allocations[movementId] = fakeAllocationJson(
        setId: financeTestAllocationSetId(900),
        movementId: movementId,
        shares: [(financeTestCategoryId(3), '-75.25')],
        revision: 3,
        supersedesId: second.allocationSetId,
      );
      final posts = backend.revisionPosts;
      final staleDraft = [_share(1, '-20.00'), _share(2, '-55.25')];

      expect(
        await controller.reviseMovementClassification(
          movementId: movementId,
          supersedesId: second.allocationSetId,
          shares: staleDraft,
        ),
        FinancialMutationOutcome.conflictReconciled,
      );

      state = container.read(_detail);
      expect(
        backend.revisionPosts,
        posts + 1,
        reason: 'one POST, zero retries',
      );
      expect(
        backend.revisionBodies.last['supersedesId'],
        second.allocationSetId,
      );
      final current = state.currentAllocations[movementId]!;
      expect(current.allocationSetId, financeTestAllocationSetId(900));
      expect(current.revision, 3);
      expect(current.allocations.single.categoryId, financeTestCategoryId(3));
      expect(state.classificationTrusted, isTrue);
      expect(state.classificationMutationInFlight, isFalse);
      expect(_economic(state, movementId), economic);

      // the stale draft is not re-applied, even when the user presses again
      expect(
        await controller.reviseMovementClassification(
          movementId: movementId,
          supersedesId: second.allocationSetId,
          shares: staleDraft,
        ),
        FinancialMutationOutcome.conflictReconciled,
      );
      expect(backend.revisionPosts, posts + 1);

      // only an explicit review against the real current set is sent
      expect(
        await controller.reviseMovementClassification(
          movementId: movementId,
          supersedesId: current.allocationSetId,
          shares: staleDraft,
        ),
        FinancialMutationOutcome.success,
      );
      expect(backend.revisionPosts, posts + 2);
      expect(
        container.read(_detail).currentAllocations[movementId]!.revision,
        4,
      );
      expect(_economic(container.read(_detail), movementId), economic);
    },
  );

  test(
    'an income can be split with positive shares and keeps its sign',
    () async {
      final backend = _backend(
        movements: [
          FakeMovementSpec(
            id: financeTestMovementId(1),
            amount: '10.00',
            effect: 'INCOME',
            description: 'Rendimento',
          ),
        ],
      );
      final container = await _loaded(backend);
      final before = _economic(
        container.read(_detail),
        financeTestMovementId(1),
      );

      expect(
        await container
            .read(_detail.notifier)
            .classifyMovementShares(
              movementId: financeTestMovementId(1),
              shares: [_share(1, '4.00'), _share(2, '6.00')],
            ),
        FinancialMutationOutcome.success,
      );

      expect(
        (backend.postedBodies.single['allocations'] as List).map(
          (share) => (share as Map)['amount'],
        ),
        ['4.00', '6.00'],
      );
      expect(
        _economic(container.read(_detail), financeTestMovementId(1)),
        before,
      );
    },
  );

  group('no N+1: the cost of a screen does not depend on the Movements', () {
    FakeFinanceBackend withMovements(int count) => _backend(
      movements: [
        for (var i = 1; i <= count; i++)
          FakeMovementSpec(id: financeTestMovementId(i)),
      ],
      allocations: {
        for (var i = 1; i <= count; i += 2)
          financeTestMovementId(i): fakeAllocationJson(
            setId: financeTestAllocationSetId(i),
            movementId: financeTestMovementId(i),
            shares: [(financeTestCategoryId(1), '-75.25')],
          ),
      },
    );

    for (final count in [0, 1, 25]) {
      test(
        '$count Movements: 1 bulk read, 0 individual allocation reads',
        () async {
          final backend = withMovements(count);
          final container = await _loaded(backend);

          expect(backend.bulkReads, 1);
          expect(backend.singleAllocationReads, 0);
          expect(backend.categoryReads, 1);
          expect(
            container.read(_detail).currentAllocations,
            hasLength((count + 1) ~/ 2),
          );
        },
      );
    }

    test(
      'the total request count is identical for 0, 1 and 25 Movements',
      () async {
        final totals = <int>{};
        for (final count in [0, 1, 25]) {
          final backend = withMovements(count);
          await _loaded(backend);
          totals.add(backend.calls.length);
        }
        expect(totals, hasLength(1));
      },
    );

    for (final count in [0, 1, 25]) {
      testWidgets('rendering $count Movements reads allocations once', (
        tester,
      ) async {
        tester.view.physicalSize = const Size(1400, 12000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        final backend = withMovements(count);
        await tester.pumpWidget(
          ProviderScope(
            overrides: financeTestOverrides(backend),
            child: MaterialApp(
              home: Scaffold(
                body: SingleChildScrollView(
                  child: FinancialAccountDetailScreen(
                    accountId: financeTestAccountId,
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();

        expect(backend.bulkReads, 1);
        expect(backend.singleAllocationReads, 0);
        expect(backend.categoryReads, 1);
        expect(
          find.textContaining('Categoria: ', skipOffstage: false),
          findsNWidgets(count),
        );
      });
    }
  });
}
