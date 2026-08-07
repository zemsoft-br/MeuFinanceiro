import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/platform/auth/auth_transport_stub.dart'
    if (dart.library.html) 'package:meufinanceiro_app/platform/auth/auth_transport_web.dart'
    if (dart.library.io) 'package:meufinanceiro_app/platform/auth/auth_transport_io.dart'
    as implementation;

AuthTransport createDefaultAuthTransport() =>
    implementation.createAuthTransport();
