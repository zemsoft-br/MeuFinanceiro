import 'dart:convert';

final _uuidPattern = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
);

const _maxTokenLength = 512;
const _maxLoginLength = 64;

class OperatorPrincipal {
  const OperatorPrincipal({
    required this.operatorId,
    required this.installationId,
    required this.primaryResidenceId,
    required this.login,
    required this.role,
    required this.expiresAt,
  });

  final String operatorId;
  final String installationId;
  final String? primaryResidenceId;
  final String login;
  final String role;
  final DateTime expiresAt;

  bool get isInstallationAdmin => role == 'installation_admin';

  factory OperatorPrincipal.fromJson(String source) {
    final Object? decoded;
    try {
      decoded = jsonDecode(source);
    } on FormatException {
      throw const FormatException(
        'Operator session response is not valid JSON.',
      );
    }
    return OperatorPrincipal.fromPayload(decoded);
  }

  factory OperatorPrincipal.fromPayload(Object? payload) {
    final values = _strictObject(
      payload,
      allowedKeys: const {
        'operator_id',
        'installation_id',
        'primary_residence_id',
        'login',
        'role',
        'expires_at',
      },
      label: 'operator principal',
    );

    final operatorId = _uuid(values['operator_id'], 'operator_id');
    final installationId = _uuid(values['installation_id'], 'installation_id');
    final primaryResidenceId = _nullableUuid(
      values['primary_residence_id'],
      'primary_residence_id',
    );
    final login = _boundedText(
      values['login'],
      'login',
      maxLength: _maxLoginLength,
    );
    final role = _boundedText(values['role'], 'role', maxLength: 64);
    if (role != 'installation_admin') {
      throw const FormatException('Operator role is not supported.');
    }

    return OperatorPrincipal(
      operatorId: operatorId,
      installationId: installationId,
      primaryResidenceId: primaryResidenceId,
      login: login,
      role: role,
      expiresAt: _utcTimestamp(values['expires_at'], 'expires_at'),
    );
  }

  @override
  String toString() => 'OperatorPrincipal(<authenticated>)';
}

class IssuedOperatorSession {
  const IssuedOperatorSession._({
    required this.accessToken,
    required this.expiresAt,
    required this.principal,
  });

  final String accessToken;
  final DateTime expiresAt;
  final OperatorPrincipal principal;

  factory IssuedOperatorSession.fromJson(String source) {
    final Object? decoded;
    try {
      decoded = jsonDecode(source);
    } on FormatException {
      throw const FormatException('Authentication response is not valid JSON.');
    }

    final values = _strictObject(
      decoded,
      allowedKeys: const {
        'access_token',
        'token_type',
        'expires_at',
        'operator',
      },
      label: 'authentication response',
    );
    final tokenType = _boundedText(
      values['token_type'],
      'token_type',
      maxLength: 16,
    );
    if (tokenType != 'bearer') {
      throw const FormatException('Authentication token type is invalid.');
    }

    final accessToken = _boundedText(
      values['access_token'],
      'access_token',
      maxLength: _maxTokenLength,
    );
    if (accessToken.length < 32) {
      throw const FormatException('Authentication token is invalid.');
    }

    final expiresAt = _utcTimestamp(values['expires_at'], 'expires_at');
    final principal = OperatorPrincipal.fromPayload(values['operator']);
    if (principal.expiresAt != expiresAt) {
      throw const FormatException('Authentication expiration is inconsistent.');
    }

    return IssuedOperatorSession._(
      accessToken: accessToken,
      expiresAt: expiresAt,
      principal: principal,
    );
  }

  @override
  String toString() => 'IssuedOperatorSession(<redacted>)';
}

enum OperatorSessionPhase {
  signedOut,
  authenticating,
  authenticated,
  invalidCredentials,
  temporarilyUnavailable,
  expiredOrRevoked,
  signingOut,
}

class OperatorSessionState {
  const OperatorSessionState._({required this.phase, this.principal});

  const OperatorSessionState.signedOut()
    : this._(phase: OperatorSessionPhase.signedOut);

  const OperatorSessionState.authenticating()
    : this._(phase: OperatorSessionPhase.authenticating);

  const OperatorSessionState.authenticated(OperatorPrincipal principal)
    : this._(phase: OperatorSessionPhase.authenticated, principal: principal);

  const OperatorSessionState.invalidCredentials()
    : this._(phase: OperatorSessionPhase.invalidCredentials);

  const OperatorSessionState.temporarilyUnavailable()
    : this._(phase: OperatorSessionPhase.temporarilyUnavailable);

  const OperatorSessionState.expiredOrRevoked()
    : this._(phase: OperatorSessionPhase.expiredOrRevoked);

  const OperatorSessionState.signingOut()
    : this._(phase: OperatorSessionPhase.signingOut);

  final OperatorSessionPhase phase;
  final OperatorPrincipal? principal;

  bool get isAuthenticated =>
      phase == OperatorSessionPhase.authenticated && principal != null;

  bool get isBusy =>
      phase == OperatorSessionPhase.authenticating ||
      phase == OperatorSessionPhase.signingOut;

  @override
  String toString() => 'OperatorSessionState(${phase.name})';
}

Map<String, Object?> _strictObject(
  Object? payload, {
  required Set<String> allowedKeys,
  required String label,
}) {
  if (payload is! Map) {
    throw FormatException('$label must be an object.');
  }
  final values = payload.map<String, Object?>(
    (key, value) => MapEntry(key.toString(), value),
  );
  if (values.keys.any((key) => !allowedKeys.contains(key)) ||
      allowedKeys.any((key) => !values.containsKey(key))) {
    throw FormatException('$label has an incompatible shape.');
  }
  return values;
}

String _boundedText(Object? value, String fieldName, {required int maxLength}) {
  if (value is! String || value.isEmpty || value.length > maxLength) {
    throw FormatException('$fieldName is invalid.');
  }
  if (value != value.trim() ||
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

String? _nullableUuid(Object? value, String fieldName) {
  if (value == null) {
    return null;
  }
  return _uuid(value, fieldName);
}

DateTime _utcTimestamp(Object? value, String fieldName) {
  final source = _boundedText(value, fieldName, maxLength: 64);
  final parsed = DateTime.tryParse(source);
  if (parsed == null || !parsed.isUtc) {
    throw FormatException('$fieldName must be a UTC timestamp.');
  }
  return parsed;
}
