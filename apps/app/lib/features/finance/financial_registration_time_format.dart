typedef FinancialDateTimeLocalizer = DateTime Function(DateTime value);

String formatFinancialRegistrationTime({
  required DateTime createdAt,
  required String effectiveDate,
  FinancialDateTimeLocalizer? localize,
}) {
  final localCreatedAt = localize?.call(createdAt) ?? createdAt.toLocal();
  final localDate = _dateKey(localCreatedAt);
  final time = _timeLabel(localCreatedAt);

  if (localDate == effectiveDate) {
    return 'Registrado às $time';
  }

  return 'Registrado em ${_dateLabel(localDate)} às $time';
}

String _dateKey(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-'
    '${value.month.toString().padLeft(2, '0')}-'
    '${value.day.toString().padLeft(2, '0')}';

String _dateLabel(String value) {
  final parts = value.split('-');
  return '${parts[2]}/${parts[1]}/${parts[0]}';
}

String _timeLabel(DateTime value) =>
    '${value.hour.toString().padLeft(2, '0')}:'
    '${value.minute.toString().padLeft(2, '0')}';
