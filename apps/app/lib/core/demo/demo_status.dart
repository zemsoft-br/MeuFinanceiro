import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/health/health_http.dart';
import 'package:meufinanceiro_app/core/health/health_transport.dart';

class DemoStatus {
  const DemoStatus({
    required this.enabled,
    required this.loaded,
    required this.fixtureId,
    required this.fixtureVersion,
    required this.referenceDate,
    required this.timezone,
    required this.currency,
    required this.scope,
    required this.contractChecksum,
    required this.loadedAt,
  });

  static const canonicalFixtureId = 'residencia-ipe-v1';
  static const canonicalFixtureVersion = 1;
  static const canonicalReferenceDate = '2026-11-01';
  static const canonicalTimezone = 'America/Sao_Paulo';
  static const canonicalCurrency = 'BRL';
  static const canonicalScope = 'foundation_only';
  static const canonicalContractChecksum =
      '34a7628233ff6c4f5eac6469b8e80fdedd5d65d80f825b4ecf72a069235a21a1';

  final bool enabled;
  final bool loaded;
  final String fixtureId;
  final int fixtureVersion;
  final DateTime referenceDate;
  final String timezone;
  final String currency;
  final String scope;
  final String contractChecksum;
  final DateTime? loadedAt;

  factory DemoStatus.fromPayload(Object? payload) {
    if (payload is! Map) {
      throw const FormatException('Demo status payload must be an object.');
    }

    final values = payload.map<String, Object?>(
      (key, value) => MapEntry(key.toString(), value),
    );
    final enabled = _requiredBool(values, 'enabled');
    final loaded = _requiredBool(values, 'loaded');
    final fixtureId = _requiredString(values, 'fixture_id');
    final fixtureVersion = _requiredInt(values, 'fixture_version');
    final referenceDateValue = _requiredString(values, 'reference_date');
    final timezone = _requiredString(values, 'timezone');
    final currency = _requiredString(values, 'currency');
    final scope = _requiredString(values, 'scope');
    final contractChecksum = _requiredString(values, 'contract_checksum');
    final loadedAt = _nullableDateTime(values, 'loaded_at');

    if (fixtureId != canonicalFixtureId ||
        fixtureVersion != canonicalFixtureVersion ||
        referenceDateValue != canonicalReferenceDate ||
        timezone != canonicalTimezone ||
        currency != canonicalCurrency ||
        scope != canonicalScope ||
        contractChecksum != canonicalContractChecksum) {
      throw const FormatException('Demo status contract is not canonical.');
    }

    final referenceDate = DateTime.tryParse(referenceDateValue);
    if (referenceDate == null) {
      throw const FormatException('Demo reference date is invalid.');
    }
    if (loaded && !enabled) {
      throw const FormatException('Disabled demo status cannot be loaded.');
    }
    if (loaded != (loadedAt != null)) {
      throw const FormatException('Demo loaded state is inconsistent.');
    }

    return DemoStatus(
      enabled: enabled,
      loaded: loaded,
      fixtureId: fixtureId,
      fixtureVersion: fixtureVersion,
      referenceDate: referenceDate,
      timezone: timezone,
      currency: currency,
      scope: scope,
      contractChecksum: contractChecksum,
      loadedAt: loadedAt,
    );
  }

  static bool _requiredBool(Map<String, Object?> values, String key) {
    final value = values[key];
    if (value is! bool) {
      throw FormatException('Demo status field $key must be a boolean.');
    }
    return value;
  }

  static int _requiredInt(Map<String, Object?> values, String key) {
    final value = values[key];
    if (value is! int) {
      throw FormatException('Demo status field $key must be an integer.');
    }
    return value;
  }

  static String _requiredString(Map<String, Object?> values, String key) {
    final value = values[key];
    if (value is! String || value.isEmpty) {
      throw FormatException('Demo status field $key must be a string.');
    }
    return value;
  }

  static DateTime? _nullableDateTime(
    Map<String, Object?> values,
    String key,
  ) {
    final value = values[key];
    if (value == null) {
      return null;
    }
    if (value is! String) {
      throw FormatException('Demo status field $key must be a timestamp.');
    }
    final parsed = DateTime.tryParse(value);
    if (parsed == null) {
      throw FormatException('Demo status field $key is invalid.');
    }
    return parsed;
  }
}

class DemoStatusService {
  const DemoStatusService({
    required this.transport,
    required this.endpoint,
    required this.timeout,
  });

  final HealthTransport transport;
  final Uri endpoint;
  final Duration timeout;

  Future<DemoStatus> check() async {
    final response = await transport.get(endpoint, timeout: timeout);
    if (!response.isSuccessful) {
      throw StateError(
        'Demo status request failed with HTTP ${response.statusCode}.',
      );
    }

    final Object? payload;
    try {
      payload = jsonDecode(response.body);
    } on FormatException {
      throw const FormatException('Demo status response is not valid JSON.');
    }
    return DemoStatus.fromPayload(payload);
  }
}

final demoStatusTransportProvider = Provider<HealthTransport>(
  (ref) => createDefaultHealthTransport(),
);

final demoStatusEndpointProvider = Provider<Uri>(
  (ref) => Uri.base.resolve('/api/v1/demo/status'),
);

final demoStatusTimeoutProvider = Provider<Duration>(
  (ref) => const Duration(seconds: 8),
);

final demoStatusServiceProvider = Provider<DemoStatusService>((ref) {
  return DemoStatusService(
    transport: ref.watch(demoStatusTransportProvider),
    endpoint: ref.watch(demoStatusEndpointProvider),
    timeout: ref.watch(demoStatusTimeoutProvider),
  );
});

final demoStatusProvider = FutureProvider<DemoStatus>((ref) async {
  return ref.watch(demoStatusServiceProvider).check();
});
