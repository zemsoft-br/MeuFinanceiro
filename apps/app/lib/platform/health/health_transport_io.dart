import 'dart:convert';
import 'dart:io';

import 'package:meufinanceiro_app/core/health/health_http.dart';

HealthTransport createHealthTransport() => IoHealthTransport();

class IoHealthTransport implements HealthTransport {
  @override
  Future<HealthHttpResponse> get(Uri uri, {required Duration timeout}) async {
    if (!uri.hasScheme || uri.host.isEmpty) {
      throw const FormatException(
        'Native health endpoint must be an absolute URI.',
      );
    }

    final client = HttpClient()..connectionTimeout = timeout;

    try {
      final request = await client.getUrl(uri).timeout(timeout);
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      request.headers.set(HttpHeaders.cacheControlHeader, 'no-store');

      final response = await request.close().timeout(timeout);
      final body = await response
          .transform(utf8.decoder)
          .join()
          .timeout(timeout);

      return HealthHttpResponse(statusCode: response.statusCode, body: body);
    } finally {
      client.close(force: true);
    }
  }
}
