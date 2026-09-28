import 'fake_health_transport.dart';

FakeHealthTransport disabledDemoTransport() {
  return FakeHealthTransport.response(
    statusCode: 200,
    body: '''
{
  "enabled": false,
  "loaded": false,
  "fixture_id": "residencia-ipe-v1",
  "fixture_version": 2,
  "reference_date": "2026-11-01",
  "timezone": "America/Sao_Paulo",
  "currency": "BRL",
  "scope": "finance_phase1",
  "contract_checksum": "a819b4913e35cabff3f20617b3e7837a6042b0c9243031a65b3f53fa7086d091",
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
  "fixture_version": 2,
  "reference_date": "2026-11-01",
  "timezone": "America/Sao_Paulo",
  "currency": "BRL",
  "scope": "finance_phase1",
  "contract_checksum": "a819b4913e35cabff3f20617b3e7837a6042b0c9243031a65b3f53fa7086d091",
  "loaded_at": "2026-11-01T12:00:00Z"
}
''',
  );
}
