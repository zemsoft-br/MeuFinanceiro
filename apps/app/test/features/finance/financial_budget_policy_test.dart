import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_finance_backend.dart';

const _owner = financeTestOwnerId;
const _other = financeTestOtherOperatorId;

FinancialCategory _category({
  required int index,
  required String name,
  FinancialVisibilityScope scope = FinancialVisibilityScope.household,
  String owner = _owner,
  FinancialCategoryStatus status = FinancialCategoryStatus.active,
}) => FinancialCategory(
  categoryId: financeTestCategoryId(index),
  ownerOperatorId: owner,
  visibilityScope: scope,
  parentId: null,
  name: name,
  status: status,
  createdAt: DateTime.utc(2026, 9),
  updatedAt: DateTime.utc(2026, 9),
  disabledAt: status == FinancialCategoryStatus.disabled
      ? DateTime.utc(2026, 9, 2)
      : null,
);

void main() {
  group('months', () {
    test('current period and labels', () {
      expect(currentFinancialBudgetPeriod(DateTime(2026, 10, 31)), '2026-10');
      expect(currentFinancialBudgetPeriod(DateTime(2026, 1, 1)), '2026-01');
      expect(financialBudgetPeriodLabel('2026-10'), 'outubro de 2026');
      expect(financialBudgetPeriodLabel('2027-03'), 'março de 2027');
    });

    test('shifting crosses year boundaries in both directions', () {
      expect(shiftFinancialBudgetPeriod('2026-12', 1), '2027-01');
      expect(shiftFinancialBudgetPeriod('2027-01', -1), '2026-12');
      expect(shiftFinancialBudgetPeriod('2026-10', 0), '2026-10');
      expect(shiftFinancialBudgetPeriod('2026-10', 14), '2027-12');
      expect(shiftFinancialBudgetPeriod('2026-02', -14), '2024-12');
    });
  });

  group('labels never depend on colour', () {
    test('status text differs for expense and income', () {
      expect(
        financialBudgetStatusLabel(
          FinancialResultEffect.expense,
          FinancialBudgetLineStatus.over,
        ),
        'Estourou o planejado',
      );
      expect(
        financialBudgetStatusLabel(
          FinancialResultEffect.income,
          FinancialBudgetLineStatus.over,
        ),
        'Acima do previsto',
      );
      expect(
        financialBudgetStatusLabel(
          FinancialResultEffect.expense,
          FinancialBudgetLineStatus.at,
        ),
        'No limite',
      );
      expect(
        financialBudgetStatusLabel(
          FinancialResultEffect.expense,
          FinancialBudgetLineStatus.under,
        ),
        'Dentro do planejado',
      );
    });

    test('scope, basis and effect labels', () {
      expect(
        financialBudgetScopeLabel(FinancialVisibilityScope.personal),
        'Pessoal',
      );
      expect(
        financialBudgetScopeLabel(FinancialVisibilityScope.household),
        'Da casa',
      );
      expect(financialBudgetBasisLabel(FinancialBudgetDateBasis.cash), 'Caixa');
      expect(
        financialBudgetBasisLabel(FinancialBudgetDateBasis.competence),
        'Competência',
      );
      expect(
        financialBudgetEffectLabel(FinancialResultEffect.income),
        'Receita',
      );
    });
  });

  group('progress is parsed from the server text with integers only', () {
    test('fraction is clamped to the bar', () {
      expect(financialBudgetProgressFraction('0.00'), 0);
      expect(financialBudgetProgressFraction('30.00'), 0.3);
      expect(financialBudgetProgressFraction('99.99'), closeTo(0.9999, 1e-12));
      expect(financialBudgetProgressFraction('100.00'), 1);
      expect(financialBudgetProgressFraction('250.50'), 1);
      expect(financialBudgetProgressFraction('-30.00'), 0);
      expect(financialBudgetProgressFraction('garbage'), 0);
    });

    test('labels drop a redundant .00 only', () {
      expect(financialBudgetProgressLabel('30.00'), '30%');
      expect(financialBudgetProgressLabel('33.33'), '33.33%');
      expect(financialBudgetProgressLabel('150.50'), '150.50%');
    });
  });

  group('category eligibility mirrors the contract', () {
    final household = _category(index: 1, name: 'Casa');
    final mine = _category(
      index: 2,
      name: 'Minha',
      scope: FinancialVisibilityScope.personal,
    );
    final theirs = _category(
      index: 3,
      name: 'Dele',
      scope: FinancialVisibilityScope.personal,
      owner: _other,
    );
    final disabled = _category(
      index: 4,
      name: 'Antiga',
      status: FinancialCategoryStatus.disabled,
    );
    final shared = _category(
      index: 5,
      name: 'Compartilhada',
      scope: FinancialVisibilityScope.shared,
    );

    bool ok(FinancialCategory c, FinancialVisibilityScope scope) =>
        isFinancialCategoryEligibleForBudget(
          category: c,
          scope: scope,
          ownerOperatorId: _owner,
        );

    test('HOUSEHOLD budget accepts only ACTIVE household categories', () {
      const scope = FinancialVisibilityScope.household;
      expect(ok(household, scope), isTrue);
      expect(ok(mine, scope), isFalse);
      expect(ok(theirs, scope), isFalse);
      expect(ok(disabled, scope), isFalse);
      expect(ok(shared, scope), isFalse);
    });

    test(
      "PERSONAL budget accepts only the owner's ACTIVE personal categories",
      () {
        const scope = FinancialVisibilityScope.personal;
        expect(ok(mine, scope), isTrue);
        expect(ok(household, scope), isFalse);
        expect(ok(theirs, scope), isFalse);
        expect(ok(disabled, scope), isFalse);
      },
    );

    test('SHARED budgets do not exist', () {
      expect(ok(household, FinancialVisibilityScope.shared), isFalse);
      expect(
        financialBudgetCreationScopes,
        isNot(contains(FinancialVisibilityScope.shared)),
      );
    });

    test('eligible list is sorted by path and excludes the rest', () {
      final index = FinancialCategoryIndex.build([
        household,
        _category(index: 6, name: 'Agua'),
        mine,
        theirs,
        disabled,
      ]);
      final list = eligibleFinancialBudgetCategories(
        index: index,
        scope: FinancialVisibilityScope.household,
        ownerOperatorId: _owner,
      );
      expect(list.map((c) => c.name), ['Agua', 'Casa']);
    });
  });

  group('draft validation', () {
    final market = _category(index: 1, name: 'Mercado');
    final mine = _category(
      index: 2,
      name: 'Minha',
      scope: FinancialVisibilityScope.personal,
    );
    final disabled = _category(
      index: 3,
      name: 'Antiga',
      status: FinancialCategoryStatus.disabled,
    );
    final index = FinancialCategoryIndex.build([market, mine, disabled]);

    List<FinancialBudgetDraftIssue> issues(
      List<FinancialBudgetDraftLine> lines, {
      String name = 'Outubro',
      FinancialVisibilityScope scope = FinancialVisibilityScope.household,
    }) => validateFinancialBudgetDraft(
      name: name,
      lines: lines,
      scope: scope,
      ownerOperatorId: _owner,
      index: index,
    );

    FinancialBudgetDraftLine line(
      String? categoryId, {
      String planned = '10',
      FinancialResultEffect effect = FinancialResultEffect.expense,
    }) => FinancialBudgetDraftLine(
      categoryId: categoryId,
      plannedText: planned,
      resultEffect: effect,
    );

    test('a complete draft has no issues', () {
      expect(issues([line(market.categoryId)]), isEmpty);
      expect(issues([line(market.categoryId, planned: '10,50')]), isEmpty);
    });

    test('flags every rule the user can break', () {
      expect(issues([line(market.categoryId)], name: '  '), [
        FinancialBudgetDraftIssue.nameRequired,
      ]);
      expect(issues([]), [FinancialBudgetDraftIssue.noLines]);
      expect(issues([line(null)]), [
        FinancialBudgetDraftIssue.categoryRequired,
      ]);
      expect(issues([line(disabled.categoryId)]), [
        FinancialBudgetDraftIssue.categoryUnavailable,
      ]);
      expect(issues([line(mine.categoryId)]), [
        FinancialBudgetDraftIssue.categoryUnavailable,
      ]);
      for (final bad in ['', '0', '-1', 'abc', '1.123456789', '1,5,5']) {
        expect(issues([line(market.categoryId, planned: bad)]), [
          FinancialBudgetDraftIssue.plannedInvalid,
        ], reason: bad);
      }
      expect(
        issues([
          line(market.categoryId),
          line(market.categoryId, planned: '5'),
        ]),
        [FinancialBudgetDraftIssue.duplicateLine],
      );
      // Same category with both effects is two valid lines.
      expect(
        issues([
          line(market.categoryId),
          line(market.categoryId, effect: FinancialResultEffect.income),
        ]),
        isEmpty,
      );
    });

    test('too many lines and every label is readable text', () {
      final many = [
        for (var i = 0; i < financialBudgetLinesMax + 1; i += 1)
          line(market.categoryId, planned: '${i + 1}'),
      ];
      expect(issues(many), contains(FinancialBudgetDraftIssue.tooManyLines));
      for (final issue in FinancialBudgetDraftIssue.values) {
        expect(financialBudgetDraftIssueLabel(issue), isNotEmpty);
      }
    });

    test('personal scope uses the personal catalog', () {
      expect(
        issues([
          line(mine.categoryId),
        ], scope: FinancialVisibilityScope.personal),
        isEmpty,
      );
      expect(
        issues([
          line(market.categoryId),
        ], scope: FinancialVisibilityScope.personal),
        [FinancialBudgetDraftIssue.categoryUnavailable],
      );
    });
  });
}
