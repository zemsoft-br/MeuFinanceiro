import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/features/finance/financial_cash_flow_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

import '../../support/fake_cash_flow_backend.dart';

({ProviderContainer container, FinancialCashFlowController controller})
_harness(FakeCashFlowBackend backend) {
  final container = ProviderContainer(
    overrides: [financialCoreApiProvider.overrideWithValue(backend.api)],
  );
  addTearDown(container.dispose);
  container.listen(financialCashFlowControllerProvider, (_, _) {});
  return (
    container: container,
    controller: container.read(financialCashFlowControllerProvider.notifier),
  );
}

void main() {
  test('load reads accounts and the projection with server defaults', () async {
    final backend = FakeCashFlowBackend();
    final h = _harness(backend);

    expect(await h.controller.load(), isTrue);

    final state = h.container.read(financialCashFlowControllerProvider);
    expect(state.phase, FinancialLoadPhase.loaded);
    expect(state.group!.currency, 'BRL');
    expect(state.accounts, hasLength(1));
    expect(backend.cashFlowCalls.single.query, isEmpty);
    expect(backend.methods.toSet(), {AuthHttpMethod.get});
  });

  test(
    'relative presets are counted by the server, calendar ones dated',
    () async {
      final backend = FakeCashFlowBackend(cashFlow: cashFlowEcho);
      final h = _harness(backend);
      await h.controller.load();

      expect(
        await h.controller.selectPeriod(FinancialCashFlowPeriod.next90),
        isTrue,
      );
      // No client-side date: the server counts 90 days from its own reference.
      expect(backend.cashFlowCalls.last.queryParameters, {'days': '90'});
      expect(
        h.container.read(financialCashFlowControllerProvider).cashFlow!.through,
        '2027-01-07',
      );
      await h.controller.selectPeriod(FinancialCashFlowPeriod.next7);
      expect(backend.cashFlowCalls.last.queryParameters, {'days': '7'});
      await h.controller.selectPeriod(FinancialCashFlowPeriod.next30);
      expect(backend.cashFlowCalls.last.query, isEmpty);
      await h.controller.selectPeriod(FinancialCashFlowPeriod.currentMonth);
      expect(backend.cashFlowCalls.last.queryParameters, {
        'from': '2026-10-01',
        'through': '2026-10-31',
      });
      await h.controller.selectPeriod(FinancialCashFlowPeriod.next60);
      expect(backend.cashFlowCalls.last.queryParameters, {'days': '60'});
      expect(
        await h.controller.selectCustomWindow('2026-09-15', '2026-10-20'),
        isTrue,
      );
      expect(backend.cashFlowCalls.last.queryParameters, {
        'from': '2026-09-15',
        'through': '2026-10-20',
      });
      // From after the reference date or longer than 92 days: nothing is sent.
      final sent = backend.cashFlowCalls.length;
      expect(
        await h.controller.selectCustomWindow('2026-10-11', '2026-10-20'),
        isFalse,
      );
      expect(
        await h.controller.selectCustomWindow('2026-07-01', '2026-10-10'),
        isFalse,
      );
      expect(backend.cashFlowCalls, hasLength(sent));
    },
  );

  test('account filter sends explicit ids and can be cleared', () async {
    final backend = FakeCashFlowBackend(
      accounts: [
        cashFlowAccountListItem(cashFlowCheckingId),
        cashFlowAccountListItem(
          cashFlowArchivedId,
          name: 'Antiga',
          archived: true,
        ),
      ],
    );
    final h = _harness(backend);
    await h.controller.load();

    await h.controller.toggleAccount(cashFlowCheckingId);
    expect(backend.cashFlowCalls.last.queryParametersAll['accountId'], [
      cashFlowCheckingId,
    ]);
    // An id that the server did not list is ignored.
    expect(await h.controller.toggleAccount(cashFlowSavingsId), isFalse);
    await h.controller.clearAccounts();
    expect(backend.cashFlowCalls.last.queryParametersAll['accountId'], isNull);
  });

  test(
    'a refused first read still lets the operator narrow and recover',
    () async {
      final backend = FakeCashFlowBackend(
        accounts: [
          cashFlowAccountListItem(cashFlowCheckingId),
          cashFlowAccountListItem(cashFlowSavingsId, name: 'Poupança'),
        ],
        cashFlow: (uri) => uri.queryParametersAll['accountId'] == null
            ? const AuthHttpResponse(statusCode: 422, body: '{}')
            : cashFlowResponse(),
      );
      final h = _harness(backend);

      expect(await h.controller.load(), isFalse);
      var state = h.container.read(financialCashFlowControllerProvider);
      expect(state.failure, FinancialCashFlowFailure.rejected);
      expect(state.cashFlow, isNull);
      expect(state.referenceDate, isNull);
      expect(state.accounts, hasLength(2));
      expect(state.canFilter, isTrue);

      expect(await h.controller.toggleAccount(cashFlowCheckingId), isTrue);
      state = h.container.read(financialCashFlowControllerProvider);
      expect(state.failure, FinancialCashFlowFailure.none);
      expect(state.cashFlow, isNotNull);
      expect(state.referenceDate, '2026-10-10');
    },
  );

  test('a refused first read recovers by a shorter relative window, never by a '
      'guessed date', () async {
    final backend = FakeCashFlowBackend(
      cashFlow: (uri) => uri.queryParameters['days'] == '7'
          ? cashFlowEcho(uri)
          : const AuthHttpResponse(statusCode: 422, body: '{}'),
    );
    final h = _harness(backend);

    expect(await h.controller.load(), isFalse);
    var state = h.container.read(financialCashFlowControllerProvider);
    expect(state.failure, FinancialCashFlowFailure.rejected);
    expect(state.cashFlow, isNull);
    expect(state.canFilter, isTrue);
    // Without a server date the calendar windows are unavailable and send
    // nothing; the relative presets are.
    expect(state.canSelect(FinancialCashFlowPeriod.currentMonth), isFalse);
    expect(state.canSelect(FinancialCashFlowPeriod.custom), isFalse);
    expect(state.canSelect(FinancialCashFlowPeriod.next7), isTrue);
    expect(
      await h.controller.selectPeriod(FinancialCashFlowPeriod.currentMonth),
      isFalse,
    );
    expect(
      await h.controller.selectCustomWindow('2026-10-01', '2026-10-05'),
      isFalse,
    );
    expect(backend.cashFlowCalls, hasLength(1));
    state = h.container.read(financialCashFlowControllerProvider);
    expect(state.period, FinancialCashFlowPeriod.next30);
    expect(state.failure, FinancialCashFlowFailure.rejected);

    expect(
      await h.controller.selectPeriod(FinancialCashFlowPeriod.next7),
      isTrue,
    );
    state = h.container.read(financialCashFlowControllerProvider);
    expect(backend.cashFlowCalls.last.queryParameters, {'days': '7'});
    expect(state.failure, FinancialCashFlowFailure.none);
    expect(state.cashFlow!.days, 7);
    expect(state.referenceDate, '2026-10-10');
    // Now the server date is known: calendar windows become available.
    expect(state.canSelect(FinancialCashFlowPeriod.currentMonth), isTrue);
  });

  test(
    'a refused first read followed by a transport failure is not stuck',
    () async {
      var answer = 422;
      final backend = FakeCashFlowBackend(
        cashFlow: (uri) {
          if (answer == 0) throw StateError('socket closed');
          if (answer == 422) {
            return const AuthHttpResponse(statusCode: 422, body: '{}');
          }
          return cashFlowEcho(uri);
        },
      );
      final h = _harness(backend);
      expect(await h.controller.load(), isFalse);
      answer = 0;
      expect(
        await h.controller.selectPeriod(FinancialCashFlowPeriod.next7),
        isFalse,
      );
      var state = h.container.read(financialCashFlowControllerProvider);
      expect(state.phase, FinancialLoadPhase.temporarilyUnavailable);
      expect(state.cashFlow, isNull);
      answer = 200;
      expect(await h.controller.refresh(), isTrue);
      state = h.container.read(financialCashFlowControllerProvider);
      expect(backend.cashFlowCalls.last.queryParameters, {'days': '7'});
      expect(state.phase, FinancialLoadPhase.loaded);
    },
  );

  test('a mixed window keeps a past deficit out of the future risk', () async {
    // October: negative on the 3rd-5th (realized), positive from then on.
    String closing(String date) =>
        date.compareTo('2026-10-03') >= 0 && date.compareTo('2026-10-05') <= 0
        ? '-50'
        : '400';
    final backend = FakeCashFlowBackend(
      cashFlow: (uri) => uri.queryParameters['from'] == '2026-10-01'
          ? cashFlowResponse(
              from: '2026-10-01',
              days: 31,
              groups: [
                cashFlowGroup(
                  from: '2026-10-01',
                  days: 31,
                  events: const [],
                  firstNegative: null,
                  closing: closing,
                ),
              ],
            )
          : cashFlowEcho(uri),
    );
    final h = _harness(backend);
    await h.controller.load();
    expect(
      await h.controller.selectPeriod(FinancialCashFlowPeriod.currentMonth),
      isTrue,
    );

    final group = h.container.read(financialCashFlowControllerProvider).group!;
    expect(group.risk!.firstNegativeDate, isNull);
    expect(group.risk!.evaluatedDays, 22);
    expect(group.historicalRisk!.firstNegativeDate, '2026-10-03');
    expect(group.historicalRisk!.negativeDays, 3);
    expect(group.historicalRisk!.evaluatedDays, 9);
    final account = group.accounts.single;
    expect(account.risk!.firstNegativeDate, isNull);
    expect(account.historicalRisk!.firstNegativeDate, '2026-10-03');
  });

  test('days before a late opening balance are never evaluated', () async {
    final backend = FakeCashFlowBackend(
      cashFlow: (uri) => uri.queryParameters['from'] == '2026-10-01'
          ? cashFlowResponse(
              from: '2026-10-01',
              days: 31,
              groups: [
                cashFlowGroup(
                  from: '2026-10-01',
                  days: 31,
                  events: const [],
                  firstNegative: null,
                  anchoredFrom: '2026-10-05',
                  status: 'INCOMPLETE',
                  issues: [
                    {
                      'code': 'OPENING_BALANCE_AFTER_WINDOW_START',
                      'severity': 'INCOMPLETE',
                      'count': 1,
                      'accountIds': [cashFlowCheckingId],
                    },
                  ],
                  // Before the anchor the balance starts from an assumed zero.
                  closing: (date) =>
                      date.compareTo('2026-10-05') < 0 ? '-100' : '500',
                ),
              ],
            )
          : cashFlowEcho(uri),
    );
    final h = _harness(backend);
    await h.controller.load();
    await h.controller.selectPeriod(FinancialCashFlowPeriod.currentMonth);

    var group = h.container.read(financialCashFlowControllerProvider).group!;
    expect(
      group.projectionStatus,
      FinancialCashFlowProjectionStatus.incomplete,
    );
    expect(group.days.first.anchored, isFalse);
    expect(group.days.first.negative, isTrue);
    expect(group.days[4].anchored, isTrue);
    // The pre-anchor "deficit" is not evidence: 5 anchored past days, none
    // negative.
    expect(group.historicalRisk!.evaluatedDays, 5);
    expect(group.historicalRisk!.firstNegativeDate, isNull);
    expect(group.risk!.evaluatedDays, 22);

    // Recovery: a window after the anchor is complete again.
    await h.controller.selectPeriod(FinancialCashFlowPeriod.next30);
    group = h.container.read(financialCashFlowControllerProvider).group!;
    expect(group.projectionStatus, FinancialCashFlowProjectionStatus.complete);
    expect(group.days.every((day) => day.anchored), isTrue);
  });

  test('a 422 refusal is explicit and shows no stale figures', () async {
    var refuse = false;
    final backend = FakeCashFlowBackend(
      cashFlow: (_) => refuse
          ? const AuthHttpResponse(statusCode: 422, body: '{}')
          : cashFlowResponse(),
    );
    final h = _harness(backend);
    await h.controller.load();
    refuse = true;

    expect(await h.controller.refresh(), isFalse);

    var state = h.container.read(financialCashFlowControllerProvider);
    expect(state.failure, FinancialCashFlowFailure.rejected);
    expect(state.cashFlow, isNull);
    // The operator is never stuck: filters stay usable after a refusal.
    expect(state.canFilter, isTrue);
    refuse = false;
    expect(
      await h.controller.selectPeriod(FinancialCashFlowPeriod.next30),
      isTrue,
    );
    state = h.container.read(financialCashFlowControllerProvider);
    expect(state.failure, FinancialCashFlowFailure.none);
    expect(state.cashFlow, isNotNull);
  });

  test(
    'a failed refresh keeps the last canonical read and marks it stale',
    () async {
      var fail = false;
      final backend = FakeCashFlowBackend(
        cashFlow: (_) => fail
            ? const AuthHttpResponse(statusCode: 503, body: '{}')
            : cashFlowResponse(),
      );
      final h = _harness(backend);
      await h.controller.load();
      fail = true;

      expect(await h.controller.refresh(), isFalse);
      var state = h.container.read(financialCashFlowControllerProvider);
      expect(state.failure, FinancialCashFlowFailure.staleAfterRefresh);
      expect(state.cashFlow, isNotNull);
      expect(state.phase, FinancialLoadPhase.loaded);

      fail = false;
      expect(await h.controller.refresh(), isTrue);
      state = h.container.read(financialCashFlowControllerProvider);
      expect(state.failure, FinancialCashFlowFailure.none);
      // Only reads, one per request: no automatic retry.
      expect(backend.cashFlowCalls, hasLength(3));
    },
  );

  test('a transport failure is unavailable and recovers on refresh', () async {
    var broken = true;
    final backend = FakeCashFlowBackend(
      cashFlow: (_) {
        if (broken) throw StateError('socket closed');
        return cashFlowResponse();
      },
    );
    final h = _harness(backend);

    expect(await h.controller.load(), isFalse);
    expect(
      h.container.read(financialCashFlowControllerProvider).phase,
      FinancialLoadPhase.temporarilyUnavailable,
    );
    broken = false;
    expect(await h.controller.refresh(), isTrue);
    expect(
      h.container.read(financialCashFlowControllerProvider).phase,
      FinancialLoadPhase.loaded,
    );
    expect(backend.cashFlowCalls, hasLength(2));
  });

  test('an invalid response on first load shows no data', () async {
    final backend = FakeCashFlowBackend(cashFlow: (_) => {'groups': 'x'});
    final h = _harness(backend);
    expect(await h.controller.load(), isFalse);
    final state = h.container.read(financialCashFlowControllerProvider);
    expect(state.phase, FinancialLoadPhase.invalidResponse);
    expect(state.cashFlow, isNull);
  });

  test('session, permission and visibility failures map to phases', () async {
    for (final (status, phase) in [
      (401, FinancialLoadPhase.authenticationRequired),
      (403, FinancialLoadPhase.forbidden),
      (404, FinancialLoadPhase.notFound),
      (409, FinancialLoadPhase.primaryResidenceRequired),
    ]) {
      final backend = FakeCashFlowBackend(
        cashFlow: (_) => AuthHttpResponse(statusCode: status, body: '{}'),
      );
      final h = _harness(backend);
      await h.controller.load();
      expect(
        h.container.read(financialCashFlowControllerProvider).phase,
        phase,
        reason: '$status',
      );
    }
  });

  test('no visible account is the explicit empty state', () async {
    final backend = FakeCashFlowBackend(
      accounts: const [],
      cashFlow: (_) => cashFlowResponse(groups: const []),
    );
    final h = _harness(backend);
    await h.controller.load();
    expect(
      h.container.read(financialCashFlowControllerProvider).phase,
      FinancialLoadPhase.empty,
    );
  });

  test('a slower earlier read never overwrites a newer one', () async {
    final first = Completer<AuthHttpResponse>();
    var call = 0;
    final backend = FakeCashFlowBackend(
      cashFlow: (_) => ++call == 1 ? first.future : cashFlowResponse(),
    );
    final h = _harness(backend);

    final slow = h.controller.load();
    await pumpEventQueue();
    expect(backend.cashFlowCalls, hasLength(1));
    expect(await h.controller.refresh(), isTrue);
    first.complete(const AuthHttpResponse(statusCode: 503, body: '{}'));

    expect(await slow, isFalse);
    final state = h.container.read(financialCashFlowControllerProvider);
    expect(state.phase, FinancialLoadPhase.loaded);
    expect(state.failure, FinancialCashFlowFailure.none);
    expect(state.cashFlow, isNotNull);
  });

  test('currency selection only switches between returned groups', () async {
    final backend = FakeCashFlowBackend(
      accounts: [
        cashFlowAccountListItem(cashFlowCheckingId),
        cashFlowAccountListItem(
          cashFlowSavingsId,
          name: 'Euro',
          currency: 'EUR',
        ),
      ],
      cashFlow: (_) => cashFlowResponse(
        groups: [
          cashFlowGroup(),
          cashFlowGroup(
            currency: 'EUR',
            accounts: [
              cashFlowAccountSummary(
                cashFlowSavingsId,
                name: 'Euro',
                currency: 'EUR',
                firstNegative: '2026-10-20',
              ),
            ],
            events: const [],
          ),
        ],
      ),
    );
    final h = _harness(backend);
    await h.controller.load();
    expect(
      h.container.read(financialCashFlowControllerProvider).group!.currency,
      'BRL',
    );
    h.controller.selectCurrency('EUR');
    expect(
      h.container.read(financialCashFlowControllerProvider).group!.currency,
      'EUR',
    );
    h.controller.selectCurrency('USD');
    expect(
      h.container.read(financialCashFlowControllerProvider).group!.currency,
      'EUR',
    );
    expect(backend.cashFlowCalls, hasLength(1));
  });

  test('calendar helpers handle month ends and leap years', () {
    expect(financialCashFlowMonthEnd('2028-02-10'), '2028-02-29');
    expect(financialCashFlowMonthEnd('2026-12-31'), '2026-12-31');
  });
}
