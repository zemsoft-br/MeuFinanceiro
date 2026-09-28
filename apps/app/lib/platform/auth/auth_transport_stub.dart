import 'package:meufinanceiro_app/core/auth/auth_http.dart';

AuthTransport createAuthTransport() => const UnsupportedAuthTransport();

class UnsupportedAuthTransport implements AuthTransport {
  const UnsupportedAuthTransport();

  @override
  Future<AuthHttpResponse> send(
    Uri uri, {
    required AuthHttpMethod method,
    required Duration timeout,
    Map<String, String> headers = const {},
    String? body,
  }) {
    throw UnsupportedError('Authentication transport is unavailable.');
  }
}
