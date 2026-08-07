import 'package:meufinanceiro_app/core/auth/auth_http.dart';

typedef AuthTransportHandler = Future<AuthHttpResponse> Function(
  Uri uri,
  AuthHttpMethod method,
  Duration timeout,
  Map<String, String> headers,
  String? body,
);

class AuthTransportCall {
  const AuthTransportCall({
    required this.uri,
    required this.method,
    required this.timeout,
    required this.headers,
    required this.body,
  });

  final Uri uri;
  final AuthHttpMethod method;
  final Duration timeout;
  final Map<String, String> headers;
  final String? body;

  @override
  String toString() => 'AuthTransportCall(${method.name}, $uri, <redacted>)';
}

class FakeAuthTransport implements AuthTransport {
  FakeAuthTransport(this.handler);

  factory FakeAuthTransport.response({
    required int statusCode,
    required String body,
  }) {
    return FakeAuthTransport(
      (uri, method, timeout, headers, requestBody) async =>
          AuthHttpResponse(statusCode: statusCode, body: body),
    );
  }

  final AuthTransportHandler handler;
  final List<AuthTransportCall> calls = [];

  @override
  Future<AuthHttpResponse> send(
    Uri uri, {
    required AuthHttpMethod method,
    required Duration timeout,
    Map<String, String> headers = const {},
    String? body,
  }) async {
    calls.add(
      AuthTransportCall(
        uri: uri,
        method: method,
        timeout: timeout,
        headers: Map<String, String>.unmodifiable(headers),
        body: body,
      ),
    );
    return handler(uri, method, timeout, headers, body);
  }
}
