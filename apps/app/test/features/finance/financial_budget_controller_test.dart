import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

import '../../support/fake_budget_backend.dart';
import '../../support/fake_finance_backend.dart';

final _market = financeTestCategoryId(1);
final _salary = financeTestCategoryId(2);
final _leisure = financeTestCategoryId(3);

List<String> _categories() => [
  fakeCategoryJson(id: _market, name: 'Mercado'),
  fakeCategoryJson(id: _salary, name: 'Salário'),
  fakeCategoryJson(id: _leisure, name: 'Lazer'),
];

FakeBudget _october({
  int index = 1,
  String scope = 'HOUSEHOLD',
  String owner = financeTestOwnerId,
}) => FakeBudget(
  index: index,
  period: '2026-10',
  scope: scope,
  owner: owner,
  lines: [
    FakeBudgetLine(_market, 'EXPENSE', '1000'),
    FakeBudgetLine(_salary, 'INCOME', '5000'),
  ],
);

FakeBudgetBackend _backend({List<FakeBudget>? budgets}) {
  final backend = FakeBudgetBackend(
    budgets: budgets ?? [_october()],
    categories: _categories(),
  );
  backend.realized[budgetTestId(1)] = {
    '$_market|EXPENSE': '300',
    '$_salary|INCOME': '4500',
  };
  return backend;
}

FinancialBudgetCreateInput _createInput({
  String period = '2026-10',
  FinancialBudgetDateBasis basis = FinancialBudgetDateBasis.competence,
  String amount = '250',
  String? key,
}) => FinancialBudgetCreateInput(
  name: 'Lazer do mês',
  visibilityScope: FinancialVisibilityScope.household,
  currency: 'BRL',
  period: period,
  dateBasis: basis,
  idempotencyKey: key,
  lines: [
    FinancialBudgetLineInput(
      categoryId: _leisure,
      resultEffect: FinancialResultEffect.expense,
      plannedAmount: amount,
    ),
  ],
);

FinancialBudgetReplaceInput _replaceInput({
  int version = 1,
  String amount = '900',
  String name = 'Outubro v2',
}) => FinancialBudgetReplaceInput(
  expectedVersion: version,
  name: name,
  currency: 'BRL',
  lines: [
    FinancialBudgetLineInput(
      categoryId: _market,
      resultEffect: FinancialResultEffect.expense,
      plannedAmount: amount,
    ),
  ],
);

Future<FinancialBudgetsState> _loaded(ProviderContainer container) async {
  await container.read(financialBudgetsControllerProvider.notifier).load();
  return container.read(financialBudgetsControllerProvider);
}

void main() {
  late FakeBudgetBackend backend;
  late ProviderContainer container;

  FinancialBudgetsController controller() =>
      container.read(financialBudgetsControllerProvider.notifier);
  FinancialBudgetsState state() =>
      container.read(financialBudgetsControllerProvider);

  setUp(() {
    backend = _backend();
    container = budgetTestContainer(backend);
    addTearDown(container.dispose);
    // Keep the autoDispose notifier alive for the whole test.
    container.listen(financialBudgetsControllerProvider, (_, _) {});
  });

  group('loading', () {
    test(
      'starts in the current month and reads categories, budgets and one summary',
      () async {
        expect(state().period, '2026-10');
        final loaded = await _loaded(container);
        expect(loaded.phase, FinancialLoadPhase.loaded);
        expect(loaded.budgets.single.id, budgetTestId(1));
        expect(loaded.selectedBudgetId, budgetTestId(1));
        expect(loaded.summaryPhase, FinancialBudgetSummaryPhase.ready);
        final line = loaded.summary!.lines.firstWhere(
          (l) => l.categoryId == _market,
        );
        expect(line.realized.amount, '300');
        expect(backend.listReads, 1);
        expect(backend.summaryReads, 1);
        expect(backend.perLineRequests, 0);
        expect(backend.calls, hasLength(3));
      },
    );

    test(
      'request cost does not depend on the number of lines or budgets',
      () async {
        final big = FakeBudget(
          index: 1,
          period: '2026-10',
          lines: [
            for (var i = 0; i < 40; i += 1)
              FakeBudgetLine(financeTestCategoryId(100 + i), 'EXPENSE', '1'),
          ],
        );
        backend = FakeBudgetBackend(
          budgets: [
            big,
            _october(index: 2, scope: 'PERSONAL'),
          ],
          categories: _categories(),
        );
        container = budgetTestContainer(backend)
          ..listen(financialBudgetsControllerProvider, (_, _) {});
        addTearDown(container.dispose);
        await _loaded(container);
        expect(backend.calls, hasLength(3));
      },
    );

    test(
      'an empty month is a distinct phase, keeps categories and reads no summary',
      () async {
        backend.budgets = [];
        final loaded = await _loaded(container);
        expect(loaded.phase, FinancialLoadPhase.empty);
        expect(loaded.isLoaded, isTrue);
        expect(loaded.categories, hasLength(3));
        expect(loaded.selected, isNull);
        expect(backend.summaryReads, 0);
      },
    );

    test(
      'shows the coverage the server reports without attributing it to lines',
      () async {
        backend.coverage[budgetTestId(1)] = (
          expense: 2,
          expenseAmount: '130.5',
          income: 1,
          incomeAmount: '10',
        );
        final loaded = await _loaded(container);
        expect(loaded.summary!.coverage.unclassifiedExpenseCount, 2);
        expect(
          loaded.summary!.coverage.unclassifiedExpenseAmount.amount,
          '130.5',
        );
        expect(loaded.summary!.coverage.unclassifiedIncomeCount, 1);
        expect(
          loaded.summary!.lines.every((l) => l.realized.amount != '130.5'),
          isTrue,
        );
      },
    );

    test('maps failures to phases without inventing data', () async {
      for (final (status, phase) in [
        (401, FinancialLoadPhase.authenticationRequired),
        (403, FinancialLoadPhase.forbidden),
        (409, FinancialLoadPhase.primaryResidenceRequired),
        (503, FinancialLoadPhase.temporarilyUnavailable),
      ]) {
        final failing = _backend()..listStatus = status;
        final c = budgetTestContainer(failing)
          ..listen(financialBudgetsControllerProvider, (_, _) {});
        addTearDown(c.dispose);
        final result = await _loaded(c);
        expect(result.phase, phase, reason: '$status');
        expect(result.budgets, isEmpty);
      }
      final invalid = _backend()..listBodyOverride = '{"items":"x"}';
      final c = budgetTestContainer(invalid)
        ..listen(financialBudgetsControllerProvider, (_, _) {});
      addTearDown(c.dispose);
      expect((await _loaded(c)).phase, FinancialLoadPhase.invalidResponse);
      final noCategories = _backend()..categoriesStatus = 503;
      final d = budgetTestContainer(noCategories)
        ..listen(financialBudgetsControllerProvider, (_, _) {});
      addTearDown(d.dispose);
      expect(
        (await _loaded(d)).phase,
        FinancialLoadPhase.temporarilyUnavailable,
      );
    });

    test(
      'a failed summary keeps the plan and retries only the summary',
      () async {
        backend.summaryStatus = 503;
        var loaded = await _loaded(container);
        expect(loaded.phase, FinancialLoadPhase.loaded);
        expect(loaded.budgets, hasLength(1));
        expect(loaded.summary, isNull);
        expect(
          loaded.summaryPhase,
          FinancialBudgetSummaryPhase.temporarilyUnavailable,
        );
        backend.summaryStatus = null;
        final listsBefore = backend.listReads;
        await controller().reloadSummary();
        loaded = state();
        expect(loaded.summaryPhase, FinancialBudgetSummaryPhase.ready);
        expect(loaded.summary, isNotNull);
        expect(backend.listReads, listsBefore);
      },
    );

    test('an invalid summary is never shown', () async {
      backend.summaryBodyOverride = '{"budget":1}';
      final loaded = await _loaded(container);
      expect(loaded.summary, isNull);
      expect(loaded.summaryPhase, FinancialBudgetSummaryPhase.invalidResponse);
    });

    test(
      'refresh failure preserves what is shown and blocks writes until a good refresh',
      () async {
        await _loaded(container);
        backend.failNextLists = 1;
        await controller().refresh();
        var current = state();
        expect(current.phase, FinancialLoadPhase.loaded);
        expect(current.budgets, hasLength(1));
        expect(
          current.refreshFailure,
          FinancialRefreshFailure.temporarilyUnavailable,
        );
        expect(current.trusted, isFalse);
        final result = await controller().replaceBudget(
          budgetTestId(1),
          _replaceInput(),
        );
        expect(result.outcome, FinancialBudgetActionOutcome.notAllowed);
        expect(backend.puts, 0);
        await controller().refresh();
        current = state();
        expect(current.trusted, isTrue);
        expect(current.refreshFailure, FinancialRefreshFailure.none);
        expect(current.summaryPhase, FinancialBudgetSummaryPhase.ready);
      },
    );
  });

  group('months', () {
    test(
      'navigation reads the requested month and resets the selection',
      () async {
        backend.budgets.add(
          FakeBudget(
            index: 2,
            period: '2026-11',
            lines: [FakeBudgetLine(_market, 'EXPENSE', '10')],
          ),
        );
        await _loaded(container);
        await controller().nextMonth();
        expect(state().period, '2026-11');
        expect(state().selectedBudgetId, budgetTestId(2));
        await controller().previousMonth();
        await controller().previousMonth();
        expect(state().period, '2026-09');
        expect(state().phase, FinancialLoadPhase.empty);
        expect(
          backend.calls
              .where((c) => c.uri.path == '/api/v1/finance/budgets')
              .map((c) => c.uri.queryParameters['period'])
              .toList(),
          ['2026-10', '2026-11', '2026-10', '2026-09'],
        );
      },
    );

    test(
      'a late answer for an old month never overwrites the current one',
      () async {
        backend.budgets.add(
          FakeBudget(
            index: 2,
            period: '2026-11',
            lines: [FakeBudgetLine(_market, 'EXPENSE', '10')],
          ),
        );
        await _loaded(container);
        final gate = Completer<void>();
        backend.listGate = gate;
        final slow = controller().nextMonth(); // November, held at the server
        await Future<void>.delayed(Duration.zero);
        backend.listGate = null;
        await controller().previousMonth(); // back to October wins immediately
        gate.complete();
        await slow;
        expect(state().period, '2026-10');
        expect(state().selectedBudgetId, budgetTestId(1));
      },
    );

    test('year boundaries roll over', () async {
      final c = budgetTestContainer(_backend(), now: DateTime(2026, 12, 3))
        ..listen(financialBudgetsControllerProvider, (_, _) {});
      addTearDown(c.dispose);
      final n = c.read(financialBudgetsControllerProvider.notifier);
      expect(c.read(financialBudgetsControllerProvider).period, '2026-12');
      await n.nextMonth();
      expect(c.read(financialBudgetsControllerProvider).period, '2027-01');
      await n.previousMonth();
      await n.previousMonth();
      expect(c.read(financialBudgetsControllerProvider).period, '2026-11');
    });
  });

  group('selection', () {
    test(
      'selecting another budget of the month reads exactly one summary',
      () async {
        backend.budgets.add(_october(index: 2, scope: 'PERSONAL'));
        await _loaded(container);
        final before = backend.summaryReads;
        await controller().select(budgetTestId(2));
        expect(state().selectedBudgetId, budgetTestId(2));
        expect(state().summary!.budget.id, budgetTestId(2));
        expect(backend.summaryReads, before + 1);
        await controller().select(budgetTestId(2)); // no-op
        await controller().select(budgetTestId(77)); // unknown: no-op
        expect(backend.summaryReads, before + 1);
      },
    );
  });

  group('create', () {
    test(
      'posts once, never optimistically, then reads the month again',
      () async {
        await _loaded(container);
        final gate = Completer<void>();
        backend.postGate = gate;
        final future = controller().createBudget(_createInput());
        await Future<void>.delayed(Duration.zero);
        // Not visible before the canonical re-read.
        expect(state().budgets, hasLength(1));
        expect(state().mutationInFlight, isTrue);
        final second = await controller().createBudget(
          _createInput(amount: '1'),
        );
        expect(second.outcome, FinancialBudgetActionOutcome.notAllowed);
        gate.complete();
        final result = await future;
        expect(result.outcome, FinancialBudgetActionOutcome.created);
        expect(result.reconciled, isTrue);
        expect(backend.posts, 2 - 1);
        expect(state().budgets, hasLength(2));
        expect(state().selectedBudgetId, result.budgetId);
        expect(state().summary!.budget.id, result.budgetId);
        expect(state().mutationInFlight, isFalse);
        expect(backend.listReads, 2);
      },
    );

    test(
      'rejects a month other than the one shown without any request',
      () async {
        await _loaded(container);
        final result = await controller().createBudget(
          _createInput(period: '2026-11'),
        );
        expect(result.outcome, FinancialBudgetActionOutcome.notAllowed);
        expect(backend.posts, 0);
      },
    );

    test(
      '409 is a conflict: nothing retried, current plan read, notice raised',
      () async {
        await _loaded(container);
        // An equal plan (same month/scope/currency/basis) exists: CASH household.
        final result = await controller().createBudget(
          _createInput(basis: FinancialBudgetDateBasis.cash),
        );
        expect(result.outcome, FinancialBudgetActionOutcome.conflict);
        expect(backend.posts, 1);
        expect(state().conflictNotice, isTrue);
        expect(state().budgets, hasLength(1));
        controller().dismissConflictNotice();
        expect(state().conflictNotice, isFalse);
      },
    );

    test(
      'an ambiguous answer is read once, never resent, and an explicit retry reuses the key',
      () async {
        await _loaded(container);
        backend.postCommitsThenFails = true;
        final input = _createInput();
        final first = await controller().createBudget(input);
        expect(first.outcome, FinancialBudgetActionOutcome.unknownOutcome);
        expect(backend.posts, 1); // never resent automatically
        expect(
          state().budgets,
          hasLength(2),
        ); // the canonical read shows it landed
        backend.postCommitsThenFails = false;
        final retry = await controller().createBudget(_createInput());
        expect(retry.outcome, FinancialBudgetActionOutcome.created);
        expect(backend.postBodies, hasLength(2));
        expect(
          backend.postBodies[1]['idempotencyKey'],
          backend.postBodies[0]['idempotencyKey'],
        );
        // The server replayed the same plan: still exactly one such budget.
        expect(
          backend.budgets.where((b) => b.name == 'Lazer do mês'),
          hasLength(1),
        );
      },
    );

    test(
      'a transport failure keeps the key and still posts only once',
      () async {
        await _loaded(container);
        backend.postThrows = true;
        final result = await controller().createBudget(_createInput());
        expect(result.outcome, FinancialBudgetActionOutcome.unknownOutcome);
        expect(backend.posts, 1);
        backend.postThrows = false;
        await controller().createBudget(_createInput());
        expect(
          backend.postBodies[1]['idempotencyKey'],
          backend.postBodies[0]['idempotencyKey'],
        );
        expect(
          backend.budgets.where((b) => b.name == 'Lazer do mês'),
          hasLength(1),
        );
      },
    );

    test(
      'a definitive answer drops the key: another attempt gets a fresh one',
      () async {
        await _loaded(container);
        backend.postStatus = 422;
        final rejected = await controller().createBudget(_createInput());
        expect(rejected.outcome, FinancialBudgetActionOutcome.rejected);
        backend.postStatus = null;
        await controller().createBudget(_createInput());
        expect(
          backend.postBodies[1]['idempotencyKey'],
          isNot(backend.postBodies[0]['idempotencyKey']),
        );
      },
    );

    test('an invalid 2xx is treated as unknown and reconciled once', () async {
      await _loaded(container);
      backend.postBodyOverride = '{"id":"nope"}';
      final result = await controller().createBudget(_createInput());
      expect(result.outcome, FinancialBudgetActionOutcome.unknownOutcome);
      expect(backend.posts, 1);
      expect(backend.listReads, 2);
    });

    test(
      'if the canonical re-read fails the plan is flagged stale and writes stay blocked',
      () async {
        await _loaded(container);
        backend.failNextLists = 1;
        final result = await controller().createBudget(_createInput());
        expect(result.outcome, FinancialBudgetActionOutcome.created);
        expect(result.reconciled, isFalse);
        expect(state().trusted, isFalse);
        final blocked = await controller().createBudget(
          _createInput(amount: '3'),
        );
        expect(blocked.outcome, FinancialBudgetActionOutcome.notAllowed);
        expect(backend.posts, 1);
      },
    );
  });

  group('replace', () {
    test(
      'sends one PUT under the current version and reads the month again',
      () async {
        await _loaded(container);
        final result = await controller().replaceBudget(
          budgetTestId(1),
          _replaceInput(),
        );
        expect(result.outcome, FinancialBudgetActionOutcome.updated);
        expect(backend.puts, 1);
        expect(state().selected!.version, 2);
        expect(state().selected!.name, 'Outubro v2');
        expect(state().summary!.budget.version, 2);
        expect(state().conflictNotice, isFalse);
      },
    );

    test(
      'a stale version is a conflict: no retry, no rebase, current plan shown',
      () async {
        await _loaded(container);
        // Someone else edits first: the server moves to version 2.
        backend.beforePut = () {
          backend.byId(budgetTestId(1))!.version = 2;
          backend.byId(budgetTestId(1))!.name = 'Alterado por outra pessoa';
          backend.beforePut = null;
        };
        final result = await controller().replaceBudget(
          budgetTestId(1),
          _replaceInput(),
        );
        expect(result.outcome, FinancialBudgetActionOutcome.conflict);
        expect(backend.puts, 1);
        expect(state().conflictNotice, isTrue);
        expect(state().selected!.version, 2);
        expect(state().selected!.name, 'Alterado por outra pessoa');
        // Only an explicit new edit against the version just read succeeds.
        final next = await controller().replaceBudget(
          budgetTestId(1),
          _replaceInput(version: 2, name: 'Depois da leitura'),
        );
        expect(next.outcome, FinancialBudgetActionOutcome.updated);
        expect(backend.puts, 2);
        expect(state().selected!.version, 3);
      },
    );

    test(
      'an edit built on a version the client no longer shows is refused locally',
      () async {
        await _loaded(container);
        final result = await controller().replaceBudget(
          budgetTestId(1),
          _replaceInput(version: 5),
        );
        expect(result.outcome, FinancialBudgetActionOutcome.notAllowed);
        expect(backend.puts, 0);
      },
    );

    test('a read-only budget is never written', () async {
      backend = _backend(
        budgets: [_october(owner: financeTestOtherOperatorId)],
      );
      container = budgetTestContainer(backend)
        ..listen(financialBudgetsControllerProvider, (_, _) {});
      addTearDown(container.dispose);
      final loaded = await _loaded(container);
      expect(loaded.selected!.canEdit, isFalse);
      final result = await controller().replaceBudget(
        budgetTestId(1),
        _replaceInput(),
      );
      expect(result.outcome, FinancialBudgetActionOutcome.notAllowed);
      expect(backend.puts, 0);
    });

    test(
      '403 from the server with access intact reports read-only after one re-read',
      () async {
        await _loaded(container);
        backend.putStatus = 403;
        final result = await controller().replaceBudget(
          budgetTestId(1),
          _replaceInput(),
        );
        expect(result.outcome, FinancialBudgetActionOutcome.readOnly);
        expect(backend.puts, 1);
        expect(state().phase, FinancialLoadPhase.loaded);
      },
    );

    test('403 on the re-read as well means the access is gone', () async {
      await _loaded(container);
      backend.putStatus = 403;
      backend.failNextListsStatus = 403;
      backend.failNextLists = 1;
      final result = await controller().replaceBudget(
        budgetTestId(1),
        _replaceInput(),
      );
      expect(result.outcome, FinancialBudgetActionOutcome.accessBlocked);
      expect(state().phase, FinancialLoadPhase.forbidden);
    });

    test(
      '401 blocks without a re-read and a 404/422 is a plain rejection',
      () async {
        await _loaded(container);
        backend.putStatus = 404;
        expect(
          (await controller().replaceBudget(
            budgetTestId(1),
            _replaceInput(),
          )).outcome,
          FinancialBudgetActionOutcome.rejected,
        );
        backend.putStatus = 422;
        expect(
          (await controller().replaceBudget(
            budgetTestId(1),
            _replaceInput(),
          )).outcome,
          FinancialBudgetActionOutcome.rejected,
        );
        backend.putStatus = 401;
        final listsBefore = backend.listReads;
        final result = await controller().replaceBudget(
          budgetTestId(1),
          _replaceInput(),
        );
        expect(result.outcome, FinancialBudgetActionOutcome.accessBlocked);
        expect(state().phase, FinancialLoadPhase.authenticationRequired);
        expect(backend.listReads, listsBefore);
        expect(backend.puts, 3);
      },
    );

    test('an ambiguous write is never resent', () async {
      await _loaded(container);
      backend.putCommitsThenFails = true;
      final result = await controller().replaceBudget(
        budgetTestId(1),
        _replaceInput(),
      );
      expect(result.outcome, FinancialBudgetActionOutcome.unknownOutcome);
      expect(backend.puts, 1);
      expect(
        state().selected!.version,
        2,
      ); // the canonical read shows it landed
      backend.putCommitsThenFails = false;
      backend.putThrows = true;
      final again = await controller().replaceBudget(
        budgetTestId(1),
        _replaceInput(version: 2),
      );
      expect(again.outcome, FinancialBudgetActionOutcome.unknownOutcome);
      expect(backend.puts, 2);
    });

    test('an invalid 2xx is unknown, not success', () async {
      await _loaded(container);
      backend.putBodyOverride = '{"id":"x"}';
      final result = await controller().replaceBudget(
        budgetTestId(1),
        _replaceInput(),
      );
      expect(result.outcome, FinancialBudgetActionOutcome.unknownOutcome);
      expect(backend.puts, 1);
    });

    test(
      'the realized values are always the next server read, never patched locally',
      () async {
        await _loaded(container);
        expect(
          state().summary!.lines
              .firstWhere((l) => l.categoryId == _market)
              .realized
              .amount,
          '300',
        );
        backend.realized[budgetTestId(1)]!['$_market|EXPENSE'] = '420';
        // Nothing happened on the client: the number only changes on a read.
        expect(
          state().summary!.lines
              .firstWhere((l) => l.categoryId == _market)
              .realized
              .amount,
          '300',
        );
        await controller().refresh();
        expect(
          state().summary!.lines
              .firstWhere((l) => l.categoryId == _market)
              .realized
              .amount,
          '420',
        );
      },
    );
  });
}
