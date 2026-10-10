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
    expect(find.text('Risco de saldo negativo'), findsOneWidget);
    expect(
      find.textContaining(
        'Saldo consolidado previsto negativo a partir de 20/10/2026',
      ),
      findsOneWidget,
    );
    // A window that starts on the reference date has no history card.
    expect(find.byKey(FinancialCashFlowScreen.historicalRiskKey), findsNothing);
    expect(find.byKey(FinancialCashFlowScreen.estimateKey), findsNothing);
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
            anchoredFrom: null,
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
    // Without an opening balance the screen never claims there is no deficit,
    // and never shows a zero-based "deficit" as a risk either.
    expect(find.text('Risco de saldo negativo não avaliável'), findsOneWidget);
    expect(find.textContaining('Corrente: sem saldo inicial'), findsOneWidget);
    expect(find.text('Sem saldo negativo previsto'), findsNothing);
    expect(find.text('Risco de saldo negativo'), findsNothing);
    expect(find.textContaining('negativo a partir de'), findsNothing);
    expect(find.textContaining('Risco futuro não avaliável'), findsOneWidget);
    expect(find.byKey(FinancialCashFlowScreen.estimateKey), findsOneWidget);
    expect(
      find.textContaining('Saldo real em 10/10/2026 · estimativa'),
      findsOneWidget,
    );
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
      cashFlow: cashFlowEcho,
    );
    await _pump(tester, backend);

    expect(find.textContaining('Antiga · BRL · arquivada'), findsOneWidget);
    await tester.tap(
      find.byKey(
        FinancialCashFlowScreen.periodKey(FinancialCashFlowPeriod.next90),
      ),
    );
    await tester.pumpAndSettle();
    expect(backend.cashFlowCalls.last.queryParameters, {'days': '90'});
    await tester.tap(
      find.byKey(
        FinancialCashFlowScreen.periodKey(FinancialCashFlowPeriod.currentMonth),
      ),
    );
    await tester.pumpAndSettle();
    expect(backend.cashFlowCalls.last.queryParameters['from'], '2026-10-01');
    expect(find.text('Sem saldo negativo previsto'), findsOneWidget);
    expect(find.text('Histórico sem saldo negativo'), findsOneWidget);

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

  testWidgets('a refused first read keeps the filters usable and recovers', (
    tester,
  ) async {
    final backend = FakeCashFlowBackend(
      accounts: [
        cashFlowAccountListItem(cashFlowCheckingId),
        cashFlowAccountListItem(cashFlowSavingsId, name: 'Poupança'),
      ],
      cashFlow: (uri) =>
          uri.queryParameters['days'] == '7' ||
              uri.queryParametersAll['accountId'] != null
          ? cashFlowEcho(uri)
          : const AuthHttpResponse(statusCode: 422, body: '{}'),
    );
    await _pump(tester, backend);

    expect(find.byKey(FinancialCashFlowScreen.rejectedKey), findsOneWidget);
    expect(find.byKey(FinancialCashFlowScreen.summaryKey), findsNothing);
    // No server date yet: relative presets and accounts work, calendar windows
    // say why they wait.
    expect(_chipEnabled(tester, FinancialCashFlowPeriod.next7), isTrue);
    expect(_chipEnabled(tester, FinancialCashFlowPeriod.next90), isTrue);
    expect(_chipEnabled(tester, FinancialCashFlowPeriod.currentMonth), isFalse);
    expect(
      tester
          .widget<ChoiceChip>(
            find.byKey(FinancialCashFlowScreen.customPeriodKey),
          )
          .onSelected,
      isNull,
    );
    expect(
      tester
          .widget<FilterChip>(
            find.byKey(
              FinancialCashFlowScreen.accountFilterKey(cashFlowSavingsId),
            ),
          )
          .onSelected,
      isNotNull,
    );
    expect(
      find.byKey(FinancialCashFlowScreen.datedPeriodHintKey),
      findsOneWidget,
    );

    await tester.tap(
      find.byKey(
        FinancialCashFlowScreen.periodKey(FinancialCashFlowPeriod.next7),
      ),
    );
    await tester.pumpAndSettle();
    expect(backend.cashFlowCalls.last.queryParameters, {'days': '7'});
    expect(find.byKey(FinancialCashFlowScreen.rejectedKey), findsNothing);
    expect(find.byKey(FinancialCashFlowScreen.summaryKey), findsOneWidget);
    expect(find.textContaining('(7 dias)'), findsOneWidget);
    expect(
      find.byKey(FinancialCashFlowScreen.datedPeriodHintKey),
      findsNothing,
    );
    expect(_chipEnabled(tester, FinancialCashFlowPeriod.currentMonth), isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a refused first read also recovers by narrowing accounts', (
    tester,
  ) async {
    final backend = FakeCashFlowBackend(
      accounts: [
        cashFlowAccountListItem(cashFlowCheckingId),
        cashFlowAccountListItem(cashFlowSavingsId, name: 'Poupança'),
      ],
      cashFlow: (uri) => uri.queryParametersAll['accountId'] != null
          ? cashFlowEcho(uri)
          : const AuthHttpResponse(statusCode: 422, body: '{}'),
    );
    await _pump(tester, backend);
    expect(find.byKey(FinancialCashFlowScreen.rejectedKey), findsOneWidget);

    await tester.tap(
      find.byKey(FinancialCashFlowScreen.accountFilterKey(cashFlowCheckingId)),
    );
    await tester.pumpAndSettle();
    expect(backend.cashFlowCalls.last.queryParametersAll['accountId'], [
      cashFlowCheckingId,
    ]);
    expect(find.byKey(FinancialCashFlowScreen.rejectedKey), findsNothing);
    expect(find.byKey(FinancialCashFlowScreen.summaryKey), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  group('a window that crosses the reference date', () {
    Future<void> month(
      WidgetTester tester,
      Map<String, Object?> Function() october, {
      List<Map<String, Object?>>? accounts,
    }) async {
      final backend = FakeCashFlowBackend(
        accounts: accounts,
        cashFlow: (uri) => uri.queryParameters['from'] == '2026-10-01'
            ? october()
            : cashFlowEcho(uri),
      );
      await _pump(tester, backend);
      await tester.tap(
        find.byKey(
          FinancialCashFlowScreen.periodKey(
            FinancialCashFlowPeriod.currentMonth,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(backend.cashFlowCalls.last.queryParameters, {
        'from': '2026-10-01',
        'through': '2026-10-31',
      });
    }

    Map<String, Object?> october(String Function(String date) closing) =>
        cashFlowResponse(
          from: '2026-10-01',
          days: 31,
          groups: [
            cashFlowGroup(
              from: '2026-10-01',
              days: 31,
              events: const [],
              firstNegative: null,
              closing: closing,
            ),
          ],
        );

    String riskText(WidgetTester tester, Key key) => tester
        .widgetList<Text>(
          find.descendant(of: find.byKey(key), matching: find.byType(Text)),
        )
        .map((text) => text.data)
        .join(' | ');

    testWidgets('a deficit only in the past is history, not a future risk', (
      tester,
    ) async {
      await month(
        tester,
        () => october(
          (date) =>
              date.compareTo('2026-10-03') >= 0 &&
                  date.compareTo('2026-10-05') <= 0
              ? '-50'
              : '400',
        ),
      );
      final future = riskText(tester, FinancialCashFlowScreen.riskKey);
      expect(future, contains('Sem saldo negativo previsto'));
      expect(future, isNot(contains('03/10/2026')));
      final past = riskText(tester, FinancialCashFlowScreen.historicalRiskKey);
      expect(past, contains('Saldo negativo já ocorrido (histórico)'));
      expect(past, contains('Fato realizado, não previsão'));
      expect(past, contains('03/10/2026'));
      expect(find.text('Risco de saldo negativo'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('a future deficit is a risk and the past stays clean', (
      tester,
    ) async {
      await month(
        tester,
        () => october(
          (date) => date.compareTo('2026-10-25') >= 0 ? '-80' : '400',
        ),
      );
      final future = riskText(tester, FinancialCashFlowScreen.riskKey);
      expect(future, contains('Risco de saldo negativo'));
      expect(future, contains('a partir de 25/10/2026'));
      final past = riskText(tester, FinancialCashFlowScreen.historicalRiskKey);
      expect(past, contains('Histórico sem saldo negativo'));
    });

    testWidgets('both are reported, each on its own card', (tester) async {
      await month(
        tester,
        () => october(
          (date) => date == '2026-10-02' || date.compareTo('2026-10-28') >= 0
              ? '-5'
              : '400',
        ),
      );
      final future = riskText(tester, FinancialCashFlowScreen.riskKey);
      expect(future, contains('a partir de 28/10/2026'));
      expect(future, isNot(contains('02/10/2026')));
      final past = riskText(tester, FinancialCashFlowScreen.historicalRiskKey);
      expect(past, contains('ficou negativo em 02/10/2026'));
      expect(past, isNot(contains('28/10/2026')));
    });

    testWidgets('per account: a past deficit of one account is history', (
      tester,
    ) async {
      final accounts = [
        cashFlowAccountListItem(cashFlowCheckingId),
        cashFlowAccountListItem(cashFlowSavingsId, name: 'Poupança'),
      ];
      Map<String, Object?> response() => cashFlowResponse(
        from: '2026-10-01',
        days: 31,
        groups: [
          cashFlowGroup(
            from: '2026-10-01',
            days: 31,
            events: const [],
            firstNegative: null,
            closing: (_) => '400',
            accounts: [
              cashFlowAccountSummary(
                cashFlowCheckingId,
                risk: cashFlowRisk(evaluatedDays: 22),
                historicalRisk: cashFlowRisk(
                  minimum: '-20',
                  minimumDate: '2026-10-03',
                  firstNegative: '2026-10-03',
                  negativeDays: 1,
                  evaluatedDays: 9,
                ),
              ),
              cashFlowAccountSummary(
                cashFlowSavingsId,
                name: 'Poupança',
                risk: cashFlowRisk(evaluatedDays: 22),
                historicalRisk: cashFlowRisk(
                  minimumDate: '2026-10-01',
                  evaluatedDays: 9,
                ),
              ),
            ],
          ),
        ],
      );
      await month(tester, response, accounts: accounts);
      final future = riskText(tester, FinancialCashFlowScreen.riskKey);
      expect(future, contains('Sem saldo negativo previsto'));
      final past = riskText(tester, FinancialCashFlowScreen.historicalRiskKey);
      expect(past, contains('conta(s) ficaram: Corrente em 03/10/2026'));
      expect(
        find.textContaining('Ficou negativa em 03/10/2026'),
        findsOneWidget,
      );
      expect(find.textContaining('Negativo previsto'), findsNothing);
    });
  });

  testWidgets('days before a late opening balance are only estimates', (
    tester,
  ) async {
    final backend = FakeCashFlowBackend(
      cashFlow: (uri) => uri.queryParameters['from'] == '2026-10-01'
          ? cashFlowResponse(
              from: '2026-10-01',
              days: 31,
              groups: [
                cashFlowGroup(
                  from: '2026-10-01',
                  days: 31,
                  events: const [],
                  firstNegative: null,
                  anchoredFrom: '2026-10-05',
                  status: 'INCOMPLETE',
                  issues: [
                    {
                      'code': 'OPENING_BALANCE_AFTER_WINDOW_START',
                      'severity': 'INCOMPLETE',
                      'count': 1,
                      'accountIds': [cashFlowCheckingId],
                    },
                  ],
                  closing: (date) =>
                      date.compareTo('2026-10-05') < 0 ? '-100' : '500',
                ),
              ],
            )
          : cashFlowEcho(uri),
    );
    await _pump(tester, backend);
    expect(find.byKey(FinancialCashFlowScreen.estimateKey), findsNothing);
    await tester.tap(
      find.byKey(
        FinancialCashFlowScreen.periodKey(FinancialCashFlowPeriod.currentMonth),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.text('Projeção incompleta: valores não confiáveis'),
      findsOneWidget,
    );
    expect(
      find.textContaining('saldo inicial dentro do período'),
      findsOneWidget,
    );
    expect(
      find.text('Saldo no início (01/10/2026) · estimativa'),
      findsOneWidget,
    );
    expect(find.byKey(FinancialCashFlowScreen.estimateKey), findsOneWidget);
    expect(
      find.textContaining('Saldo inicial só a partir de 05/10/2026'),
      findsOneWidget,
    );
    final past = tester
        .widgetList<Text>(
          find.descendant(
            of: find.byKey(FinancialCashFlowScreen.historicalRiskKey),
            matching: find.byType(Text),
          ),
        )
        .map((text) => text.data)
        .join(' | ');
    // The pre-anchor "-100" is not presented as a deficit that happened.
    expect(past, contains('Avaliados 5 de 9 dias antes de 10/10/2026'));
    expect(past, contains('Histórico sem saldo negativo'));
    expect(past, isNot(contains('01/10/2026')));

    await tester.ensureVisible(find.byKey(FinancialCashFlowScreen.allDaysKey));
    await tester.tap(find.byKey(FinancialCashFlowScreen.allDaysKey));
    await tester.pumpAndSettle();
    expect(
      find.text('Realizado · saldo estimado (sem saldo inicial em vigor)'),
      findsNWidgets(4),
    );
    expect(find.textContaining('· negativo'), findsNothing);
    expect(find.text('BRL -100,00 (estimativa)'), findsNWidgets(4));

    // Recovery: a window from the reference date on is anchored again.
    await tester.ensureVisible(
      find.byKey(
        FinancialCashFlowScreen.periodKey(FinancialCashFlowPeriod.next30),
      ),
    );
    await tester.tap(
      find.byKey(
        FinancialCashFlowScreen.periodKey(FinancialCashFlowPeriod.next30),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(FinancialCashFlowScreen.estimateKey), findsNothing);
    expect(find.text('Saldo no início (10/10/2026)'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

bool _chipEnabled(WidgetTester tester, FinancialCashFlowPeriod period) =>
    tester
        .widget<ChoiceChip>(
          find.byKey(FinancialCashFlowScreen.periodKey(period)),
        )
        .onSelected !=
    null;
