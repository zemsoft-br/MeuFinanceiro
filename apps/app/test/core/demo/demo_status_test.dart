import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';

import '../../support/fake_demo_transport.dart';
import '../../support/fake_health_transport.dart';

void main() {
  const endpoint = 'http://localhost/api/v1/demo/status';
  const timeout = Duration(seconds: 3);

  DemoStatusService service(FakeHealthTransport transport) {
    return DemoStatusService(
      transport: transport,
      endpoint: Uri.parse(endpoint),
      timeout: timeout,
    );
  }

  test('parses the canonical enabled contract', () async {
    final transport = enabledDemoTransport();

    final status = await service(transport).check();

    expect(status.enabled, isTrue);
    expect(status.loaded, isTrue);
    expect(status.fixtureId, DemoStatus.canonicalFixtureId);
    expect(status.fixtureVersion, DemoStatus.canonicalFixtureVersion);
    expect(status.referenceDate, DateTime(2026, 11));
    expect(status.timezone, DemoStatus.canonicalTimezone);
    expect(status.currency, DemoStatus.canonicalCurrency);
    expect(status.scope, DemoStatus.canonicalScope);
    expect(status.contractChecksum, DemoStatus.canonicalContractChecksum);
    expect(status.loadedAt, DateTime.utc(2026, 11, 1, 12));
    expect(transport.lastUri, Uri.parse(endpoint));
    expect(transport.lastTimeout, timeout);
  });

  test(
    'parses the canonical disabled contract without a false positive',
    () async {
      final status = await service(disabledDemoTransport()).check();

      expect(status.enabled, isFalse);
      expect(status.loaded, isFalse);
      expect(status.loadedAt, isNull);
    },
  );

  test('rejects an unexpected scope', () async {
    final transport = FakeHealthTransport.response(
      statusCode: 200,
      body: _payload(scope: 'full'),
    );

    await expectLater(
      service(transport).check(),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects an inconsistent loaded state', () async {
    final transport = FakeHealthTransport.response(
      statusCode: 200,
      body: _payload(enabled: false, loaded: true),
    );

    await expectLater(
      service(transport).check(),
      throwsA(isA<FormatException>()),
    );
  });

  test('rejects non-successful responses', () async {
    final transport = FakeHealthTransport.response(statusCode: 503, body: '{}');

    await expectLater(service(transport).check(), throwsA(isA<StateError>()));
  });

  test('propagates transport timeouts', () async {
    final transport = FakeHealthTransport.failure(
      TimeoutException('demo timeout'),
    );

    await expectLater(
      service(transport).check(),
      throwsA(isA<TimeoutException>()),
    );
  });
}

String _payload({
  bool enabled = true,
  bool loaded = true,
  String scope = 'foundation_only',
}) {
  final loadedAt = loaded ? '"2026-11-01T12:00:00Z"' : 'null';
  return '''
{
  "enabled": $enabled,
  "loaded": $loaded,
  "fixture_id": "residencia-ipe-v1",
  "fixture_version": 1,
  "reference_date": "2026-11-01",
  "timezone": "America/Sao_Paulo",
  "currency": "BRL",
  "scope": "$scope",
  "contract_checksum": "34a7628233ff6c4f5eac6469b8e80fdedd5d65d80f825b4ecf72a069235a21a1",
  "loaded_at": $loadedAt
}
''';
}
