import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';

void main() {
  test('normalizes comma or dot to canonical wire decimal', () {
    expect(normalizeFinancialMoneyInput('123,45'), '123.45');
    expect(normalizeFinancialMoneyInput('123.45'), '123.45');
    expect(normalizeFinancialMoneyInput('10'), '10');
    expect(normalizeFinancialMoneyInput('-12,34000000'), '-12.34000000');
  });

  test('rejects ambiguous thousand-style inputs', () {
    for (final value in ['1.234,56', '1,234.56']) {
      expect(
        () => normalizeFinancialMoneyInput(value),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test('preserves current precision and canonical shape limits', () {
    expect(
      normalizeFinancialMoneyInput('9999999999999999,12345678'),
      '9999999999999999.12345678',
    );

    for (final value in [
      '99999999999999999,1',
      '1,123456789',
      '01,20',
      '',
      ',50',
      '1,',
    ]) {
      expect(
        () => normalizeFinancialMoneyInput(value),
        throwsA(isA<FormatException>()),
      );
    }
  });

  test('positive validator accepts comma and dot but rejects zero or negative', () {
    for (final value in ['1', '1,00', '1.00', '123,45']) {
      expect(
        validateFinancialMoneyInput(value, requirePositive: true),
        isNull,
      );
    }

    for (final value in ['0', '0,00', '0.00', '-1', '-1,00', '-1.00']) {
      expect(
        validateFinancialMoneyInput(value, requirePositive: true),
        isNotNull,
      );
    }
  });

  test('signed validator accepts negative opening balance with comma', () {
    expect(
      validateFinancialMoneyInput('-12,34', requirePositive: false),
      isNull,
    );
    expect(
      validateFinancialMoneyInput('12.34', requirePositive: false),
      isNull,
    );
  });
}
