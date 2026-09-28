import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/theme/components/app_state_panel.dart';

void main() {
  Future<void> pumpPanel(WidgetTester tester, AppStateKind kind) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: AppStatePanel(
            kind: kind,
            title: 'Título',
            description: 'Descrição',
          ),
        ),
      ),
    );
  }

  testWidgets('loading state renders an indeterminate progress indicator', (
    tester,
  ) async {
    await pumpPanel(tester, AppStateKind.loading);

    final indicator = tester.widget<CircularProgressIndicator>(
      find.byType(CircularProgressIndicator),
    );

    expect(
      indicator.value,
      isNull,
      reason:
          'This loading state has no measurable progress; declaring a '
          'numeric value announces a fictitious percentage to assistive '
          'technologies.',
    );
    expect(tester.takeException(), isNull);
  });
}
