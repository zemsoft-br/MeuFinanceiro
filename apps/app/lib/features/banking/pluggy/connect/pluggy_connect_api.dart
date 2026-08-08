import 'dart:convert';

import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';

final _uuidPattern = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
);

const _connectionStatuses = <String>{
  'PENDING_USER_ACTION',
  'SYNC_REQUESTED',
  'SYNCING',
  'AVAILABLE',
  'PARTIAL',
  'REAUTHENTICATION_REQUIRED',
  'TEMPORARILY_UNAVAILABLE',
  'RATE_LIMITED',
  'DISCONNECTED',
  'FAILED',
};

class EphemeralConnectToken {
  EphemeralConnectToken._(this._value);

  String? _value;

  String take() {
    final value = _value;
    _value = null;
    if (value == null) {
      throw StateError('Connect token is no longer available.');
    }
    return value;
  }

  void clear() {
    _value = null;
  }

  @override
  String toString() => 'EphemeralConnectToken(<redacted>)';
}

class RegisteredPluggyConnection {
  const RegisteredPluggyConnection({
    required this.connectionId,
    required this.status,
    required this.requiresUserAction,
  });

  final String connectionId;
  final String status;
  final bool requiresUserAction;

  @override
  String toString() =>
      'RegisteredPluggyConnection(status=$status, requiresUserAction=$requiresUserAction)';
}

class PluggyConnectApi {
  const PluggyConnectApi(this.client);

  final AuthenticatedApiClient client;

  Future<EphemeralConnectToken> issueToken() async {
    final response = await client.post('banking/pluggy/connect-token');
    final values = _strictJsonObject(
      response.body,
      allowedKeys: const {'accessToken'},
      label: 'connect token response',
    );
    final accessToken = _boundedText(
      values['accessToken'],
      'accessToken',
      maxLength: 4096,
    );
    return EphemeralConnectToken._(accessToken);
  }

  Future<RegisteredPluggyConnection> registerItem(String itemId) async {
    final normalizedItemId = _boundedItemId(itemId);
    final response = await client.post(
      'banking/pluggy/connections',
      jsonBody: {'itemId': normalizedItemId},
    );
    final values = _strictJsonObject(
      response.body,
      allowedKeys: const {'connectionId', 'status', 'requiresUserAction'},
      label: 'connection registration response',
    );
    final connectionId = _uuid(values['connectionId'], 'connectionId');
    final status = _boundedText(values['status'], 'status', maxLength: 64);
    if (!_connectionStatuses.contains(status)) {
      throw const FormatException('Connection status is invalid.');
    }
    final requiresUserAction = values['requiresUserAction'];
    if (requiresUserAction is! bool) {
      throw const FormatException('requiresUserAction is invalid.');
    }
    return RegisteredPluggyConnection(
      connectionId: connectionId,
      status: status,
      requiresUserAction: requiresUserAction,
    );
  }
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
  if (values.length != allowedKeys.length ||
      values.keys.any((key) => !allowedKeys.contains(key)) ||
      allowedKeys.any((key) => !values.containsKey(key))) {
    throw FormatException('$label has an incompatible shape.');
  }
  return values;
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

String _boundedItemId(String value) {
  final normalized = _boundedText(value, 'itemId', maxLength: 512);
  if (normalized.contains('/') ||
      normalized.contains(r'\') ||
      normalized.contains('?') ||
      normalized.contains('#')) {
    throw const FormatException('itemId is invalid.');
  }
  return normalized;
}

String _uuid(Object? value, String fieldName) {
  final normalized = _boundedText(value, fieldName, maxLength: 36);
  if (!_uuidPattern.hasMatch(normalized)) {
    throw FormatException('$fieldName is invalid.');
  }
  return normalized.toLowerCase();
}
