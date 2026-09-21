import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

String formatFinancialMoney(FinancialMoneyWire money) {
  final amount = money.amount;
  final negative = amount.startsWith('-');
  final unsigned = negative ? amount.substring(1) : amount;
  final parts = unsigned.split('.');
  final integerPart = parts.first;
  var fractionalPart = parts.length == 2 ? parts[1] : '';

  while (fractionalPart.length > 2 && fractionalPart.endsWith('0')) {
    fractionalPart = fractionalPart.substring(0, fractionalPart.length - 1);
  }
  fractionalPart = fractionalPart.padRight(2, '0');

  final signedIntegerPart = negative ? '-$integerPart' : integerPart;
  return '${money.currency} $signedIntegerPart,$fractionalPart';
}
