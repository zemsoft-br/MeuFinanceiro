import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/core/health/health_http.dart';

import '../../support/fake_health_transport.dart';

void main() {
  final endpoint = Uri.parse('/api/v1/health/ready');
  const timeout = Duration(milliseconds: 250);
  final checkedAt = DateTime.utc(2026, 7, 20, 1, 0);

  ApiHealthService serviceFor(FakeHealthTransport transport) {
    return ApiHealthService(
      transport: transport,
      endpoint: endpoint,
      timeout: timeout,
      clock: () => checkedAt,
    );
  }

  test('classifies a valid readiness response as operational', () async {
    final transport = operationalHealthTransport();

    final snapshot = await serviceFor(transport).check();

    expect(snapshot.availability, ApiAvailability.operational);
    expect(snapshot.readiness?.process, 'ok');
    expect(snapshot.readiness?.database, 'ok');
    expect(snapshot.readiness?.schema, 'ok');
    expect(snapshot.checkedAt, checkedAt);
    expect(transport.callCount, 1);
    expect(transport.lastUri, endpoint);
    expect(transport.lastTimeout, timeout);
  });

  test('keeps successful responses operational with defensive parsing',
      () async {
    final transport = FakeHealthTransport.response(
      statusCode: 200,
      body: '{"unexpected":true}',
    );

    final snapshot = await serviceFor(transport).check();

    expect(snapshot.availability, ApiAvailability.operational);
    expect(snapshot.readiness?.status, 'unknown');
  });

  test('preserves degraded readiness independently of HTTP success', () async {
    final snapshot = await serviceFor(degradedHealthTransport()).check();

    expect(snapshot.availability, ApiAvailability.degraded);
    expect(snapshot.readiness?.database, 'unavailable');
  });

  test('classifies malformed or unsuccessful responses as unavailable',
      () async {
    final transport = FakeHealthTransport.response(
      statusCode: 500,
      body: '<html>failure</html>',
    );

    final snapshot = await serviceFor(transport).check();

    expect(snapshot.availability, ApiAvailability.unavailable);
    expect(snapshot.readiness?.status, 'unknown');
  });

  test('maps transport failure to unavailable without throwing', () async {
    final transport = FakeHealthTransport.failure(
      const FormatException('invalid endpoint'),
    );

    final snapshot = await serviceFor(transport).check();

    expect(snapshot.availability, ApiAvailability.unavailable);
    expect(snapshot.readiness, isNull);
    expect(snapshot.reason, 'transport');
  });

  test('maps timeout to unavailable and exposes timeout reason', () async {
    final snapshot = await serviceFor(timeoutHealthTransport()).check();

    expect(snapshot.availability, ApiAvailability.unavailable);
    expect(snapshot.reason, 'timeout');
  });

  test('passes the injected timeout to the transport', () async {
    final completer = Completer<HealthHttpResponse>();
    final transport = FakeHealthTransport.handler((uri, receivedTimeout) {
      expect(receivedTimeout, timeout);
      completer.complete(
        const HealthHttpResponse(statusCode: 200, body: '{"status":"ok"}'),
      );
      return completer.future;
    });

    await serviceFor(transport).check();

    expect(transport.lastTimeout, timeout);
  });
}
