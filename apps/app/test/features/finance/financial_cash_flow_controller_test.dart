import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/features/finance/financial_cash_flow_controller.dart';
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

  test('presets derive the window from the server reference date', () async {
    final backend = FakeCashFlowBackend(
      cashFlow: (uri) {
        final from = uri.queryParameters['from'] ?? '2026-10-10';
        final through = uri.queryParameters['through'];
        final days = through == null
            ? 30
            : DateTime.parse(through).difference(DateTime.parse(from)).inDays +
                  1;
        return cashFlowResponse(
          from: from,
          days: days,
          groups: [
            cashFlowGroup(
              from: from,
              days: days,
              events: const [],
              firstNegative: null,
            ),
          ],
        );
      },
    );
    final h = _harness(backend);
    await h.controller.load();

    await h.controller.selectPeriod(FinancialCashFlowPeriod.next90);
    expect(backend.cashFlowCalls.last.queryParameters, {
      'from': '2026-10-10',
      'through': '2027-01-07',
    });
    await h.controller.selectPeriod(FinancialCashFlowPeriod.currentMonth);
    expect(backend.cashFlowCalls.last.queryParameters, {
      'from': '2026-10-01',
      'through': '2026-10-31',
    });
    await h.controller.selectPeriod(FinancialCashFlowPeriod.next60);
    expect(backend.cashFlowCalls.last.queryParameters['through'], '2026-12-08');
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
  });

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
    expect(financialCashFlowAddDays('2028-02-28', 1), '2028-02-29');
    expect(financialCashFlowAddDays('2027-02-28', 1), '2027-03-01');
    expect(financialCashFlowMonthEnd('2028-02-10'), '2028-02-29');
    expect(financialCashFlowMonthEnd('2026-12-31'), '2026-12-31');
  });
}
