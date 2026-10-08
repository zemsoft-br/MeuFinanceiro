import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_controller.dart';

import '../../support/fake_finance_backend.dart';
import '../../support/fake_goal_backend.dart';

FakeGoal _goal({
  int index = 1,
  String scope = 'HOUSEHOLD',
  String owner = financeTestOwnerId,
  String target = '1000',
  String title = 'Reserva',
}) => FakeGoal(
  index: index,
  scope: scope,
  owner: owner,
  target: target,
  title: title,
);

FakeGoalBackend _backend({
  List<FakeGoal>? goals,
  String operatorId = financeTestOwnerId,
}) {
  final backend = FakeGoalBackend(
    goals: goals ?? [_goal()],
    accounts: [
      FakeGoalAccount(index: 1, name: 'Conta casa', balance: '1000'),
      FakeGoalAccount(index: 2, name: 'Poupança', balance: '500'),
    ],
    operatorId: operatorId,
  );
  return backend;
}

FinancialGoalCreateInput _createInput({String? key, String amount = '2000'}) =>
    FinancialGoalCreateInput(
      title: 'Viagem',
      visibilityScope: FinancialVisibilityScope.household,
      currency: 'BRL',
      targetAmount: amount,
      idempotencyKey: key,
    );

FinancialGoalReplaceInput _replaceInput({
  int version = 1,
  String amount = '1500',
}) => FinancialGoalReplaceInput(
  expectedVersion: version,
  title: 'Reserva v2',
  currency: 'BRL',
  targetAmount: amount,
);

FinancialGoalAllocationInput _allocation(
  FakeGoalBackend backend, {
  FinancialGoalOperation operation = FinancialGoalOperation.allocate,
  String amount = '100',
  int account = 1,
  String? key,
}) => FinancialGoalAllocationInput(
  operation: operation,
  accountId: goalTestAccountId(account),
  amount: amount,
  currency: 'BRL',
  idempotencyKey: key,
);

void main() {
  late FakeGoalBackend backend;
  late ProviderContainer container;

  FinancialGoalsController controller() =>
      container.read(financialGoalsControllerProvider.notifier);
  FinancialGoalsState state() =>
      container.read(financialGoalsControllerProvider);

  Future<FinancialGoalsState> loaded() async {
    await controller().load();
    return state();
  }

  void start([FakeGoalBackend? custom]) {
    backend = custom ?? _backend();
    container = goalTestContainer(backend);
    addTearDown(container.dispose);
    // Keep the autoDispose notifier alive for the whole test.
    container.listen(financialGoalsControllerProvider, (_, _) {});
  }

  setUp(start);

  group('loading', () {
    test('reads the accounts, the goals and one summary', () async {
      backend.seed(
        backend.goals.single,
        backend.accounts[0],
        'ALLOCATE',
        '250',
      );
      final result = await loaded();

      expect(result.phase, FinancialLoadPhase.loaded);
      expect(result.goals.single.goal.id, goalTestId(1));
      expect(result.selectedGoalId, goalTestId(1));
      expect(result.summaryPhase, FinancialGoalSummaryPhase.ready);
      expect(result.summary!.allocated.amount, '250');
      expect(result.accounts, hasLength(2));
      expect(backend.accountReads, 1);
      expect(backend.listReads, 1);
      expect(backend.summaryReads, 1);
      expect(backend.perItemRequests, 0);
    });

    test('the cost does not grow with goals, accounts or events', () async {
      final many = _backend(
        goals: [for (var i = 1; i <= 25; i += 1) _goal(index: i)],
      );
      for (var i = 0; i < 40; i += 1) {
        many.seed(many.goals.first, many.accounts[i % 2], 'ALLOCATE', '1');
      }
      start(many);
      await loaded();
      expect(backend.accountReads, 1);
      expect(backend.listReads, 1);
      expect(backend.summaryReads, 1);
      expect(backend.calls, hasLength(3));
    });

    test('no goals is the empty phase and reads no summary', () async {
      start(_backend(goals: []));
      final result = await loaded();
      expect(result.phase, FinancialLoadPhase.empty);
      expect(result.summaryPhase, FinancialGoalSummaryPhase.none);
      expect(backend.summaryReads, 0);
    });

    test('selecting another goal reads only its summary', () async {
      start(
        _backend(
          goals: [
            _goal(),
            _goal(index: 2, title: 'Casa'),
          ],
        ),
      );
      await loaded();
      await controller().select(goalTestId(2));
      expect(state().selectedGoalId, goalTestId(2));
      expect(state().summary!.goal.id, goalTestId(2));
      expect(backend.summaryReads, 2);
      expect(backend.listReads, 1);
    });

    test('failures map to phases and a transport error is retryable', () async {
      backend.listStatus = 403;
      expect((await loaded()).phase, FinancialLoadPhase.forbidden);
      backend.listStatus = null;
      backend.listThrows = true;
      await controller().load();
      expect(state().phase, FinancialLoadPhase.temporarilyUnavailable);
      backend.listThrows = false;
      backend.listBodyOverride = '{"items":"nope"}';
      await controller().load();
      expect(state().phase, FinancialLoadPhase.invalidResponse);
      backend.listBodyOverride = null;
      await controller().load();
      expect(state().phase, FinancialLoadPhase.loaded);
    });

    test('an expired session is reported as such', () async {
      backend.listStatus = 401;
      expect((await loaded()).phase, FinancialLoadPhase.authenticationRequired);
    });

    test('a summary failure keeps the goals and is retryable alone', () async {
      backend.summaryStatus = 503;
      final result = await loaded();
      expect(result.phase, FinancialLoadPhase.loaded);
      expect(
        result.summaryPhase,
        FinancialGoalSummaryPhase.temporarilyUnavailable,
      );
      expect(result.summary, isNull);
      backend.summaryStatus = null;
      await controller().reloadSummary();
      expect(state().summaryPhase, FinancialGoalSummaryPhase.ready);
      expect(backend.listReads, 1);
    });

    test('an invalid summary is reported without dropping the goals', () async {
      backend.summaryBodyOverride = '{"goal":1}';
      final result = await loaded();
      expect(result.summaryPhase, FinancialGoalSummaryPhase.invalidResponse);
      expect(result.goals, hasLength(1));
    });
  });

  group('create', () {
    test('sends one POST, then reads the goals again and selects it', () async {
      await loaded();
      final result = await controller().createGoal(_createInput());

      expect(result.outcome, FinancialGoalActionOutcome.created);
      expect(result.reconciled, isTrue);
      expect(backend.creates, 1);
      expect(backend.listReads, 2);
      expect(state().goals, hasLength(2));
      expect(state().selected!.goal.title, 'Viagem');
      expect(state().mutationInFlight, isFalse);
    });

    test('nothing is shown before the canonical read', () async {
      await loaded();
      final gate = Completer<void>();
      backend.listGate = gate;
      final pending = controller().createGoal(_createInput());
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      expect(state().goals, hasLength(1));
      expect(state().isBusy, isTrue);
      gate.complete();
      await pending;
      expect(state().goals, hasLength(2));
    });

    test(
      'an ambiguous create keeps its key for an explicit identical retry',
      () async {
        await loaded();
        backend.postCommitsThenFails = true;
        final first = await controller().createGoal(_createInput());
        expect(first.outcome, FinancialGoalActionOutcome.unknownOutcome);
        expect(backend.creates, 1);

        backend.postCommitsThenFails = false;
        final retry = await controller().createGoal(_createInput());
        expect(retry.outcome, FinancialGoalActionOutcome.created);
        expect(backend.creates, 2);
        expect(
          backend.postBodies.first['idempotencyKey'],
          backend.postBodies.last['idempotencyKey'],
        );
        // The server replayed it: still one extra goal, never two.
        expect(state().goals, hasLength(2));
      },
    );

    test('a different request never reuses the unknown attempt key', () async {
      await loaded();
      backend.postCommitsThenFails = true;
      await controller().createGoal(_createInput());
      backend.postCommitsThenFails = false;
      await controller().createGoal(_createInput(amount: '3000'));
      expect(
        backend.postBodies.first['idempotencyKey'],
        isNot(backend.postBodies.last['idempotencyKey']),
      );
    });

    test('a 422 is rejected and reads the truth', () async {
      await loaded();
      backend.postStatus = 422;
      final result = await controller().createGoal(_createInput());
      expect(result.outcome, FinancialGoalActionOutcome.rejected);
      expect(backend.listReads, 2);
      expect(backend.creates, 1);
    });

    test('an invalid 2xx is an unknown outcome and is not resent', () async {
      await loaded();
      backend.postBodyOverride = backend.goalJson(
        _goal(index: 77, title: 'Outra'),
      );
      final result = await controller().createGoal(_createInput());
      expect(result.outcome, FinancialGoalActionOutcome.unknownOutcome);
      expect(backend.creates, 1);
    });
  });

  group('edit under CAS', () {
    test('replaces once and reads again', () async {
      await loaded();
      final result = await controller().replaceGoal(
        goalTestId(1),
        _replaceInput(),
      );
      expect(result.outcome, FinancialGoalActionOutcome.updated);
      expect(backend.puts, 1);
      expect(state().selected!.goal.version, 2);
      expect(state().selected!.goal.title, 'Reserva v2');
    });

    test(
      'a stale version is a conflict that is never retried or re-based',
      () async {
        await loaded();
        backend.beforePut = () => backend.goals.single.version = 5;
        final result = await controller().replaceGoal(
          goalTestId(1),
          _replaceInput(),
        );

        expect(result.outcome, FinancialGoalActionOutcome.conflict);
        expect(backend.puts, 1);
        expect(state().conflictNotice, isTrue);
        expect(state().selected!.goal.version, 5);
        expect(state().selected!.goal.title, 'Reserva');
        controller().dismissConflictNotice();
        expect(state().conflictNotice, isFalse);
      },
    );

    test('local guards refuse without any request', () async {
      start(_backend(goals: [_goal(owner: financeTestOtherOperatorId)]));
      await loaded();
      expect(state().selected!.goal.canEdit, isFalse);
      final readOnly = await controller().replaceGoal(
        goalTestId(1),
        _replaceInput(),
      );
      expect(readOnly.outcome, FinancialGoalActionOutcome.notAllowed);
      expect(backend.puts, 0);

      start();
      await loaded();
      final stale = await controller().replaceGoal(
        goalTestId(1),
        _replaceInput(version: 9),
      );
      expect(stale.outcome, FinancialGoalActionOutcome.notAllowed);
      expect(backend.puts, 0);
    });

    test('a 403 reads the truth and reports read-only', () async {
      await loaded();
      backend.putStatus = 403;
      final result = await controller().replaceGoal(
        goalTestId(1),
        _replaceInput(),
      );
      expect(result.outcome, FinancialGoalActionOutcome.readOnly);
      expect(backend.listReads, 2);
    });

    test(
      'a 503 after commit is unknown, reads the truth and does not resend',
      () async {
        await loaded();
        backend.putCommitsThenFails = true;
        final result = await controller().replaceGoal(
          goalTestId(1),
          _replaceInput(),
        );
        expect(result.outcome, FinancialGoalActionOutcome.unknownOutcome);
        expect(backend.puts, 1);
        expect(state().selected!.goal.title, 'Reserva v2');
      },
    );
  });

  group('allocation', () {
    test(
      'allocate and release go through one POST each, never optimistic',
      () async {
        await loaded();
        final gate = Completer<void>();
        backend.listGate = gate;
        final pending = controller().allocate(
          goalTestId(1),
          _allocation(backend),
        );
        await Future<void>.delayed(Duration.zero);
        await Future<void>.delayed(Duration.zero);
        expect(state().summary!.allocated.amount, '0');
        gate.complete();
        final allocated = await pending;
        backend.listGate = null;

        expect(allocated.outcome, FinancialGoalActionOutcome.allocated);
        expect(state().summary!.allocated.amount, '100');
        expect(state().selected!.allocated.amount, '100');
        expect(backend.allocationPosts, 1);

        final released = await controller().allocate(
          goalTestId(1),
          _allocation(
            backend,
            operation: FinancialGoalOperation.release,
            amount: '40',
          ),
        );
        expect(released.outcome, FinancialGoalActionOutcome.released);
        expect(state().summary!.allocated.amount, '60');
        expect(backend.allocationPosts, 2);
        expect(backend.accountReads, 3);
      },
    );

    test(
      'exceeding the available balance is a conflict that writes nothing',
      () async {
        await loaded();
        final result = await controller().allocate(
          goalTestId(1),
          _allocation(backend, amount: '1000.01'),
        );
        expect(result.outcome, FinancialGoalActionOutcome.conflict);
        expect(state().conflictNotice, isTrue);
        expect(state().summary!.allocated.amount, '0');
        expect(backend.events, isEmpty);
        expect(backend.allocationPosts, 1);
      },
    );

    test('two goals cannot take the same availability', () async {
      start(
        _backend(
          goals: [
            _goal(),
            _goal(index: 2, title: 'Casa'),
          ],
        ),
      );
      await loaded();
      expect(
        (await controller().allocate(
          goalTestId(1),
          _allocation(backend, amount: '700'),
        )).outcome,
        FinancialGoalActionOutcome.allocated,
      );
      await controller().select(goalTestId(2));
      expect(
        (await controller().allocate(
          goalTestId(2),
          _allocation(backend, amount: '400'),
        )).outcome,
        FinancialGoalActionOutcome.conflict,
      );
      expect(
        (await controller().allocate(
          goalTestId(2),
          _allocation(backend, amount: '300'),
        )).outcome,
        FinancialGoalActionOutcome.allocated,
      );
    });

    test('releasing more than allocated is a conflict', () async {
      await loaded();
      final result = await controller().allocate(
        goalTestId(1),
        _allocation(backend, operation: FinancialGoalOperation.release),
      );
      expect(result.outcome, FinancialGoalActionOutcome.conflict);
    });

    test(
      'an ambiguous allocation reuses its key only for an identical retry',
      () async {
        await loaded();
        backend.allocCommitsThenFails = true;
        final first = await controller().allocate(
          goalTestId(1),
          _allocation(backend),
        );
        expect(first.outcome, FinancialGoalActionOutcome.unknownOutcome);
        expect(backend.allocationPosts, 1);
        // The write happened; the truth was read, and nothing was resent.
        expect(state().summary!.allocated.amount, '100');

        backend.allocCommitsThenFails = false;
        final retry = await controller().allocate(
          goalTestId(1),
          _allocation(backend),
        );
        expect(retry.outcome, FinancialGoalActionOutcome.allocated);
        expect(
          backend.allocationBodies.first['idempotencyKey'],
          backend.allocationBodies.last['idempotencyKey'],
        );
        // Replayed by the server: still 100, never 200.
        expect(state().summary!.allocated.amount, '100');
        expect(backend.events, hasLength(1));
      },
    );

    test('a different amount gets a different key', () async {
      await loaded();
      backend.allocCommitsThenFails = true;
      await controller().allocate(goalTestId(1), _allocation(backend));
      backend.allocCommitsThenFails = false;
      await controller().allocate(
        goalTestId(1),
        _allocation(backend, amount: '101'),
      );
      expect(
        backend.allocationBodies.first['idempotencyKey'],
        isNot(backend.allocationBodies.last['idempotencyKey']),
      );
    });

    test(
      'local guards: read-only, busy and untrusted states send nothing',
      () async {
        start(_backend(goals: [_goal(owner: financeTestOtherOperatorId)]));
        await loaded();
        expect(
          (await controller().allocate(
            goalTestId(1),
            _allocation(backend),
          )).outcome,
          FinancialGoalActionOutcome.notAllowed,
        );

        start();
        await loaded();
        final wrongCurrency = FinancialGoalAllocationInput(
          operation: FinancialGoalOperation.allocate,
          accountId: goalTestAccountId(1),
          amount: '1',
          currency: 'USD',
        );
        expect(
          (await controller().allocate(goalTestId(1), wrongCurrency)).outcome,
          FinancialGoalActionOutcome.notAllowed,
        );
        expect(
          (await controller().allocate(
            goalTestId(99),
            _allocation(backend),
          )).outcome,
          FinancialGoalActionOutcome.notAllowed,
        );
        backend.listThrows = true;
        await controller().refresh();
        expect(state().trusted, isFalse);
        backend.listThrows = false;
        expect(
          (await controller().allocate(
            goalTestId(1),
            _allocation(backend),
          )).outcome,
          FinancialGoalActionOutcome.notAllowed,
        );
        expect(backend.allocationPosts, 0);
      },
    );

    test('a balance that falls later is shown, never repaired', () async {
      await loaded();
      await controller().allocate(
        goalTestId(1),
        _allocation(backend, amount: '800'),
      );
      expect(state().summary!.hasInsufficientBacking, isFalse);

      backend.accounts[0].balance = '300'; // a later expense
      await controller().refresh();
      final summary = state().summary!;
      expect(summary.hasInsufficientBacking, isTrue);
      expect(summary.allocated.amount, '800');
      expect(summary.accounts.single.shortfall.amount, '500');
      expect(backend.events, hasLength(1));
      // New allocations are refused by the server; the client sent no repair.
      final refused = await controller().allocate(
        goalTestId(1),
        _allocation(backend, amount: '1'),
      );
      expect(refused.outcome, FinancialGoalActionOutcome.conflict);
      final released = await controller().allocate(
        goalTestId(1),
        _allocation(
          backend,
          operation: FinancialGoalOperation.release,
          amount: '800',
        ),
      );
      expect(released.outcome, FinancialGoalActionOutcome.released);
      expect(state().summary!.hasInsufficientBacking, isFalse);
    });

    test('access lost during a write blocks the screen', () async {
      await loaded();
      backend.allocStatus = 401;
      final result = await controller().allocate(
        goalTestId(1),
        _allocation(backend),
      );
      expect(result.outcome, FinancialGoalActionOutcome.accessBlocked);
      expect(state().phase, FinancialLoadPhase.authenticationRequired);
    });
  });

  group('a failed re-read after a write', () {
    test(
      'keeps what was shown, marks it untrusted and blocks further writes',
      () async {
        await loaded();
        backend.postCommitsThenFails = true;
        backend.listThrows = true;
        final result = await controller().createGoal(_createInput());

        expect(result.reconciled, isFalse);
        expect(state().trusted, isFalse);
        expect(
          state().refreshFailure,
          FinancialRefreshFailure.temporarilyUnavailable,
        );
        expect(state().goals, hasLength(1));
        expect(
          (await controller().createGoal(_createInput())).outcome,
          FinancialGoalActionOutcome.notAllowed,
        );
        backend.listThrows = false;
        backend.postCommitsThenFails = false;
        await controller().refresh();
        expect(state().trusted, isTrue);
      },
    );
  });
}
