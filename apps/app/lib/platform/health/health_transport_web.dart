// ignore_for_file: deprecated_member_use

import 'dart:async';
import 'dart:html' as html;

import 'package:meufinanceiro_app/core/health/health_http.dart';

HealthTransport createHealthTransport() => const BrowserHealthTransport();

class BrowserHealthTransport implements HealthTransport {
  const BrowserHealthTransport();

  @override
  Future<HealthHttpResponse> get(
    Uri uri, {
    required Duration timeout,
  }) {
    final request = html.HttpRequest();
    final completer = Completer<HealthHttpResponse>();
    var timedOut = false;

    void completeError(Object error) {
      if (!completer.isCompleted) {
        completer.completeError(error);
      }
    }

    request
      ..open('GET', uri.toString())
      ..withCredentials = true
      ..setRequestHeader('Accept', 'application/json')
      ..setRequestHeader('Cache-Control', 'no-store');

    request.onLoad.listen((_) {
      if (!completer.isCompleted) {
        completer.complete(
          HealthHttpResponse(
            statusCode: request.status,
            body: request.responseText ?? '',
          ),
        );
      }
    });
    request.onError.listen((_) {
      completeError(StateError('Health request failed.'));
    });
    request.onAbort.listen((_) {
      completeError(
        timedOut
            ? TimeoutException('Health request timed out.', timeout)
            : StateError('Health request was aborted.'),
      );
    });

    final timer = Timer(timeout, () {
      timedOut = true;
      request.abort();
      completeError(TimeoutException('Health request timed out.', timeout));
    });

    request.send();
    return completer.future.whenComplete(timer.cancel);
  }
}
