class OperatorAuthenticationRequired implements Exception {
  const OperatorAuthenticationRequired();

  @override
  String toString() => 'Operator authentication is required.';
}

class SessionTokenVault {
  String? _token;

  bool get hasToken => _token != null;

  void store(String token) {
    if (token.isEmpty) {
      throw const FormatException('Authentication token is invalid.');
    }
    _token = token;
  }

  Future<T> use<T>(Future<T> Function(String token) operation) {
    final token = _token;
    if (token == null) {
      throw const OperatorAuthenticationRequired();
    }
    return operation(token);
  }

  String? take() {
    final token = _token;
    _token = null;
    return token;
  }

  void clear() {
    _token = null;
  }

  @override
  String toString() => 'SessionTokenVault(<redacted>)';
}
