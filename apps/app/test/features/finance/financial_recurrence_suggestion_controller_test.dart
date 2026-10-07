import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_controller.dart';

import '../../support/fake_finance_backend.dart';
import '../../support/fake_recurrence_backend.dart';

final _account = recurrenceTestAccountId(1);
final _fingerprint = suggestionTestFingerprint(1);
const _otherOperator = '30000000-0000-4000-8000-000000000009';

FakeRecurrenceBackend _backend({
  bool withRule = false,
  String operatorId = financeTestOwnerId,
  String owner = financeTestOwnerId,
}) {
  final backend = FakeRecurrenceBackend(operatorId: operatorId);
  if (withRule) backend.rules.add(FakeRule(index: 1, accountId: _account));
  backend.suggestions.add(
    FakeSuggestion(index: 1, accountId: _account, owner: owner),
  );
  return backend;
}

FinancialRecurrenceSuggestionAcceptInput _accept({
  String amount = '41.90',
  String description = 'Streaming',
  String? key,
  String fingerprint = '',
  String? account,
  String currency = 'BRL',
}) => FinancialRecurrenceSuggestionAcceptInput(
  fingerprint: fingerprint.isEmpty ? _fingerprint : fingerprint,
  accountId: account ?? _account,
  currency: currency,
  description: description,
  expectedAmount: amount,
  startDate: '2026-11-01',
  dayOfMonth: 10,
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
    container.listen(financialRecurrencesControllerProvider, (_, _) {});
  }

  Future<FinancialRecurrencesState> loaded() async {
    await controller().load();
    return state();
  }

  setUp(() => start(_backend()));

  group('reading', () {
    test(
      'loads the suggestions with the rules, even with no rule yet',
      () async {
        final value = await loaded();
        expect(value.phase, FinancialLoadPhase.empty);
        expect(value.recurrences, isEmpty);
        expect(value.suggestions.single.fingerprint, _fingerprint);
        expect(value.suggestionsUnavailable, isFalse);
        expect(backend.suggestionReads, 1);
        expect(backend.totalWrites, 0);
      },
    );

    test(
      'the cost is fixed: one suggestions read whatever their number',
      () async {
        for (var i = 2; i < 40; i += 1) {
          backend.suggestions.add(
            FakeSuggestion(index: i, accountId: _account, description: 'S$i'),
          );
        }
        final value = await loaded();
        expect(value.suggestions, hasLength(39));
        expect(
          backend.calls,
          hasLength(4),
        ); // accounts, rules, month, suggestions
      },
    );

    test('reading, refreshing and paging never write anything', () async {
      await loaded();
      await controller().refresh();
      await controller().nextMonth();
      expect(backend.totalWrites, 0);
      expect(backend.acceptCalls + backend.dismissCalls, 0);
      expect(backend.rules, isEmpty);
      expect(backend.ledger, isEmpty);
      expect(backend.occurrences, isEmpty);
    });

    test(
      'a failing suggestions read never hides or distrusts the rules',
      () async {
        start(_backend(withRule: true));
        backend.suggestionsStatus = 503;
        final value = await loaded();
        expect(value.phase, FinancialLoadPhase.loaded);
        expect(value.trusted, isTrue);
        expect(value.suggestionsUnavailable, isTrue);
        expect(value.suggestions, isEmpty);
        expect(value.recurrences, hasLength(1));
        // Writes on the rules stay available.
        expect(
          (await controller().pause(backend.rules.single.id)).outcome,
          FinancialRecurrenceActionOutcome.paused,
        );
      },
    );

    test(
      'an invalid or throwing suggestions answer is just unavailable',
      () async {
        backend.suggestionsBodyOverride = '{"items":[]}';
        expect((await loaded()).suggestionsUnavailable, isTrue);
        start(_backend());
        backend.suggestionsThrows = true;
        expect((await loaded()).suggestionsUnavailable, isTrue);
      },
    );

    test('a lost session on the suggestions read blocks the screen', () async {
      backend.suggestionsStatus = 401;
      expect((await loaded()).phase, FinancialLoadPhase.authenticationRequired);
    });

    test('a later successful read recovers the section', () async {
      backend.suggestionsStatus = 503;
      expect((await loaded()).suggestionsUnavailable, isTrue);
      backend.suggestionsStatus = null;
      await controller().refresh();
      expect(state().suggestionsUnavailable, isFalse);
      expect(state().suggestions, hasLength(1));
    });
  });

  group('accept', () {
    test(
      'creates exactly one recurrence, no occurrence and no Movement',
      () async {
        await loaded();
        final before = backend.balanceOf(_account);
        final result = await controller().acceptSuggestion(_accept());
        expect(
          result.outcome,
          FinancialRecurrenceActionOutcome.suggestionAccepted,
        );
        expect(result.reconciled, isTrue);
        expect(backend.acceptCalls, 1);
        expect(backend.rules, hasLength(1));
        expect(backend.rules.single.effect, 'EXPENSE');
        expect(backend.rules.single.accountId, _account);
        expect(backend.occurrences, isEmpty);
        expect(backend.ledger, isEmpty);
        expect(backend.balanceOf(_account), before);
        // One canonical re-read replaced the state: the rule is there, the
        // suggestion is gone.
        expect(state().recurrences, hasLength(1));
        expect(state().suggestions, isEmpty);
        expect(backend.suggestionReads, 2);
      },
    );

    test(
      'nothing is optimistic: the suggestion stays until the server answers',
      () async {
        await loaded();
        final gate = Completer<void>();
        backend.writeGate = gate;
        final pending = controller().acceptSuggestion(_accept());
        await Future<void>.delayed(Duration.zero);
        expect(state().mutationInFlight, isTrue);
        expect(state().suggestions, hasLength(1));
        expect(state().recurrences, isEmpty);
        // Another write is refused while one is in flight (no request).
        expect(
          (await controller().dismissSuggestion(_fingerprint)).outcome,
          FinancialRecurrenceActionOutcome.notAllowed,
        );
        gate.complete();
        expect(
          (await pending).outcome,
          FinancialRecurrenceActionOutcome.suggestionAccepted,
        );
        expect(backend.dismissCalls, 0);
      },
    );

    test(
      'an ambiguous answer is never resent and the screen is read again',
      () async {
        await loaded();
        backend.writeCommitsThenFails = true;
        final first = await controller().acceptSuggestion(_accept());
        expect(first.outcome, FinancialRecurrenceActionOutcome.unknownOutcome);
        expect(backend.acceptCalls, 1); // never automatic
        // The server did commit, and the canonical re-read says so.
        expect(backend.rules, hasLength(1));
        expect(state().suggestions, isEmpty);
        expect(state().recurrences, hasLength(1));
      },
    );

    test(
      'an identical retry of an unconfirmed attempt reuses its own key',
      () async {
        await loaded();
        backend.writeStatus = 503;
        final input = _accept();
        final first = await controller().acceptSuggestion(input);
        expect(first.outcome, FinancialRecurrenceActionOutcome.unknownOutcome);
        backend.writeStatus = null;
        final second = await controller().acceptSuggestion(
          _accept(), // the same material, a new object
        );
        expect(
          second.outcome,
          FinancialRecurrenceActionOutcome.suggestionAccepted,
        );
        expect(backend.acceptCalls, 2);
        final keys = backend.writeBodies
            .map((body) => body['idempotencyKey'])
            .toSet();
        expect(keys, hasLength(1)); // same key both times
        expect(backend.rules, hasLength(1));
      },
    );

    test(
      'a definite failure drops the key: the next attempt gets a new one',
      () async {
        await loaded();
        backend.suggestions.single.status = 'DISMISSED';
        final first = await controller().acceptSuggestion(_accept());
        expect(
          first.outcome,
          FinancialRecurrenceActionOutcome.suggestionConflict,
        );
        backend.suggestions.single.status =
            'OPEN'; // the user changed their mind
        await controller().refresh();
        final second = await controller().acceptSuggestion(_accept());
        expect(
          second.outcome,
          FinancialRecurrenceActionOutcome.suggestionAccepted,
        );
        final keys = backend.writeBodies
            .map((b) => b['idempotencyKey'])
            .toList();
        expect(keys, hasLength(2));
        expect(
          keys.toSet(),
          hasLength(2),
        ); // never the key of a refused attempt
      },
    );

    test('a changed request after an ambiguous one gets a new key', () async {
      await loaded();
      backend.writeStatus = 503;
      await controller().acceptSuggestion(_accept());
      backend.writeStatus = null;
      await controller().acceptSuggestion(_accept(amount: '50'));
      final keys = backend.writeBodies.map((b) => b['idempotencyKey']).toList();
      expect(keys, hasLength(2));
      expect(keys.toSet(), hasLength(2));
    });

    test(
      'a 409 is a conflict notice: nothing re-applied, nothing resent',
      () async {
        await loaded();
        backend.suggestions.single.status = 'DISMISSED'; // decided elsewhere
        final result = await controller().acceptSuggestion(_accept());
        expect(
          result.outcome,
          FinancialRecurrenceActionOutcome.suggestionConflict,
        );
        expect(state().conflictNotice, isTrue);
        expect(backend.acceptCalls, 1);
        expect(backend.rules, isEmpty);
        expect(state().suggestions, isEmpty); // re-read shows the current state
      },
    );

    test(
      'a member who does not own the account cannot send an accept',
      () async {
        start(_backend(operatorId: _otherOperator));
        final value = await loaded();
        expect(value.suggestions.single.canAccept, isFalse);
        final result = await controller().acceptSuggestion(_accept());
        expect(result.outcome, FinancialRecurrenceActionOutcome.notAllowed);
        expect(backend.acceptCalls, 0);
      },
    );

    test(
      'an account or currency other than the suggestion is refused locally',
      () async {
        await loaded();
        for (final input in [
          _accept(account: recurrenceTestAccountId(2)),
          _accept(currency: 'USD'),
          _accept(fingerprint: suggestionTestFingerprint(9)),
        ]) {
          expect(
            (await controller().acceptSuggestion(input)).outcome,
            FinancialRecurrenceActionOutcome.notAllowed,
          );
        }
        expect(backend.acceptCalls, 0);
      },
    );

    test('a 403 from the server is read-only, not a lost session', () async {
      await loaded();
      backend.writeStatus = 403;
      final result = await controller().acceptSuggestion(_accept());
      expect(result.outcome, FinancialRecurrenceActionOutcome.readOnly);
      expect(state().isLoaded, isTrue);
    });

    test('an invalid 2xx answer is unknown and nothing is resent', () async {
      await loaded();
      backend.writeBodyOverride = '{"recurrence":{},"decision":{}}';
      final result = await controller().acceptSuggestion(_accept());
      expect(result.outcome, FinancialRecurrenceActionOutcome.unknownOutcome);
      expect(backend.acceptCalls, 1);
    });
  });

  group('dismiss', () {
    test('is one POST, personal and creates nothing', () async {
      await loaded();
      final result = await controller().dismissSuggestion(_fingerprint);
      expect(
        result.outcome,
        FinancialRecurrenceActionOutcome.suggestionDismissed,
      );
      expect(backend.dismissCalls, 1);
      expect(backend.rules, isEmpty);
      expect(backend.ledger, isEmpty);
      expect(backend.occurrences, isEmpty);
      expect(state().suggestions, isEmpty);
    });

    test('a 409 is explained and the suggestions are read again', () async {
      await loaded();
      backend.suggestions.single.status = 'ACCEPTED';
      final result = await controller().dismissSuggestion(_fingerprint);
      expect(
        result.outcome,
        FinancialRecurrenceActionOutcome.suggestionConflict,
      );
      expect(state().conflictNotice, isTrue);
      expect(backend.dismissCalls, 1);
    });

    test('an unknown suggestion is refused locally', () async {
      await loaded();
      final result = await controller().dismissSuggestion(
        suggestionTestFingerprint(9),
      );
      expect(result.outcome, FinancialRecurrenceActionOutcome.notAllowed);
      expect(backend.dismissCalls, 0);
    });

    test('a transport failure is unknown and never retried', () async {
      await loaded();
      backend.writeThrows = true;
      final result = await controller().dismissSuggestion(_fingerprint);
      expect(result.outcome, FinancialRecurrenceActionOutcome.unknownOutcome);
      expect(backend.dismissCalls, 1);
    });

    test('a non-owner may dismiss (it is personal) but not accept', () async {
      start(_backend(operatorId: _otherOperator));
      await loaded();
      expect(
        (await controller().dismissSuggestion(_fingerprint)).outcome,
        FinancialRecurrenceActionOutcome.suggestionDismissed,
      );
    });
  });
}
