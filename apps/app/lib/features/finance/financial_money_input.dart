final _financialMoneyInputPattern = RegExp(
  r'^-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$',
);
final _financialZeroMoneyPattern = RegExp(r'^-?0(?:\.0{1,8})?$');

String normalizeFinancialMoneyInput(String value) {
  if (value.contains('.') && value.contains(',')) {
    throw const FormatException('ambiguous decimal separators');
  }

  final normalized = value.replaceAll(',', '.');

  if (!_financialMoneyInputPattern.hasMatch(normalized)) {
    throw const FormatException('financial money input is invalid');
  }

  return normalized;
}

String? validateFinancialMoneyInput(
  String? value, {
  required bool requirePositive,
}) {
  final source = value ?? '';

  try {
    final normalized = normalizeFinancialMoneyInput(source);
    if (requirePositive &&
        (normalized.startsWith('-') ||
            _financialZeroMoneyPattern.hasMatch(normalized))) {
      return 'Informe um valor positivo válido.';
    }
    return null;
  } on FormatException {
    return requirePositive
        ? 'Informe um valor positivo válido.'
        : 'Informe um valor decimal válido.';
  }
}
