import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_policy.dart';

import '../../support/fake_finance_backend.dart';
import '../../support/fake_goal_backend.dart';

FinancialAccount _account({
  int index = 1,
  String owner = financeTestOwnerId,
  FinancialVisibilityScope scope = FinancialVisibilityScope.household,
  String currency = 'BRL',
  FinancialAccountStatus status = FinancialAccountStatus.active,
  String name = 'Conta',
}) => FinancialAccount(
  accountId: goalTestAccountId(index),
  ownerOperatorId: owner,
  visibilityScope: scope,
  accountType: FinancialAccountType.checking,
  customTypeName: null,
  name: name,
  currency: currency,
  status: status,
  createdAt: DateTime.utc(2026, 9, 1),
  updatedAt: DateTime.utc(2026, 9, 1),
  archivedAt: status == FinancialAccountStatus.archived
      ? DateTime.utc(2026, 9, 2)
      : null,
);

FinancialGoal _goal({
  FinancialVisibilityScope scope = FinancialVisibilityScope.household,
  String owner = financeTestOwnerId,
  String currency = 'BRL',
}) => FinancialGoal(
  id: goalTestId(1),
  ownerOperatorId: owner,
  visibilityScope: scope,
  title: 'Meta',
  description: null,
  currency: currency,
  target: FinancialMoneyWire(amount: '100', currency: currency),
  targetDate: null,
  version: 1,
  createdAt: DateTime.utc(2026, 10, 1),
  updatedAt: DateTime.utc(2026, 10, 1),
  canEdit: true,
);

void main() {
  group('eligible accounts', () {
    test('mirror the contract: same owner, audience, currency, ACTIVE', () {
      final goal = _goal();
      final accounts = [
        _account(index: 1),
        _account(index: 2, scope: FinancialVisibilityScope.personal),
        _account(index: 3, scope: FinancialVisibilityScope.shared),
        _account(index: 4, owner: financeTestOtherOperatorId),
        _account(index: 5, currency: 'USD'),
        _account(index: 6, status: FinancialAccountStatus.archived),
      ];
      expect(
        eligibleFinancialGoalAccounts(
          goal: goal,
          accounts: accounts,
        ).map((account) => account.accountId),
        [goalTestAccountId(1)],
      );
    });

    test('a personal goal accepts only the owner personal accounts', () {
      final goal = _goal(scope: FinancialVisibilityScope.personal);
      final accounts = [
        _account(index: 1, scope: FinancialVisibilityScope.personal),
        _account(index: 2),
      ];
      expect(
        eligibleFinancialGoalAccounts(
          goal: goal,
          accounts: accounts,
        ).map((account) => account.accountId),
        [goalTestAccountId(1)],
      );
    });
  });

  group('draft validation', () {
    final today = DateTime(2026, 10, 7);

    List<FinancialGoalDraftIssue> validate({
      String title = 'Meta',
      String description = '',
      String currency = 'BRL',
      String target = '10',
      String date = '',
      String? existing,
    }) => validateFinancialGoalDraft(
      title: title,
      description: description,
      currency: currency,
      targetText: target,
      targetDateText: date,
      today: today,
      existingTargetDate: existing,
    );

    test('a valid draft has no issue', () {
      expect(validate(), isEmpty);
      expect(validate(date: '2027-06-01'), isEmpty);
    });

    test('each rule reports its own issue', () {
      expect(validate(title: ' '), [FinancialGoalDraftIssue.titleRequired]);
      expect(validate(title: 'x' * 97), [
        FinancialGoalDraftIssue.titleRequired,
      ]);
      expect(validate(description: 'x' * 281), [
        FinancialGoalDraftIssue.descriptionTooLong,
      ]);
      expect(validate(currency: 'br'), [
        FinancialGoalDraftIssue.currencyInvalid,
      ]);
      for (final bad in ['0', '-1', 'abc', '1e3', '']) {
        expect(validate(target: bad), [FinancialGoalDraftIssue.targetInvalid]);
      }
      expect(validate(target: '12,5'), isEmpty);
    });

    test('the target date mirrors the range and the calendar', () {
      expect(validate(date: '2026-10-06'), isEmpty);
      expect(validate(date: '2026-10-05'), [
        FinancialGoalDraftIssue.targetDateOutOfRange,
      ]);
      expect(validate(date: '2126-12-31'), isEmpty);
      expect(validate(date: '2127-01-01'), [
        FinancialGoalDraftIssue.targetDateOutOfRange,
      ]);
      expect(validate(date: '2026-02-30'), [
        FinancialGoalDraftIssue.targetDateInvalid,
      ]);
      expect(validate(date: '01/02/2027'), [
        FinancialGoalDraftIssue.targetDateInvalid,
      ]);
    });

    test('keeping the stored date is never revalidated', () {
      expect(validate(date: '2020-01-01', existing: '2020-01-01'), isEmpty);
      expect(validate(date: '2020-01-02', existing: '2020-01-01'), [
        FinancialGoalDraftIssue.targetDateOutOfRange,
      ]);
    });

    test('every issue has a readable label', () {
      for (final issue in FinancialGoalDraftIssue.values) {
        expect(financialGoalDraftIssueLabel(issue), isNotEmpty);
      }
    });
  });

  group('allocation validation', () {
    test('needs an account and a positive amount', () {
      expect(validateFinancialGoalAllocation(accountId: null, amountText: ''), [
        FinancialGoalAllocationIssue.accountRequired,
        FinancialGoalAllocationIssue.amountInvalid,
      ]);
      expect(validateFinancialGoalAllocation(accountId: 'x', amountText: '0'), [
        FinancialGoalAllocationIssue.amountInvalid,
      ]);
      expect(
        validateFinancialGoalAllocation(accountId: 'x', amountText: '10,5'),
        isEmpty,
      );
    });
  });

  group('presentation', () {
    test('the progress fraction uses integers only and is clamped', () {
      expect(financialGoalProgressFraction('0.00'), 0);
      expect(financialGoalProgressFraction('25.00'), 0.25);
      expect(financialGoalProgressFraction('99.99'), 0.9999);
      expect(financialGoalProgressFraction('100.00'), 1);
      expect(financialGoalProgressFraction('250.00'), 1);
      expect(financialGoalProgressFraction('bad'), 0);
      expect(financialGoalProgressLabel('25.00'), '25%');
      expect(financialGoalProgressLabel('33.33'), '33.33%');
    });

    test(
      'status text never depends on colour and the virtual notice is fixed',
      () {
        for (final status in FinancialGoalProgressStatus.values) {
          expect(financialGoalProgressStatusLabel(status), isNotEmpty);
        }
        for (final status in FinancialGoalBackingStatus.values) {
          expect(financialGoalBackingStatusLabel(status), isNotEmpty);
        }
        expect(
          financialGoalVirtualNotice,
          'Destinação virtual; não transfere nem bloqueia dinheiro.',
        );
        expect(
          financialGoalInsufficientBackingNotice,
          contains('garantia bancária'),
        );
        expect(financialGoalDateLabel('2027-06-01'), '01/06/2027');
      },
    );

    test('creation audiences never include SHARED', () {
      expect(financialGoalCreationScopes, [
        FinancialVisibilityScope.household,
        FinancialVisibilityScope.personal,
      ]);
    });
  });
}
