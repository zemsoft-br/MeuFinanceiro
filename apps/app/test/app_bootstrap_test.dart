import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/app/app.dart';
import 'package:meufinanceiro_app/features/bootstrap/bootstrap_screen.dart';

void main() {
  testWidgets('boots through ProviderScope and GoRouter', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: MeuFinanceiroApp()));
    await tester.pumpAndSettle();

    expect(find.byKey(BootstrapScreen.titleKey), findsOneWidget);
    expect(find.text('MeuFinanceiro'), findsOneWidget);
    expect(find.textContaining('Base Flutter inicial'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
