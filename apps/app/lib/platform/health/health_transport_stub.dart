import 'package:meufinanceiro_app/core/health/health_http.dart';

HealthTransport createHealthTransport() => const UnsupportedHealthTransport();

class UnsupportedHealthTransport implements HealthTransport {
  const UnsupportedHealthTransport();

  @override
  Future<HealthHttpResponse> get(Uri uri, {required Duration timeout}) {
    throw UnsupportedError(
      'Health check HTTP transport is unavailable on this platform.',
    );
  }
}
