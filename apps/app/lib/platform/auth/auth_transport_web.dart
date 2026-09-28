// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:async';
import 'dart:html' as html;

import 'package:meufinanceiro_app/core/auth/auth_http.dart';

AuthTransport createAuthTransport() => const BrowserAuthTransport();

class BrowserAuthTransport implements AuthTransport {
  const BrowserAuthTransport();

  @override
  Future<AuthHttpResponse> send(
    Uri uri, {
    required AuthHttpMethod method,
    required Duration timeout,
    Map<String, String> headers = const {},
    String? body,
  }) {
    final request = html.HttpRequest();
    final completer = Completer<AuthHttpResponse>();
    var timedOut = false;

    void completeError(Object error) {
      if (!completer.isCompleted) {
        completer.completeError(error);
      }
    }

    request.open(method.name.toUpperCase(), uri.toString());
    request.withCredentials = true;
    for (final entry in headers.entries) {
      request.setRequestHeader(entry.key, entry.value);
    }

    request.onLoad.listen((_) {
      if (!completer.isCompleted) {
        completer.complete(
          AuthHttpResponse(
            statusCode: request.status ?? 0,
            body: request.responseText ?? '',
          ),
        );
      }
    });
    request.onError.listen((_) {
      completeError(StateError('Authentication request failed.'));
    });
    request.onAbort.listen((_) {
      completeError(
        timedOut
            ? TimeoutException('Authentication request timed out.', timeout)
            : StateError('Authentication request was aborted.'),
      );
    });

    final timer = Timer(timeout, () {
      timedOut = true;
      request.abort();
      completeError(
        TimeoutException('Authentication request timed out.', timeout),
      );
    });

    request.send(body);
    return completer.future.whenComplete(timer.cancel);
  }
}
