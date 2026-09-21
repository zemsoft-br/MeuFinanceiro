import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';

void main() {
  test('formats canonical money with at least two decimal places', () {
    expect(_label('5102.7'), 'BRL 5102,70');
    expect(_label('5102.70'), 'BRL 5102,70');
    expect(_label('0'), 'BRL 0,00');
    expect(_label('-23.45'), 'BRL -23,45');
    expect(_label('-10'), 'BRL -10,00');
  });

  test('preserves meaningful precision without using floating point', () {
    expect(_label('1.23400000'), 'BRL 1,234');
    expect(_label('-0.12345678'), 'BRL -0,12345678');
  });
}

String _label(String amount) => formatFinancialMoney(
  FinancialMoneyWire(amount: amount, currency: 'BRL'),
);
