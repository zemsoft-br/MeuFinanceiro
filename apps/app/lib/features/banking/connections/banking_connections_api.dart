import 'dart:convert';

import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';

final _uuidPattern = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
);
final _providerPattern = RegExp(r'^[a-z][a-z0-9_]{0,62}$');
final _timezoneSuffixPattern = RegExp(r'(Z|[+-][0-9]{2}:[0-9]{2})$');

const _connectionKeys = <String>{
  'connectionId',
  'provider',
  'status',
  'requiresUserAction',
  'lastSuccessfulSyncAt',
  'lastAttemptAt',
  'nextRefreshAllowedAt',
  'consentExpiresAt',
  'disconnectedAt',
  'updatedAt',
  'reauthenticationAvailable',
};

enum BankingConnectionStatus {
  pendingUserAction('PENDING_USER_ACTION'),
  syncRequested('SYNC_REQUESTED'),
  syncing('SYNCING'),
  available('AVAILABLE'),
  partial('PARTIAL'),
  reauthenticationRequired('REAUTHENTICATION_REQUIRED'),
  temporarilyUnavailable('TEMPORARILY_UNAVAILABLE'),
  rateLimited('RATE_LIMITED'),
  disconnected('DISCONNECTED'),
  failed('FAILED');

  const BankingConnectionStatus(this.wireValue);

  final String wireValue;

  static BankingConnectionStatus parse(Object? value) {
    final normalized = _boundedText(value, 'status', maxLength: 64);
    for (final status in values) {
      if (status.wireValue == normalized) {
        return status;
      }
    }
    throw const FormatException('status is invalid.');
  }
}

class LocalBankingConnection {
  const LocalBankingConnection({
    required this.connectionId,
    required this.provider,
    required this.status,
    required this.requiresUserAction,
    required this.lastSuccessfulSyncAt,
    required this.lastAttemptAt,
    required this.nextRefreshAllowedAt,
    required this.consentExpiresAt,
    required this.disconnectedAt,
    required this.updatedAt,
    required this.reauthenticationAvailable,
  });

  final String connectionId;
  final String provider;
  final BankingConnectionStatus status;
  final bool requiresUserAction;
  final DateTime? lastSuccessfulSyncAt;
  final DateTime? lastAttemptAt;
  final DateTime? nextRefreshAllowedAt;
  final DateTime? consentExpiresAt;
  final DateTime? disconnectedAt;
  final DateTime updatedAt;
  final bool reauthenticationAvailable;

  @override
  String toString() =>
      'LocalBankingConnection(provider=$provider, status=${status.wireValue}, requiresUserAction=$requiresUserAction, reauthenticationAvailable=$reauthenticationAvailable)';
}

class BankingConnectionsApi {
  const BankingConnectionsApi(this.client);

  final AuthenticatedApiClient client;

  Future<List<LocalBankingConnection>> listConnections() async {
    final response = await client.get('banking/connections');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: const {'connections'},
      label: 'banking connections response',
    );
    final rawConnections = root['connections'];
    if (rawConnections is! List) {
      throw const FormatException('connections is invalid.');
    }
    if (rawConnections.length > 1000) {
      throw const FormatException('connections exceeds the supported size.');
    }

    return List<LocalBankingConnection>.unmodifiable(
      rawConnections.map(_parseConnection),
    );
  }
}

LocalBankingConnection _parseConnection(Object? raw) {
  if (raw is! Map) {
    throw const FormatException('connection entry must be an object.');
  }
  final values = raw.map<String, Object?>(
    (key, value) => MapEntry(key.toString(), value),
  );
  _requireExactKeys(
    values,
    allowedKeys: _connectionKeys,
    label: 'connection entry',
  );

  final provider = _boundedText(values['provider'], 'provider', maxLength: 63);
  if (!_providerPattern.hasMatch(provider)) {
    throw const FormatException('provider is invalid.');
  }
  final requiresUserAction = values['requiresUserAction'];
  final reauthenticationAvailable = values['reauthenticationAvailable'];
  if (requiresUserAction is! bool) {
    throw const FormatException('requiresUserAction is invalid.');
  }
  if (reauthenticationAvailable is! bool) {
    throw const FormatException('reauthenticationAvailable is invalid.');
  }

  return LocalBankingConnection(
    connectionId: _uuid(values['connectionId'], 'connectionId'),
    provider: provider,
    status: BankingConnectionStatus.parse(values['status']),
    requiresUserAction: requiresUserAction,
    lastSuccessfulSyncAt: _optionalTimestamp(
      values['lastSuccessfulSyncAt'],
      'lastSuccessfulSyncAt',
    ),
    lastAttemptAt: _optionalTimestamp(values['lastAttemptAt'], 'lastAttemptAt'),
    nextRefreshAllowedAt: _optionalTimestamp(
      values['nextRefreshAllowedAt'],
      'nextRefreshAllowedAt',
    ),
    consentExpiresAt: _optionalTimestamp(
      values['consentExpiresAt'],
      'consentExpiresAt',
    ),
    disconnectedAt: _optionalTimestamp(
      values['disconnectedAt'],
      'disconnectedAt',
    ),
    updatedAt: _requiredTimestamp(values['updatedAt'], 'updatedAt'),
    reauthenticationAvailable: reauthenticationAvailable,
  );
}

Map<String, Object?> _strictJsonObject(
  String source, {
  required Set<String> allowedKeys,
  required String label,
}) {
  final Object? decoded;
  try {
    decoded = jsonDecode(source);
  } on FormatException {
    throw FormatException('$label is not valid JSON.');
  }
  if (decoded is! Map) {
    throw FormatException('$label must be an object.');
  }
  final values = decoded.map<String, Object?>(
    (key, value) => MapEntry(key.toString(), value),
  );
  _requireExactKeys(values, allowedKeys: allowedKeys, label: label);
  return values;
}

void _requireExactKeys(
  Map<String, Object?> values, {
  required Set<String> allowedKeys,
  required String label,
}) {
  if (values.length != allowedKeys.length ||
      values.keys.any((key) => !allowedKeys.contains(key)) ||
      allowedKeys.any((key) => !values.containsKey(key))) {
    throw FormatException('$label has an incompatible shape.');
  }
}

String _boundedText(
  Object? value,
  String fieldName, {
  required int maxLength,
}) {
  if (value is! String ||
      value.isEmpty ||
      value.length > maxLength ||
      value != value.trim() ||
      value.codeUnits.any((unit) => unit < 32 || unit == 127)) {
    throw FormatException('$fieldName is invalid.');
  }
  return value;
}

String _uuid(Object? value, String fieldName) {
  final normalized = _boundedText(value, fieldName, maxLength: 36);
  if (!_uuidPattern.hasMatch(normalized)) {
    throw FormatException('$fieldName is invalid.');
  }
  return normalized.toLowerCase();
}

DateTime? _optionalTimestamp(Object? value, String fieldName) {
  if (value == null) {
    return null;
  }
  return _requiredTimestamp(value, fieldName);
}

DateTime _requiredTimestamp(Object? value, String fieldName) {
  final source = _boundedText(value, fieldName, maxLength: 64);
  if (!_timezoneSuffixPattern.hasMatch(source)) {
    throw FormatException('$fieldName must include a timezone.');
  }
  final parsed = DateTime.tryParse(source);
  if (parsed == null) {
    throw FormatException('$fieldName is invalid.');
  }
  return parsed.toUtc();
}
