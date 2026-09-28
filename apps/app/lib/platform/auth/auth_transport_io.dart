import 'dart:convert';
import 'dart:io';

import 'package:meufinanceiro_app/core/auth/auth_http.dart';

AuthTransport createAuthTransport() => IoAuthTransport();

class IoAuthTransport implements AuthTransport {
  @override
  Future<AuthHttpResponse> send(
    Uri uri, {
    required AuthHttpMethod method,
    required Duration timeout,
    Map<String, String> headers = const {},
    String? body,
  }) async {
    if (!uri.hasScheme || uri.host.isEmpty) {
      throw const FormatException(
        'Native authentication endpoint must be an absolute URI.',
      );
    }

    final client = HttpClient()..connectionTimeout = timeout;
    try {
      final request = await client
          .openUrl(method.name.toUpperCase(), uri)
          .timeout(timeout);
      for (final entry in headers.entries) {
        request.headers.set(entry.key, entry.value);
      }
      if (body != null) {
        request.write(body);
      }

      final response = await request.close().timeout(timeout);
      final responseBody = await response
          .transform(utf8.decoder)
          .join()
          .timeout(timeout);
      return AuthHttpResponse(
        statusCode: response.statusCode,
        body: responseBody,
      );
    } finally {
      client.close(force: true);
    }
  }
}
