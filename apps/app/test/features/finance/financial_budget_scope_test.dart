import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_editor_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_screen.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_budget_backend.dart';
import '../../support/fake_finance_backend.dart';

// The realization account scope (P1 of the pre-PR gate): a HOUSEHOLD budget
// realizes from HOUSEHOLD accounts only, a PERSONAL one from the owner's PERSONAL
// accounts only. The server declares it; the client validates, shows it in plain
// text everywhere the budget is created, edited or read, and never recomputes it.

final _market = financeTestCategoryId(1);
final _mine = financeTestCategoryId(2);

FinancialCoreApi _api(FakeAuthTransport transport) => FinancialCoreApi(
  AuthenticatedApiClient(
    transport: transport,
    tokenVault: SessionTokenVault()..store(financeTestToken),
    apiBaseUri: Uri.parse('http://localhost/api/v1/'),
    timeout: const Duration(seconds: 2),
    onUnauthorized: () {},
  ),
);

FakeBudget _budget({
  int index = 1,
  String scope = 'HOUSEHOLD',
  String? declared,
}) => FakeBudget(
  index: index,
  period: '2026-10',
  scope: scope,
  name: scope == 'HOUSEHOLD' ? 'Casa' : 'Meu mês',
  lines: [
    FakeBudgetLine(scope == 'HOUSEHOLD' ? _market : _mine, 'EXPENSE', '100'),
  ],
)..realizationScope = declared;

FakeBudgetBackend _backend(List<FakeBudget> budgets) => FakeBudgetBackend(
  budgets: budgets,
  categories: [
    fakeCategoryJson(id: _market, name: 'Mercado'),
    fakeCategoryJson(
      id: _mine,
      name: 'Minha reserva',
      scope: 'PERSONAL',
      owner: financeTestOwnerId,
    ),
  ],
);

const _householdNotice =
    'Orçamento da casa: considera somente as contas da casa. Contas pessoais e '
    'compartilhadas não entram no realizado nem na cobertura, mesmo que um '
    'lançamento delas esteja numa categoria da casa; por isso o realizado '
    'pode ser menor que o gasto total do período.';
const _personalNotice =
    'Orçamento pessoal: considera somente as suas contas pessoais. Contas da '
    'casa, compartilhadas e de outros membros não entram no realizado nem '
    'na cobertura de não classificados.';

Future<void> _pump(WidgetTester tester, FakeBudgetBackend backend) async {
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
    ],
  );
  addTearDown(router.dispose);
  await tester.pumpWidget(
    ProviderScope(
      overrides: budgetTestOverrides(backend),
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  group('wire contract', () {
    test('the server-declared scope is parsed for both audiences', () async {
      final backend = _backend([
        _budget(),
        _budget(index: 2, scope: 'PERSONAL'),
      ]);
      final budgets = await _api(backend.transport).listBudgets('2026-10');
      expect(
        {for (final b in budgets) b.id: b.realizationAccountScope},
        {
          budgetTestId(1): FinancialBudgetRealizationAccountScope.householdOnly,
          budgetTestId(2):
              FinancialBudgetRealizationAccountScope.ownerPersonalOnly,
        },
      );
      expect(
        FinancialBudgetRealizationAccountScope.householdOnly.wireValue,
        'HOUSEHOLD_ONLY',
      );
      expect(
        FinancialBudgetRealizationAccountScope.ownerPersonalOnly.wireValue,
        'OWNER_PERSONAL_ONLY',
      );
    });

    test('the summary carries the same declared scope', () async {
      final backend = _backend([_budget()]);
      final summary = await _api(
        backend.transport,
      ).getBudgetSummary(budgetTestId(1));
      expect(
        summary.budget.realizationAccountScope,
        FinancialBudgetRealizationAccountScope.householdOnly,
      );
    });

    test(
      'a missing, unknown or contradictory scope is an invalid response',
      () async {
        final good = _backend([_budget()]);
        final json = good.budgetJson(good.byId(budgetTestId(1))!);
        final mutations = <String, String>{
          'missing': json.replaceFirst(
            '"realizationAccountScope":"HOUSEHOLD_ONLY",',
            '',
          ),
          'unknown': json.replaceFirst('"HOUSEHOLD_ONLY"', '"EVERYTHING"'),
          'personal declared for a household budget': json.replaceFirst(
            '"HOUSEHOLD_ONLY"',
            '"OWNER_PERSONAL_ONLY"',
          ),
          'lowercase': json.replaceFirst(
            '"HOUSEHOLD_ONLY"',
            '"household_only"',
          ),
          'not text': json.replaceFirst('"HOUSEHOLD_ONLY"', '1'),
        };
        for (final entry in mutations.entries) {
          good.listBodyOverride = '{"items":[${entry.value}]}';
          await expectLater(
            _api(good.transport).listBudgets('2026-10'),
            throwsFormatException,
            reason: entry.key,
          );
        }
        final personal = _backend([_budget(scope: 'PERSONAL')]);
        personal.listBodyOverride =
            '{"items":[${personal.budgetJson(personal.byId(budgetTestId(1))!).replaceFirst('"OWNER_PERSONAL_ONLY"', '"HOUSEHOLD_ONLY"')}]}';
        await expectLater(
          _api(personal.transport).listBudgets('2026-10'),
          throwsFormatException,
        );
      },
    );

    test(
      'a created budget must come back with the contract scope of its audience',
      () async {
        final backend = _backend([]);
        backend.postBodyOverride = backend
            .budgetJson(
              FakeBudget(
                index: 5,
                period: '2026-10',
                lines: [FakeBudgetLine(_market, 'EXPENSE', '100')],
              ),
            )
            .replaceFirst('"HOUSEHOLD_ONLY"', '"OWNER_PERSONAL_ONLY"');
        await expectLater(
          _api(backend.transport).createBudget(
            FinancialBudgetCreateInput(
              name: 'Casa',
              visibilityScope: FinancialVisibilityScope.household,
              currency: 'BRL',
              period: '2026-10',
              dateBasis: FinancialBudgetDateBasis.cash,
              lines: [
                FinancialBudgetLineInput(
                  categoryId: _market,
                  resultEffect: FinancialResultEffect.expense,
                  plannedAmount: '100',
                ),
              ],
            ),
          ),
          throwsFormatException,
        );
      },
    );

    test('the explanation texts state what is in and what is out', () {
      final household = financialBudgetRealizationScopeNotice(
        FinancialBudgetRealizationAccountScope.householdOnly,
      );
      expect(household, _householdNotice);
      expect(household, contains('somente as contas da casa'));
      expect(
        household,
        contains('Contas pessoais e compartilhadas não entram'),
      );
      expect(household, contains('nem na cobertura'));
      final personal = financialBudgetRealizationScopeNotice(
        FinancialBudgetRealizationAccountScope.ownerPersonalOnly,
      );
      expect(personal, _personalNotice);
      expect(personal, contains('somente as suas contas pessoais'));
      expect(
        financialBudgetRealizationScopeLabel(
          FinancialBudgetRealizationAccountScope.householdOnly,
        ),
        'Somente contas da casa',
      );
    });
  });

  group('loaded budget', () {
    testWidgets(
      'a household budget says that personal and shared accounts are out',
      (tester) async {
        await _pump(tester, _backend([_budget()]));
        expect(
          find.byKey(FinancialBudgetScreen.scopeNoticeKey),
          findsOneWidget,
        );
        expect(find.text('Somente contas da casa'), findsOneWidget);
        expect(find.text(_householdNotice), findsOneWidget);
        expect(find.text(_personalNotice), findsNothing);
      },
    );

    testWidgets(
      'a personal budget says only the owner personal accounts count',
      (tester) async {
        await _pump(tester, _backend([_budget(scope: 'PERSONAL')]));
        expect(find.text('Somente suas contas pessoais'), findsOneWidget);
        expect(find.text(_personalNotice), findsOneWidget);
        expect(find.text(_householdNotice), findsNothing);
      },
    );

    testWidgets(
      'the notice follows the selected budget and never the screen intro',
      (tester) async {
        final backend = _backend([
          _budget(),
          _budget(index: 2, scope: 'PERSONAL'),
        ]);
        await _pump(tester, backend);
        expect(find.text(_householdNotice), findsOneWidget);
        await tester.tap(
          find.byKey(FinancialBudgetScreen.selectorKey(budgetTestId(2))),
        );
        await tester.pumpAndSettle();
        expect(find.text(_personalNotice), findsOneWidget);
        expect(find.text(_householdNotice), findsNothing);
        expect(
          find.textContaining('das contas do escopo de cada orçamento'),
          findsOneWidget,
        );
      },
    );

    testWidgets('the notice is plain text, readable without hover', (
      tester,
    ) async {
      await _pump(tester, _backend([_budget()]));
      expect(
        find.descendant(
          of: find.byKey(FinancialBudgetScreen.scopeNoticeKey),
          matching: find.byType(Tooltip),
        ),
        findsNothing,
      );
      expect(
        find.descendant(
          of: find.byKey(FinancialBudgetScreen.scopeNoticeKey),
          matching: find.byType(Text),
        ),
        findsNWidgets(2),
      );
    });

    testWidgets('a contradictory declared scope is never presented as data', (
      tester,
    ) async {
      await _pump(tester, _backend([_budget(declared: 'OWNER_PERSONAL_ONLY')]));
      expect(find.byKey(FinancialBudgetScreen.errorKey), findsOneWidget);
      expect(find.byKey(FinancialBudgetScreen.scopeNoticeKey), findsNothing);
      expect(find.text('Resposta inválida'), findsOneWidget);
    });

    testWidgets(
      'realized and remaining stay the server numbers, scope or not',
      (tester) async {
        final backend = _backend([_budget()]);
        // The ledger the server derives from holds more, but the server only
        // reports what its declared scope counts; the client adds nothing.
        backend.realized[budgetTestId(1)] = {'$_market|EXPENSE': '40'};
        await _pump(tester, backend);
        expect(find.text('BRL 40,00'), findsOneWidget);
        expect(find.text('BRL 60,00'), findsOneWidget);
        expect(find.text('BRL 100,00'), findsOneWidget);
      },
    );
  });

  group('editor', () {
    testWidgets('create states the scope of the audience being chosen', (
      tester,
    ) async {
      await _pump(tester, _backend([]));
      await tester.tap(find.byKey(FinancialBudgetScreen.createKey));
      await tester.pumpAndSettle();
      final notice = find.byKey(FinancialBudgetEditorDialog.scopeNoticeKey);
      expect(notice, findsOneWidget);
      // HOUSEHOLD is the default audience.
      expect(
        find.descendant(of: notice, matching: find.text(_householdNotice)),
        findsOneWidget,
      );
      await tester.tap(find.byKey(FinancialBudgetEditorDialog.scopeKey));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Pessoal').last);
      await tester.pumpAndSettle();
      expect(
        find.descendant(of: notice, matching: find.text(_personalNotice)),
        findsOneWidget,
      );
      expect(
        find.descendant(of: notice, matching: find.text(_householdNotice)),
        findsNothing,
      );
    });

    testWidgets('edit states the scope the server declared for that budget', (
      tester,
    ) async {
      await _pump(tester, _backend([_budget()]));
      await tester.tap(find.byKey(FinancialBudgetScreen.editKey));
      await tester.pumpAndSettle();
      final notice = find.byKey(FinancialBudgetEditorDialog.scopeNoticeKey);
      expect(
        find.descendant(of: notice, matching: find.text(_householdNotice)),
        findsOneWidget,
      );
      expect(find.byKey(FinancialBudgetEditorDialog.scopeKey), findsNothing);
    });

    testWidgets('editing a personal budget states the personal scope', (
      tester,
    ) async {
      await _pump(tester, _backend([_budget(scope: 'PERSONAL')]));
      await tester.tap(find.byKey(FinancialBudgetScreen.editKey));
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byKey(FinancialBudgetEditorDialog.scopeNoticeKey),
          matching: find.text(_personalNotice),
        ),
        findsOneWidget,
      );
    });
  });
}
