import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/core/health/health_http.dart';

import '../../support/fake_health_transport.dart';

void main() {
  test('rejects invalid JSON without enabling demo mode', () async {
    final service = DemoStatusService(
      transport: FakeHealthTransport.response(statusCode: 200, body: '{'),
      endpoint: Uri.parse('http://localhost/api/v1/demo/status'),
      timeout: const Duration(seconds: 3),
    );

    await expectLater(service.check(), throwsA(isA<FormatException>()));
  });

  test('rejects a payload missing a required field', () async {
    final service = DemoStatusService(
      transport: FakeHealthTransport.response(
        statusCode: 200,
        body: '{"enabled":false}',
      ),
      endpoint: Uri.parse('http://localhost/api/v1/demo/status'),
      timeout: const Duration(seconds: 3),
    );

    await expectLater(service.check(), throwsA(isA<FormatException>()));
  });

  test('provider invalidation performs a side-effect-free retry', () async {
    var attempts = 0;
    final transport = FakeHealthTransport.handler((uri, timeout) async {
      attempts += 1;
      return HealthHttpResponse(statusCode: 200, body: _disabledPayload);
    });
    final container = ProviderContainer(
      overrides: [
        demoStatusTransportProvider.overrideWithValue(transport),
        demoStatusEndpointProvider.overrideWithValue(
          Uri.parse('http://localhost/api/v1/demo/status'),
        ),
        demoStatusTimeoutProvider.overrideWithValue(const Duration(seconds: 3)),
      ],
    );
    addTearDown(container.dispose);

    final first = await container.read(demoStatusProvider.future);
    container.invalidate(demoStatusProvider);
    final second = await container.read(demoStatusProvider.future);

    expect(first.enabled, isFalse);
    expect(second.enabled, isFalse);
    expect(attempts, 2);
    expect(transport.callCount, 2);
  });
}

const _disabledPayload = '''
{
  "enabled": false,
  "loaded": false,
  "fixture_id": "residencia-ipe-v1",
  "fixture_version": 1,
  "reference_date": "2026-11-01",
  "timezone": "America/Sao_Paulo",
  "currency": "BRL",
  "scope": "foundation_only",
  "contract_checksum": "34a7628233ff6c4f5eac6469b8e80fdedd5d65d80f825b4ecf72a069235a21a1",
  "loaded_at": null
}
''';
