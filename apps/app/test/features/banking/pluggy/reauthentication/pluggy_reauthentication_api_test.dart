import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_api.dart';

import '../../../../support/fake_auth_transport.dart';

const _sessionToken = 'SSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSSS';
const _connectToken = 'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC';
const _connectionId = '30000000-0000-4000-8000-000000000003';
const _itemId = 'synthetic-existing-item';

void main() {
  test(
    'reauthentication uses only local UUID path and returns single-use material',
    () async {
      final transport = FakeAuthTransport.response(
        statusCode: 200,
        body: '{"accessToken":"$_connectToken","itemId":"$_itemId"}',
      );
      final api = _api(transport);

      final material = await api.issueReauthenticationMaterial(_connectionId);
      final launch = material.take();

      expect(transport.calls, hasLength(1));
      expect(
        transport.calls.single.uri.path,
        '/api/v1/banking/pluggy/connections/$_connectionId/reauthentication-token',
      );
      expect(transport.calls.single.body, isNull);
      expect(launch.connectToken, _connectToken);
      expect(launch.updateItem, _itemId);
      expect(material.toString(), isNot(contains(_connectToken)));
      expect(material.toString(), isNot(contains(_itemId)));
      expect(launch.toString(), isNot(contains(_connectToken)));
      expect(launch.toString(), isNot(contains(_itemId)));
      expect(() => material.take(), throwsA(isA<StateError>()));
    },
  );

  test('invalid local connection UUID fails before transport', () async {
    final transport = FakeAuthTransport.response(statusCode: 200, body: '{}');
    final api = _api(transport);

    for (final connectionId in [
      '',
      'not-a-uuid',
      ' $_connectionId',
      '$_connectionId/child',
    ]) {
      await expectLater(
        api.issueReauthenticationMaterial(connectionId),
        throwsA(isA<FormatException>()),
      );
    }
    expect(transport.calls, isEmpty);
  });

  test(
    'reauthentication response is strict and validates provider item ID',
    () async {
      for (final body in [
        '{"accessToken":"$_connectToken"}',
        '{"accessToken":"$_connectToken","itemId":"$_itemId","extra":true}',
        '{"accessToken":"$_connectToken","itemId":" item "}',
        '{"accessToken":"$_connectToken","itemId":"item/child"}',
        '{"accessToken":42,"itemId":"$_itemId"}',
      ]) {
        final api = _api(
          FakeAuthTransport.response(statusCode: 200, body: body),
        );
        await expectLater(
          api.issueReauthenticationMaterial(_connectionId),
          throwsA(isA<FormatException>()),
        );
      }
    },
  );
}

PluggyConnectApi _api(FakeAuthTransport transport) {
  final vault = SessionTokenVault()..store(_sessionToken);
  return PluggyConnectApi(
    AuthenticatedApiClient(
      transport: transport,
      tokenVault: vault,
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () {},
    ),
  );
}
