String financialOperationInitialDate({
  required DateTime now,
  String? openingBalanceDate,
  Iterable<String> movementEffectiveDates = const <String>[],
  String? targetMovementDate,
}) {
  var candidate = _civilDate(now);

  void consider(String? value) {
    if (value == null) return;
    final normalized = _validatedDate(value);
    if (normalized.compareTo(candidate) > 0) {
      candidate = normalized;
    }
  }

  consider(openingBalanceDate);
  for (final value in movementEffectiveDates) {
    consider(value);
  }
  consider(targetMovementDate);

  return candidate;
}

String _civilDate(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-'
    '${value.month.toString().padLeft(2, '0')}-'
    '${value.day.toString().padLeft(2, '0')}';

String _validatedDate(String value) {
  if (!RegExp(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$').hasMatch(value)) {
    throw const FormatException('financial operation date is invalid');
  }
  final parsed = DateTime.tryParse('${value}T00:00:00Z');
  if (parsed == null || _civilDate(parsed) != value) {
    throw const FormatException('financial operation date is invalid');
  }
  return value;
}
