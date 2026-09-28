import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_operation_date_policy.dart';

void main() {
  test('uses today when ledger has no future effective date', () {
    expect(
      financialOperationInitialDate(now: DateTime(2026, 11, 10)),
      '2026-11-10',
    );
  });

  test('never precedes a future opening balance', () {
    expect(
      financialOperationInitialDate(
        now: DateTime(2026, 9, 20),
        openingBalanceDate: '2026-10-31',
      ),
      '2026-10-31',
    );
  });

  test('uses latest loaded movement when ledger is future-dated', () {
    expect(
      financialOperationInitialDate(
        now: DateTime(2026, 9, 20),
        openingBalanceDate: '2026-10-31',
        movementEffectiveDates: const ['2026-11-01', '2026-11-05'],
      ),
      '2026-11-05',
    );
  });

  test('reversal never defaults before its target movement', () {
    expect(
      financialOperationInitialDate(
        now: DateTime(2026, 9, 20),
        movementEffectiveDates: const ['2026-11-01'],
        targetMovementDate: '2026-11-08',
      ),
      '2026-11-08',
    );
  });

  test('today wins when it is later than all loaded ledger dates', () {
    expect(
      financialOperationInitialDate(
        now: DateTime(2026, 12, 1),
        openingBalanceDate: '2026-10-31',
        movementEffectiveDates: const ['2026-11-05'],
        targetMovementDate: '2026-11-04',
      ),
      '2026-12-01',
    );
  });

  test('rejects non-canonical ledger dates fail closed', () {
    for (final value in ['2026-02-30', '20/09/2026', '']) {
      expect(
        () => financialOperationInitialDate(
          now: DateTime(2026, 9, 20),
          openingBalanceDate: value,
        ),
        throwsA(isA<FormatException>()),
      );
    }
  });
}
