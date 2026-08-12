import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/app/app_shell.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/features/auth/login_screen.dart';
import 'package:meufinanceiro_app/features/banking/connections/banking_connections_screen.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_screen.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/reauthentication/pluggy_reauthentication_screen.dart';
import 'package:meufinanceiro_app/features/components_catalog/components_catalog_screen.dart';
import 'package:meufinanceiro_app/features/home/home_screen.dart';
import 'package:meufinanceiro_app/features/not_found/not_found_screen.dart';
import 'package:meufinanceiro_app/features/system_health/system_health_screen.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/routing/auth_route_guard.dart';

final initialLocationProvider = Provider<String?>((ref) => null);

final _authRouterRefreshProvider = Provider<_AuthRouterRefresh>((ref) {
  final refresh = _AuthRouterRefresh();
  ref.listen(operatorSessionControllerProvider, (previous, next) {
    refresh.trigger();
  });
  ref.onDispose(refresh.dispose);
  return refresh;
});

final appRouterProvider = Provider<GoRouter>((ref) {
  final router = GoRouter(
    initialLocation: ref.watch(initialLocationProvider),
    refreshListenable: ref.watch(_authRouterRefreshProvider),
    redirect: (context, state) {
      if (!AuthRouteGuard.requiresAuthentication(state.uri)) {
        return null;
      }
      return AuthRouteGuard.redirectForProtectedRoute(
        session: ref.read(operatorSessionControllerProvider),
        location: state.uri,
      );
    },
    routes: [
      GoRoute(
        path: AppRoutes.loginPath,
        name: AppRoutes.login,
        pageBuilder: (context, state) {
          final redirectTo = AuthRouteGuard.sanitizeRedirect(
            state.uri.queryParameters['redirect'],
          );
          return NoTransitionPage(child: LoginScreen(redirectTo: redirectTo));
        },
      ),
      ShellRoute(
        builder: (context, state, child) {
          return AppShell(currentLocation: state.uri.path, child: child);
        },
        routes: [
          GoRoute(
            path: '/',
            name: AppRoutes.home,
            pageBuilder: (context, state) {
              return const NoTransitionPage(child: _HomeRoute());
            },
          ),
          GoRoute(
            path: '/componentes',
            name: AppRoutes.components,
            pageBuilder: (context, state) {
              return const NoTransitionPage(child: ComponentsCatalogScreen());
            },
          ),
          GoRoute(
            path: '/sistema',
            name: AppRoutes.system,
            pageBuilder: (context, state) {
              return const NoTransitionPage(child: SystemHealthScreen());
            },
          ),
          GoRoute(
            path: AppRoutes.integrationsPath,
            name: AppRoutes.integrations,
            pageBuilder: (context, state) {
              return const NoTransitionPage(child: BankingConnectionsScreen());
            },
          ),
          GoRoute(
            path: AppRoutes.pluggyConnectPath,
            name: AppRoutes.pluggyConnect,
            pageBuilder: (context, state) {
              return const NoTransitionPage(child: PluggyConnectScreen());
            },
          ),
          GoRoute(
            path: AppRoutes.pluggyReauthenticationPath,
            name: AppRoutes.pluggyReauthentication,
            pageBuilder: (context, state) {
              return NoTransitionPage(
                child: PluggyReauthenticationScreen(
                  connectionId: state.pathParameters['connectionId'] ?? '',
                ),
              );
            },
          ),
        ],
      ),
    ],
    errorPageBuilder: (context, state) {
      final location = state.uri.toString();
      return NoTransitionPage(
        child: AppShell(
          currentLocation: state.uri.path,
          child: NotFoundScreen(location: location),
        ),
      );
    },
  );

  ref.onDispose(router.dispose);
  return router;
});

class _AuthRouterRefresh extends ChangeNotifier {
  void trigger() {
    notifyListeners();
  }
}

class _HomeRoute extends ConsumerWidget {
  const _HomeRoute();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final availability = ref.watch(apiHealthProvider).value?.availability;
    return HomeScreen(availability: availability);
  }
}
