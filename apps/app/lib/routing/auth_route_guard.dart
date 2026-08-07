import 'package:meufinanceiro_app/core/auth/operator_session.dart';

abstract final class AuthRouteGuard {
  static String? redirectForProtectedRoute({
    required OperatorSessionState session,
    required Uri location,
  }) {
    if (session.isAuthenticated) {
      return null;
    }
    final destination = _safeInternalDestination(location.toString());
    return Uri(
      path: '/login',
      queryParameters: destination == null ? null : {'redirect': destination},
    ).toString();
  }

  static String? sanitizeRedirect(String? rawValue) {
    if (rawValue == null || rawValue.isEmpty) {
      return null;
    }
    return _safeInternalDestination(rawValue);
  }

  static String? _safeInternalDestination(String rawValue) {
    final uri = Uri.tryParse(rawValue);
    if (uri == null ||
        uri.hasScheme ||
        uri.hasAuthority ||
        !uri.path.startsWith('/') ||
        uri.path.startsWith('//') ||
        uri.path == '/login') {
      return null;
    }
    return uri.toString();
  }
}
