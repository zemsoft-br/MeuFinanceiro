import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/app/app.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/features/auth/login_screen.dart';
import 'package:meufinanceiro_app/features/banking/connections/banking_connections_screen.dart';
import 'package:meufinanceiro_app/routing/app_router.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';

import '../support/fake_auth_transport.dart';

const _sessionToken = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const _connectionId = '30000000-0000-4000-8000-000000000003';

void main() {
  test('integration destination remains selected for Pluggy child routes', () {
    final overview = AppRoutes.destinationForLocation(AppRoutes.integrationsPath);
    final connect = AppRoutes.destinationForLocation(AppRoutes.pluggyConnectPath);
    final reauthentication = AppRoutes.destinationForLocation(
      AppRoutes.pluggyReauthenticationLocation(_connectionId),
    );

    expect(overview?.id, AppRouteId.integrations);
    expect(connect?.id, AppRouteId.integrations);
    expect(reauthentication?.id, AppRouteId.integrations);
    expect(AppRoutes.destinationForLocation('/componentes')?.id, AppRouteId.components);
    expect(AppRoutes.destinationForLocation('/sistema')?.id, AppRouteId.system);
  });

  testWidgets('protected integrations deep link resumes after login and loads locally', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final transport = FakeAuthTransport((uri, method, timeout, headers, body) async {
      if (uri.path.endsWith('/auth/session')) {
        return const AuthHttpResponse(statusCode: 200, body: _issuedSession);
      }
      if (uri.path.endsWith('/banking/connections')) {
        return const AuthHttpResponse(
          statusCode: 200,
          body: '{"connections":[]}',
        );
      }
      throw StateError('unexpected synthetic route');
    });

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          initialLocationProvider.overrideWithValue(AppRoutes.integrationsPath),
          authTransportProvider.overrideWithValue(transport),
          authApiBaseUriProvider.overrideWithValue(
            Uri.parse('http://localhost/api/v1/'),
          ),
          demoStatusProvider.overrideWithValue(
            AsyncValue.data(_demoStatus()),
          ),
          apiHealthProvider.overrideWithValue(
            AsyncValue.data(
              ApiHealthSnapshot(
                availability: ApiAvailability.operational,
                readiness: const ApiReadiness.unknown(),
                checkedAt: DateTime.utc(2026, 8, 8),
              ),
            ),
          ),
        ],
        child: const MeuFinanceiroApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(LoginScreen.submitButtonKey), findsOneWidget);
    expect(find.byKey(BankingConnectionsScreen.titleKey), findsNothing);

    await tester.enterText(find.byKey(LoginScreen.loginFieldKey), 'admin');
    await tester.enterText(
      find.byKey(LoginScreen.passwordFieldKey),
      'synthetic-password',
    );
    await tester.tap(find.byKey(LoginScreen.submitButtonKey));
    await tester.pumpAndSettle();

    expect(find.byKey(BankingConnectionsScreen.titleKey), findsOneWidget);
    expect(find.byKey(BankingConnectionsScreen.emptyKey), findsOneWidget);
    expect(find.byKey(LoginScreen.submitButtonKey), findsNothing);
    expect(
      transport.calls.where(
        (call) => call.uri.path.endsWith('/banking/connections'),
      ),
      hasLength(1),
    );
    expect(tester.takeException(), isNull);
  });
}

DemoStatus _demoStatus() {
  return DemoStatus(
    enabled: false,
    loaded: false,
    fixtureId: DemoStatus.canonicalFixtureId,
    fixtureVersion: DemoStatus.canonicalFixtureVersion,
    referenceDate: DateTime(2026, 11, 1),
    timezone: DemoStatus.canonicalTimezone,
    currency: DemoStatus.canonicalCurrency,
    scope: DemoStatus.canonicalScope,
    contractChecksum: DemoStatus.canonicalContractChecksum,
    loadedAt: null,
  );
}

const _issuedSession = '''
{
  "access_token":"$_sessionToken",
  "token_type":"bearer",
  "expires_at":"2027-08-08T00:00:00Z",
  "operator":{
    "operator_id":"10000000-0000-4000-8000-000000000001",
    "installation_id":"20000000-0000-4000-8000-000000000002",
    "primary_residence_id":"30000000-0000-4000-8000-000000000003",
    "login":"admin",
    "role":"installation_admin",
    "expires_at":"2027-08-08T00:00:00Z"
  }
}
''';
