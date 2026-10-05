import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_account_detail_screen.dart';
import 'package:meufinanceiro_app/features/finance/financial_categorization_apply_dialog.dart';

import '../../support/fake_finance_backend.dart';

final _category = financeTestCategoryId(1);
final _rule = financeTestRuleId(1);

FakeFinanceBackend _backend({
  String accountScope = 'PERSONAL',
  String accountStatus = 'ACTIVE',
  List<FakeMovementSpec>? movements,
  Map<String, String>? allocations,
  List<String>? rules,
}) {
  final backend = FakeFinanceBackend(
    accountScope: accountScope,
    accountStatus: accountStatus,
    movements:
        movements ??
        [
          FakeMovementSpec(
            id: financeTestMovementId(1),
            description: 'Padaria Pão',
          ),
          FakeMovementSpec(
            id: financeTestMovementId(2),
            description: 'Padaria Sul',
          ),
          FakeMovementSpec(id: financeTestMovementId(3), description: 'Cinema'),
        ],
    allocations: allocations,
    categories: [
      fakeCategoryJson(id: _category, name: 'Mercado'),
      fakeCategoryJson(id: financeTestCategoryId(2), name: 'Lazer'),
    ],
  );
  backend.rules = rules ?? [fakeRuleJson(id: _rule, categoryId: _category)];
  return backend;
}

Future<void> _pumpDetail(
  WidgetTester tester,
  FakeFinanceBackend backend, {
  String operatorId = financeTestOwnerId,
}) async {
  tester.view.physicalSize = const Size(1400, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: financeTestOverrides(backend, operatorId: operatorId),
      child: const MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: FinancialAccountDetailScreen(
              accountId: financeTestAccountId,
            ),
          ),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _openApplyDialog(WidgetTester tester) async {
  await tester.tap(
    find.byKey(FinancialAccountDetailScreen.applyRulesButtonKey),
  );
  await tester.pumpAndSettle();
}

Key _origin(int movement) =>
    Key('financial-movement-rule-origin-${financeTestMovementId(movement)}');

int _count(WidgetTester tester, Key key) {
  final row = find.descendant(of: find.byKey(key), matching: find.byType(Row));
  final value = tester.widget<Row>(row.first).children.last as Text;
  return int.parse(value.data!);
}

void main() {
  group('entry points', () {
    testWidgets(
      'the owner of an active account can apply rules; others cannot',
      (tester) async {
        await _pumpDetail(tester, _backend());
        expect(
          tester
              .widget<FilledButton>(
                find.byKey(FinancialAccountDetailScreen.applyRulesButtonKey),
              )
              .onPressed,
          isNotNull,
        );
        expect(
          find.byKey(FinancialAccountDetailScreen.manageRulesButtonKey),
          findsOneWidget,
        );
      },
    );

    testWidgets('non-owner and archived accounts are read-only for rules', (
      tester,
    ) async {
      await _pumpDetail(
        tester,
        _backend(accountScope: 'HOUSEHOLD'),
        operatorId: financeTestOtherOperatorId,
      );
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(FinancialAccountDetailScreen.applyRulesButtonKey),
            )
            .onPressed,
        isNull,
      );
    });

    testWidgets('an archived account offers no apply', (tester) async {
      await _pumpDetail(tester, _backend(accountStatus: 'ARCHIVED'));
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(FinancialAccountDetailScreen.applyRulesButtonKey),
            )
            .onPressed,
        isNull,
      );
    });
  });

  group('preview then explicit apply', () {
    testWidgets(
      'preview writes nothing; confirmation applies; the summary is the backend result',
      (tester) async {
        final backend = _backend();
        await _pumpDetail(tester, backend);
        expect(backend.originReads, 1);

        await _openApplyDialog(tester);

        // preview shown, nothing written, confirmation still pending
        expect(
          find.byKey(FinancialCategorizationApplyDialog.dialogKey),
          findsOneWidget,
        );
        expect(backend.previewPosts, 1);
        expect(backend.applyPosts, 0);
        expect(backend.allocations, isEmpty);
        expect(
          _count(
            tester,
            FinancialCategorizationApplyDialog.previewCountKey('matched'),
          ),
          3,
        );
        final candidate = find.byKey(
          FinancialCategorizationApplyDialog.candidateKey(
            financeTestMovementId(1),
          ),
        );
        expect(candidate, findsOneWidget);
        expect(
          tester.widget<Text>(candidate).data,
          allOf(contains('Padaria Pão'), contains('→ Mercado')),
        );
        final confirm = find.byKey(
          FinancialCategorizationApplyDialog.confirmKey,
        );
        expect(
          find.descendant(
            of: confirm,
            matching: find.textContaining('3 classificações'),
          ),
          findsOneWidget,
        );

        await tester.tap(confirm);
        await tester.pumpAndSettle();

        expect(backend.applyPosts, 1);
        expect(
          find.byKey(FinancialCategorizationApplyDialog.headlineKey),
          findsOneWidget,
        );
        expect(
          tester
              .widget<Text>(
                find.byKey(FinancialCategorizationApplyDialog.headlineKey),
              )
              .data,
          startsWith('Concluído: 3 de 3'),
        );
        expect(
          find.byKey(FinancialCategorizationApplyDialog.partialNoticeKey),
          findsNothing,
        );
        // bulk refresh of the canonical state: one more read of each, nothing per row
        expect(backend.statementReads, 2);
        expect(backend.bulkReads, 2);
        expect(backend.originReads, 2);
        expect(backend.singleAllocationReads, 0);

        await tester.tap(
          find.byKey(FinancialCategorizationApplyDialog.closeKey),
        );
        await tester.pumpAndSettle();
        for (final i in [1, 2, 3]) {
          expect(
            find.byKey(_origin(i)),
            findsOneWidget,
            reason: 'Aplicada por regra',
          );
        }
        expect(find.text('Aplicada por regra'), findsNWidgets(3));
      },
    );

    testWidgets('a partial result is shown as partial with every count', (
      tester,
    ) async {
      final backend = _backend();
      backend.applyResponder = (items) {
        final results = [
          '{"movementId":"${items[0]['movementId']}","status":"CLASSIFIED","ruleId":"${items[0]['ruleId']}","allocationSetId":"${financeTestAllocationSetId(50)}"}',
          '{"movementId":"${items[1]['movementId']}","status":"ALREADY_CLASSIFIED","ruleId":null,"allocationSetId":null}',
          '{"movementId":"${items[2]['movementId']}","status":"CONFLICT","ruleId":null,"allocationSetId":null}',
        ];
        return '{"accountId":"$financeTestAccountId","requested":3,'
            '"counts":{"classified":1,"alreadyClassified":1,"ambiguous":0,'
            '"noMatch":0,"ineligible":0,"conflict":1,"failed":0},'
            '"results":[${results.join(',')}]}';
      };
      await _pumpDetail(tester, backend);
      await _openApplyDialog(tester);
      await tester.tap(
        find.byKey(FinancialCategorizationApplyDialog.confirmKey),
      );
      await tester.pumpAndSettle();

      expect(
        tester
            .widget<Text>(
              find.byKey(FinancialCategorizationApplyDialog.headlineKey),
            )
            .data,
        startsWith('Resultado parcial: 1 de 3'),
      );
      expect(
        find.byKey(FinancialCategorizationApplyDialog.partialNoticeKey),
        findsOneWidget,
      );
      expect(
        _count(
          tester,
          FinancialCategorizationApplyDialog.resultCountKey('classified'),
        ),
        1,
      );
      expect(
        _count(
          tester,
          FinancialCategorizationApplyDialog.resultCountKey(
            'alreadyClassified',
          ),
        ),
        1,
      );
      expect(
        _count(
          tester,
          FinancialCategorizationApplyDialog.resultCountKey('conflict'),
        ),
        1,
      );
    });

    testWidgets('ambiguity is visible and nothing can be applied for it', (
      tester,
    ) async {
      final backend = _backend();
      backend.previewBody =
          '{"accountId":"$financeTestAccountId","totalMovements":3,'
          '"counts":{"matched":0,"noMatch":1,"ambiguous":2,"ineligible":0,"alreadyClassified":0},'
          '"items":[{"movementId":"${financeTestMovementId(1)}","status":"AMBIGUOUS","ruleId":null,"targetCategoryId":null},'
          '{"movementId":"${financeTestMovementId(2)}","status":"AMBIGUOUS","ruleId":null,"targetCategoryId":null}],'
          '"itemsTruncated":false}';
      await _pumpDetail(tester, backend);
      await _openApplyDialog(tester);

      expect(
        _count(
          tester,
          FinancialCategorizationApplyDialog.previewCountKey('ambiguous'),
        ),
        2,
      );
      expect(
        find.byKey(
          FinancialCategorizationApplyDialog.ambiguousKey(
            financeTestMovementId(1),
          ),
        ),
        findsOneWidget,
      );
      expect(
        find.byKey(FinancialCategorizationApplyDialog.emptyNoticeKey),
        findsOneWidget,
      );
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(FinancialCategorizationApplyDialog.confirmKey),
            )
            .onPressed,
        isNull,
      );
      expect(backend.applyPosts, 0);
    });

    testWidgets(
      'an unknown outcome is not success, is not retried, and reloads the truth',
      (tester) async {
        final backend = _backend()..applyStatus = 502;
        await _pumpDetail(tester, backend);
        await _openApplyDialog(tester);
        await tester.tap(
          find.byKey(FinancialCategorizationApplyDialog.confirmKey),
        );
        await tester.pumpAndSettle();
        await tester.pump(const Duration(seconds: 5));

        expect(
          find.byKey(FinancialCategorizationApplyDialog.unknownNoticeKey),
          findsOneWidget,
        );
        expect(
          find.byKey(FinancialCategorizationApplyDialog.headlineKey),
          findsNothing,
        );
        expect(backend.applyPosts, 1, reason: 'no automatic retry');
        expect(
          backend.statementReads,
          2,
          reason: 'canonical state re-read once',
        );
        expect(
          find.byKey(FinancialCategorizationApplyDialog.confirmKey),
          findsNothing,
        );
        expect(
          find.byKey(FinancialCategorizationApplyDialog.refreshKey),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'a manual classification that wins the race keeps its row and gets no rule label',
      (tester) async {
        final backend = _backend();
        final manual = fakeAllocationJson(
          setId: financeTestAllocationSetId(900),
          movementId: financeTestMovementId(2),
          shares: [(financeTestCategoryId(2), '-75.25')],
        );
        backend.onApplyPost = (_) =>
            backend.allocations[financeTestMovementId(2)] = manual;
        await _pumpDetail(tester, backend);
        await _openApplyDialog(tester);
        await tester.tap(
          find.byKey(FinancialCategorizationApplyDialog.confirmKey),
        );
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<Text>(
                find.byKey(FinancialCategorizationApplyDialog.headlineKey),
              )
              .data,
          startsWith('Resultado parcial: 2 de 3'),
        );
        await tester.tap(
          find.byKey(FinancialCategorizationApplyDialog.closeKey),
        );
        await tester.pumpAndSettle();

        expect(find.byKey(_origin(1)), findsOneWidget);
        expect(
          find.byKey(_origin(2)),
          findsNothing,
          reason: 'manual stays manual',
        );
        expect(find.byKey(_origin(3)), findsOneWidget);
        expect(
          tester
              .widget<Text>(
                find.byKey(
                  Key(
                    'financial-movement-classification-${financeTestMovementId(2)}',
                  ),
                ),
              )
              .data,
          'Categoria: Lazer',
        );
      },
    );

    testWidgets('closing the dialog sends nothing', (tester) async {
      final backend = _backend();
      await _pumpDetail(tester, backend);
      await _openApplyDialog(tester);
      await tester.tap(find.byKey(FinancialCategorizationApplyDialog.closeKey));
      await tester.pumpAndSettle();
      expect(backend.applyPosts, 0);
      expect(backend.allocations, isEmpty);
    });
  });

  group('provenance label', () {
    testWidgets('only the current classification applied by a rule is labelled', (
      tester,
    ) async {
      final set1 = financeTestAllocationSetId(1);
      final backend = _backend(
        allocations: {
          financeTestMovementId(1): fakeAllocationJson(
            setId: set1,
            movementId: financeTestMovementId(1),
            shares: [(_category, '-75.25')],
          ),
          financeTestMovementId(2): fakeAllocationJson(
            setId: financeTestAllocationSetId(2),
            movementId: financeTestMovementId(2),
            shares: [(_category, '-75.25')],
          ),
        },
      );
      // an origin for movement 1's current set, and a STALE origin of a set that
      // is no longer current for movement 2 (history after a manual revision)
      backend.origins = {
        set1: fakeOriginJson(
          movementId: financeTestMovementId(1),
          setId: set1,
          ruleId: _rule,
        ),
        financeTestAllocationSetId(77): fakeOriginJson(
          movementId: financeTestMovementId(2),
          setId: financeTestAllocationSetId(77),
          ruleId: _rule,
        ),
      };
      await _pumpDetail(tester, backend);
      expect(find.byKey(_origin(1)), findsOneWidget);
      expect(find.byKey(_origin(2)), findsNothing);
      expect(find.byKey(_origin(3)), findsNothing);
      // the rule label never replaces the authoritative classification
      expect(
        tester
            .widget<Text>(
              find.byKey(
                Key(
                  'financial-movement-classification-${financeTestMovementId(1)}',
                ),
              ),
            )
            .data,
        'Categoria: Mercado',
      );
    });
  });
}
