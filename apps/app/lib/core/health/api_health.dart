import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/health/health_http.dart';
import 'package:meufinanceiro_app/core/health/health_transport.dart';

enum ApiAvailability { operational, degraded, unavailable }

class ApiReadiness {
  const ApiReadiness({
    required this.status,
    required this.process,
    required this.database,
    required this.schema,
    required this.currentRevision,
    required this.expectedRevision,
  });

  const ApiReadiness.unknown()
    : status = 'unknown',
      process = 'unknown',
      database = 'unknown',
      schema = 'unknown',
      currentRevision = null,
      expectedRevision = null;

  final String status;
  final String process;
  final String database;
  final String schema;
  final String? currentRevision;
  final String? expectedRevision;

  factory ApiReadiness.fromPayload(Object? payload) {
    if (payload is! Map<String, Object?>) {
      return const ApiReadiness.unknown();
    }

    return ApiReadiness(
      status: _enumValue(payload['status'], const {'ok', 'degraded'}),
      process: _enumValue(payload['process'], const {'ok'}),
      database: _enumValue(payload['database'], const {'ok', 'unavailable'}),
      schema: _enumValue(payload['schema'], const {
        'ok',
        'outdated',
        'unavailable',
      }),
      currentRevision: _nullableString(payload['current_revision']),
      expectedRevision: _nullableString(payload['expected_revision']),
    );
  }

  static String _enumValue(Object? value, Set<String> allowed) {
    return value is String && allowed.contains(value) ? value : 'unknown';
  }

  static String? _nullableString(Object? value) {
    return value is String && value.isNotEmpty ? value : null;
  }
}

class ApiHealthSnapshot {
  const ApiHealthSnapshot({
    required this.availability,
    required this.readiness,
    required this.checkedAt,
    this.reason,
  });

  final ApiAvailability availability;
  final ApiReadiness? readiness;
  final DateTime checkedAt;
  final String? reason;
}

typedef HealthClock = DateTime Function();

class ApiHealthService {
  const ApiHealthService({
    required this.transport,
    required this.endpoint,
    required this.timeout,
    required this.clock,
  });

  final HealthTransport transport;
  final Uri endpoint;
  final Duration timeout;
  final HealthClock clock;

  Future<ApiHealthSnapshot> check() async {
    try {
      final response = await transport.get(endpoint, timeout: timeout);
      final payload = _decodePayload(response.body);
      final readiness = ApiReadiness.fromPayload(payload);
      final availability = _classify(response, readiness);

      return ApiHealthSnapshot(
        availability: availability,
        readiness: readiness,
        checkedAt: clock(),
      );
    } on TimeoutException {
      return ApiHealthSnapshot(
        availability: ApiAvailability.unavailable,
        readiness: null,
        checkedAt: clock(),
        reason: 'timeout',
      );
    } on Object {
      return ApiHealthSnapshot(
        availability: ApiAvailability.unavailable,
        readiness: null,
        checkedAt: clock(),
        reason: 'transport',
      );
    }
  }

  static Object? _decodePayload(String body) {
    if (body.trim().isEmpty) {
      return null;
    }

    try {
      final decoded = jsonDecode(body);
      if (decoded is Map) {
        return decoded.map<String, Object?>(
          (key, value) => MapEntry(key.toString(), value),
        );
      }
      return decoded;
    } on FormatException {
      return null;
    }
  }

  static ApiAvailability _classify(
    HealthHttpResponse response,
    ApiReadiness readiness,
  ) {
    if (readiness.status == 'degraded') {
      return ApiAvailability.degraded;
    }

    if (response.isSuccessful) {
      return ApiAvailability.operational;
    }

    return ApiAvailability.unavailable;
  }
}

final healthTransportProvider = Provider<HealthTransport>(
  (ref) => createDefaultHealthTransport(),
);

final healthEndpointProvider = Provider<Uri>(
  (ref) => Uri.base.resolve('/api/v1/health/ready'),
);

final healthTimeoutProvider = Provider<Duration>(
  (ref) => const Duration(seconds: 8),
);

final healthClockProvider = Provider<HealthClock>((ref) => DateTime.now);

final apiHealthServiceProvider = Provider<ApiHealthService>((ref) {
  return ApiHealthService(
    transport: ref.watch(healthTransportProvider),
    endpoint: ref.watch(healthEndpointProvider),
    timeout: ref.watch(healthTimeoutProvider),
    clock: ref.watch(healthClockProvider),
  );
});

final apiHealthProvider = FutureProvider<ApiHealthSnapshot>((ref) async {
  return ref.watch(apiHealthServiceProvider).check();
});
