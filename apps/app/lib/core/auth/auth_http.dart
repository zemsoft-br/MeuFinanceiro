enum AuthHttpMethod { get, post, delete }

class AuthHttpResponse {
  const AuthHttpResponse({required this.statusCode, required this.body});

  final int statusCode;
  final String body;

  bool get isSuccessful => statusCode >= 200 && statusCode < 300;
}

abstract interface class AuthTransport {
  Future<AuthHttpResponse> send(
    Uri uri, {
    required AuthHttpMethod method,
    required Duration timeout,
    Map<String, String> headers = const {},
    String? body,
  });
}
