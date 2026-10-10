import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_cash_flow_backend.dart';

Future<FinancialCashFlow> _read(Object? body, {FinancialCashFlowQuery? query}) {
  final backend = FakeCashFlowBackend(cashFlow: (_) => body);
  return backend.api.getCashFlow(query ?? FinancialCashFlowQuery());
}

Map<String, Object?> _mutable() =>
    jsonDecode(jsonEncode(cashFlowResponse())) as Map<String, Object?>;

Map<String, Object?> _group(Map<String, Object?> root) =>
    (root['groups']! as List).first as Map<String, Object?>;

List<Object?> _events(Map<String, Object?> root) =>
    _group(root)['events']! as List<Object?>;

void main() {
  group('query', () {
    test('defaults keep every server default and the path minimal', () {
      expect(FinancialCashFlowQuery().path, 'finance/cash-flow');
    });

    test('explicit filters are canonical and repeat accountId', () {
      final query = FinancialCashFlowQuery(
        from: '2026-10-01',
        through: '2026-12-31',
        accountIds: [cashFlowCheckingId.toUpperCase(), cashFlowSavingsId],
        currency: 'BRL',
      );
      expect(
        query.path,
        'finance/cash-flow?from=2026-10-01&through=2026-12-31'
        '&accountId=$cashFlowCheckingId&accountId=$cashFlowSavingsId'
        '&currency=BRL',
      );
    });

    test('invalid windows and selections never leave the client', () {
      expect(
        () => FinancialCashFlowQuery(from: '2026-10-10', through: '2026-10-09'),
        throwsFormatException,
      );
      expect(
        () => FinancialCashFlowQuery(from: '2026-10-10', through: '2027-01-10'),
        throwsFormatException,
      );
      expect(
        () => FinancialCashFlowQuery(from: '2026-02-30'),
        throwsFormatException,
      );
      expect(
        () => FinancialCashFlowQuery(
          accountIds: [cashFlowCheckingId, cashFlowCheckingId],
        ),
        throwsFormatException,
      );
      expect(
        () => FinancialCashFlowQuery(currency: 'brl'),
        throwsFormatException,
      );
      expect(
        () => FinancialCashFlowQuery(
          accountIds: [
            for (var i = 0; i < 51; i++)
              '41000000-0000-4000-8000-${i.toString().padLeft(12, '0')}',
          ],
        ),
        throwsFormatException,
      );
      // 92 days is the maximum and is accepted.
      expect(
        FinancialCashFlowQuery(from: '2026-07-01', through: '2026-09-30').path,
        contains('through=2026-09-30'),
      );
    });
  });

  group('response', () {
    test(
      'a contract-shaped response is parsed without any arithmetic',
      () async {
        final cashFlow = await _read(cashFlowResponse());

        expect(cashFlow.referenceDate, '2026-10-10');
        expect(cashFlow.days, 30);
        expect(cashFlow.isHistorical, isFalse);
        expect(cashFlow.excludedSources, contains('BUDGETS'));
        final group = cashFlow.groups.single;
        expect(group.currency, 'BRL');
        expect(group.balanceAtReference.amount, '2200');
        expect(group.closingBalance.amount, '-300');
        expect(group.risk.firstNegativeDate, '2026-10-20');
        expect(group.days, hasLength(30));
        expect(group.days.first.hasActivity, isTrue);
        expect(group.days[1].hasActivity, isFalse);
        final kinds = group.events.map((event) => event.kind).toList();
        expect(kinds, [
          FinancialCashFlowEventKind.realized,
          FinancialCashFlowEventKind.realized,
          FinancialCashFlowEventKind.realized,
          FinancialCashFlowEventKind.expectedOccurrence,
        ]);
        expect(group.events[2].transferId, cashFlowTransferId);
        expect(group.events[3].occurrenceId, cashFlowOccurrenceId);
        expect(group.events[3].expectedAmount!.amount, '-2500');
        expect(group.account(cashFlowCheckingId)!.name, 'Corrente');
      },
    );

    test('a historical window is recognised from the server dates', () async {
      final cashFlow = await _read(
        cashFlowResponse(
          from: '2026-09-01',
          days: 30,
          groups: [
            cashFlowGroup(
              from: '2026-09-01',
              days: 30,
              events: const [],
              status: 'NOT_APPLICABLE',
              firstNegative: null,
            ),
          ],
        ),
      );
      expect(cashFlow.isHistorical, isTrue);
      expect(
        cashFlow.groups.single.projectionStatus,
        FinancialCashFlowProjectionStatus.notApplicable,
      );
    });

    test('a window different from the request is ambiguous', () async {
      await expectLater(
        _read(
          cashFlowResponse(),
          query: FinancialCashFlowQuery(
            from: '2026-10-01',
            through: '2026-10-30',
          ),
        ),
        throwsFormatException,
      );
    });

    test('an account outside the requested selection is refused', () async {
      await expectLater(
        _read(
          cashFlowResponse(),
          query: FinancialCashFlowQuery(accountIds: [cashFlowSavingsId]),
        ),
        throwsFormatException,
      );
    });

    final mutations = <String, void Function(Map<String, Object?>)>{
      'unknown top-level key': (root) => root['extra'] = 1,
      'missing groups': (root) => root.remove('groups'),
      'days do not match the window': (root) => root['days'] = 29,
      'from after the reference date': (root) => root['from'] = '2026-10-11',
      'money as a JSON number': (root) =>
          _group(root)['closingBalance'] = {'amount': 1.5, 'currency': 'BRL'},
      'money in another currency': (root) =>
          _group(root)['closingBalance'] = cashFlowMoney('1', 'USD'),
      'money with too many decimals': (root) =>
          _group(root)['startingBalance'] = cashFlowMoney('1.123456789'),
      'unknown event kind': (root) =>
          (_events(root).first! as Map)['kind'] = 'GUESS',
      'events out of order': (root) {
        final events = _events(root);
        final last = events.removeLast();
        events.insert(0, last);
      },
      'event outside the window': (root) =>
          (_events(root).first! as Map)['date'] = '2026-11-09',
      'event of an unknown account': (root) =>
          (_events(root).first! as Map)['accountId'] = cashFlowSavingsId,
      'expected event carrying a Movement': (root) =>
          (_events(root).last! as Map)['movementId'] = cashFlowMovementId,
      'expected event without recurrence': (root) =>
          (_events(root).last! as Map)['recurrenceId'] = null,
      'expected occurrence without occurrence id': (root) =>
          (_events(root).last! as Map)['occurrenceId'] = null,
      'overdue flag contradicting the dates': (root) =>
          (_events(root).last! as Map)['overdue'] = true,
      'realized event without Movement': (root) =>
          (_events(root).first! as Map)['movementId'] = null,
      'zero event amount': (root) =>
          (_events(root).first! as Map)['amount'] = cashFlowMoney('0'),
      'days not contiguous': (root) {
        final days = _group(root)['days']! as List;
        (days[3]! as Map)['date'] = '2026-10-14';
      },
      'negative flag contradicting the closing': (root) {
        final days = _group(root)['days']! as List;
        (days.first! as Map)['negative'] = true;
      },
      'complete status with an incomplete issue': (root) =>
          _group(root)['issues'] = [
            {
              'code': 'OPENING_BALANCE_MISSING',
              'severity': 'INCOMPLETE',
              'count': 1,
              'accountIds': [cashFlowCheckingId],
            },
          ],
      'issue naming an unknown account': (root) {
        _group(root)['projectionStatus'] = 'INCOMPLETE';
        _group(root)['issues'] = [
          {
            'code': 'OPENING_BALANCE_MISSING',
            'severity': 'INCOMPLETE',
            'count': 1,
            'accountIds': [cashFlowSavingsId],
          },
        ];
      },
      'unknown issue code': (root) => _group(root)['issues'] = [
        {
          'code': 'SOMETHING_ELSE',
          'severity': 'ATTENTION',
          'count': 1,
          'accountIds': <String>[],
        },
      ],
      'risk without negative days but with a date': (root) =>
          (_group(root)['risk']! as Map)['negativeDays'] = 0,
      'opening flag contradicting its date': (root) {
        final accounts = _group(root)['accounts']! as List;
        (accounts.first! as Map)['hasOpeningBalance'] = false;
      },
      'duplicate currency group': (root) =>
          (root['groups']! as List).add(_group(root)),
    };
    for (final entry in mutations.entries) {
      test('rejects ${entry.key}', () async {
        final root = _mutable();
        entry.value(root);
        await expectLater(_read(root), throwsFormatException);
      });
    }

    test('more events than the contract allows are rejected', () async {
      final events = [
        for (var i = 0; i < financialCashFlowEventsMax + 1; i++)
          cashFlowEvent(
            date: '2026-10-10',
            movementId:
                '44000000-0000-4000-8000-${i.toString().padLeft(12, '0')}',
          ),
      ];
      await expectLater(
        _read(cashFlowResponse(groups: [cashFlowGroup(events: events)])),
        throwsFormatException,
      );
    });

    test('server statuses surface as API exceptions, never as data', () async {
      for (final status in [401, 403, 404, 409, 422, 503]) {
        final backend = FakeCashFlowBackend(
          cashFlow: (_) => AuthHttpResponse(statusCode: status, body: '{}'),
        );
        await expectLater(
          backend.api.getCashFlow(FinancialCashFlowQuery()),
          throwsA(isA<AuthenticatedApiException>()),
        );
      }
    });

    test('a non-JSON body is an invalid response', () async {
      final backend = FakeCashFlowBackend(
        cashFlow: (_) =>
            const AuthHttpResponse(statusCode: 200, body: '<html>'),
      );
      await expectLater(
        backend.api.getCashFlow(FinancialCashFlowQuery()),
        throwsFormatException,
      );
    });
  });
}
