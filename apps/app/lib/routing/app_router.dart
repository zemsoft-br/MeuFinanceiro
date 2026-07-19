import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/bootstrap/bootstrap_screen.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final router = GoRouter(
    routes: [
      GoRoute(
        path: '/',
        name: 'bootstrap',
        builder: (context, state) => const BootstrapScreen(),
      ),
    ],
  );

  ref.onDispose(router.dispose);
  return router;
});
