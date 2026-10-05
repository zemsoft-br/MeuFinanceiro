import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_allocation_math.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

const _owner = '30000000-0000-4000-8000-000000000003';
String _id(int n) => 'a1000000-0000-4000-8000-${n.toString().padLeft(12, '0')}';

FinancialAccount _account({
  FinancialAccountStatus status = FinancialAccountStatus.active,
}) => FinancialAccount(
  accountId: '40000000-0000-4000-8000-000000000004',
  ownerOperatorId: _owner,
  visibilityScope: FinancialVisibilityScope.personal,
  accountType: FinancialAccountType.checking,
  customTypeName: null,
  name: 'Conta',
  currency: 'BRL',
  status: status,
  createdAt: DateTime.utc(2026),
  updatedAt: DateTime.utc(2026),
  archivedAt: status == FinancialAccountStatus.archived
      ? DateTime.utc(2026, 2)
      : null,
);

FinancialCategory _category(
  int n, {
  FinancialCategoryStatus status = FinancialCategoryStatus.active,
  FinancialVisibilityScope scope = FinancialVisibilityScope.household,
}) => FinancialCategory(
  categoryId: _id(n),
  ownerOperatorId: _owner,
  visibilityScope: scope,
  parentId: null,
  name: 'Cat $n',
  status: status,
  createdAt: DateTime.utc(2026),
  updatedAt: DateTime.utc(2026),
  disabledAt: status == FinancialCategoryStatus.disabled
      ? DateTime.utc(2026, 2)
      : null,
);

FinancialMovement _movement(String amount, {String effect = 'EXPENSE'}) =>
    FinancialMovement(
      movementId: '60000000-0000-4000-8000-000000000001',
      accountId: '40000000-0000-4000-8000-000000000004',
      money: FinancialMoneyWire(amount: amount, currency: 'BRL'),
      resultEffect: FinancialResultEffect.parse(effect),
      role: FinancialMovementRole.standard,
      effectiveDate: '2026-09-10',
      competenceDate: '2026-09-10',
      description: 'x',
      reversalOfId: null,
      reversalReason: null,
      createdAt: DateTime.utc(2026, 9, 10),
    );

FinancialAllocationDraftReport _evaluate(
  String movementAmount,
  List<(int?, String)> rows, {
  int categories = 60,
  List<FinancialCategory> extra = const [],
}) {
  final index = FinancialCategoryIndex.build([
    for (var n = 1; n <= categories; n++) _category(n),
    ...extra,
  ]);
  return evaluateFinancialAllocationDraft(
    movement: _movement(
      movementAmount,
      effect: movementAmount.startsWith('-') ? 'EXPENSE' : 'INCOME',
    ),
    account: _account(),
    index: index,
    rows: [
      for (final row in rows)
        FinancialAllocationDraftRow(
          categoryId: row.$1 == null ? null : _id(row.$1!),
          amountText: row.$2,
        ),
    ],
  );
}

FinancialAllocationShareInput _share(int n, String amount) =>
    FinancialAllocationShareInput(
      categoryId: _id(n),
      amount: amount,
      currency: 'BRL',
    );

void main() {
  group('exact decimal units', () {
    test('0.1 + 0.2 is exactly 0.3, with no binary error', () {
      final sum = sumFinancialDecimalUnits(['0.1', '0.2']);
      expect(sum, parseFinancialDecimalUnits('0.3'));
      expect(formatFinancialDecimalUnits(sum), '0.30');
      expect(
        formatFinancialDecimalUnits(sumFinancialDecimalUnits(['0.10', '0.20'])),
        '0.30',
      );
    });

    test('keeps 8 decimal places exactly', () {
      expect(
        parseFinancialDecimalUnits('0.00000001'),
        BigInt.one,
        reason: 'one unit of the 8th decimal',
      );
      expect(formatFinancialDecimalUnits(BigInt.one), '0.00000001');
      expect(
        formatFinancialDecimalUnits(
          parseFinancialDecimalUnits('123456789.12345678'),
        ),
        '123456789.12345678',
      );
      expect(
        formatFinancialDecimalUnits(
          sumFinancialDecimalUnits(['123456789.12345678', '0.00000002']),
        ),
        '123456789.1234568',
      );
      expect(
        formatFinancialDecimalUnits(
          sumFinancialDecimalUnits(['0.00000001', '0.00000001']),
        ),
        '0.00000002',
      );
    });

    test('handles the largest wire value without precision loss', () {
      const biggest = '9999999999999999.99999999';
      expect(
        formatFinancialDecimalUnits(parseFinancialDecimalUnits(biggest)),
        biggest,
      );
      expect(
        formatFinancialDecimalUnits(
          sumFinancialDecimalUnits([biggest, '-9999999999999999.99999998']),
        ),
        '0.00000001',
      );
    });

    test('negative amounts sum with their sign', () {
      expect(
        formatFinancialDecimalUnits(sumFinancialDecimalUnits(['-0.1', '-0.2'])),
        '-0.30',
      );
      expect(sumFinancialDecimalUnits(['-75.25', '50', '25.25']), BigInt.zero);
    });

    test('rejects more than 8 decimals, commas, exponents and junk', () {
      for (final text in [
        '0.123456789',
        '1,5',
        '1e3',
        '',
        ' 1',
        '1.',
        '.5',
        '00.5',
        '+1',
        'abc',
      ]) {
        expect(
          () => parseFinancialDecimalUnits(text),
          throwsA(isA<FormatException>()),
          reason: text,
        );
      }
    });

    test('canonical decimal collapses equal values and only those', () {
      expect(canonicalFinancialDecimal('-75.250'), '-75.25');
      expect(canonicalFinancialDecimal('-75.25'), '-75.25');
      expect(canonicalFinancialDecimal('10.00'), '10');
      expect(canonicalFinancialDecimal('0.10'), '0.1');
      expect(canonicalFinancialDecimal('-0'), '0');
      expect(
        canonicalFinancialDecimal('0.10') == canonicalFinancialDecimal('0.11'),
        isFalse,
      );
    });
  });

  group('share wire amount from an unsigned magnitude', () {
    final expense = FinancialMoneyWire(amount: '-75.25', currency: 'BRL');
    final income = FinancialMoneyWire(amount: '100', currency: 'BRL');

    test('an expense keeps the Movement sign', () {
      expect(
        financialShareWireAmount(
          movementMoney: expense,
          magnitudeText: '75.25',
        ),
        '-75.25',
      );
      expect(
        financialShareWireAmount(movementMoney: expense, magnitudeText: '0,10'),
        '-0.10',
      );
      expect(
        financialShareWireAmount(
          movementMoney: expense,
          magnitudeText: '0.00000001',
        ),
        '-0.00000001',
      );
    });

    test('an income stays positive', () {
      expect(
        financialShareWireAmount(movementMoney: income, magnitudeText: '33,33'),
        '33.33',
      );
    });

    test('a signed or malformed magnitude is refused, never coerced', () {
      for (final text in ['-5', '1.2.3', '1,2.3', 'x', '', '0.123456789']) {
        expect(
          () => financialShareWireAmount(
            movementMoney: expense,
            magnitudeText: text,
          ),
          throwsA(isA<FormatException>()),
          reason: text,
        );
      }
    });

    test('magnitude text strips the sign of a stored share', () {
      expect(financialShareMagnitudeText('-25'), '25.00');
      expect(financialShareMagnitudeText('25.5'), '25.50');
    });
  });

  group('closure of shares (SUM == movement.money, no tolerance)', () {
    final expense = FinancialMoneyWire(amount: '-75.25', currency: 'BRL');

    test('exact sum closes', () {
      expect(
        financialAllocationClosureIssues(
          movementMoney: expense,
          shares: [_share(1, '-50'), _share(2, '-25.25')],
        ),
        isEmpty,
      );
    });

    test('0.1 + 0.2 closes a 0.3 movement', () {
      expect(
        financialAllocationClosureIssues(
          movementMoney: FinancialMoneyWire(amount: '0.3', currency: 'BRL'),
          shares: [_share(1, '0.1'), _share(2, '0.2')],
        ),
        isEmpty,
      );
    });

    test('one unit of the 8th decimal under/over is not closed', () {
      expect(
        financialAllocationClosureIssues(
          movementMoney: expense,
          shares: [_share(1, '-50'), _share(2, '-25.24999999')],
        ),
        {FinancialAllocationIssue.notClosed},
        reason: 'under-allocation',
      );
      expect(
        financialAllocationClosureIssues(
          movementMoney: expense,
          shares: [_share(1, '-50'), _share(2, '-25.25000001')],
        ),
        {FinancialAllocationIssue.notClosed},
        reason: 'over-allocation',
      );
    });

    test('an expense share with the wrong sign is refused', () {
      final issues = financialAllocationClosureIssues(
        movementMoney: expense,
        shares: [_share(1, '75.25')],
      );
      expect(issues, contains(FinancialAllocationIssue.signMismatch));
      expect(issues, contains(FinancialAllocationIssue.notClosed));
    });

    test('currency, duplicates and emptiness are refused', () {
      expect(
        financialAllocationClosureIssues(
          movementMoney: expense,
          shares: [
            FinancialAllocationShareInput(
              categoryId: _id(1),
              amount: '-75.25',
              currency: 'USD',
            ),
          ],
        ),
        contains(FinancialAllocationIssue.currencyMismatch),
      );
      expect(
        financialAllocationClosureIssues(
          movementMoney: expense,
          shares: [_share(1, '-50'), _share(1, '-25.25')],
        ),
        contains(FinancialAllocationIssue.duplicateCategory),
      );
      expect(
        financialAllocationClosureIssues(movementMoney: expense, shares: []),
        {FinancialAllocationIssue.noShares},
      );
    });

    test('50 shares are accepted and 51 are blocked', () {
      List<FinancialAllocationShareInput> shares(int count) => [
        for (var i = 1; i <= count; i++) _share(i, '-1'),
      ];
      expect(
        financialAllocationClosureIssues(
          movementMoney: FinancialMoneyWire(amount: '-50', currency: 'BRL'),
          shares: shares(50),
        ),
        isEmpty,
      );
      expect(
        financialAllocationClosureIssues(
          movementMoney: FinancialMoneyWire(amount: '-51', currency: 'BRL'),
          shares: shares(51),
        ),
        contains(FinancialAllocationIssue.tooManyShares),
      );
    });
  });

  group('editor draft report', () {
    test('Total / Rateado / Restante for an expense are magnitudes', () {
      final report = _evaluate('-75.25', [(1, '50'), (2, '')]);
      expect(report.movementText, '75.25');
      expect(report.allocatedText, '50.00');
      expect(report.remainingText, '25.25');
      expect(report.isClosed, isFalse);
      expect(report.shares, isNull);
    });

    test('exact closure yields shares with the Movement sign', () {
      final report = _evaluate('-75.25', [(1, '50'), (2, '25,25')]);
      expect(report.remainingText, '0.00');
      expect(report.isClosed, isTrue);
      expect(report.shares!.map((s) => s.amount), ['-50.00', '-25.25']);
      expect(report.shares!.map((s) => s.currency).toSet(), {'BRL'});
    });

    test('income closes with positive shares', () {
      final report = _evaluate('0.3', [(1, '0.1'), (2, '0.2')]);
      expect(report.isClosed, isTrue);
      expect(report.shares!.map((s) => s.amount), ['0.10', '0.20']);
    });

    test('under-allocation is open and shows what remains', () {
      final report = _evaluate('-75.25', [(1, '50'), (2, '25.24999999')]);
      expect(report.isClosed, isFalse);
      expect(report.issues, contains(FinancialAllocationIssue.notClosed));
      expect(report.remainingText, '0.00000001');
    });

    test('over-allocation shows a negative remainder and is not closed', () {
      final expense = _evaluate('-75.25', [(1, '50'), (2, '25.26')]);
      expect(expense.isClosed, isFalse);
      expect(expense.issues, contains(FinancialAllocationIssue.notClosed));
      expect(expense.remainingText, '-0.01');
      final income = _evaluate('10', [(1, '6'), (2, '4.01')]);
      expect(income.isClosed, isFalse);
      expect(income.issues, contains(FinancialAllocationIssue.notClosed));
      expect(income.remainingText, '-0.01');
    });

    test('a zero share blocks closure even if the sum matches', () {
      final report = _evaluate('-75.25', [(1, '75.25'), (2, '0')]);
      expect(report.isClosed, isFalse);
      expect(
        report.rows[1].issues,
        contains(FinancialAllocationIssue.zeroAmount),
      );
    });

    test('a duplicated category blocks closure on both rows', () {
      final report = _evaluate('-10', [(1, '5'), (1, '5')]);
      expect(report.isClosed, isFalse);
      expect(
        report.rows.map((r) => r.issues),
        everyElement(contains(FinancialAllocationIssue.duplicateCategory)),
      );
    });

    test('a DISABLED or unknown category blocks closure', () {
      final disabled = _evaluate(
        '-10',
        [(61, '10')],
        extra: [_category(61, status: FinancialCategoryStatus.disabled)],
      );
      expect(disabled.isClosed, isFalse);
      expect(
        disabled.rows.single.issues,
        contains(FinancialAllocationIssue.categoryUnavailable),
      );
      final unknown = _evaluate('-10', [(99, '10')]);
      expect(unknown.isClosed, isFalse);
    });

    test('a category outside the account audience blocks closure', () {
      final other = FinancialCategory(
        categoryId: _id(70),
        ownerOperatorId: '31000000-0000-4000-8000-000000000031',
        visibilityScope: FinancialVisibilityScope.personal,
        parentId: null,
        name: 'Do outro',
        status: FinancialCategoryStatus.active,
        createdAt: DateTime.utc(2026),
        updatedAt: DateTime.utc(2026),
        disabledAt: null,
      );
      final report = _evaluate('-10', [(70, '10')], extra: [other]);
      expect(report.isClosed, isFalse);
    });

    test('missing category, negative or malformed amount block closure', () {
      expect(_evaluate('-10', [(null, '10')]).isClosed, isFalse);
      expect(_evaluate('-10', [(1, '-10')]).isClosed, isFalse);
      expect(_evaluate('-10', [(1, '1.2.3')]).isClosed, isFalse);
      expect(_evaluate('-10', [(1, '')]).isClosed, isFalse);
      expect(_evaluate('-10', []).isClosed, isFalse);
    });

    test('50 rows can close and 51 rows cannot', () {
      final fifty = _evaluate('-50', [for (var i = 1; i <= 50; i++) (i, '1')]);
      expect(fifty.isClosed, isTrue);
      expect(fifty.shares, hasLength(50));
      final fiftyOne = _evaluate('-51', [
        for (var i = 1; i <= 51; i++) (i, '1'),
      ]);
      expect(fiftyOne.isClosed, isFalse);
      expect(fiftyOne.issues, contains(FinancialAllocationIssue.tooManyShares));
    });

    test('8 decimals survive a full round trip', () {
      final report = _evaluate('-0.00000003', [
        (1, '0.00000001'),
        (2, '0.00000002'),
      ]);
      expect(report.isClosed, isTrue);
      expect(report.shares!.map((s) => s.amount), [
        '-0.00000001',
        '-0.00000002',
      ]);
    });
  });

  group('attempt identity (idempotency material)', () {
    String identity({
      String kind = 'revise',
      String movementId = 'm1',
      String? supersedes = 's1',
      required List<FinancialAllocationShareInput> shares,
    }) => financialAllocationAttemptIdentity(
      kind: kind,
      movementId: movementId,
      supersedesId: supersedes,
      shares: shares,
    );

    final base = [_share(1, '-50'), _share(2, '-25.25')];

    test('is stable for visual reordering and equal-valued text', () {
      expect(identity(shares: base), identity(shares: [base[1], base[0]]));
      expect(
        identity(shares: base),
        identity(shares: [_share(1, '-50.00'), _share(2, '-25.250')]),
      );
    });

    test('changes for every material difference', () {
      final reference = identity(shares: base);
      expect(
        identity(shares: [_share(1, '-50'), _share(3, '-25.25')]),
        isNot(reference),
        reason: 'category',
      );
      expect(
        identity(shares: [_share(1, '-50'), _share(2, '-25.24')]),
        isNot(reference),
        reason: 'amount',
      );
      expect(
        identity(
          shares: [
            _share(1, '-50'),
            FinancialAllocationShareInput(
              categoryId: _id(2),
              amount: '-25.25',
              currency: 'USD',
            ),
          ],
        ),
        isNot(reference),
        reason: 'currency',
      );
      expect(identity(supersedes: 's2', shares: base), isNot(reference));
      expect(identity(movementId: 'm2', shares: base), isNot(reference));
      expect(identity(kind: 'classify', shares: base), isNot(reference));
    });
  });

  group('no floating point authority', () {
    test('the money helper never touches double, num or percentages', () {
      final source = File('lib/features/finance/financial_allocation_math.dart')
          .readAsStringSync()
          .split('\n')
          .where((line) {
            final trimmed = line.trimLeft();
            return !trimmed.startsWith('//') && !trimmed.startsWith('///');
          })
          .join('\n');

      for (final forbidden in [
        'double',
        'num.',
        'toDouble',
        'parseDouble',
        'tryParse',
        'toStringAsFixed',
        'round(',
        'percent',
        '/ 100',
        '* 100',
        '1e',
      ]) {
        expect(
          source.contains(forbidden),
          isFalse,
          reason: 'found "$forbidden" in the allocation money helper',
        );
      }
    });

    test('binary floats would have failed where units do not', () {
      // Documents why the helper exists: 0.1 + 0.2 != 0.3 in IEEE-754.
      // ignore: prefer_const_declarations
      final binary = 0.1 + 0.2;
      expect(binary == 0.3, isFalse);
      expect(
        sumFinancialDecimalUnits(['0.1', '0.2']) ==
            parseFinancialDecimalUnits('0.3'),
        isTrue,
      );
    });
  });

  group('revision policy', () {
    FinancialMovementAllocation current() => FinancialMovementAllocation(
      allocationSetId: 'e5000000-0000-4000-8000-000000000001',
      movementId: '60000000-0000-4000-8000-000000000001',
      revision: 1,
      supersedesId: null,
      allocations: [
        FinancialAllocationShare(
          categoryId: _id(1),
          money: FinancialMoneyWire(amount: '-10', currency: 'BRL'),
        ),
      ],
      createdAt: DateTime.utc(2026, 9, 20),
    );

    test('only the owner of an ACTIVE account may revise a classified row', () {
      bool can({
        FinancialAccountStatus status = FinancialAccountStatus.active,
        String? operator = _owner,
        FinancialMovementAllocation? allocation,
        String effect = 'EXPENSE',
        FinancialMovementRole role = FinancialMovementRole.standard,
      }) {
        final base = _movement('-10', effect: effect);
        final movement = FinancialMovement(
          movementId: base.movementId,
          accountId: base.accountId,
          money: base.money,
          resultEffect: base.resultEffect,
          role: role,
          effectiveDate: base.effectiveDate,
          competenceDate: base.competenceDate,
          description: base.description,
          reversalOfId: null,
          reversalReason: null,
          createdAt: base.createdAt,
        );
        return canReviseFinancialMovementClassification(
          account: _account(status: status),
          movement: movement,
          currentAllocation: allocation ?? current(),
          operatorId: operator,
        );
      }

      expect(can(), isTrue);
      expect(can(operator: '31000000-0000-4000-8000-000000000031'), isFalse);
      expect(can(operator: null), isFalse);
      expect(can(status: FinancialAccountStatus.archived), isFalse);
      expect(can(effect: 'NEUTRAL'), isFalse);
      expect(can(role: FinancialMovementRole.reversal), isFalse);
      expect(
        canReviseFinancialMovementClassification(
          account: _account(),
          movement: _movement('-10'),
          currentAllocation: null,
          operatorId: _owner,
        ),
        isFalse,
        reason: 'nothing to revise',
      );
    });

    test('a revision identical to the current set is detected', () {
      expect(
        financialSharesMatchAllocation(current(), [_share(1, '-10.00')]),
        isTrue,
      );
      expect(
        financialSharesMatchAllocation(current(), [_share(2, '-10')]),
        isFalse,
      );
      expect(
        financialSharesMatchAllocation(current(), [
          _share(1, '-5'),
          _share(2, '-5'),
        ]),
        isFalse,
      );
    });
  });
}
