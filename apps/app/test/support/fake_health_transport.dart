import 'dart:async';

import 'package:meufinanceiro_app/core/health/health_http.dart';

class FakeHealthTransport implements HealthTransport {
  FakeHealthTransport.response({
    required int statusCode,
    required String body,
  }) : _handler = ((_, __) async {
          return HealthHttpResponse(statusCode: statusCode, body: body);
        });

  FakeHealthTransport.failure(Object error)
      : _handler = ((_, __) async => throw error);

  FakeHealthTransport.handler(
    Future<HealthHttpResponse> Function(Uri uri, Duration timeout) handler,
  ) : _handler = handler;

  final Future<HealthHttpResponse> Function(Uri uri, Duration timeout) _handler;

  int callCount = 0;
  Uri? lastUri;
  Duration? lastTimeout;

  @override
  Future<HealthHttpResponse> get(
    Uri uri, {
    required Duration timeout,
  }) async {
    callCount += 1;
    lastUri = uri;
    lastTimeout = timeout;
    return _handler(uri, timeout);
  }
}

FakeHealthTransport operationalHealthTransport() {
  return FakeHealthTransport.response(
    statusCode: 200,
    body: '''
{
  "status": "ok",
  "process": "ok",
  "database": "ok",
  "schema": "ok",
  "current_revision": "abc",
  "expected_revision": "abc"
}
''',
  );
}

FakeHealthTransport degradedHealthTransport() {
  return FakeHealthTransport.response(
    statusCode: 503,
    body: '''
{
  "status": "degraded",
  "process": "ok",
  "database": "unavailable",
  "schema": "unknown"
}
''',
  );
}

FakeHealthTransport timeoutHealthTransport() {
  return FakeHealthTransport.failure(TimeoutException('health timeout'));
}
