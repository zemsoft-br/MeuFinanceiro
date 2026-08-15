import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/routing/auth_route_guard.dart';

void main() {
  test('finance destination covers list create and detail routes', () {
    final finance = AppRoutes.destinations.singleWhere(
      (destination) => destination.id == AppRouteId.finance,
    );

    expect(finance.path, '/app/financas');
    expect(AppRoutes.destinationForLocation('/app/financas'), same(finance));
    expect(
      AppRoutes.destinationForLocation('/app/financas/contas/nova'),
      same(finance),
    );
    expect(
      AppRoutes.destinationForLocation(
        '/app/financas/contas/40000000-0000-4000-8000-000000000004',
      ),
      same(finance),
    );
  });

  test('all financial routes remain behind the existing app auth guard', () {
    for (final location in [
      AppRoutes.financePath,
      AppRoutes.financeAccountCreatePath,
      AppRoutes.financeAccountDetailLocation(
        '40000000-0000-4000-8000-000000000004',
      ),
    ]) {
      expect(
        AuthRouteGuard.requiresAuthentication(Uri.parse(location)),
        isTrue,
      );
    }
  });

  test(
    'detail location keeps the canonical account id as one path segment',
    () {
      const id = '40000000-0000-4000-8000-000000000004';
      expect(
        AppRoutes.financeAccountDetailLocation(id),
        '/app/financas/contas/$id',
      );
    },
  );
}
