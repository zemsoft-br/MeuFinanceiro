import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_account_detail_screen.dart';

import '../../support/fake_finance_backend.dart';

Key _classifyButton(int movement) =>
    Key('financial-movement-classify-${financeTestMovementId(movement)}');
Key _label(int movement) =>
    Key('financial-movement-classification-${financeTestMovementId(movement)}');
Key _pickerTile(int category) =>
    Key('financial-classify-category-${financeTestCategoryId(category)}');

String _labelText(WidgetTester tester, int movement) =>
    tester.widget<Text>(find.byKey(_label(movement))).data!;

FakeFinanceBackend _backend({
  String accountScope = 'PERSONAL',
  String accountStatus = 'ACTIVE',
  List<FakeMovementSpec>? movements,
  Map<String, String>? allocations,
}) => FakeFinanceBackend(
  accountScope: accountScope,
  accountStatus: accountStatus,
  movements: movements,
  allocations: allocations,
  categories: [
    fakeCategoryJson(id: financeTestCategoryId(1), name: 'Moradia'),
    fakeCategoryJson(
      id: financeTestCategoryId(2),
      name: 'Energia',
      parentId: financeTestCategoryId(1),
    ),
    fakeCategoryJson(
      id: financeTestCategoryId(3),
      name: 'Pessoal',
      scope: 'PERSONAL',
    ),
    fakeCategoryJson(
      id: financeTestCategoryId(4),
      name: 'Do outro',
      scope: 'PERSONAL',
      owner: financeTestOtherOperatorId,
    ),
    fakeCategoryJson(
      id: financeTestCategoryId(5),
      name: 'Antiga',
      status: 'DISABLED',
    ),
  ],
);

String _allocation(int movement, List<int> categories, {int set = 1}) =>
    fakeAllocationJson(
      setId: financeTestAllocationSetId(set),
      movementId: financeTestMovementId(movement),
      shares: [for (final c in categories) (financeTestCategoryId(c), '-25')],
    );

Future<void> _pump(
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
      child: MaterialApp(
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

Future<void> _openPicker(WidgetTester tester, int movement) async {
  await tester.tap(find.byKey(_classifyButton(movement)));
  await tester.pumpAndSettle();
}

Future<void> _confirmPicker(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('financial-classify-confirm')));
}

void main() {
  testWidgets('rows show Sem categoria, a category name and N categorias', (
    tester,
  ) async {
    await _pump(
      tester,
      _backend(
        movements: [
          FakeMovementSpec(id: financeTestMovementId(1)),
          FakeMovementSpec(id: financeTestMovementId(2)),
          FakeMovementSpec(id: financeTestMovementId(3)),
        ],
        allocations: {
          financeTestMovementId(2): _allocation(2, [1], set: 2),
          financeTestMovementId(3): _allocation(3, [1, 2, 3], set: 3),
        },
      ),
    );

    expect(_labelText(tester, 1), 'Categoria: Sem categoria');
    expect(_labelText(tester, 2), 'Categoria: Moradia');
    expect(_labelText(tester, 3), 'Categoria: 3 categorias');
  });

  testWidgets('Classificar is offered only for eligible unclassified rows', (
    tester,
  ) async {
    await _pump(
      tester,
      _backend(
        movements: [
          FakeMovementSpec(id: financeTestMovementId(1)),
          FakeMovementSpec(id: financeTestMovementId(2)),
          FakeMovementSpec(
            id: financeTestMovementId(3),
            effect: 'NEUTRAL',
            description: 'Transferência',
          ),
          FakeMovementSpec(
            id: financeTestMovementId(4),
            role: 'REVERSAL',
            amount: '75.25',
            description: null,
          ),
        ],
        allocations: {
          financeTestMovementId(2): _allocation(2, [1], set: 2),
        },
      ),
    );

    expect(find.byKey(_classifyButton(1)), findsOneWidget);
    expect(find.text('Classificar'), findsOneWidget);
    expect(find.byKey(_classifyButton(2)), findsNothing);
    expect(find.byKey(_classifyButton(3)), findsNothing);
    expect(find.byKey(_classifyButton(4)), findsNothing);
    expect(_labelText(tester, 3), 'Categoria: Não se aplica');
    expect(_labelText(tester, 4), 'Categoria: Não se aplica');
  });

  testWidgets('non-owners and archived accounts are read-only', (tester) async {
    final shared = _backend(
      accountScope: 'HOUSEHOLD',
      allocations: {
        financeTestMovementId(2): _allocation(2, [1], set: 2),
      },
      movements: [
        FakeMovementSpec(id: financeTestMovementId(1)),
        FakeMovementSpec(id: financeTestMovementId(2)),
      ],
    );
    await _pump(tester, shared, operatorId: financeTestOtherOperatorId);

    expect(_labelText(tester, 1), 'Categoria: Sem categoria');
    expect(_labelText(tester, 2), 'Categoria: Moradia');
    expect(find.text('Classificar'), findsNothing);
  });

  testWidgets('archived accounts offer no classification', (tester) async {
    await _pump(tester, _backend(accountStatus: 'ARCHIVED'));

    expect(find.text('Classificar'), findsNothing);
  });

  testWidgets(
    'DISABLED history keeps its name but never appears in the picker',
    (tester) async {
      await _pump(
        tester,
        _backend(
          movements: [
            FakeMovementSpec(id: financeTestMovementId(1)),
            FakeMovementSpec(id: financeTestMovementId(2)),
          ],
          allocations: {
            financeTestMovementId(1): _allocation(1, [5]),
          },
        ),
      );

      expect(_labelText(tester, 1), 'Categoria: Antiga');
      await _openPicker(tester, 2);

      // ACTIVE eligible for a PERSONAL account of this owner only.
      expect(find.byKey(_pickerTile(1)), findsOneWidget);
      expect(find.byKey(_pickerTile(2)), findsOneWidget);
      expect(find.byKey(_pickerTile(3)), findsOneWidget);
      expect(find.byKey(_pickerTile(4)), findsNothing, reason: 'other owner');
      expect(find.byKey(_pickerTile(5)), findsNothing, reason: 'DISABLED');
      expect(
        find.descendant(
          of: find.byKey(const Key('financial-classify-dialog')),
          matching: find.text('Moradia > Energia'),
        ),
        findsOneWidget,
      );
      expect(find.text('Antiga'), findsNothing);
    },
  );

  testWidgets('a HOUSEHOLD account picker offers only HOUSEHOLD categories', (
    tester,
  ) async {
    await _pump(tester, _backend(accountScope: 'HOUSEHOLD'));
    await _openPicker(tester, 1);

    expect(find.byKey(_pickerTile(1)), findsOneWidget);
    expect(find.byKey(_pickerTile(2)), findsOneWidget);
    expect(find.byKey(_pickerTile(3)), findsNothing, reason: 'PERSONAL');
  });

  testWidgets('confirm needs a category and shows success only after 201', (
    tester,
  ) async {
    final backend = _backend();
    await _pump(tester, backend);
    await _openPicker(tester, 1);

    expect(
      tester
          .widget<FilledButton>(
            find.byKey(const Key('financial-classify-confirm')),
          )
          .onPressed,
      isNull,
      reason: 'no category chosen yet',
    );
    await tester.tap(find.byKey(_pickerTile(1)));
    await tester.pump();
    final gate = Completer<void>();
    backend.allocationPostGate = gate;
    await _confirmPicker(tester);
    await tester.pumpAndSettle();

    // The POST is on the wire but nothing may look classified yet.
    expect(backend.allocationPosts, 1);
    expect(_labelText(tester, 1), 'Categoria: Sem categoria');
    expect(find.text('Lançamento classificado.'), findsNothing);
    expect(
      find.byKey(_classifyButton(1)),
      findsNothing,
      reason: 'a second submission is blocked while the write is in flight',
    );

    gate.complete();
    await tester.pumpAndSettle();

    expect(_labelText(tester, 1), 'Categoria: Moradia');
    expect(find.text('Lançamento classificado.'), findsOneWidget);
    expect(find.byKey(_classifyButton(1)), findsNothing);
    expect(backend.allocationPosts, 1);
    expect(backend.postedBodies.single['allocations'], [
      {
        'categoryId': financeTestCategoryId(1),
        'amount': '-75.25',
        'currency': 'BRL',
      },
    ]);
  });

  testWidgets('a new category can be created inside the classification flow', (
    tester,
  ) async {
    final backend = _backend();
    await _pump(tester, backend);
    await _openPicker(tester, 1);

    await tester.tap(find.byKey(const Key('financial-classify-new-category')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('financial-category-name')),
      'Mercado',
    );
    await tester.tap(
      find.byKey(const ValueKey('financial-category-parent-personal')),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Pessoal').last);
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const Key('financial-category-create-confirm')),
    );
    await tester.pumpAndSettle();

    // Confirmed by the backend, offered with its hierarchy and preselected.
    final created = backend.categories.last;
    expect(created, contains('"name":"Mercado"'));
    expect(created, contains('"parentId":"${financeTestCategoryId(3)}"'));
    expect(backend.statementReads, 1, reason: 'no detail reload');
    expect(find.text('Pessoal > Mercado'), findsOneWidget);
    expect(
      tester
          .widget<FilledButton>(
            find.byKey(const Key('financial-classify-confirm')),
          )
          .onPressed,
      isNotNull,
    );

    await _confirmPicker(tester);
    await tester.pumpAndSettle();

    expect(_labelText(tester, 1), 'Categoria: Pessoal > Mercado');
    expect(backend.postedBodies.single['allocations'], [
      {
        'categoryId': financeTestCategoryId(501),
        'amount': '-75.25',
        'currency': 'BRL',
      },
    ]);
  });

  testWidgets('a rejected category creation shows an error and adds nothing', (
    tester,
  ) async {
    final backend = _backend()..categoryPostStatus = 422;
    await _pump(tester, backend);
    await _openPicker(tester, 1);

    await tester.tap(find.byKey(const Key('financial-classify-new-category')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('financial-category-name')),
      'Lazer',
    );
    await tester.tap(
      find.byKey(const Key('financial-category-create-confirm')),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('financial-classify-error')), findsOneWidget);
    expect(find.text('Lazer'), findsNothing);
    expect(backend.categories, hasLength(5));
  });

  testWidgets('409 reports reconciliation, not success, and shows the truth', (
    tester,
  ) async {
    final backend = _backend()..allocationPostStatus = 409;
    backend.onAllocationPost = (movementId) {
      backend.allocations[movementId] = _allocation(1, [2], set: 9);
    };
    await _pump(tester, backend);
    await _openPicker(tester, 1);
    await tester.tap(find.byKey(_pickerTile(1)));
    await tester.pump();

    await _confirmPicker(tester);
    await tester.pumpAndSettle();

    expect(
      find.textContaining('foi atualizado com a classificação persistida'),
      findsOneWidget,
    );
    expect(find.text('Lançamento classificado.'), findsNothing);
    expect(_labelText(tester, 1), 'Categoria: Moradia > Energia');
    expect(find.byKey(_classifyButton(1)), findsNothing);
    expect(backend.allocationPosts, 1, reason: 'never retried');
  });

  testWidgets('an unavailable backend never looks like a classification', (
    tester,
  ) async {
    final backend = _backend()..allocationPostStatus = 503;
    await _pump(tester, backend);
    await _openPicker(tester, 1);
    await tester.tap(find.byKey(_pickerTile(1)));
    await tester.pump();

    await _confirmPicker(tester);
    await tester.pumpAndSettle();

    expect(
      find.textContaining('reconciliado com o persistido'),
      findsOneWidget,
    );
    expect(find.text('Lançamento classificado.'), findsNothing);
    expect(_labelText(tester, 1), 'Categoria: Sem categoria');
    expect(find.byKey(_classifyButton(1)), findsOneWidget);
    expect(
      find.byKey(FinancialAccountDetailScreen.untrustedNoticeKey),
      findsNothing,
    );
  });

  testWidgets(
    'an untrusted classification state hides Classificar until a refresh restores it',
    (tester) async {
      final backend = _backend(
        movements: [
          FakeMovementSpec(id: financeTestMovementId(1)),
          FakeMovementSpec(id: financeTestMovementId(2)),
        ],
      )..allocationPostStatus = 409;
      backend.onAllocationPost = (movementId) {
        backend.allocations[movementId] = _allocation(1, [2], set: 9);
        backend.categoryReadStatus = 503; // the reconciliation read will fail
      };
      await _pump(tester, backend);
      await _openPicker(tester, 1);
      await tester.tap(find.byKey(_pickerTile(1)));
      await tester.pump();

      await _confirmPicker(tester);
      await tester.pumpAndSettle();

      expect(
        find.byKey(FinancialAccountDetailScreen.untrustedNoticeKey),
        findsOneWidget,
      );
      expect(
        find.textContaining('Não foi possível confirmar o estado'),
        findsOneWidget,
      );
      expect(find.text('Classificar'), findsNothing);
      expect(find.byKey(_classifyButton(1)), findsNothing);
      expect(find.byKey(_classifyButton(2)), findsNothing);
      // Last known state and the ledger stay visible.
      expect(_labelText(tester, 1), 'Categoria: Sem categoria');
      expect(find.text('Saldo atual'), findsOneWidget);
      expect(backend.allocationPosts, 1);

      backend.categoryReadStatus = null;
      backend.allocationPostStatus = null;
      await tester.tap(
        find.byKey(FinancialAccountDetailScreen.refreshButtonKey),
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(FinancialAccountDetailScreen.untrustedNoticeKey),
        findsNothing,
      );
      expect(_labelText(tester, 1), 'Categoria: Moradia > Energia');
      expect(find.byKey(_classifyButton(1)), findsNothing);
      expect(find.byKey(_classifyButton(2)), findsOneWidget);
    },
  );

  testWidgets(
    'an unknown category outcome blocks creating another until categories are re-read',
    (tester) async {
      final backend = _backend()..categoryPostStatus = 503;
      backend.onCategoryPost = (_) => backend.categoryReadStatus = 503;
      await _pump(tester, backend);
      await _openPicker(tester, 1);

      await tester.tap(
        find.byKey(const Key('financial-classify-new-category')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('financial-category-name')),
        'Lazer',
      );
      await tester.tap(
        find.byKey(const Key('financial-category-create-confirm')),
      );
      await tester.pumpAndSettle();

      expect(backend.categoryPosts, 1);
      expect(
        find.byKey(const Key('financial-classify-category-unknown')),
        findsOneWidget,
      );
      expect(
        find.byKey(FinancialAccountDetailScreen.unknownCategoryNoticeKey),
        findsOneWidget,
      );
      expect(
        tester
            .widget<TextButton>(
              find.byKey(const Key('financial-classify-new-category')),
            )
            .onPressed,
        isNull,
        reason: 'no blind second POST while the outcome is unknown',
      );

      // Re-reading while the backend still fails keeps the block.
      await tester.tap(
        find.byKey(const Key('financial-classify-reconcile-categories')),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('financial-classify-category-unknown')),
        findsOneWidget,
      );

      backend.categoryReadStatus = null;
      await tester.tap(
        find.byKey(const Key('financial-classify-reconcile-categories')),
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(const Key('financial-classify-category-unknown')),
        findsNothing,
      );
      expect(
        find.byKey(FinancialAccountDetailScreen.unknownCategoryNoticeKey),
        findsNothing,
      );
      expect(
        tester
            .widget<TextButton>(
              find.byKey(const Key('financial-classify-new-category')),
            )
            .onPressed,
        isNotNull,
      );
      expect(backend.categoryPosts, 1);
    },
  );

  testWidgets(
    'a possible duplicate after an unknown outcome is offered, never auto-selected',
    (tester) async {
      final backend = _backend()..categoryPostStatus = 503;
      backend.onCategoryPost = (_) => backend.categories.add(
        fakeCategoryJson(
          id: financeTestCategoryId(700),
          name: 'Lazer',
          scope: 'PERSONAL',
        ),
      );
      await _pump(tester, backend);
      await _openPicker(tester, 1);

      await tester.tap(
        find.byKey(const Key('financial-classify-new-category')),
      );
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('financial-category-name')),
        'Lazer',
      );
      await tester.tap(
        find.byKey(const Key('financial-category-create-confirm')),
      );
      await tester.pumpAndSettle();

      expect(backend.categoryPosts, 1);
      expect(
        tester
            .widget<Text>(find.byKey(const Key('financial-classify-notice')))
            .data,
        contains('uma categoria compatível'),
      );
      // The newcomer is listed for the user to pick, but nothing is selected.
      expect(find.byKey(_pickerTile(700)), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const Key('financial-classify-confirm')),
            )
            .onPressed,
        isNull,
      );
      expect(backend.allocationPosts, 0);
    },
  );

  for (final persisted in [false, true]) {
    testWidgets(
      'ambiguous write + failed reconciliation hides Classificar; after a refresh '
      'it returns only if the movement is still unclassified '
      '(persisted: $persisted)',
      (tester) async {
        final backend = _backend()..allocationPostStatus = 503;
        backend.onAllocationPost = (movementId) {
          if (persisted) {
            backend.allocations[movementId] = _allocation(1, [2], set: 7);
          }
          backend.bulkReadStatus = 503; // the reconciliation read fails
        };
        await _pump(tester, backend);
        await _openPicker(tester, 1);
        await tester.tap(find.byKey(_pickerTile(1)));
        await tester.pump();

        await _confirmPicker(tester);
        await tester.pumpAndSettle();

        expect(backend.allocationPosts, 1);
        expect(find.byKey(_classifyButton(1)), findsNothing);
        expect(find.text('Classificar'), findsNothing);
        expect(
          find.byKey(FinancialAccountDetailScreen.untrustedNoticeKey),
          findsOneWidget,
        );
        expect(_labelText(tester, 1), 'Categoria: Sem categoria');

        backend.bulkReadStatus = null;
        backend.allocationPostStatus = null;
        await tester.tap(
          find.byKey(FinancialAccountDetailScreen.refreshButtonKey),
        );
        await tester.pumpAndSettle();

        expect(
          find.byKey(FinancialAccountDetailScreen.untrustedNoticeKey),
          findsNothing,
        );
        if (persisted) {
          expect(_labelText(tester, 1), 'Categoria: Moradia > Energia');
          expect(find.byKey(_classifyButton(1)), findsNothing);
        } else {
          expect(_labelText(tester, 1), 'Categoria: Sem categoria');
          expect(find.byKey(_classifyButton(1)), findsOneWidget);
        }
        expect(
          backend.allocationPosts,
          1,
          reason: 'never re-sent automatically',
        );
      },
    );
  }
}
