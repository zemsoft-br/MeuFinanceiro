import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_registration_time_format.dart';

void main() {
  test('shows only registration time when local date matches effective date', () {
    final createdAt = DateTime(2026, 9, 21, 14, 5);

    expect(
      formatFinancialRegistrationTime(
        createdAt: createdAt,
        effectiveDate: '2026-09-21',
      ),
      'Registrado às 14:05',
    );
  });

  test('shows registration date and time when local date differs', () {
    final createdAt = DateTime(2026, 9, 21, 14, 5);

    expect(
      formatFinancialRegistrationTime(
        createdAt: createdAt,
        effectiveDate: '2026-09-20',
      ),
      'Registrado em 21/09/2026 às 14:05',
    );
  });

  test('compares effective date after timezone localization', () {
    final createdAt = DateTime.parse('2026-09-21T01:30:00Z');

    expect(
      formatFinancialRegistrationTime(
        createdAt: createdAt,
        effectiveDate: '2026-09-20',
        localize: (value) => value.toUtc().subtract(const Duration(hours: 3)),
      ),
      'Registrado às 22:30',
    );
  });
}
