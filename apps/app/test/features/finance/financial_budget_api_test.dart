import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_budget_backend.dart';
import '../../support/fake_finance_backend.dart';

final _market = financeTestCategoryId(1);
final _salary = financeTestCategoryId(2);

FinancialCoreApi _api(FakeAuthTransport transport) => FinancialCoreApi(
  AuthenticatedApiClient(
    transport: transport,
    tokenVault: SessionTokenVault()..store(financeTestToken),
    apiBaseUri: Uri.parse('http://localhost/api/v1/'),
    timeout: const Duration(seconds: 2),
    onUnauthorized: () {},
  ),
);

FakeBudget _budget({int index = 1, String period = '2026-10'}) => FakeBudget(
  index: index,
  period: period,
  lines: [
    FakeBudgetLine(_market, 'EXPENSE', '1000'),
    FakeBudgetLine(_salary, 'INCOME', '5000'),
  ],
);

FinancialBudgetCreateInput _create({
  String period = '2026-10',
  FinancialVisibilityScope scope = FinancialVisibilityScope.household,
  String? key,
}) => FinancialBudgetCreateInput(
  name: 'Outubro',
  visibilityScope: scope,
  currency: 'BRL',
  period: period,
  dateBasis: FinancialBudgetDateBasis.cash,
  idempotencyKey: key,
  lines: [
    FinancialBudgetLineInput(
      categoryId: _market,
      resultEffect: FinancialResultEffect.expense,
      plannedAmount: '1000',
    ),
    FinancialBudgetLineInput(
      categoryId: _salary,
      resultEffect: FinancialResultEffect.income,
      plannedAmount: '5000',
    ),
  ],
);

void main() {
  group('requests', () {
    test('listBudgets asks for exactly one month with GET', () async {
      final backend = FakeBudgetBackend(budgets: [_budget()]);
      final budgets = await _api(backend.transport).listBudgets('2026-10');
      final call = backend.calls.single;
      expect(call.method, AuthHttpMethod.get);
      expect(call.uri.path, '/api/v1/finance/budgets');
      expect(call.uri.queryParameters, {'period': '2026-10'});
      expect(budgets, hasLength(1));
      expect(budgets.single.period, '2026-10');
      expect(budgets.single.canEdit, isTrue);
      expect(budgets.single.lines, hasLength(2));
    });

    test('rejects malformed periods before any request', () async {
      final backend = FakeBudgetBackend();
      for (final period in ['2026-13', '2026-1', '2026-10-01', 'abc', '']) {
        await expectLater(
          _api(backend.transport).listBudgets(period),
          throwsFormatException,
        );
      }
      expect(backend.calls, isEmpty);
    });

    test(
      'create posts the explicit contract with decimal text money',
      () async {
        final backend = FakeBudgetBackend();
        final created = await _api(backend.transport).createBudget(_create());
        final call = backend.calls.single;
        expect(call.method, AuthHttpMethod.post);
        expect(call.uri.path, '/api/v1/finance/budgets');
        final body = jsonDecode(call.body!) as Map<String, dynamic>;
        expect(body.keys.toSet(), {
          'idempotencyKey',
          'name',
          'visibilityScope',
          'currency',
          'period',
          'dateBasis',
          'lines',
        });
        expect(body['visibilityScope'], 'HOUSEHOLD');
        expect(body['dateBasis'], 'CASH');
        expect(body['currency'], 'BRL');
        for (final line in body['lines'] as List<dynamic>) {
          expect((line as Map)['plannedAmount'], isA<String>());
        }
        expect(created.version, 1);
      },
    );

    test('create requires a client-generated UUID v4 idempotency key', () {
      final input = _create();
      expect(
        RegExp(
          r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ).hasMatch(input.idempotencyKey),
        isTrue,
      );
      expect(_create().idempotencyKey, isNot(input.idempotencyKey));
      expect(() => _create(key: 'not-a-uuid'), throwsFormatException);
    });

    test('line order never changes the logical attempt', () {
      final a = _create();
      final reversed = FinancialBudgetCreateInput(
        name: 'Outubro',
        visibilityScope: FinancialVisibilityScope.household,
        currency: 'BRL',
        period: '2026-10',
        dateBasis: FinancialBudgetDateBasis.cash,
        lines: a.lines.reversed.toList(),
      );
      expect(reversed.attemptKey, a.attemptKey);
      expect(
        jsonEncode(reversed.toJson()['lines']),
        jsonEncode(a.toJson()['lines']),
      );
    });

    test('replace sends PUT with expectedVersion and stays strict', () async {
      final backend = FakeBudgetBackend(budgets: [_budget()]);
      final updated = await _api(backend.transport).replaceBudget(
        budgetTestId(1),
        FinancialBudgetReplaceInput(
          expectedVersion: 1,
          name: 'Outubro v2',
          currency: 'BRL',
          lines: [
            FinancialBudgetLineInput(
              categoryId: _market,
              resultEffect: FinancialResultEffect.expense,
              plannedAmount: '900.50',
            ),
          ],
        ),
      );
      final call = backend.calls.single;
      expect(call.method, AuthHttpMethod.put);
      expect(call.uri.path, '/api/v1/finance/budgets/${budgetTestId(1)}');
      final body = jsonDecode(call.body!) as Map<String, dynamic>;
      expect(body['expectedVersion'], 1);
      expect(updated.version, 2);
      expect(updated.lines.single.planned.amount, '900.5');
    });

    test('inputs refuse invalid money, effects, duplicates and sizes', () {
      FinancialBudgetLineInput line(
        String amount, [
        FinancialResultEffect? e,
      ]) => FinancialBudgetLineInput(
        categoryId: _market,
        resultEffect: e ?? FinancialResultEffect.expense,
        plannedAmount: amount,
      );
      for (final bad in [
        '0',
        '0.00',
        '-1',
        '1e3',
        '1,5',
        'abc',
        '',
        '1.123456789',
      ]) {
        expect(() => line(bad), throwsFormatException, reason: bad);
      }
      expect(
        () => line('1', FinancialResultEffect.neutral),
        throwsFormatException,
      );
      FinancialBudgetCreateInput make(List<FinancialBudgetLineInput> lines) =>
          FinancialBudgetCreateInput(
            name: 'x',
            visibilityScope: FinancialVisibilityScope.household,
            currency: 'BRL',
            period: '2026-10',
            dateBasis: FinancialBudgetDateBasis.cash,
            lines: lines,
          );
      expect(() => make([]), throwsFormatException);
      expect(() => make([line('1'), line('2')]), throwsFormatException);
      expect(
        () => make([
          for (var i = 0; i < 101; i += 1)
            FinancialBudgetLineInput(
              categoryId: financeTestCategoryId(i + 10),
              resultEffect: FinancialResultEffect.expense,
              plannedAmount: '1',
            ),
        ]),
        throwsFormatException,
      );
      expect(
        () => FinancialBudgetCreateInput(
          name: 'x',
          visibilityScope: FinancialVisibilityScope.shared,
          currency: 'BRL',
          period: '2026-10',
          dateBasis: FinancialBudgetDateBasis.cash,
          lines: [line('1')],
        ),
        throwsFormatException,
      );
      expect(
        () => FinancialBudgetCreateInput(
          name: 'x',
          visibilityScope: FinancialVisibilityScope.household,
          currency: 'br',
          period: '2026-10',
          dateBasis: FinancialBudgetDateBasis.cash,
          lines: [line('1')],
        ),
        throwsFormatException,
      );
      expect(
        () => FinancialBudgetReplaceInput(
          expectedVersion: 0,
          name: 'x',
          currency: 'BRL',
          lines: [line('1')],
        ),
        throwsFormatException,
      );
    });
  });

  group('responses', () {
    test('summary exposes server-derived values and coverage', () async {
      final backend = FakeBudgetBackend(budgets: [_budget()]);
      backend.realized[budgetTestId(1)] = {
        '$_market|EXPENSE': '300',
        '$_salary|INCOME': '4500',
      };
      backend.coverage[budgetTestId(1)] = (
        expense: 1,
        expenseAmount: '100',
        income: 0,
        incomeAmount: '0',
      );
      final summary = await _api(
        backend.transport,
      ).getBudgetSummary(budgetTestId(1));
      expect(backend.calls.single.uri.path, endsWith('/summary'));
      final market = summary.lines.firstWhere((l) => l.categoryId == _market);
      expect(market.realized.amount, '300');
      expect(market.remaining.amount, '700');
      expect(market.status, FinancialBudgetLineStatus.under);
      expect(market.progressPercent, '30.00');
      final salary = summary.lines.firstWhere((l) => l.categoryId == _salary);
      expect(salary.remaining.amount, '500');
      expect(summary.coverage.unclassifiedExpenseCount, 1);
      expect(summary.coverage.unclassifiedExpenseAmount.amount, '100');
      expect(summary.coverage.isIncomplete, isTrue);
    });

    test(
      'summary keeps negative realized and over status as the server says',
      () async {
        final backend = FakeBudgetBackend(budgets: [_budget()]);
        backend.realized[budgetTestId(1)] = {
          '$_market|EXPENSE': '-300',
          '$_salary|INCOME': '6000',
        };
        final summary = await _api(
          backend.transport,
        ).getBudgetSummary(budgetTestId(1));
        final market = summary.lines.firstWhere((l) => l.categoryId == _market);
        expect(market.realized.amount, '-300');
        expect(market.remaining.amount, '1300');
        expect(market.status, FinancialBudgetLineStatus.under);
        final salary = summary.lines.firstWhere((l) => l.categoryId == _salary);
        expect(salary.status, FinancialBudgetLineStatus.over);
        expect(salary.progressPercent, '120.00');
        expect(summary.coverage.isIncomplete, isFalse);
      },
    );

    test(
      'rejects extra and missing keys, SHARED, bad shapes and mismatches',
      () async {
        final backend = FakeBudgetBackend(budgets: [_budget()]);
        final good = backend.budgetJson(backend.byId(budgetTestId(1))!);
        final mutations = <String, String>{
          'extra key': good.replaceFirst(
            '"canEdit"',
            '"balance":"1","canEdit"',
          ),
          'missing key': good.replaceFirst('"canEdit":true,', ''),
          'shared': good.replaceFirst('"HOUSEHOLD"', '"SHARED"'),
          'period kind': good.replaceFirst('"MONTHLY"', '"WEEKLY"'),
          'not first day': good.replaceFirst('"2026-10-01"', '"2026-10-02"'),
          'version zero': good.replaceFirst('"version":1', '"version":0'),
          'float version': good.replaceFirst('"version":1', '"version":1.5'),
          'can edit text': good.replaceFirst(
            '"canEdit":true',
            '"canEdit":"true"',
          ),
          'zero planned': good.replaceFirst('"amount":"1000"', '"amount":"0"'),
          'negative planned': good.replaceFirst(
            '"amount":"1000"',
            '"amount":"-5"',
          ),
          'numeric planned': good.replaceFirst(
            '"amount":"1000"',
            '"amount":1000',
          ),
          'planned currency': good.replaceFirst(
            '"planned":{"amount":"1000","currency":"BRL"}',
            '"planned":{"amount":"1000","currency":"USD"}',
          ),
          'neutral line': good.replaceFirst('"EXPENSE"', '"NEUTRAL"'),
          'no lines': good.replaceFirst(
            RegExp(r'"lines":\[.*\]\}$'),
            '"lines":[]}',
          ),
        };
        for (final entry in mutations.entries) {
          backend.listBodyOverride = '{"items":[${entry.value}]}';
          await expectLater(
            _api(backend.transport).listBudgets('2026-10'),
            throwsFormatException,
            reason: entry.key,
          );
        }
      },
    );

    test(
      'list rejects duplicates, another month and malformed envelopes',
      () async {
        final backend = FakeBudgetBackend(budgets: [_budget()]);
        final one = backend.budgetJson(backend.byId(budgetTestId(1))!);
        for (final body in [
          '{"items":[$one,$one]}',
          '{"items":[${one.replaceFirst('"periodStart":"2026-10-01"', '"periodStart":"2026-09-01"')}]}',
          '{"items":[],"extra":1}',
          '{}',
          '[]',
          'not json',
        ]) {
          backend.listBodyOverride = body;
          await expectLater(
            _api(backend.transport).listBudgets('2026-10'),
            throwsFormatException,
            reason: body,
          );
        }
      },
    );

    test(
      'summary rejects mismatching lines, amounts, percent and coverage',
      () async {
        final backend = FakeBudgetBackend(budgets: [_budget()]);
        final good = backend.summaryJson(backend.byId(budgetTestId(1))!);
        final mutations = <String, String>{
          'unknown line': good.replaceFirst(
            '"categoryId":"$_market","resultEffect":"EXPENSE","planned":{"amount":"1000"',
            '"categoryId":"${financeTestCategoryId(9)}","resultEffect":"EXPENSE","planned":{"amount":"1000"',
          ),
          'planned drift': good.replaceFirst(
            '"planned":{"amount":"1000","currency":"BRL"},"realized"',
            '"planned":{"amount":"999","currency":"BRL"},"realized"',
          ),
          'status': good.replaceFirst('"status":"UNDER"', '"status":"MAYBE"'),
          'percent': good.replaceFirst(
            '"progressPercent":"0.00"',
            '"progressPercent":"0"',
          ),
          'coverage count': good.replaceFirst(
            '"unclassifiedExpenseCount":0',
            '"unclassifiedExpenseCount":-1',
          ),
          'coverage float': good.replaceFirst(
            '"unclassifiedExpenseCount":0',
            '"unclassifiedExpenseCount":0.5',
          ),
          'coverage currency': good.replaceFirst(
            '"unclassifiedExpenseAmount":{"amount":"0","currency":"BRL"}',
            '"unclassifiedExpenseAmount":{"amount":"0","currency":"USD"}',
          ),
          'extra': good.replaceFirst('"coverage"', '"balance":"1","coverage"'),
        };
        for (final entry in mutations.entries) {
          backend.summaryBodyOverride = entry.value;
          await expectLater(
            _api(backend.transport).getBudgetSummary(budgetTestId(1)),
            throwsFormatException,
            reason: entry.key,
          );
        }
        backend.summaryBodyOverride = null;
        // A summary of another budget is not this budget's summary.
        backend.budgets.add(_budget(index: 2, period: '2026-11'));
        backend.summaryBodyOverride = backend.summaryJson(
          backend.byId(budgetTestId(2))!,
        );
        await expectLater(
          _api(backend.transport).getBudgetSummary(budgetTestId(1)),
          throwsFormatException,
        );
      },
    );

    test(
      'create refuses a response that does not mirror the request',
      () async {
        for (final mutate in <String Function(String)>[
          (json) => json.replaceFirst(
            '"currency":"BRL","periodKind"',
            '"currency":"USD","periodKind"',
          ),
          (json) => json.replaceFirst('"CASH"', '"COMPETENCE"'),
          (json) => json.replaceFirst('"HOUSEHOLD"', '"PERSONAL"'),
          (json) => json.replaceFirst('"amount":"1000"', '"amount":"1001"'),
          (json) => json.replaceFirst(
            '"periodStart":"2026-10-01"',
            '"periodStart":"2026-11-01"',
          ),
        ]) {
          final backend = FakeBudgetBackend();
          backend.postBodyOverride = mutate(
            backend.budgetJson(
              FakeBudget(
                index: 5,
                period: '2026-10',
                lines: [
                  FakeBudgetLine(_market, 'EXPENSE', '1000'),
                  FakeBudgetLine(_salary, 'INCOME', '5000'),
                ],
              ),
            ),
          );
          await expectLater(
            _api(backend.transport).createBudget(_create()),
            throwsFormatException,
          );
        }
      },
    );

    test(
      'replace refuses a response that skips the CAS version or ignores the plan',
      () async {
        final backend = FakeBudgetBackend(budgets: [_budget()]);
        backend.putBodyOverride = backend.budgetJson(
          backend.byId(budgetTestId(1))!,
        );
        await expectLater(
          _api(backend.transport).replaceBudget(
            budgetTestId(1),
            FinancialBudgetReplaceInput(
              expectedVersion: 1,
              name: 'Outubro',
              currency: 'BRL',
              lines: [
                FinancialBudgetLineInput(
                  categoryId: _market,
                  resultEffect: FinancialResultEffect.expense,
                  plannedAmount: '1000',
                ),
                FinancialBudgetLineInput(
                  categoryId: _salary,
                  resultEffect: FinancialResultEffect.income,
                  plannedAmount: '5000',
                ),
              ],
            ),
          ),
          throwsFormatException, // version did not advance
        );
      },
    );

    test('http failures surface as authenticated API exceptions', () async {
      final backend = FakeBudgetBackend(budgets: [_budget()]);
      backend.putStatus = 409;
      await expectLater(
        _api(backend.transport).replaceBudget(
          budgetTestId(1),
          FinancialBudgetReplaceInput(
            expectedVersion: 1,
            name: 'x',
            currency: 'BRL',
            lines: [
              FinancialBudgetLineInput(
                categoryId: _market,
                resultEffect: FinancialResultEffect.expense,
                plannedAmount: '1',
              ),
            ],
          ),
        ),
        throwsA(
          isA<AuthenticatedApiException>().having(
            (e) => e.statusCode,
            'statusCode',
            409,
          ),
        ),
      );
    });
  });
}
