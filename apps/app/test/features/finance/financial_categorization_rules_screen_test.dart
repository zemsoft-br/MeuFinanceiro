import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_categorization_rules_screen.dart';

import '../../support/fake_finance_backend.dart';

final _mercado = financeTestCategoryId(1);

FakeFinanceBackend _backend({List<String>? rules}) {
  final backend = FakeFinanceBackend(
    categories: [
      fakeCategoryJson(id: _mercado, name: 'Mercado'),
      fakeCategoryJson(
        id: financeTestCategoryId(2),
        name: 'Pessoal',
        scope: 'PERSONAL',
      ),
      fakeCategoryJson(
        id: financeTestCategoryId(3),
        name: 'Do outro',
        scope: 'PERSONAL',
        owner: financeTestOtherOperatorId,
      ),
      fakeCategoryJson(
        id: financeTestCategoryId(4),
        name: 'Antiga',
        status: 'DISABLED',
      ),
    ],
  );
  backend.rules = rules ?? [];
  return backend;
}

Future<void> _pump(
  WidgetTester tester,
  FakeFinanceBackend backend, {
  String operatorId = financeTestOwnerId,
}) async {
  tester.view.physicalSize = const Size(1400, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: financeTestOverrides(backend, operatorId: operatorId),
      child: const MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: FinancialCategorizationRulesScreen(),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _openCreate(WidgetTester tester) async {
  await tester.tap(
    find.byKey(FinancialCategorizationRulesScreen.createButtonKey),
  );
  await tester.pumpAndSettle();
}

Future<void> _chooseCategory(WidgetTester tester, String name) async {
  await tester.tap(
    find.byKey(FinancialCategorizationRulesScreen.categoryFieldKey),
  );
  await tester.pumpAndSettle();
  await tester.tap(find.text(name).last);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'empty state, then a created rule appears only after the backend confirms',
    (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      expect(
        find.byKey(FinancialCategorizationRulesScreen.emptyKey),
        findsOneWidget,
      );
      // fixed reads: rules + categories + accounts
      expect(backend.calls, hasLength(3));

      await _openCreate(tester);
      await tester.enterText(
        find.byKey(FinancialCategorizationRulesScreen.patternFieldKey),
        '  Padaria  ',
      );
      await _chooseCategory(tester, 'Mercado');
      await tester.enterText(
        find.byKey(FinancialCategorizationRulesScreen.priorityFieldKey),
        '25',
      );
      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.submitKey),
      );
      await tester.pumpAndSettle();

      expect(backend.rulePosts, 1);
      final body = backend.ruleBodies.single;
      expect(body['descriptionMatcher'], 'CONTAINS');
      expect(body['descriptionPattern'], 'Padaria');
      expect(body['targetCategoryId'], _mercado);
      expect(body['priority'], 25);
      expect(body.containsKey('accountId'), isFalse);
      expect(body.containsKey('resultEffect'), isFalse);
      expect(
        find.byKey(FinancialCategorizationRulesScreen.emptyKey),
        findsNothing,
      );
      expect(find.textContaining('“Padaria”'), findsOneWidget);
      expect(find.textContaining('Prioridade 25'), findsOneWidget);
      expect(find.text('Regra criada.'), findsOneWidget);
    },
  );

  testWidgets(
    'the form only offers ACTIVE categories the operator may target and validates input',
    (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _openCreate(tester);

      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.categoryFieldKey),
      );
      await tester.pumpAndSettle();
      expect(find.text('Mercado'), findsWidgets);
      expect(find.text('Pessoal'), findsWidgets);
      expect(
        find.text('Do outro'),
        findsNothing,
        reason: 'another owner\'s PERSONAL category',
      );
      expect(find.text('Antiga'), findsNothing, reason: 'DISABLED category');
      await tester.tap(find.text('Mercado').last);
      await tester.pumpAndSettle();

      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.submitKey),
      );
      await tester.pumpAndSettle();
      expect(
        find.text('Informe um texto válido de até 256 caracteres.'),
        findsOneWidget,
      );
      await tester.enterText(
        find.byKey(FinancialCategorizationRulesScreen.patternFieldKey),
        'ok',
      );
      await tester.enterText(
        find.byKey(FinancialCategorizationRulesScreen.priorityFieldKey),
        '0',
      );
      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.submitKey),
      );
      await tester.pumpAndSettle();
      expect(find.text('Informe um número de 1 a 1000.'), findsOneWidget);
      await tester.enterText(
        find.byKey(FinancialCategorizationRulesScreen.priorityFieldKey),
        '1001',
      );
      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.submitKey),
      );
      await tester.pumpAndSettle();
      expect(find.text('Informe um número de 1 a 1000.'), findsOneWidget);
      expect(backend.rulePosts, 0, reason: 'nothing was sent');
    },
  );

  testWidgets(
    'a rule can be limited to an owned account and to income or expense',
    (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _openCreate(tester);
      await tester.enterText(
        find.byKey(FinancialCategorizationRulesScreen.patternFieldKey),
        'Salário',
      );
      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.matcherExactKey),
      );
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.accountFieldKey),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Conta Corrente').last);
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.effectFieldKey),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Somente receitas').last);
      await tester.pumpAndSettle();
      await _chooseCategory(tester, 'Mercado');
      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.submitKey),
      );
      await tester.pumpAndSettle();

      final body = backend.ruleBodies.single;
      expect(body['descriptionMatcher'], 'EXACT');
      expect(body['accountId'], financeTestAccountId);
      expect(body['resultEffect'], 'INCOME');
      expect(
        find.textContaining('A descrição é igual a “Salário”'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Conta Corrente · Somente receitas'),
        findsOneWidget,
      );
    },
  );

  testWidgets(
    'an ambiguous creation is never shown as success and is not resent',
    (tester) async {
      final backend = _backend()..rulePostStatus = 503;
      await _pump(tester, backend);
      await _openCreate(tester);
      await tester.enterText(
        find.byKey(FinancialCategorizationRulesScreen.patternFieldKey),
        'Padaria',
      );
      await _chooseCategory(tester, 'Mercado');
      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.submitKey),
      );
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 5));

      expect(backend.rulePosts, 1, reason: 'zero automatic retries');
      expect(find.text('Regra criada.'), findsNothing);
      expect(
        find.textContaining('Não foi possível confirmar a criação'),
        findsOneWidget,
      );
      expect(
        find.byKey(FinancialCategorizationRulesScreen.emptyKey),
        findsOneWidget,
      );
    },
  );

  testWidgets(
    'disabling asks for confirmation and keeps the rule semantics visible',
    (tester) async {
      final rule = financeTestRuleId(1);
      final backend = _backend(
        rules: [
          fakeRuleJson(id: rule, pattern: 'Padaria', categoryId: _mercado),
        ],
      );
      await _pump(tester, backend);
      expect(find.text('Ativa'), findsOneWidget);

      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.disableKey(rule)),
      );
      await tester.pumpAndSettle();
      expect(backend.disabledRuleIds, isEmpty, reason: 'confirmation first');
      expect(
        find.textContaining(
          'Classificações já feitas por ela não são alteradas',
        ),
        findsOneWidget,
      );
      await tester.tap(
        find.byKey(FinancialCategorizationRulesScreen.disableConfirmKey),
      );
      await tester.pumpAndSettle();

      expect(backend.disabledRuleIds, [rule]);
      expect(find.text('Desabilitada'), findsOneWidget);
      expect(find.textContaining('“Padaria”'), findsOneWidget);
      expect(
        find.byKey(FinancialCategorizationRulesScreen.disableKey(rule)),
        findsNothing,
      );
    },
  );

  testWidgets('only the creator can disable and there is no edit affordance', (
    tester,
  ) async {
    final rule = financeTestRuleId(1);
    final backend = _backend(
      rules: [
        fakeRuleJson(
          id: rule,
          createdBy: financeTestOtherOperatorId,
          categoryId: _mercado,
        ),
      ],
    );
    await _pump(tester, backend);
    expect(
      tester
          .widget<OutlinedButton>(
            find.byKey(FinancialCategorizationRulesScreen.disableKey(rule)),
          )
          .onPressed,
      isNull,
    );
    expect(find.text('Editar'), findsNothing);
    expect(find.byIcon(Icons.edit_outlined), findsNothing);
    expect(find.textContaining('desabilite-a e crie outra'), findsOneWidget);
  });

  testWidgets('a failed load is an error state, never an empty list', (
    tester,
  ) async {
    final backend = _backend()..rulesReadStatus = 503;
    await _pump(tester, backend);
    expect(
      find.byKey(FinancialCategorizationRulesScreen.emptyKey),
      findsNothing,
    );
    expect(find.text('Serviço temporariamente indisponível'), findsOneWidget);
    expect(find.text('Tentar novamente'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(
            find.byKey(FinancialCategorizationRulesScreen.createButtonKey),
          )
          .onPressed,
      isNull,
    );
  });
}
