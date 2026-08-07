import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';

enum AuthenticatedApiFailure {
  authenticationRequired,
  forbidden,
  rejected,
  temporarilyUnavailable,
  transportFailure,
}

class AuthenticatedApiException implements Exception {
  const AuthenticatedApiException(
    this.failure, {
    this.statusCode,
  });

  final AuthenticatedApiFailure failure;
  final int? statusCode;

  @override
  String toString() => 'Authenticated API request failed.';
}

class AuthenticatedApiClient {
  const AuthenticatedApiClient({
    required this.transport,
    required this.tokenVault,
    required this.apiBaseUri,
    required this.timeout,
    required this.onUnauthorized,
  });

  final AuthTransport transport;
  final SessionTokenVault tokenVault;
  final Uri apiBaseUri;
  final Duration timeout;
  final void Function() onUnauthorized;

  Future<AuthHttpResponse> get(String relativePath) {
    return _send(relativePath, method: AuthHttpMethod.get);
  }

  Future<AuthHttpResponse> post(
    String relativePath, {
    Map<String, Object?>? jsonBody,
  }) {
    return _send(
      relativePath,
      method: AuthHttpMethod.post,
      jsonBody: jsonBody,
    );
  }

  Future<AuthHttpResponse> delete(String relativePath) {
    return _send(relativePath, method: AuthHttpMethod.delete);
  }

  Future<AuthHttpResponse> _send(
    String relativePath, {
    required AuthHttpMethod method,
    Map<String, Object?>? jsonBody,
  }) async {
    final endpoint = _resolveRelativePath(relativePath);
    try {
      return await tokenVault.use((token) async {
        final headers = <String, String>{
          'Accept': 'application/json',
          'Authorization': 'Bearer $token',
          'Cache-Control': 'no-store',
          'Pragma': 'no-cache',
        };
        String? body;
        if (jsonBody != null) {
          headers['Content-Type'] = 'application/json';
          body = jsonEncode(jsonBody);
        }

        final response = await transport.send(
          endpoint,
          method: method,
          timeout: timeout,
          headers: headers,
          body: body,
        );

        if (response.statusCode == 401) {
          tokenVault.clear();
          _notifyUnauthorized();
          throw const AuthenticatedApiException(
            AuthenticatedApiFailure.authenticationRequired,
            statusCode: 401,
          );
        }
        if (response.statusCode == 403) {
          throw const AuthenticatedApiException(
            AuthenticatedApiFailure.forbidden,
            statusCode: 403,
          );
        }
        if (response.statusCode >= 500) {
          throw AuthenticatedApiException(
            AuthenticatedApiFailure.temporarilyUnavailable,
            statusCode: response.statusCode,
          );
        }
        if (!response.isSuccessful) {
          throw AuthenticatedApiException(
            AuthenticatedApiFailure.rejected,
            statusCode: response.statusCode,
          );
        }
        return response;
      });
    } on OperatorAuthenticationRequired {
      _notifyUnauthorized();
      throw const AuthenticatedApiException(
        AuthenticatedApiFailure.authenticationRequired,
      );
    } on AuthenticatedApiException {
      rethrow;
    } catch (_) {
      throw const AuthenticatedApiException(
        AuthenticatedApiFailure.transportFailure,
      );
    }
  }

  Uri _resolveRelativePath(String relativePath) {
    if (relativePath.isEmpty ||
        relativePath.contains('\\') ||
        relativePath.codeUnits.any((unit) => unit < 32 || unit == 127)) {
      throw const FormatException('API path must be relative.');
    }
    final parsed = Uri.tryParse(relativePath);
    if (parsed == null ||
        parsed.hasScheme ||
        parsed.hasAuthority ||
        parsed.hasFragment ||
        relativePath.startsWith('/') ||
        parsed.pathSegments.any((segment) => segment == '.' || segment == '..')) {
      throw const FormatException('API path must be relative.');
    }

    final endpoint = apiBaseUri.resolveUri(parsed);
    final basePath = apiBaseUri.path.endsWith('/')
        ? apiBaseUri.path
        : '${apiBaseUri.path}/';
    if (endpoint.scheme != apiBaseUri.scheme ||
        endpoint.authority != apiBaseUri.authority ||
        !endpoint.path.startsWith(basePath)) {
      throw const FormatException('API path escapes the configured API base.');
    }
    return endpoint;
  }

  void _notifyUnauthorized() {
    try {
      onUnauthorized();
    } catch (_) {
      // Local notification must not change the HTTP authentication semantics.
    }
  }

  @override
  String toString() => 'AuthenticatedApiClient(<redacted>)';
}

final authenticatedApiClientProvider = Provider<AuthenticatedApiClient>((ref) {
  return AuthenticatedApiClient(
    transport: ref.watch(authTransportProvider),
    tokenVault: ref.watch(sessionTokenVaultProvider),
    apiBaseUri: ref.watch(authApiBaseUriProvider),
    timeout: ref.watch(authRequestTimeoutProvider),
    onUnauthorized: () {
      ref
          .read(operatorSessionControllerProvider.notifier)
          .invalidateFromUnauthorized();
    },
  );
});
