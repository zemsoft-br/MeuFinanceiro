import 'package:meufinanceiro_app/core/health/health_http.dart';
import 'package:meufinanceiro_app/platform/health/health_transport_stub.dart'
    if (dart.library.html) 'package:meufinanceiro_app/platform/health/health_transport_web.dart'
    if (dart.library.io) 'package:meufinanceiro_app/platform/health/health_transport_io.dart'
    as implementation;

HealthTransport createDefaultHealthTransport() =>
    implementation.createHealthTransport();
