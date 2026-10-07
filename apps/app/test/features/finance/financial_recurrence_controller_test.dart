import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_controller.dart';

import '../../support/fake_finance_backend.dart';
import '../../support/fake_recurrence_backend.dart';

final _account = recurrenceTestAccountId(1);

FakeRecurrenceBackend _backend({
  bool withRule = true,
  String operatorId = financeTestOwnerId,
}) {
  final backend = FakeRecurrenceBackend(operatorId: operatorId);
  if (withRule) backend.rules.add(FakeRule(index: 1, accountId: _account));
  return backend;
}

FinancialRecurrenceCreateInput _createInput({
  String description = 'Aluguel',
  String amount = '1500',
  String? key,
  String? account,
}) => FinancialRecurrenceCreateInput(
  accountId: account ?? _account,
  description: description,
  resultEffect: FinancialResultEffect.expense,
  expectedAmount: amount,
  currency: 'BRL',
  startDate: '2026-01-05',
  dayOfMonth: 5,
  idempotencyKey: key,
);

FinancialRecurrenceReplaceInput _replaceInput({
  int version = 1,
  String amount = '135',
  String description = 'Internet',
}) => FinancialRecurrenceReplaceInput(
  expectedVersion: version,
  description: description,
  expectedAmount: amount,
  dayOfMonth: 10,
);

FinancialRecurrenceRealizeInput _realizeInput({
  String amount = '127.50',
  String? key,
  String currency = 'BRL',
}) => FinancialRecurrenceRealizeInput(
  actualAmount: amount,
  currency: currency,
  effectiveDate: '2026-10-11',
  competenceDate: '2026-10-01',
  idempotencyKey: key,
);

void main() {
  late FakeRecurrenceBackend backend;
  late ProviderContainer container;

  FinancialRecurrencesController controller() =>
      container.read(financialRecurrencesControllerProvider.notifier);
  FinancialRecurrencesState state() =>
      container.read(financialRecurrencesControllerProvider);

  void start(FakeRecurrenceBackend value, {String? operatorId}) {
    backend = value;
    container = recurrenceTestContainer(
      backend,
      operatorId: operatorId ?? financeTestOwnerId,
    );
    addTearDown(container.dispose);
    // Keep the autoDispose notifier alive for the whole test.
    container.listen(financialRecurrencesControllerProvider, (_, _) {});
  }

  Future<FinancialRecurrencesState> loaded() async {
    await controller().load();
    return state();
  }

  setUp(() => start(_backend()));

  group('loading', () {
    test(
      'starts in the injected current month and reads exactly four things',
      () async {
        expect(state().period, '2026-10');
        final value = await loaded();
        expect(value.phase, FinancialLoadPhase.loaded);
        expect(value.recurrences.single.description, 'Internet');
        expect(value.accounts, hasLength(1));
        expect(value.occurrences, isEmpty);
        // accounts, rules, one month and the suggestions
        expect(backend.calls, hasLength(4));
        expect(backend.suggestionReads, 1);
        expect(backend.listReads, 1);
        expect(backend.occurrenceReads, 1);
        expect(backend.totalWrites, 0);
      },
    );

    test('the request cost does not depend on the number of rules', () async {
      for (var i = 2; i < 30; i += 1) {
        backend.rules.add(FakeRule(index: i, accountId: _account));
      }
      await loaded();
      expect(backend.calls, hasLength(4));
    });

    test('reading never generates a forecast or a Movement', () async {
      await loaded();
      await controller().refresh();
      await controller().nextMonth();
      expect(backend.occurrences, isEmpty);
      expect(backend.ledger, isEmpty);
      expect(backend.totalWrites, 0);
    });

    test('no rules is the empty phase', () async {
      start(_backend(withRule: false));
      expect((await loaded()).phase, FinancialLoadPhase.empty);
    });

    test('a failed load is its own phase and offers no stale data', () async {
      backend.listStatus = 503;
      expect((await loaded()).phase, FinancialLoadPhase.temporarilyUnavailable);
      backend.listStatus = 401;
      await controller().refresh();
      expect(state().phase, FinancialLoadPhase.authenticationRequired);
    });

    test('an invalid response is not shown', () async {
      backend.listBodyOverride = '{"items":[{"id":"x"}]}';
      final value = await loaded();
      expect(value.phase, FinancialLoadPhase.invalidResponse);
      expect(value.recurrences, isEmpty);
    });

    test('a refresh that fails keeps the data but blocks writes', () async {
      final first = await loaded();
      expect(first.trusted, isTrue);
      backend.listStatus = 503;
      await controller().refresh();
      final value = state();
      expect(
        value.refreshFailure,
        FinancialRefreshFailure.temporarilyUnavailable,
      );
      expect(value.trusted, isFalse);
      expect(value.recurrences, hasLength(1));
      final result = await controller().createRecurrence(_createInput());
      expect(result.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      expect(backend.totalWrites, 0);
    });

    test('months page without writing', () async {
      await loaded();
      await controller().nextMonth();
      expect(state().period, '2026-11');
      await controller().previousMonth();
      await controller().previousMonth();
      expect(state().period, '2026-09');
      expect(backend.occurrenceReads, 4);
      expect(backend.totalWrites, 0);
    });
  });

  group('create', () {
    test(
      'sends once, shows only what the server returns after a re-read',
      () async {
        await loaded();
        final result = await controller().createRecurrence(_createInput());
        expect(result.outcome, FinancialRecurrenceActionOutcome.created);
        expect(result.reconciled, isTrue);
        expect(backend.writes(AuthHttpMethod.post, '/recurrences'), 1);
        expect(backend.listReads, 2); // initial + the canonical re-read
        expect(state().recurrences.map((r) => r.description), [
          'Internet',
          'Aluguel',
        ]);
        // Creating a rule creates no forecast and no Movement.
        expect(backend.occurrences, isEmpty);
        expect(backend.ledger, isEmpty);
      },
    );

    test(
      'an account of another owner is refused by the server, not retried',
      () async {
        backend.accounts.add(
          FakeAccount(
            id: recurrenceTestAccountId(2),
            owner: financeTestOtherOperatorId,
          ),
        );
        await loaded();
        final result = await controller().createRecurrence(
          _createInput(account: recurrenceTestAccountId(2)),
        );
        expect(result.outcome, FinancialRecurrenceActionOutcome.rejected);
        expect(backend.totalWrites, 1);
        expect(backend.rules, hasLength(1));
      },
    );

    test('a 5xx is never resent automatically', () async {
      await loaded();
      backend.writeStatus = 503;
      final result = await controller().createRecurrence(_createInput());
      expect(result.outcome, FinancialRecurrenceActionOutcome.unknownOutcome);
      expect(backend.totalWrites, 1);
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(backend.totalWrites, 1);
    });

    test(
      'an ambiguous create is replayed by key only on an identical retry',
      () async {
        await loaded();
        backend.writeCommitsThenFails = true;
        final first = await controller().createRecurrence(_createInput());
        expect(first.outcome, FinancialRecurrenceActionOutcome.unknownOutcome);
        expect(backend.rules, hasLength(2)); // it did commit
        backend.writeCommitsThenFails = false;
        final retry = await controller().createRecurrence(_createInput());
        expect(retry.outcome, FinancialRecurrenceActionOutcome.created);
        expect(backend.rules, hasLength(2)); // the server replayed it
        expect(
          backend.writeBodies.map((b) => b['idempotencyKey']).toSet(),
          hasLength(1),
        );
      },
    );

    test('a different request after an ambiguous one gets a new key', () async {
      await loaded();
      backend.writeCommitsThenFails = true;
      await controller().createRecurrence(_createInput());
      backend.writeCommitsThenFails = false;
      await controller().createRecurrence(_createInput(amount: '1600'));
      expect(
        backend.writeBodies.map((b) => b['idempotencyKey']).toSet(),
        hasLength(2),
      );
    });

    test('an invalid 2xx answer is unknown and nothing is resent', () async {
      await loaded();
      backend.writeBodyOverride = backend.ruleJson(
        FakeRule(index: 77, accountId: _account, expected: '1'),
      );
      final result = await controller().createRecurrence(_createInput());
      expect(result.outcome, FinancialRecurrenceActionOutcome.unknownOutcome);
      expect(backend.totalWrites, 1);
    });
  });

  group('edit (CAS)', () {
    test(
      'sends the version, reads again and reports the superseded count',
      () async {
        final rule = backend.rules.single;
        backend.addOccurrence(rule, '2026-11');
        backend.addOccurrence(rule, '2026-12');
        await loaded();
        final result = await controller().replaceRecurrence(
          rule.id,
          _replaceInput(),
        );
        expect(result.outcome, FinancialRecurrenceActionOutcome.updated);
        expect(result.supersededCount, 2);
        expect(state().recurrences.single.version, 2);
        expect(state().recurrences.single.expected.amount, '135');
        expect(backend.writes(AuthHttpMethod.put), 1);
      },
    );

    test(
      'a stale version is a conflict: nothing re-based, nothing resent',
      () async {
        final rule = backend.rules.single;
        await loaded();
        backend.beforeWrite = () => rule.version += 1; // someone else edited
        final result = await controller().replaceRecurrence(
          rule.id,
          _replaceInput(),
        );
        expect(result.outcome, FinancialRecurrenceActionOutcome.conflict);
        expect(backend.writes(AuthHttpMethod.put), 1);
        expect(state().conflictNotice, isTrue);
        expect(state().recurrences.single.version, 2); // the current one, read
        expect(
          state().recurrences.single.expected.amount,
          '120',
        ); // not applied
      },
    );

    test('a rule the operator does not own is refused locally', () async {
      start(_backend(operatorId: financeTestOtherOperatorId));
      backend.rules.single.owner = financeTestOwnerId;
      await loaded();
      final rule = state().recurrences.single;
      expect(rule.canEdit, isFalse);
      for (final result in [
        await controller().replaceRecurrence(rule.id, _replaceInput()),
        await controller().pause(rule.id),
        await controller().generateForShownMonth(rule.id),
      ]) {
        expect(result.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      }
      expect(backend.totalWrites, 0);
    });

    test('a 403 from the server is read-only, not a lost session', () async {
      await loaded();
      backend.writeStatus = 403;
      final result = await controller().replaceRecurrence(
        backend.rules.single.id,
        _replaceInput(),
      );
      expect(result.outcome, FinancialRecurrenceActionOutcome.readOnly);
      expect(state().isLoaded, isTrue);
    });

    test(
      'an edit with another version than the one on screen is not sent',
      () async {
        await loaded();
        final result = await controller().replaceRecurrence(
          backend.rules.single.id,
          _replaceInput(version: 9),
        );
        expect(result.outcome, FinancialRecurrenceActionOutcome.notAllowed);
        expect(backend.totalWrites, 0);
      },
    );
  });

  group('pause, resume and explicit generation', () {
    test('nothing exists until the user generates the shown month', () async {
      await loaded();
      expect(state().occurrences, isEmpty);
      final result = await controller().generateForShownMonth(
        backend.rules.single.id,
      );
      expect(result.outcome, FinancialRecurrenceActionOutcome.generated);
      expect(result.createdCount, 1);
      expect(
        state().occurrences.single.status,
        FinancialOccurrenceStatus.pending,
      );
      expect(state().occurrences.single.scheduledDate, '2026-10-10');
      // A forecast is not a fact.
      expect(backend.ledger, isEmpty);
      expect(backend.balanceOf(_account), '1000');
      expect(backend.generateCalls, 1);
    });

    test('generating again creates nothing', () async {
      await loaded();
      await controller().generateForShownMonth(backend.rules.single.id);
      final again = await controller().generateForShownMonth(
        backend.rules.single.id,
      );
      expect(again.createdCount, 0);
      expect(state().occurrences, hasLength(1));
    });

    test(
      'a paused rule cannot generate (not even a request) and keeps history',
      () async {
        final rule = backend.rules.single;
        backend.addOccurrence(rule, '2026-10');
        await loaded();
        final paused = await controller().pause(rule.id);
        expect(paused.outcome, FinancialRecurrenceActionOutcome.paused);
        expect(state().recurrences.single.isPaused, isTrue);
        expect(state().occurrences, hasLength(1)); // history kept
        final before = backend.generateCalls;
        final blocked = await controller().generateForShownMonth(rule.id);
        expect(blocked.outcome, FinancialRecurrenceActionOutcome.notAllowed);
        expect(backend.generateCalls, before);
        final again = await controller().pause(rule.id);
        expect(again.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      },
    );

    test(
      'resume allows generation again and generates nothing itself',
      () async {
        final rule = backend.rules.single..status = 'PAUSED';
        await loaded();
        final resumed = await controller().resume(rule.id);
        expect(resumed.outcome, FinancialRecurrenceActionOutcome.resumed);
        expect(state().occurrences, isEmpty);
        expect(backend.generateCalls, 0);
        expect(
          (await controller().generateForShownMonth(rule.id)).createdCount,
          1,
        );
      },
    );

    test(
      'a 409 from generate (paused elsewhere) is a conflict notice',
      () async {
        final rule = backend.rules.single;
        await loaded();
        backend.beforeWrite = () => rule.status = 'PAUSED';
        final result = await controller().generateForShownMonth(rule.id);
        expect(result.outcome, FinancialRecurrenceActionOutcome.conflict);
        expect(state().conflictNotice, isTrue);
        expect(state().recurrences.single.isPaused, isTrue);
        expect(backend.occurrences, isEmpty);
      },
    );
  });

  group('skip', () {
    test('creates no Movement and does not move the balance', () async {
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await loaded();
      final result = await controller().skip(occurrence.id);
      expect(result.outcome, FinancialRecurrenceActionOutcome.skipped);
      expect(
        state().occurrences.single.status,
        FinancialOccurrenceStatus.skipped,
      );
      expect(backend.ledger, isEmpty);
      expect(backend.balanceOf(_account), '1000');
    });

    test('only a pending occurrence can be skipped', () async {
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10')
        ..status = 'SKIPPED';
      await loaded();
      final result = await controller().skip(occurrence.id);
      expect(result.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      expect(backend.skipCalls, 0);
    });

    test(
      'a 409 (already handled elsewhere) is explained and re-read',
      () async {
        final occurrence = backend.addOccurrence(
          backend.rules.single,
          '2026-10',
        );
        await loaded();
        backend.beforeWrite = () => occurrence.status = 'SUPERSEDED';
        final result = await controller().skip(occurrence.id);
        expect(result.outcome, FinancialRecurrenceActionOutcome.conflict);
        expect(state().occurrences, isEmpty);
      },
    );
  });

  group('registering (the only act that creates a fact)', () {
    test('creates exactly one Movement and shows expected x actual', () async {
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await loaded();
      expect(backend.balanceOf(_account), '1000'); // forecast: no effect
      final result = await controller().realize(occurrence.id, _realizeInput());
      expect(result.outcome, FinancialRecurrenceActionOutcome.realized);
      expect(backend.ledger, hasLength(1));
      expect(backend.balanceOf(_account), '872.5');
      final shown = state().occurrences.single;
      expect(shown.status, FinancialOccurrenceStatus.realized);
      expect(shown.expected.amount, '120');
      expect(shown.realization!.actual.amount, '127.5');
      expect(backend.realizeCalls, 1);
    });

    test('an ambiguous registration never registers twice', () async {
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await loaded();
      backend.writeCommitsThenFails = true;
      final first = await controller().realize(occurrence.id, _realizeInput());
      expect(first.outcome, FinancialRecurrenceActionOutcome.unknownOutcome);
      expect(backend.realizeCalls, 1); // never auto retried
      expect(backend.ledger, hasLength(1)); // it did commit
      // The screen already shows the truth, so the occurrence is registered.
      expect(
        state().occurrences.single.status,
        FinancialOccurrenceStatus.realized,
      );
      backend.writeCommitsThenFails = false;
      // An explicit identical retry (an old dialog) is refused locally.
      final retry = await controller().realize(occurrence.id, _realizeInput());
      expect(retry.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      expect(backend.ledger, hasLength(1));
    });

    test(
      'an identical retry of an unconfirmed attempt reuses its key',
      () async {
        final occurrence = backend.addOccurrence(
          backend.rules.single,
          '2026-10',
        );
        await loaded();
        backend.writeThrows = true;
        final first = await controller().realize(
          occurrence.id,
          _realizeInput(),
        );
        expect(first.outcome, FinancialRecurrenceActionOutcome.unknownOutcome);
        backend.writeThrows = false;
        final retry = await controller().realize(
          occurrence.id,
          _realizeInput(),
        );
        expect(retry.outcome, FinancialRecurrenceActionOutcome.realized);
        expect(backend.ledger, hasLength(1));
        expect(
          backend.writeBodies.map((b) => b['idempotencyKey']).toSet(),
          hasLength(1),
        );
      },
    );

    test('a foreign currency is refused before any request', () async {
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await loaded();
      final result = await controller().realize(
        occurrence.id,
        _realizeInput(currency: 'USD'),
      );
      expect(result.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      expect(backend.realizeCalls, 0);
    });

    test('a non-pending occurrence cannot be registered', () async {
      final skipped = backend.addOccurrence(backend.rules.single, '2026-10')
        ..status = 'SKIPPED';
      await loaded();
      final result = await controller().realize(skipped.id, _realizeInput());
      expect(result.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      expect(backend.realizeCalls, 0);
    });

    test(
      'a 409 means someone else handled it: explained, nothing duplicated',
      () async {
        final occurrence = backend.addOccurrence(
          backend.rules.single,
          '2026-10',
        );
        await loaded();
        backend.beforeWrite = () => occurrence.status = 'SKIPPED';
        final result = await controller().realize(
          occurrence.id,
          _realizeInput(),
        );
        expect(result.outcome, FinancialRecurrenceActionOutcome.conflict);
        expect(backend.ledger, isEmpty);
        expect(state().conflictNotice, isTrue);
        expect(
          state().occurrences.single.status,
          FinancialOccurrenceStatus.skipped,
        );
      },
    );

    test('a reversal of the Movement never reopens the occurrence', () async {
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await loaded();
      await controller().realize(occurrence.id, _realizeInput());
      backend.reverseMovementOf(occurrence.id);
      await controller().refresh();
      final shown = state().occurrences.single;
      expect(shown.status, FinancialOccurrenceStatus.realized);
      expect(
        shown.realization!.movementState,
        FinancialOccurrenceMovementState.reversed,
      );
      final retry = await controller().realize(occurrence.id, _realizeInput());
      expect(retry.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      expect(backend.realizeCalls, 1);
    });

    test('writes are blocked while another write is in flight', () async {
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await loaded();
      final gate = Completer<void>();
      backend.writeGate = gate;
      final pending = controller().realize(occurrence.id, _realizeInput());
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(state().mutationInFlight, isTrue);
      final second = await controller().skip(occurrence.id);
      expect(second.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      gate.complete();
      await pending;
      expect(backend.ledger, hasLength(1));
      expect(state().mutationInFlight, isFalse);
    });
  });

  group('access', () {
    test('a lost session after a write blocks the screen', () async {
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await loaded();
      backend.writeStatus = 401;
      final result = await controller().skip(occurrence.id);
      expect(result.outcome, FinancialRecurrenceActionOutcome.accessBlocked);
      expect(state().phase, FinancialLoadPhase.authenticationRequired);
    });
  });
}
