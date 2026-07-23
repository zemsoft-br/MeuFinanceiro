import 'fake_health_transport.dart';

FakeHealthTransport disabledDemoTransport() {
  return FakeHealthTransport.response(
    statusCode: 200,
    body: '''
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
''',
  );
}

FakeHealthTransport enabledDemoTransport() {
  return FakeHealthTransport.response(
    statusCode: 200,
    body: '''
{
  "enabled": true,
  "loaded": true,
  "fixture_id": "residencia-ipe-v1",
  "fixture_version": 1,
  "reference_date": "2026-11-01",
  "timezone": "America/Sao_Paulo",
  "currency": "BRL",
  "scope": "foundation_only",
  "contract_checksum": "34a7628233ff6c4f5eac6469b8e80fdedd5d65d80f825b4ecf72a069235a21a1",
  "loaded_at": "2026-11-01T12:00:00Z"
}
''',
  );
}
