class HealthHttpResponse {
  const HealthHttpResponse({required this.statusCode, required this.body});

  final int statusCode;
  final String body;

  bool get isSuccessful => statusCode >= 200 && statusCode < 300;
}

abstract interface class HealthTransport {
  Future<HealthHttpResponse> get(Uri uri, {required Duration timeout});
}
