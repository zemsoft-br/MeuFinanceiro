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

/// A window that crosses the reference date (2026-10-10).
final _october = FinancialCashFlowQuery(
  from: '2026-10-01',
  through: '2026-10-31',
);

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

    test('a relative window sends days and never a client date', () {
      expect(FinancialCashFlowQuery(days: 7).path, 'finance/cash-flow?days=7');
      expect(
        FinancialCashFlowQuery(from: '2026-10-01', days: 92).path,
        'finance/cash-flow?from=2026-10-01&days=92',
      );
      for (final days in [0, -1, 93]) {
        expect(
          () => FinancialCashFlowQuery(days: days),
          throwsFormatException,
          reason: '$days',
        );
      }
      // days and through are exclusive, as on the server.
      expect(
        () => FinancialCashFlowQuery(through: '2026-10-20', days: 7),
        throwsFormatException,
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
        expect(group.risk!.firstNegativeDate, '2026-10-20');
        expect(group.risk!.evaluatedDays, 30);
        expect(group.historicalRisk, isNull);
        expect(group.days.every((day) => day.anchored), isTrue);
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
        query: FinancialCashFlowQuery(
          from: '2026-09-01',
          through: '2026-09-30',
        ),
      );
      expect(cashFlow.isHistorical, isTrue);
      final group = cashFlow.groups.single;
      expect(
        group.projectionStatus,
        FinancialCashFlowProjectionStatus.notApplicable,
      );
      // Nothing to forecast: only the realized history is evaluated.
      expect(group.risk, isNull);
      expect(group.historicalRisk!.evaluatedDays, 30);
      expect(group.days.any((day) => day.projected), isFalse);
    });

    test('a mixed window splits history from the forecast', () async {
      // Negative on 2026-10-03 only (realized), positive afterwards.
      final cashFlow = await _read(
        cashFlowResponse(
          from: '2026-10-01',
          days: 31,
          groups: [
            cashFlowGroup(
              from: '2026-10-01',
              days: 31,
              events: const [],
              firstNegative: null,
              closing: (date) => date == '2026-10-03' ? '-10' : '100',
            ),
          ],
        ),
        query: _october,
      );
      final group = cashFlow.groups.single;
      expect(group.historicalRisk!.firstNegativeDate, '2026-10-03');
      expect(group.historicalRisk!.evaluatedDays, 9);
      expect(group.risk!.firstNegativeDate, isNull);
      expect(group.risk!.evaluatedDays, 22);
    });

    test('a late opening balance leaves earlier days unanchored', () async {
      final cashFlow = await _read(
        cashFlowResponse(
          from: '2026-10-01',
          days: 31,
          groups: [
            cashFlowGroup(
              from: '2026-10-01',
              days: 31,
              events: const [],
              firstNegative: null,
              anchoredFrom: '2026-10-12',
              status: 'INCOMPLETE',
              issues: [
                {
                  'code': 'OPENING_BALANCE_AFTER_WINDOW_START',
                  'severity': 'INCOMPLETE',
                  'count': 1,
                  'accountIds': [cashFlowCheckingId],
                },
              ],
            ),
          ],
        ),
        query: _october,
      );
      final group = cashFlow.groups.single;
      // No past day is anchored: the history is not assessable at all, and the
      // forecast covers only the 20 days from the opening balance on.
      expect(group.historicalRisk, isNull);
      expect(group.risk!.evaluatedDays, 20);
      expect(group.accounts.single.historicalRisk, isNull);
      expect(group.accounts.single.anchoredOn('2026-10-11'), isFalse);
      expect(group.accounts.single.anchoredOn('2026-10-12'), isTrue);
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
      // A relative request answered with another length.
      await expectLater(
        _read(cashFlowResponse(), query: FinancialCashFlowQuery(days: 7)),
        throwsFormatException,
      );
      // The default window starts at the server reference date.
      await expectLater(
        _read(
          cashFlowResponse(
            from: '2026-10-01',
            groups: [cashFlowGroup(from: '2026-10-01')],
          ),
        ),
        throwsFormatException,
      );
      final relative = await _read(
        cashFlowEcho(Uri.parse('http://x/?days=7')),
        query: FinancialCashFlowQuery(days: 7),
      );
      expect(relative.days, 7);
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
      'risk without evaluatedDays': (root) =>
          (_group(root)['risk']! as Map).remove('evaluatedDays'),
      'evaluatedDays different from the evaluated days': (root) =>
          (_group(root)['risk']! as Map)['evaluatedDays'] = 29,
      'risk missing where days are evaluable': (root) =>
          _group(root)['risk'] = null,
      'historical risk without any past day': (root) =>
          _group(root)['historicalRisk'] = _group(root)['risk'],
      'risk first deficit on a non-negative day': (root) =>
          (_group(root)['risk']! as Map)['firstNegativeDate'] = '2026-10-11',
      'missing anchored flag': (root) {
        final days = _group(root)['days']! as List;
        (days.first! as Map).remove('anchored');
      },
      'anchored flag contradicting the opening balance': (root) {
        final days = _group(root)['days']! as List;
        (days.first! as Map)['anchored'] = false;
      },
      'projected flag contradicting the date': (root) {
        final days = _group(root)['days']! as List;
        (days.first! as Map)['projected'] = false;
      },
      'account risk over days it did not evaluate': (root) {
        final accounts = _group(root)['accounts']! as List;
        ((accounts.first! as Map)['risk']! as Map)['evaluatedDays'] = 31;
      },
      'account historical risk without any past day': (root) {
        final accounts = _group(root)['accounts']! as List;
        final account = accounts.first! as Map;
        account['historicalRisk'] = account['risk'];
      },
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

    test('a past deficit reported as a future risk is rejected', () async {
      Map<String, Object?> mixed() =>
          jsonDecode(
                jsonEncode(
                  cashFlowResponse(
                    from: '2026-10-01',
                    days: 31,
                    groups: [
                      cashFlowGroup(
                        from: '2026-10-01',
                        days: 31,
                        events: const [],
                        firstNegative: null,
                        closing: (date) => date == '2026-10-03' ? '-10' : '100',
                      ),
                    ],
                  ),
                ),
              )
              as Map<String, Object?>;
      final query = FinancialCashFlowQuery(
        from: '2026-10-01',
        through: '2026-10-31',
      );
      expect((await _read(mixed(), query: query)).groups, hasLength(1));

      final group = mixed();
      final risk = _group(group)['risk']! as Map;
      risk['firstNegativeDate'] = '2026-10-03';
      risk['negativeDays'] = 1;
      await expectLater(_read(group, query: query), throwsFormatException);

      final account = mixed();
      final summary =
          ((_group(account)['accounts']! as List).first! as Map)['risk']!
              as Map;
      summary['firstNegativeDate'] = '2026-10-03';
      summary['negativeDays'] = 1;
      await expectLater(_read(account, query: query), throwsFormatException);
    });

    test('a risk over pre-anchor days is rejected', () async {
      final root =
          jsonDecode(
                jsonEncode(
                  cashFlowResponse(
                    groups: [
                      cashFlowGroup(
                        anchoredFrom: null,
                        status: 'INCOMPLETE',
                        issues: [
                          {
                            'code': 'OPENING_BALANCE_MISSING',
                            'severity': 'INCOMPLETE',
                            'count': 1,
                            'accountIds': [cashFlowCheckingId],
                          },
                        ],
                      ),
                    ],
                  ),
                ),
              )
              as Map<String, Object?>;
      final parsed = await _read(root);
      // Not assessable is null, never a "safe" risk.
      expect(parsed.groups.single.risk, isNull);
      expect(parsed.groups.single.accounts.single.risk, isNull);

      _group(root)['risk'] = cashFlowRisk(
        minimum: '-300',
        minimumDate: '2026-10-20',
        firstNegative: '2026-10-20',
        negativeDays: 20,
      );
      await expectLater(_read(root), throwsFormatException);
    });

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

    test('every issue code and severity of the contract is accepted', () {
      // OPENING_BALANCE_AFTER_WINDOW_START is longer than 32 characters.
      for (final code in FinancialCashFlowIssueCode.values) {
        expect(FinancialCashFlowIssueCode.parse(code.wireValue), code);
      }
      for (final severity in FinancialCashFlowIssueSeverity.values) {
        expect(
          FinancialCashFlowIssueSeverity.parse(severity.wireValue),
          severity,
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
