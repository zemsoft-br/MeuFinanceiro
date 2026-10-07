import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_policy.dart';

import '../../support/fake_finance_backend.dart';

FinancialAccount _account(
  String id, {
  String owner = financeTestOwnerId,
  FinancialAccountStatus status = FinancialAccountStatus.active,
  String name = 'Conta',
}) => FinancialAccount(
  accountId: id,
  ownerOperatorId: owner,
  visibilityScope: FinancialVisibilityScope.household,
  accountType: FinancialAccountType.checking,
  customTypeName: null,
  name: name,
  currency: 'BRL',
  status: status,
  createdAt: DateTime.utc(2026),
  updatedAt: DateTime.utc(2026),
  archivedAt: null,
);

const _a = 'd3000000-0000-4000-8000-000000000001';
const _b = 'd3000000-0000-4000-8000-000000000002';
const _c = 'd3000000-0000-4000-8000-000000000003';

void main() {
  group('copy', () {
    test(
      'the forecast notice states that previsto never moves the balance',
      () {
        expect(financialRecurrenceForecastNotice, contains('Previsto'));
        expect(financialRecurrenceForecastNotice, contains('saldo'));
        expect(financialRecurrenceForecastNotice, contains('Registrar'));
        expect(financialRecurrenceRealizeNotice, contains('saldo'));
      },
    );

    test(
      'every status has a label and a ledger hint that is not colour only',
      () {
        for (final status in FinancialOccurrenceStatus.values) {
          expect(financialOccurrenceStatusLabel(status), isNotEmpty);
          expect(financialOccurrenceStatusHint(status), isNotEmpty);
        }
        expect(
          financialOccurrenceStatusHint(FinancialOccurrenceStatus.pending),
          contains('não afeta o saldo'),
        );
        expect(
          financialOccurrenceStatusHint(FinancialOccurrenceStatus.skipped),
          contains('não afeta o saldo'),
        );
        expect(
          financialOccurrenceStatusLabel(FinancialOccurrenceStatus.pending),
          'Prevista',
        );
        expect(
          financialRecurrenceStatusLabel(FinancialRecurrenceStatus.paused),
          'Pausada',
        );
      },
    );

    test('a reversed Movement is stated without reopening the occurrence', () {
      expect(
        financialOccurrenceMovementStateLabel(
          FinancialOccurrenceMovementState.reversed,
        ),
        contains('continua registrada'),
      );
    });

    test('the schedule label explains days that may not exist', () {
      expect(financialRecurrenceScheduleLabel(10), 'Todo dia 10');
      expect(financialRecurrenceScheduleLabel(28), 'Todo dia 28');
      expect(financialRecurrenceScheduleLabel(31), contains('último dia'));
      expect(financialRecurrenceDateLabel('2026-10-05'), '05/10/2026');
    });
  });

  group('dates', () {
    test('accepts only real calendar dates', () {
      for (final valid in ['2026-10-05', '2028-02-29', '2026-12-31']) {
        expect(isFinancialRecurrenceDate(valid), isTrue, reason: valid);
      }
      for (final invalid in [
        '2026-02-29',
        '2026-13-01',
        '2026-1-1',
        '2026/10/05',
        '',
        '2026-10-05T00:00',
        '20261005',
      ]) {
        expect(isFinancialRecurrenceDate(invalid), isFalse, reason: invalid);
      }
    });
  });

  group('accounts', () {
    test('only the operator\'s own active accounts are eligible', () {
      final eligible = eligibleFinancialRecurrenceAccounts(
        accounts: [
          _account(_c, name: 'Zeta'),
          _account(_a, name: 'Alfa'),
          _account(_b, owner: financeTestOtherOperatorId),
          _account(
            'd3000000-0000-4000-8000-000000000004',
            status: FinancialAccountStatus.archived,
          ),
        ],
        operatorId: financeTestOwnerId,
      );
      expect(eligible.map((a) => a.name), ['Alfa', 'Zeta']);
    });
  });

  group('rule draft', () {
    final accounts = [_account(_a)];

    List<FinancialRecurrenceDraftIssue> issues({
      String description = 'Internet',
      String? accountId = _a,
      bool editing = false,
      String amount = '120',
      String start = '2026-01-10',
      String day = '10',
      String end = '',
    }) => validateFinancialRecurrenceDraft(
      description: description,
      accountId: accountId,
      eligibleAccounts: accounts,
      editing: editing,
      amountText: amount,
      startDate: start,
      dayText: day,
      endDate: end,
    );

    test('a complete draft has no issue', () {
      expect(issues(), isEmpty);
      expect(issues(amount: '120,50', end: '2026-12-31'), isEmpty);
    });

    test('each invalid field is reported', () {
      expect(issues(description: ' '), [
        FinancialRecurrenceDraftIssue.descriptionRequired,
      ]);
      expect(issues(accountId: null), [
        FinancialRecurrenceDraftIssue.accountRequired,
      ]);
      expect(issues(accountId: _c), [
        FinancialRecurrenceDraftIssue.accountUnavailable,
      ]);
      expect(issues(amount: '0'), [
        FinancialRecurrenceDraftIssue.amountInvalid,
      ]);
      expect(issues(amount: '-1'), [
        FinancialRecurrenceDraftIssue.amountInvalid,
      ]);
      expect(issues(amount: '1.2.3'), [
        FinancialRecurrenceDraftIssue.amountInvalid,
      ]);
      expect(issues(start: '2026-02-30'), [
        FinancialRecurrenceDraftIssue.startDateInvalid,
      ]);
      for (final day in ['0', '32', 'x', '']) {
        expect(issues(day: day), [FinancialRecurrenceDraftIssue.dayInvalid]);
      }
      expect(issues(end: 'x'), [FinancialRecurrenceDraftIssue.endDateInvalid]);
      expect(issues(end: '2025-12-31'), [
        FinancialRecurrenceDraftIssue.endBeforeStart,
      ]);
    });

    test('editing never asks for the immutable fields', () {
      expect(issues(editing: true, accountId: null, start: ''), isEmpty);
    });

    test('every issue has a label', () {
      for (final issue in FinancialRecurrenceDraftIssue.values) {
        expect(financialRecurrenceDraftIssueLabel(issue), isNotEmpty);
      }
    });
  });

  group('realization draft', () {
    test('needs a positive amount and two real dates', () {
      expect(
        validateFinancialRealizeDraft(
          amountText: '127,50',
          effectiveDate: '2026-10-11',
          competenceDate: '2026-10-01',
        ),
        isEmpty,
      );
      expect(
        validateFinancialRealizeDraft(
          amountText: '0',
          effectiveDate: '2026-10-11',
          competenceDate: '2026-10-01',
        ),
        [FinancialRealizeDraftIssue.amountInvalid],
      );
      expect(
        validateFinancialRealizeDraft(
          amountText: '1',
          effectiveDate: '2026-10-32',
          competenceDate: '2026-13-01',
        ),
        [
          FinancialRealizeDraftIssue.effectiveDateInvalid,
          FinancialRealizeDraftIssue.competenceDateInvalid,
        ],
      );
      for (final issue in FinancialRealizeDraftIssue.values) {
        expect(financialRealizeDraftIssueLabel(issue), isNotEmpty);
      }
    });
  });
}
