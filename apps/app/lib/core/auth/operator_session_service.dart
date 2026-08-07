import 'dart:convert';

import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';

class InvalidOperatorCredentials implements Exception {
  const InvalidOperatorCredentials();

  @override
  String toString() => 'Operator credentials are invalid.';
}

class OperatorAuthenticationUnavailable implements Exception {
  const OperatorAuthenticationUnavailable();

  @override
  String toString() => 'Operator authentication is unavailable.';
}

class OperatorSessionService {
  const OperatorSessionService({
    required this.transport,
    required this.apiBaseUri,
    required this.timeout,
  });

  final AuthTransport transport;
  final Uri apiBaseUri;
  final Duration timeout;

  Uri get _sessionEndpoint => apiBaseUri.resolve('auth/session');

  Future<IssuedOperatorSession> login({
    required String login,
    required String password,
  }) async {
    final normalizedLogin = login.trim();
    if (normalizedLogin.length < 3 || normalizedLogin.length > 64) {
      throw const InvalidOperatorCredentials();
    }
    if (password.isEmpty || password.length > 1024) {
      throw const InvalidOperatorCredentials();
    }

    final response = await transport.send(
      _sessionEndpoint,
      method: AuthHttpMethod.post,
      timeout: timeout,
      headers: const {
        'Accept': 'application/json',
        'Cache-Control': 'no-store',
        'Content-Type': 'application/json',
      },
      body: jsonEncode({'login': normalizedLogin, 'password': password}),
    );

    if (response.statusCode == 401) {
      throw const InvalidOperatorCredentials();
    }
    if (response.statusCode == 503) {
      throw const OperatorAuthenticationUnavailable();
    }
    if (!response.isSuccessful) {
      throw const OperatorAuthenticationUnavailable();
    }

    return IssuedOperatorSession.fromJson(response.body);
  }

  Future<void> logout(String token) async {
    try {
      final response = await transport.send(
        _sessionEndpoint,
        method: AuthHttpMethod.delete,
        timeout: timeout,
        headers: {
          'Accept': 'application/json',
          'Authorization': 'Bearer $token',
          'Cache-Control': 'no-store',
        },
      );
      if (response.statusCode == 401 || response.statusCode == 204) {
        return;
      }
      if (!response.isSuccessful) {
        throw const OperatorAuthenticationUnavailable();
      }
    } on OperatorAuthenticationUnavailable {
      rethrow;
    } catch (_) {
      throw const OperatorAuthenticationUnavailable();
    }
  }
}
