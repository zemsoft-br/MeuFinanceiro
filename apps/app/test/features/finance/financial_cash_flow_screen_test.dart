import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/features/finance/financial_cash_flow_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_cash_flow_screen.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

import '../../support/fake_cash_flow_backend.dart';

Future<void> _pump(
  WidgetTester tester,
  FakeCashFlowBackend backend, {
  Size size = const Size(1920, 1080),
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      // A fresh scope per pump: never reuse a previous backend's state.
      key: UniqueKey(),
      overrides: [financialCoreApiProvider.overrideWithValue(backend.api)],
      child: const MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            padding: EdgeInsets.all(16),
            child: FinancialCashFlowScreen(),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('desktop Full HD shows real vs projected, risk and origins', (
    tester,
  ) async {
    final backend = FakeCashFlowBackend();
    await _pump(tester, backend);

    expect(find.byKey(FinancialCashFlowScreen.titleKey), findsOneWidget);
    expect(find.byKey(FinancialCashFlowScreen.noticeKey), findsOneWidget);
    expect(
      find.textContaining('nada nesta tela cria lançamentos'),
      findsOneWidget,
    );
    expect(find.textContaining('orçamentos, metas, projetos'), findsOneWidget);
    expect(find.text('Saldo real em 10/10/2026'), findsOneWidget);
    expect(find.text('BRL 2200,00'), findsWidgets);
    expect(find.text('Saldo projetado em 08/11/2026'), findsOneWidget);
    expect(find.text('BRL -300,00'), findsWidgets);
    expect(
      find.textContaining('Risco de saldo negativo a partir de 20/10/2026'),
      findsOneWidget,
    );
    expect(find.byKey(FinancialCashFlowScreen.comparisonKey), findsOneWidget);
    expect(find.text('Realizado'), findsWidgets);
    expect(find.text('Previsto · ocorrência gerada'), findsOneWidget);
    expect(find.text('Corrente · Transferência'), findsOneWidget);
    expect(find.text('Eventos usados no cálculo (4)'), findsOneWidget);
    expect(
      find.text('Projeção completa para as fontes consideradas'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
    expect(backend.methods.toSet(), {AuthHttpMethod.get});
  });

  testWidgets('event detail explains the origin and never offers a write', (
    tester,
  ) async {
    final backend = FakeCashFlowBackend();
    await _pump(tester, backend);

    await tester.ensureVisible(find.byKey(FinancialCashFlowScreen.eventKey(3)));
    await tester.tap(find.byKey(FinancialCashFlowScreen.eventKey(3)));
    await tester.pumpAndSettle();

    expect(find.byKey(FinancialCashFlowScreen.eventDetailKey), findsOneWidget);
    expect(find.textContaining('Não é um lançamento'), findsOneWidget);
    expect(find.text(cashFlowOccurrenceId), findsOneWidget);
    expect(find.text(cashFlowRuleId), findsOneWidget);
    expect(find.text('Vencimento previsto'), findsOneWidget);
    expect(find.text('Registrar'), findsNothing);
    await tester.tap(find.text('Fechar'));
    await tester.pumpAndSettle();
    expect(backend.methods.toSet(), {AuthHttpMethod.get});
  });

  testWidgets('incomplete projection and overdue items are said in text', (
    tester,
  ) async {
    final backend = FakeCashFlowBackend(
      cashFlow: (_) => cashFlowResponse(
        groups: [
          cashFlowGroup(
            status: 'INCOMPLETE',
            accounts: [
              cashFlowAccountSummary(
                cashFlowCheckingId,
                opening: false,
                firstNegative: '2026-10-20',
              ),
            ],
            issues: [
              {
                'code': 'OPENING_BALANCE_MISSING',
                'severity': 'INCOMPLETE',
                'count': 1,
                'accountIds': [cashFlowCheckingId],
              },
              {
                'code': 'OVERDUE_OCCURRENCES',
                'severity': 'ATTENTION',
                'count': 1,
                'accountIds': [cashFlowCheckingId],
              },
            ],
            events: [
              cashFlowEvent(
                date: '2026-10-10',
                kind: 'EXPECTED_OCCURRENCE',
                amount: '-2500',
                description: 'Aluguel',
                movementId: null,
                role: null,
                occurrenceId: cashFlowOccurrenceId,
                recurrenceId: cashFlowRuleId,
                ruleVersion: 1,
                periodStart: '2026-09-01',
                scheduledDate: '2026-09-20',
                overdue: true,
                expectedAmount: '-2500',
                balanceAfter: '-300',
              ),
            ],
          ),
        ],
      ),
    );
    await _pump(tester, backend);

    expect(
      find.text('Projeção incompleta: valores não confiáveis'),
      findsOneWidget,
    );
    expect(
      find.byKey(
        FinancialCashFlowScreen.issueKey(
          FinancialCashFlowIssueCode.openingBalanceMissing,
        ),
      ),
      findsOneWidget,
    );
    expect(find.textContaining('sem saldo inicial (Corrente)'), findsOneWidget);
    expect(
      find.textContaining('Registre ou pule em Recorrências'),
      findsOneWidget,
    );
    expect(find.text('Prevista vencida'), findsOneWidget);
    // Without an opening balance the screen never claims there is no deficit.
    expect(find.text('Risco de saldo negativo não avaliável'), findsOneWidget);
    expect(find.text('Saldo sem déficit'), findsNothing);
    expect(find.textContaining('Estimativa sem saldo inicial'), findsOneWidget);
    expect(find.textContaining('Sem saldo inicial'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('mobile width lays out without overflow', (tester) async {
    final backend = FakeCashFlowBackend();
    await _pump(tester, backend, size: const Size(390, 844));
    expect(find.byKey(FinancialCashFlowScreen.summaryKey), findsOneWidget);
    expect(find.byKey(FinancialCashFlowScreen.daysKey), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('1366 width and all days toggle', (tester) async {
    final backend = FakeCashFlowBackend();
    await _pump(tester, backend, size: const Size(1366, 768));
    expect(find.text('Mostrar todos os 30 dias'), findsOneWidget);
    await tester.ensureVisible(find.byKey(FinancialCashFlowScreen.allDaysKey));
    await tester.tap(find.byKey(FinancialCashFlowScreen.allDaysKey));
    await tester.pumpAndSettle();
    expect(find.text('Mostrar só dias com movimento'), findsOneWidget);
    expect(find.text('08/11/2026'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('many events are shown in pages, never silently cut', (
    tester,
  ) async {
    final events = [
      for (var i = 0; i < 150; i++)
        cashFlowEvent(
          date: '2026-10-10',
          movementId:
              '44000000-0000-4000-8000-${i.toString().padLeft(12, '0')}',
        ),
    ];
    final backend = FakeCashFlowBackend(
      cashFlow: (_) =>
          cashFlowResponse(groups: [cashFlowGroup(events: events)]),
    );
    await _pump(tester, backend);
    expect(find.text('Exibindo 100 de 150 eventos.'), findsOneWidget);
    await tester.ensureVisible(
      find.byKey(FinancialCashFlowScreen.moreEventsKey),
    );
    await tester.tap(find.byKey(FinancialCashFlowScreen.moreEventsKey));
    await tester.pumpAndSettle();
    expect(find.byKey(FinancialCashFlowScreen.moreEventsKey), findsNothing);
    expect(find.byKey(FinancialCashFlowScreen.eventKey(149)), findsOneWidget);
  });

  testWidgets('server refusal, empty and failures have explicit panels', (
    tester,
  ) async {
    final refusal = FakeCashFlowBackend(
      cashFlow: (_) => const AuthHttpResponse(statusCode: 422, body: '{}'),
    );
    await _pump(tester, refusal);
    expect(find.byKey(FinancialCashFlowScreen.rejectedKey), findsOneWidget);
    expect(find.textContaining('Nada foi omitido em silêncio'), findsOneWidget);

    final empty = FakeCashFlowBackend(
      accounts: const [],
      cashFlow: (_) => cashFlowResponse(groups: const []),
    );
    await _pump(tester, empty);
    expect(find.byKey(FinancialCashFlowScreen.emptyKey), findsOneWidget);

    for (final (status, text) in [
      (401, 'Sessão expirada'),
      (403, 'Acesso negado'),
      (404, 'Conta indisponível'),
      (409, 'Residência não definida'),
      (503, 'Fluxo de caixa indisponível'),
    ]) {
      final failing = FakeCashFlowBackend(
        cashFlow: (_) => AuthHttpResponse(statusCode: status, body: '{}'),
      );
      await _pump(tester, failing);
      expect(find.byKey(FinancialCashFlowScreen.errorKey), findsOneWidget);
      expect(find.text(text), findsOneWidget, reason: '$status');
    }

    final invalid = FakeCashFlowBackend(cashFlow: (_) => {'unexpected': true});
    await _pump(tester, invalid);
    expect(find.text('Resposta inválida'), findsOneWidget);
    expect(find.textContaining('Nenhum valor foi exibido'), findsOneWidget);
  });

  testWidgets('a failed manual refresh keeps data and flags it as stale', (
    tester,
  ) async {
    var fail = false;
    final backend = FakeCashFlowBackend(
      cashFlow: (_) => fail
          ? const AuthHttpResponse(statusCode: 503, body: '{}')
          : cashFlowResponse(),
    );
    await _pump(tester, backend);
    fail = true;
    await tester.tap(find.byKey(FinancialCashFlowScreen.refreshKey));
    await tester.pumpAndSettle();
    expect(find.byKey(FinancialCashFlowScreen.staleKey), findsOneWidget);
    expect(find.byKey(FinancialCashFlowScreen.summaryKey), findsOneWidget);

    fail = false;
    await tester.tap(find.byKey(FinancialCashFlowScreen.refreshKey));
    await tester.pumpAndSettle();
    expect(find.byKey(FinancialCashFlowScreen.staleKey), findsNothing);
    expect(backend.cashFlowCalls, hasLength(3));
  });

  testWidgets('period and account filters trigger a new canonical read', (
    tester,
  ) async {
    final backend = FakeCashFlowBackend(
      accounts: [
        cashFlowAccountListItem(cashFlowCheckingId),
        cashFlowAccountListItem(
          cashFlowArchivedId,
          name: 'Antiga',
          archived: true,
        ),
      ],
      cashFlow: (uri) {
        final from = uri.queryParameters['from'] ?? '2026-10-10';
        final through = uri.queryParameters['through'];
        final days = through == null
            ? 30
            : DateTime.parse(through).difference(DateTime.parse(from)).inDays +
                  1;
        return cashFlowResponse(
          from: from,
          days: days,
          groups: [
            cashFlowGroup(
              from: from,
              days: days,
              events: const [],
              firstNegative: null,
            ),
          ],
        );
      },
    );
    await _pump(tester, backend);

    expect(find.textContaining('Antiga · BRL · arquivada'), findsOneWidget);
    await tester.tap(
      find.byKey(
        FinancialCashFlowScreen.periodKey(FinancialCashFlowPeriod.currentMonth),
      ),
    );
    await tester.pumpAndSettle();
    expect(backend.cashFlowCalls.last.queryParameters['from'], '2026-10-01');
    expect(
      find.textContaining('Nenhum saldo negativo no período'),
      findsOneWidget,
    );

    await tester.tap(
      find.byKey(FinancialCashFlowScreen.accountFilterKey(cashFlowCheckingId)),
    );
    await tester.pumpAndSettle();
    expect(backend.cashFlowCalls.last.queryParametersAll['accountId'], [
      cashFlowCheckingId,
    ]);
    expect(backend.methods.toSet(), {AuthHttpMethod.get});
    expect(tester.takeException(), isNull);
  });
}
