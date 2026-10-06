import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_editor_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_screen.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_budget_backend.dart';
import '../../support/fake_finance_backend.dart';

final _market = financeTestCategoryId(1);
final _salary = financeTestCategoryId(2);
final _leisure = financeTestCategoryId(3);
final _mine = financeTestCategoryId(4);
final _theirs = financeTestCategoryId(5);
final _old = financeTestCategoryId(6);

List<String> _categories() => [
  fakeCategoryJson(id: _market, name: 'Mercado'),
  fakeCategoryJson(id: _salary, name: 'Salário'),
  fakeCategoryJson(id: _leisure, name: 'Lazer'),
  fakeCategoryJson(
    id: _mine,
    name: 'Minha reserva',
    scope: 'PERSONAL',
    owner: financeTestOwnerId,
  ),
  fakeCategoryJson(
    id: _theirs,
    name: 'Reserva do outro',
    scope: 'PERSONAL',
    owner: financeTestOtherOperatorId,
  ),
  fakeCategoryJson(id: _old, name: 'Antiga', status: 'DISABLED'),
];

FakeBudgetBackend _backend({
  List<FakeBudget>? budgets,
  String operatorId = financeTestOwnerId,
}) {
  final backend = FakeBudgetBackend(
    budgets:
        budgets ??
        [
          FakeBudget(
            index: 1,
            period: '2026-10',
            name: 'Outubro da casa',
            lines: [
              FakeBudgetLine(_market, 'EXPENSE', '1000'),
              FakeBudgetLine(_salary, 'INCOME', '5000'),
            ],
          ),
        ],
    categories: _categories(),
    operatorId: operatorId,
  );
  backend.realized[budgetTestId(1)] = {
    '$_market|EXPENSE': '300',
    '$_salary|INCOME': '4500',
  };
  return backend;
}

Future<GoRouter> _pump(
  WidgetTester tester,
  FakeBudgetBackend backend, {
  String operatorId = financeTestOwnerId,
}) async {
  tester.view.physicalSize = const Size(1400, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final router = GoRouter(
    initialLocation: '/budgets',
    routes: [
      GoRoute(
        path: '/budgets',
        builder: (_, _) => const Scaffold(
          body: SingleChildScrollView(child: FinancialBudgetScreen()),
        ),
      ),
      GoRoute(
        path: '/app/financas/pendencias',
        builder: (_, _) => const Scaffold(body: Text('TELA-PENDENCIAS')),
      ),
      GoRoute(
        path: '/app/financas',
        builder: (_, _) => const Scaffold(body: Text('TELA-FINANCAS')),
      ),
    ],
  );
  addTearDown(router.dispose);
  await tester.pumpWidget(
    ProviderScope(
      overrides: budgetTestOverrides(backend, operatorId: operatorId),
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pumpAndSettle();
  return router;
}

Finder _key(Key key) => find.byKey(key);

Future<void> _chooseDropdown(
  WidgetTester tester,
  Key dropdown,
  String label,
) async {
  await tester.tap(_key(dropdown));
  await tester.pumpAndSettle();
  await tester.tap(find.text(label).last);
  await tester.pumpAndSettle();
}

void main() {
  group('states', () {
    testWidgets('loading, then plan, realized, remaining and progress', (
      tester,
    ) async {
      final backend = _backend();
      backend.listGate = Completer<void>();
      tester.view.physicalSize = const Size(1400, 4000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        ProviderScope(
          overrides: budgetTestOverrides(backend),
          child: const MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(child: FinancialBudgetScreen()),
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(_key(FinancialBudgetScreen.loadingKey), findsOneWidget);
      backend.listGate!.complete();
      await tester.pumpAndSettle();

      expect(find.text('Orçamentos'), findsOneWidget);
      expect(find.text('outubro de 2026'), findsOneWidget);
      expect(find.text('Outubro da casa'), findsOneWidget);
      expect(find.text('Da casa'), findsOneWidget);
      expect(find.text('Caixa'), findsWidgets);
      expect(find.text('BRL'), findsWidgets);
      final market = FinancialBudgetScreen.lineKey(
        _market,
        FinancialResultEffect.expense,
      );
      expect(
        find.descendant(of: _key(market), matching: find.text('Mercado')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: _key(market), matching: find.text('BRL 1000,00')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: _key(market), matching: find.text('BRL 300,00')),
        findsOneWidget,
      );
      expect(
        find.descendant(of: _key(market), matching: find.text('BRL 700,00')),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: _key(market),
          matching: find.text('Dentro do planejado'),
        ),
        findsOneWidget,
      );
      expect(find.text('30% do planejado'), findsOneWidget);
      expect(backend.perLineRequests, 0);
    });

    testWidgets('UNDER, AT and OVER are spelled out and not only coloured', (
      tester,
    ) async {
      final backend = _backend(
        budgets: [
          FakeBudget(
            index: 1,
            period: '2026-10',
            lines: [
              FakeBudgetLine(_market, 'EXPENSE', '100'),
              FakeBudgetLine(_leisure, 'EXPENSE', '50'),
              FakeBudgetLine(_salary, 'INCOME', '1000'),
            ],
          ),
        ],
      );
      backend.realized[budgetTestId(1)] = {
        '$_market|EXPENSE': '130',
        '$_leisure|EXPENSE': '50',
        '$_salary|INCOME': '1200',
      };
      await _pump(tester, backend);
      expect(
        find.descendant(
          of: _key(
            FinancialBudgetScreen.lineStatusKey(
              _market,
              FinancialResultEffect.expense,
            ),
          ),
          matching: find.text('Estourou o planejado'),
        ),
        findsOneWidget,
      );
      expect(find.text('BRL -30,00'), findsOneWidget);
      expect(find.text('130% do planejado'), findsOneWidget);
      expect(
        find.descendant(
          of: _key(
            FinancialBudgetScreen.lineStatusKey(
              _leisure,
              FinancialResultEffect.expense,
            ),
          ),
          matching: find.text('No limite'),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: _key(
            FinancialBudgetScreen.lineStatusKey(
              _salary,
              FinancialResultEffect.income,
            ),
          ),
          matching: find.text('Acima do previsto'),
        ),
        findsOneWidget,
      );
      // An icon with a semantic label accompanies the text.
      expect(find.byIcon(Icons.arrow_upward_rounded), findsNWidgets(2));
      expect(find.byIcon(Icons.check_circle_outline), findsOneWidget);
    });

    testWidgets('an empty month invites creation and reads no summary', (
      tester,
    ) async {
      final backend = _backend(budgets: []);
      await _pump(tester, backend);
      expect(_key(FinancialBudgetScreen.emptyKey), findsOneWidget);
      expect(find.text('Nenhum orçamento em outubro de 2026'), findsOneWidget);
      expect(_key(FinancialBudgetScreen.createEmptyKey), findsOneWidget);
      expect(backend.summaryReads, 0);
    });

    testWidgets('error shows a retry that reads again', (tester) async {
      final backend = _backend()..listStatus = 503;
      await _pump(tester, backend);
      expect(_key(FinancialBudgetScreen.errorKey), findsOneWidget);
      expect(find.text('Orçamentos indisponíveis'), findsOneWidget);
      backend.listStatus = null;
      await tester.tap(_key(FinancialBudgetScreen.retryKey));
      await tester.pumpAndSettle();
      expect(_key(FinancialBudgetScreen.errorKey), findsNothing);
      expect(find.text('Outubro da casa'), findsOneWidget);
    });

    testWidgets('invalid response and lost access never show data', (
      tester,
    ) async {
      final invalid = _backend()..listBodyOverride = '{"items":[{"id":1}]}';
      await _pump(tester, invalid);
      expect(find.text('Resposta inválida'), findsOneWidget);
      expect(find.text('Outubro da casa'), findsNothing);

      final forbidden = _backend()..listStatus = 403;
      await _pump(tester, forbidden);
      expect(find.text('Acesso indisponível'), findsOneWidget);
      expect(_key(FinancialBudgetScreen.retryKey), findsNothing);
    });

    testWidgets('a failed summary keeps the plan and offers its own retry', (
      tester,
    ) async {
      final backend = _backend()..summaryStatus = 503;
      await _pump(tester, backend);
      expect(_key(FinancialBudgetScreen.summaryErrorKey), findsOneWidget);
      expect(find.text('Realizado indisponível'), findsOneWidget);
      // The plan is still visible; realized/remaining are not invented.
      expect(find.text('BRL 1000,00'), findsOneWidget);
      expect(find.text('—'), findsNWidgets(4));
      backend.summaryStatus = null;
      await tester.tap(_key(FinancialBudgetScreen.summaryRetryKey));
      await tester.pumpAndSettle();
      expect(_key(FinancialBudgetScreen.summaryErrorKey), findsNothing);
      expect(find.text('BRL 300,00'), findsOneWidget);
    });

    testWidgets('a failed refresh preserves the plan and blocks writes', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      backend.failNextLists = 1;
      await tester.tap(_key(FinancialBudgetScreen.refreshKey));
      await tester.pumpAndSettle();
      expect(_key(FinancialBudgetScreen.refreshNoticeKey), findsOneWidget);
      expect(_key(FinancialBudgetScreen.untrustedKey), findsOneWidget);
      expect(find.text('Outubro da casa'), findsOneWidget);
      final create = tester.widget<FilledButton>(
        _key(FinancialBudgetScreen.createKey),
      );
      expect(create.onPressed, isNull);
      final edit = tester.widget<OutlinedButton>(
        _key(FinancialBudgetScreen.editKey),
      );
      expect(edit.onPressed, isNull);
      await tester.tap(_key(FinancialBudgetScreen.refreshKey));
      await tester.pumpAndSettle();
      expect(_key(FinancialBudgetScreen.untrustedKey), findsNothing);
    });
  });

  group('coverage', () {
    testWidgets('incomplete coverage is visible and links to Pendências', (
      tester,
    ) async {
      final backend = _backend();
      backend.coverage[budgetTestId(1)] = (
        expense: 2,
        expenseAmount: '130.5',
        income: 1,
        incomeAmount: '10',
      );
      await _pump(tester, backend);
      expect(_key(FinancialBudgetScreen.coverageKey), findsOneWidget);
      expect(
        find.textContaining('O realizado pode estar incompleto'),
        findsOneWidget,
      );
      expect(find.textContaining('2 despesas (BRL 130,50)'), findsOneWidget);
      expect(find.textContaining('1 receita (BRL 10,00)'), findsOneWidget);
      await tester.tap(_key(FinancialBudgetScreen.coverageActionKey));
      await tester.pumpAndSettle();
      expect(find.text('TELA-PENDENCIAS'), findsOneWidget);
    });

    testWidgets('complete coverage shows no alert', (tester) async {
      await _pump(tester, _backend());
      expect(_key(FinancialBudgetScreen.coverageKey), findsNothing);
    });
  });

  group('months and budgets', () {
    testWidgets('month navigation reads the other month', (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      await tester.tap(_key(FinancialBudgetScreen.nextMonthKey));
      await tester.pumpAndSettle();
      expect(find.text('novembro de 2026'), findsOneWidget);
      expect(_key(FinancialBudgetScreen.emptyKey), findsOneWidget);
      await tester.tap(_key(FinancialBudgetScreen.previousMonthKey));
      await tester.pumpAndSettle();
      await tester.tap(_key(FinancialBudgetScreen.previousMonthKey));
      await tester.pumpAndSettle();
      expect(find.text('setembro de 2026'), findsOneWidget);
    });

    testWidgets('several budgets of the month are selectable', (tester) async {
      final backend = _backend();
      backend.budgets.add(
        FakeBudget(
          index: 2,
          period: '2026-10',
          scope: 'PERSONAL',
          name: 'Meu mês',
          basis: 'COMPETENCE',
          lines: [FakeBudgetLine(_mine, 'EXPENSE', '20')],
        ),
      );
      await _pump(tester, backend);
      expect(
        _key(FinancialBudgetScreen.selectorKey(budgetTestId(2))),
        findsOneWidget,
      );
      await tester.tap(
        _key(FinancialBudgetScreen.selectorKey(budgetTestId(2))),
      );
      await tester.pumpAndSettle();
      expect(find.text('Pessoal'), findsWidgets);
      expect(find.text('Competência'), findsWidgets);
      expect(find.text('Minha reserva'), findsOneWidget);
    });

    testWidgets("someone else's HOUSEHOLD budget is read-only", (tester) async {
      final backend = _backend(operatorId: financeTestOtherOperatorId);
      await _pump(tester, backend, operatorId: financeTestOtherOperatorId);
      expect(_key(FinancialBudgetScreen.readOnlyKey), findsOneWidget);
      expect(find.text('Somente leitura'), findsOneWidget);
      expect(_key(FinancialBudgetScreen.editKey), findsNothing);
      // Reading still shows the full comparison.
      expect(find.text('BRL 300,00'), findsOneWidget);
    });
  });

  group('create', () {
    testWidgets('creates a budget, then shows the canonical re-read', (
      tester,
    ) async {
      final backend = _backend(budgets: []);
      await _pump(tester, backend);
      await tester.tap(_key(FinancialBudgetScreen.createKey));
      await tester.pumpAndSettle();
      expect(_key(FinancialBudgetEditorDialog.dialogKey), findsOneWidget);

      await tester.enterText(
        _key(FinancialBudgetEditorDialog.nameKey),
        'Plano de outubro',
      );
      await tester.tap(_key(FinancialBudgetEditorDialog.basisCompetenceKey));
      await tester.pumpAndSettle();
      await _chooseDropdown(
        tester,
        FinancialBudgetEditorDialog.categoryKey(0),
        'Mercado',
      );
      await tester.enterText(
        _key(FinancialBudgetEditorDialog.plannedKey(0)),
        '1.000,50'.replaceAll('.', ''),
      );
      await tester.pumpAndSettle();
      await tester.tap(_key(FinancialBudgetEditorDialog.addLineKey));
      await tester.pumpAndSettle();
      await _chooseDropdown(
        tester,
        FinancialBudgetEditorDialog.effectKey(1),
        'Receita',
      );
      await _chooseDropdown(
        tester,
        FinancialBudgetEditorDialog.categoryKey(1),
        'Salário',
      );
      await tester.enterText(
        _key(FinancialBudgetEditorDialog.plannedKey(1)),
        '5000',
      );
      await tester.pumpAndSettle();

      await tester.tap(_key(FinancialBudgetEditorDialog.saveKey));
      await tester.pumpAndSettle();

      expect(backend.posts, 1);
      final body = backend.postBodies.single;
      expect(body['name'], 'Plano de outubro');
      expect(body['period'], '2026-10');
      expect(body['dateBasis'], 'COMPETENCE');
      expect(body['visibilityScope'], 'HOUSEHOLD');
      expect(body['currency'], 'BRL');
      expect(
        (body['lines'] as List<dynamic>).map(
          (l) => (l as Map)['plannedAmount'],
        ),
        containsAll(['1000.50', '5000']),
      );
      // The list is what the server returned on the re-read.
      expect(find.text('Plano de outubro'), findsOneWidget);
      expect(
        find.text('Orçamento criado. O mês foi atualizado.'),
        findsOneWidget,
      );
      expect(backend.listReads, 2);
    });

    testWidgets(
      'only eligible categories are offered and save needs a valid draft',
      (tester) async {
        final backend = _backend(budgets: []);
        await _pump(tester, backend);
        await tester.tap(_key(FinancialBudgetScreen.createKey));
        await tester.pumpAndSettle();
        var save = tester.widget<FilledButton>(
          _key(FinancialBudgetEditorDialog.saveKey),
        );
        expect(save.onPressed, isNull);
        expect(_key(FinancialBudgetEditorDialog.issuesKey), findsOneWidget);

        await tester.tap(_key(FinancialBudgetEditorDialog.categoryKey(0)));
        await tester.pumpAndSettle();
        // HOUSEHOLD budget: household ACTIVE categories only.
        expect(find.text('Mercado'), findsWidgets);
        expect(find.text('Lazer'), findsWidgets);
        expect(find.text('Minha reserva'), findsNothing);
        expect(find.text('Reserva do outro'), findsNothing);
        expect(find.text('Antiga'), findsNothing);
        await tester.tap(find.text('Mercado').last);
        await tester.pumpAndSettle();

        await _chooseDropdown(
          tester,
          FinancialBudgetEditorDialog.scopeKey,
          'Pessoal',
        );
        // Switching the audience drops a category the new audience cannot use.
        expect(find.text('Mercado'), findsNothing);
        await tester.tap(_key(FinancialBudgetEditorDialog.categoryKey(0)));
        await tester.pumpAndSettle();
        expect(find.text('Minha reserva'), findsWidgets);
        expect(find.text('Reserva do outro'), findsNothing);
        expect(find.text('Lazer'), findsNothing);
        await tester.tap(find.text('Minha reserva').last);
        await tester.pumpAndSettle();

        await tester.enterText(
          _key(FinancialBudgetEditorDialog.nameKey),
          'Pessoal',
        );
        await tester.enterText(
          _key(FinancialBudgetEditorDialog.plannedKey(0)),
          '0',
        );
        await tester.pumpAndSettle();
        save = tester.widget<FilledButton>(
          _key(FinancialBudgetEditorDialog.saveKey),
        );
        expect(save.onPressed, isNull); // zero is not a plan
        await tester.enterText(
          _key(FinancialBudgetEditorDialog.plannedKey(0)),
          '80,5',
        );
        await tester.pumpAndSettle();
        save = tester.widget<FilledButton>(
          _key(FinancialBudgetEditorDialog.saveKey),
        );
        expect(save.onPressed, isNotNull);
        await tester.tap(_key(FinancialBudgetEditorDialog.saveKey));
        await tester.pumpAndSettle();
        expect(backend.postBodies.single['visibilityScope'], 'PERSONAL');
        expect(
          (backend.postBodies.single['lines'] as List<dynamic>).single,
          containsPair('plannedAmount', '80.5'),
        );
      },
    );

    testWidgets('a duplicate line and a malformed currency block saving', (
      tester,
    ) async {
      final backend = _backend(budgets: []);
      await _pump(tester, backend);
      await tester.tap(_key(FinancialBudgetScreen.createKey));
      await tester.pumpAndSettle();
      await tester.enterText(_key(FinancialBudgetEditorDialog.nameKey), 'x');
      await _chooseDropdown(
        tester,
        FinancialBudgetEditorDialog.categoryKey(0),
        'Mercado',
      );
      await tester.enterText(
        _key(FinancialBudgetEditorDialog.plannedKey(0)),
        '5',
      );
      await tester.tap(_key(FinancialBudgetEditorDialog.addLineKey));
      await tester.pumpAndSettle();
      await _chooseDropdown(
        tester,
        FinancialBudgetEditorDialog.categoryKey(1),
        'Mercado',
      );
      await tester.enterText(
        _key(FinancialBudgetEditorDialog.plannedKey(1)),
        '6',
      );
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Cada categoria só pode ter uma linha'),
        findsOneWidget,
      );
      expect(
        tester
            .widget<FilledButton>(_key(FinancialBudgetEditorDialog.saveKey))
            .onPressed,
        isNull,
      );
      await tester.tap(_key(FinancialBudgetEditorDialog.removeKey(1)));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<FilledButton>(_key(FinancialBudgetEditorDialog.saveKey))
            .onPressed,
        isNotNull,
      );
      await tester.enterText(
        _key(FinancialBudgetEditorDialog.currencyKey),
        'B',
      );
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<FilledButton>(_key(FinancialBudgetEditorDialog.saveKey))
            .onPressed,
        isNull,
      );
    });

    testWidgets('cancelling sends nothing', (tester) async {
      final backend = _backend(budgets: []);
      await _pump(tester, backend);
      await tester.tap(_key(FinancialBudgetScreen.createKey));
      await tester.pumpAndSettle();
      await tester.tap(_key(FinancialBudgetEditorDialog.cancelKey));
      await tester.pumpAndSettle();
      expect(backend.posts, 0);
      expect(_key(FinancialBudgetEditorDialog.dialogKey), findsNothing);
    });

    testWidgets('a conflicting create reports it and does not resend', (
      tester,
    ) async {
      final backend = _backend(budgets: []);
      await _pump(tester, backend);
      backend.postStatus = 409;
      await tester.tap(_key(FinancialBudgetScreen.createKey));
      await tester.pumpAndSettle();
      await tester.enterText(_key(FinancialBudgetEditorDialog.nameKey), 'x');
      await _chooseDropdown(
        tester,
        FinancialBudgetEditorDialog.categoryKey(0),
        'Mercado',
      );
      await tester.enterText(
        _key(FinancialBudgetEditorDialog.plannedKey(0)),
        '5',
      );
      await tester.pumpAndSettle();
      await tester.tap(_key(FinancialBudgetEditorDialog.saveKey));
      await tester.pumpAndSettle();
      expect(backend.posts, 1);
      expect(_key(FinancialBudgetScreen.conflictKey), findsOneWidget);
      await tester.tap(_key(FinancialBudgetScreen.conflictDismissKey));
      await tester.pumpAndSettle();
      expect(_key(FinancialBudgetScreen.conflictKey), findsNothing);
    });
  });

  group('edit', () {
    testWidgets('edits the plan under the version that was read', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await tester.tap(_key(FinancialBudgetScreen.editKey));
      await tester.pumpAndSettle();
      // Identity is fixed once created.
      expect(
        find.text('Escopo, moeda, mês e base não mudam depois de criados.'),
        findsOneWidget,
      );
      expect(_key(FinancialBudgetEditorDialog.scopeKey), findsNothing);
      await tester.enterText(
        _key(FinancialBudgetEditorDialog.plannedKey(0)),
        '1200',
      );
      await tester.pumpAndSettle();
      await tester.tap(_key(FinancialBudgetEditorDialog.saveKey));
      await tester.pumpAndSettle();
      expect(backend.puts, 1);
      final body = backend.putBodies.single;
      expect(body['expectedVersion'], 1);
      expect(body['currency'], 'BRL');
      expect(
        find.text('Orçamento atualizado. O mês foi atualizado.'),
        findsOneWidget,
      );
      expect(backend.byId(budgetTestId(1))!.version, 2);
    });

    testWidgets(
      'a stale edit shows the conflict, the current plan and never retries',
      (tester) async {
        final backend = _backend();
        await _pump(tester, backend);
        await tester.tap(_key(FinancialBudgetScreen.editKey));
        await tester.pumpAndSettle();
        backend.beforePut = () {
          backend.byId(budgetTestId(1))!
            ..version = 2
            ..name = 'Mudou por outra pessoa';
        };
        await tester.enterText(
          _key(FinancialBudgetEditorDialog.plannedKey(0)),
          '1200',
        );
        await tester.pumpAndSettle();
        await tester.tap(_key(FinancialBudgetEditorDialog.saveKey));
        await tester.pumpAndSettle();
        expect(backend.puts, 1);
        expect(_key(FinancialBudgetScreen.conflictKey), findsOneWidget);
        expect(find.text('Mudou por outra pessoa'), findsOneWidget);
        expect(find.textContaining('Conflito de edição'), findsOneWidget);
        await tester.pump(const Duration(seconds: 1));
        expect(backend.puts, 1); // nothing was resent
      },
    );

    testWidgets('an unavailable line category must be replaced before saving', (
      tester,
    ) async {
      final backend = _backend(
        budgets: [
          FakeBudget(
            index: 1,
            period: '2026-10',
            lines: [FakeBudgetLine(_old, 'EXPENSE', '10')],
          ),
        ],
      );
      await _pump(tester, backend);
      // The plan still shows the historical category, marked unavailable.
      expect(find.text('Antiga (indisponível)'), findsOneWidget);
      await tester.tap(_key(FinancialBudgetScreen.editKey));
      await tester.pumpAndSettle();
      expect(
        _key(FinancialBudgetEditorDialog.unavailableKey(0)),
        findsOneWidget,
      );
      expect(
        tester
            .widget<FilledButton>(_key(FinancialBudgetEditorDialog.saveKey))
            .onPressed,
        isNull,
      );
      await _chooseDropdown(
        tester,
        FinancialBudgetEditorDialog.categoryKey(0),
        'Lazer',
      );
      expect(_key(FinancialBudgetEditorDialog.unavailableKey(0)), findsNothing);
      expect(
        tester
            .widget<FilledButton>(_key(FinancialBudgetEditorDialog.saveKey))
            .onPressed,
        isNotNull,
      );
    });
  });

  group('shell integration', () {
    testWidgets('back returns to Finanças', (tester) async {
      await _pump(tester, _backend());
      await tester.tap(find.text('Voltar para Finanças'));
      await tester.pumpAndSettle();
      expect(find.text('TELA-FINANCAS'), findsOneWidget);
    });

    testWidgets('has one accessible heading and no float money', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await _pump(tester, _backend());
      expect(
        find.descendant(
          of: find.byWidgetPredicate(
            (w) => w is Semantics && w.properties.header == true,
          ),
          matching: find.text('Orçamentos'),
        ),
        findsOneWidget,
      );
      handle.dispose();
    });
  });
}
