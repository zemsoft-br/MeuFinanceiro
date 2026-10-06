import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

  group('split and revision editor', () {
    Key reviseButton(int movement) =>
        Key('financial-movement-revise-${financeTestMovementId(movement)}');
    Key shareLine(int movement, int category) => Key(
      'financial-movement-share-${financeTestMovementId(movement)}-'
      '${financeTestCategoryId(category)}',
    );
    Key rowCategory(int index) =>
        Key('financial-allocation-row-category-$index');
    Key rowAmount(int index) => Key('financial-allocation-row-amount-$index');
    Key rowRemove(int index) => Key('financial-allocation-row-remove-$index');
    Key option(int category) =>
        Key('financial-allocation-option-${financeTestCategoryId(category)}');
    const confirm = Key('financial-classify-confirm');
    const remaining = Key('financial-allocation-remaining');

    String set(int n) => financeTestAllocationSetId(n);

    String current(
      List<(int, String)> shares, {
      int movement = 1,
      int id = 1,
      int revision = 1,
      int? supersedes,
    }) => fakeAllocationJson(
      setId: set(id),
      movementId: financeTestMovementId(movement),
      shares: [for (final s in shares) (financeTestCategoryId(s.$1), s.$2)],
      revision: revision,
      supersedesId: supersedes == null ? null : set(supersedes),
    );

    bool confirmEnabled(WidgetTester tester) =>
        tester.widget<FilledButton>(find.byKey(confirm)).onPressed != null;

    Future<void> choose(WidgetTester tester, int row, int category) async {
      await tester.tap(find.byKey(rowCategory(row)));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(option(category)).hitTestable());
      await tester.pumpAndSettle();
    }

    Future<void> amount(WidgetTester tester, int row, String text) async {
      await tester.enterText(find.byKey(rowAmount(row)), text);
      await tester.pump();
    }

    Future<void> openSplit(WidgetTester tester, int movement) async {
      await _openPicker(tester, movement);
      await tester.tap(find.text('Ratear entre categorias'));
      await tester.pumpAndSettle();
    }

    String text(WidgetTester tester, Key key) =>
        tester.widget<Text>(find.byKey(key)).data!;

    testWidgets('Ratear shows Total, Rateado and Restante and closes exactly', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await openSplit(tester, 1);

      expect(
        text(tester, const Key('financial-allocation-total')),
        contains('75,25'),
      );
      expect(text(tester, remaining), 'Restante: BRL 75,25');
      expect(confirmEnabled(tester), isFalse);

      await choose(tester, 0, 1);
      await amount(tester, 0, '50');
      expect(
        text(tester, const Key('financial-allocation-allocated')),
        'Total rateado: BRL 50,00',
      );
      expect(text(tester, remaining), 'Restante: BRL 25,25');
      expect(confirmEnabled(tester), isFalse);

      await choose(tester, 1, 2);
      await amount(tester, 1, '25,24');
      expect(text(tester, remaining), 'Restante: BRL 0,01');
      expect(confirmEnabled(tester), isFalse, reason: 'under-allocated');

      await amount(tester, 1, '25,26');
      expect(text(tester, remaining), 'Restante: BRL -0,01');
      expect(confirmEnabled(tester), isFalse, reason: 'over-allocated');

      await amount(tester, 1, '25,25');
      expect(text(tester, remaining), 'Restante: BRL 0,00');
      expect(confirmEnabled(tester), isTrue);

      await tester.tap(find.byKey(confirm));
      await tester.pumpAndSettle();

      expect(find.text('Lançamento classificado.'), findsOneWidget);
      expect(backend.allocationPosts, 1);
      expect(backend.postedBodies.single['allocations'], [
        {
          'categoryId': financeTestCategoryId(1),
          'amount': '-50.00',
          'currency': 'BRL',
        },
        {
          'categoryId': financeTestCategoryId(2),
          'amount': '-25.25',
          'currency': 'BRL',
        },
      ]);
      expect(_labelText(tester, 1), 'Categoria: 2 categorias');
      expect(find.byKey(shareLine(1, 1)), findsOneWidget);
      expect(find.byKey(shareLine(1, 2)), findsOneWidget);
      expect(
        tester.widget<Text>(find.byKey(shareLine(1, 1))).data,
        'Moradia · BRL -50,00',
      );
      expect(
        tester.widget<Text>(find.byKey(shareLine(1, 2))).data,
        'Moradia > Energia · BRL -25,25',
      );
    });

    testWidgets('zero and malformed shares never enable Confirmar', (
      tester,
    ) async {
      await _pump(tester, _backend());
      await openSplit(tester, 1);
      await choose(tester, 0, 1);
      await choose(tester, 1, 2);

      await amount(tester, 0, '75,25');
      await amount(tester, 1, '0');
      expect(text(tester, remaining), 'Restante: BRL 0,00');
      expect(confirmEnabled(tester), isFalse, reason: 'zero share');
      expect(find.text('Informe um valor maior que zero.'), findsOneWidget);

      await amount(tester, 1, '1.2.3');
      expect(confirmEnabled(tester), isFalse);
      expect(find.text('Valor inválido.'), findsOneWidget);

      await amount(tester, 1, '-5');
      expect(
        confirmEnabled(tester),
        isFalse,
        reason: 'sign is the Movement\'s',
      );
    });

    testWidgets('adding and removing shares', (tester) async {
      await _pump(tester, _backend());
      await openSplit(tester, 1);

      expect(find.byKey(rowAmount(1)), findsOneWidget);
      expect(find.byKey(rowAmount(2)), findsNothing);

      await tester.tap(find.byKey(const Key('financial-allocation-add')));
      await tester.pumpAndSettle();
      expect(find.byKey(rowAmount(2)), findsOneWidget);

      await choose(tester, 0, 1);
      await amount(tester, 0, '10');
      await amount(tester, 1, '20');
      await amount(tester, 2, '30');
      expect(
        text(tester, const Key('financial-allocation-allocated')),
        'Total rateado: BRL 60,00',
      );

      await tester.tap(find.byKey(rowRemove(1)));
      await tester.pumpAndSettle();

      expect(find.byKey(rowAmount(2)), findsNothing);
      expect(
        text(tester, const Key('financial-allocation-allocated')),
        'Total rateado: BRL 40,00',
      );
      expect(
        tester.widget<TextField>(find.byKey(rowAmount(1))).controller!.text,
        '30',
        reason: 'the right row was removed',
      );
    });

    testWidgets('a category already used is unavailable in the other rows', (
      tester,
    ) async {
      await _pump(tester, _backend());
      await openSplit(tester, 1);
      await choose(tester, 0, 1);

      List<String?> offered(int row) => tester
          .widget<DropdownButton<String>>(
            find.descendant(
              of: find.byKey(rowCategory(row)),
              matching: find.byType(DropdownButton<String>),
            ),
          )
          .items!
          .map((item) => item.value)
          .toList();

      expect(offered(1), isNot(contains(financeTestCategoryId(1))));
      expect(offered(1), contains(financeTestCategoryId(2)));
      // The row that owns a category keeps it; it is merely not offered twice.
      expect(offered(0), contains(financeTestCategoryId(1)));
      // DISABLED and other people's PERSONAL categories are never offered.
      expect(offered(1), isNot(contains(financeTestCategoryId(5))));
      expect(offered(1), isNot(contains(financeTestCategoryId(4))));
    });

    testWidgets('the share count is capped at 50', (tester) async {
      await _pump(tester, _backend());
      await openSplit(tester, 1);
      final add = find.byKey(const Key('financial-allocation-add'));

      for (var i = 0; i < 48; i++) {
        await tester.ensureVisible(add);
        await tester.tap(add);
        await tester.pump();
      }

      expect(find.byKey(rowAmount(49), skipOffstage: false), findsOneWidget);
      expect(find.byKey(rowAmount(50), skipOffstage: false), findsNothing);
      expect(tester.widget<TextButton>(add).onPressed, isNull);
    });

    testWidgets(
      'Alterar classificação is offered to the owner of a classified row',
      (tester) async {
        await _pump(
          tester,
          _backend(
            movements: [
              FakeMovementSpec(id: financeTestMovementId(1)),
              FakeMovementSpec(id: financeTestMovementId(2)),
            ],
            allocations: {
              financeTestMovementId(1): current([(1, '-75.25')]),
            },
          ),
        );

        expect(find.byKey(reviseButton(1)), findsOneWidget);
        expect(find.text('Alterar classificação'), findsOneWidget);
        expect(find.byKey(_classifyButton(1)), findsNothing);
        expect(find.byKey(reviseButton(2)), findsNothing);
        expect(find.byKey(_classifyButton(2)), findsOneWidget);
      },
    );

    testWidgets('simple -> split revises against the current set', (
      tester,
    ) async {
      final backend = _backend(
        allocations: {
          financeTestMovementId(1): current([(1, '-75.25')]),
        },
      );
      await _pump(tester, backend);
      await tester.tap(find.byKey(reviseButton(1)));
      await tester.pumpAndSettle();

      expect(find.text('Alterar classificação'), findsWidgets);
      expect(
        find.byKey(const Key('financial-allocation-unchanged')),
        findsOneWidget,
      );
      expect(confirmEnabled(tester), isFalse, reason: 'nothing changed yet');

      await tester.tap(find.text('Ratear entre categorias'));
      await tester.pumpAndSettle();
      expect(
        tester.widget<TextField>(find.byKey(rowAmount(0))).controller!.text,
        '75.25',
        reason: 'the current share stays visible',
      );
      await amount(tester, 0, '50');
      await choose(tester, 1, 2);
      await amount(tester, 1, '25.25');
      expect(confirmEnabled(tester), isTrue);

      await tester.tap(find.byKey(confirm));
      await tester.pumpAndSettle();

      expect(find.text('Classificação alterada.'), findsOneWidget);
      expect(backend.revisionPosts, 1);
      expect(backend.allocationPosts, 0);
      expect(backend.revisionBodies.single['supersedesId'], set(1));
      expect(_labelText(tester, 1), 'Categoria: 2 categorias');
      expect(find.byKey(reviseButton(1)), findsOneWidget);
    });

    testWidgets('split -> simple', (tester) async {
      final backend = _backend(
        allocations: {
          financeTestMovementId(1): current([(1, '-50'), (2, '-25.25')]),
        },
      );
      await _pump(tester, backend);
      expect(_labelText(tester, 1), 'Categoria: 2 categorias');

      await tester.tap(find.byKey(reviseButton(1)));
      await tester.pumpAndSettle();
      expect(
        tester.widget<TextField>(find.byKey(rowAmount(0))).controller!.text,
        '50.00',
      );

      await tester.tap(find.text('1 categoria'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(_pickerTile(3)));
      await tester.pump();
      expect(confirmEnabled(tester), isTrue);

      await tester.tap(find.byKey(confirm));
      await tester.pumpAndSettle();

      expect(find.text('Classificação alterada.'), findsOneWidget);
      expect(_labelText(tester, 1), 'Categoria: Pessoal');
      expect(backend.revisionBodies.single['allocations'], [
        {
          'categoryId': financeTestCategoryId(3),
          'amount': '-75.25',
          'currency': 'BRL',
        },
      ]);
      expect(find.byKey(shareLine(1, 1)), findsNothing);
    });

    testWidgets(
      'a DISABLED category of the history stays visible but cannot be submitted',
      (tester) async {
        final backend = _backend(
          allocations: {
            financeTestMovementId(1): current([(5, '-50'), (2, '-25.25')]),
          },
        );
        await _pump(tester, backend);

        expect(
          tester.widget<Text>(find.byKey(shareLine(1, 5))).data,
          'Antiga (indisponível) · BRL -50,00',
        );

        await tester.tap(find.byKey(reviseButton(1)));
        await tester.pumpAndSettle();

        expect(find.text('Antiga (indisponível)'), findsWidgets);
        expect(
          find.byKey(const Key('financial-allocation-row-unavailable-0')),
          findsOneWidget,
        );
        expect(confirmEnabled(tester), isFalse);

        // It is not offered as a destination, only as a visible leftover.
        await tester.tap(find.byKey(rowCategory(0)));
        await tester.pumpAndSettle();
        expect(find.byKey(option(5)), findsNothing);
        await tester.tap(find.byKey(option(1)).hitTestable());
        await tester.pumpAndSettle();

        expect(
          find.byKey(const Key('financial-allocation-row-unavailable-0')),
          findsNothing,
        );
        expect(confirmEnabled(tester), isTrue);
        await tester.tap(find.byKey(confirm));
        await tester.pumpAndSettle();

        expect(backend.revisionPosts, 1);
        expect(
          (backend.revisionBodies.single['allocations'] as List).map(
            (s) => (s as Map)['categoryId'],
          ),
          [financeTestCategoryId(1), financeTestCategoryId(2)],
        );
      },
    );

    testWidgets('a simple DISABLED classification must be replaced', (
      tester,
    ) async {
      await _pump(
        tester,
        _backend(
          allocations: {
            financeTestMovementId(1): current([(5, '-75.25')]),
          },
        ),
      );
      await tester.tap(find.byKey(reviseButton(1)));
      await tester.pumpAndSettle();

      expect(
        find.byKey(
          Key('financial-classify-unavailable-${financeTestCategoryId(5)}'),
        ),
        findsOneWidget,
      );
      expect(find.byKey(_pickerTile(5)), findsNothing);
      expect(confirmEnabled(tester), isFalse);

      await tester.tap(find.byKey(_pickerTile(1)));
      await tester.pump();
      expect(confirmEnabled(tester), isTrue);
    });

    testWidgets(
      'non-owner, NEUTRAL, REVERSAL and archived accounts cannot edit',
      (tester) async {
        final movements = [
          FakeMovementSpec(id: financeTestMovementId(1)),
          FakeMovementSpec(
            id: financeTestMovementId(2),
            effect: 'NEUTRAL',
            description: 'Transferência',
          ),
          FakeMovementSpec(
            id: financeTestMovementId(3),
            role: 'REVERSAL',
            effect: 'NEUTRAL',
            description: null,
          ),
        ];
        final allocations = {
          financeTestMovementId(1): current([(1, '-75.25')]),
        };

        await _pump(
          tester,
          _backend(movements: movements, allocations: allocations),
        );
        expect(find.byKey(reviseButton(1)), findsOneWidget);
        expect(find.byKey(reviseButton(2)), findsNothing);
        expect(find.byKey(reviseButton(3)), findsNothing);
        expect(find.byKey(_classifyButton(2)), findsNothing);
        expect(find.byKey(_classifyButton(3)), findsNothing);
      },
    );

    testWidgets('a non-owner reads the classification but cannot change it', (
      tester,
    ) async {
      await _pump(
        tester,
        _backend(
          accountScope: 'HOUSEHOLD',
          allocations: {
            financeTestMovementId(1): current([(1, '-50'), (2, '-25.25')]),
          },
        ),
        operatorId: financeTestOtherOperatorId,
      );

      expect(_labelText(tester, 1), 'Categoria: 2 categorias');
      expect(find.byKey(shareLine(1, 1)), findsOneWidget);
      expect(find.byKey(reviseButton(1)), findsNothing);
      expect(find.byKey(_classifyButton(1)), findsNothing);
    });

    testWidgets('an archived account offers no revision', (tester) async {
      await _pump(
        tester,
        _backend(
          accountStatus: 'ARCHIVED',
          allocations: {
            financeTestMovementId(1): current([(1, '-75.25')]),
          },
        ),
      );

      expect(find.byKey(reviseButton(1)), findsNothing);
    });

    testWidgets(
      '409 shows the conflict, never success, and the edit must be reopened',
      (tester) async {
        final backend = _backend(
          allocations: {
            financeTestMovementId(1): current([(1, '-75.25')]),
          },
        )..revisionPostStatus = 409;
        // Another writer appended R2 before this revision arrived.
        backend.onRevisionPost = (movementId, body) {
          backend.allocations[movementId] = current(
            [(3, '-75.25')],
            id: 2,
            revision: 2,
            supersedes: 1,
          );
        };
        await _pump(tester, backend);
        await tester.tap(find.byKey(reviseButton(1)));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Ratear entre categorias'));
        await tester.pumpAndSettle();
        await amount(tester, 0, '50');
        await choose(tester, 1, 2);
        await amount(tester, 1, '25.25');
        await tester.tap(find.byKey(confirm));
        await tester.pumpAndSettle();

        expect(
          find.textContaining('A classificação mudou antes de salvar'),
          findsOneWidget,
        );
        expect(find.text('Classificação alterada.'), findsNothing);
        expect(backend.revisionPosts, 1, reason: 'never retried');
        // The persisted truth is on screen; the edit was not applied.
        expect(_labelText(tester, 1), 'Categoria: Pessoal');
        expect(
          find.byKey(const Key('financial-classify-dialog')),
          findsNothing,
        );
        expect(
          find.byKey(FinancialAccountDetailScreen.untrustedNoticeKey),
          findsNothing,
        );

        // The user opens the editor again, now on R2, and decides explicitly.
        backend.revisionPostStatus = null;
        backend.onRevisionPost = null;
        await tester.pumpAndSettle(const Duration(seconds: 5));
        await tester.tap(find.byKey(reviseButton(1)));
        await tester.pumpAndSettle();
        expect(
          tester
              .widget<Text>(
                find.byKey(const Key('financial-allocation-unchanged')),
              )
              .data,
          isNotEmpty,
        );
        await tester.tap(find.byKey(_pickerTile(1)));
        await tester.pump();
        await tester.tap(find.byKey(confirm));
        await tester.pumpAndSettle();

        expect(backend.revisionPosts, 2);
        expect(backend.revisionBodies[1]['supersedesId'], set(2));
        expect(find.text('Classificação alterada.'), findsOneWidget);
      },
    );

    testWidgets(
      '409 with a failed reconciliation hides the actions until Atualizar',
      (tester) async {
        final backend = _backend(
          allocations: {
            financeTestMovementId(1): current([(1, '-75.25')]),
          },
        )..revisionPostStatus = 409;
        backend.onRevisionPost = (movementId, body) {
          backend.allocations[movementId] = current(
            [(3, '-75.25')],
            id: 2,
            revision: 2,
            supersedes: 1,
          );
          backend.bulkReadStatus = 503;
        };
        await _pump(tester, backend);
        await tester.tap(find.byKey(reviseButton(1)));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(_pickerTile(2)));
        await tester.pump();
        await tester.tap(find.byKey(confirm));
        await tester.pumpAndSettle();

        expect(
          find.byKey(FinancialAccountDetailScreen.untrustedNoticeKey),
          findsOneWidget,
        );
        expect(find.text('Classificação alterada.'), findsNothing);
        expect(find.byKey(reviseButton(1)), findsNothing);
        expect(backend.revisionPosts, 1);

        backend.bulkReadStatus = null;
        backend.revisionPostStatus = null;
        await tester.tap(
          find.byKey(FinancialAccountDetailScreen.refreshButtonKey),
        );
        await tester.pumpAndSettle();

        expect(
          find.byKey(FinancialAccountDetailScreen.untrustedNoticeKey),
          findsNothing,
        );
        expect(_labelText(tester, 1), 'Categoria: Pessoal');
        expect(find.byKey(reviseButton(1)), findsOneWidget);
      },
    );

    testWidgets(
      'an ambiguous revision is never shown as success and allows an explicit retry',
      (tester) async {
        final backend = _backend(
          allocations: {
            financeTestMovementId(1): current([(1, '-75.25')]),
          },
        )..revisionPostStatus = 503;
        await _pump(tester, backend);
        await tester.tap(find.byKey(reviseButton(1)));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(_pickerTile(2)));
        await tester.pump();
        await tester.tap(find.byKey(confirm));
        await tester.pumpAndSettle();

        expect(find.text('Classificação alterada.'), findsNothing);
        expect(
          find.textContaining('nada mudou na classificação persistida'),
          findsOneWidget,
        );
        expect(backend.revisionPosts, 1);
        expect(_labelText(tester, 1), 'Categoria: Moradia');
        expect(find.byKey(reviseButton(1)), findsOneWidget);

        backend.revisionPostStatus = null;
        await tester.pumpAndSettle(const Duration(seconds: 5));
        await tester.tap(find.byKey(reviseButton(1)));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(_pickerTile(2)));
        await tester.pump();
        await tester.tap(find.byKey(confirm));
        await tester.pumpAndSettle();

        expect(backend.revisionPosts, 2);
        expect(backend.revisionKeys[1], backend.revisionKeys[0]);
        expect(_labelText(tester, 1), 'Categoria: Moradia > Energia');
      },
    );

    testWidgets(
      'a rejected revision (422) leaves the classification untouched',
      (tester) async {
        final backend = _backend(
          allocations: {
            financeTestMovementId(1): current([(1, '-75.25')]),
          },
        )..revisionPostStatus = 422;
        await _pump(tester, backend);
        await tester.tap(find.byKey(reviseButton(1)));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(_pickerTile(2)));
        await tester.pump();
        await tester.tap(find.byKey(confirm));
        await tester.pumpAndSettle();

        expect(find.textContaining('não foi aceita'), findsOneWidget);
        expect(find.text('Classificação alterada.'), findsNothing);
        expect(_labelText(tester, 1), 'Categoria: Moradia');
        expect(backend.revisionPosts, 1);
      },
    );

    testWidgets('editor controls are labelled for assistive technology', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await _pump(tester, _backend());
      await openSplit(tester, 1);

      String? tooltip(Key key) =>
          tester.getSemantics(find.byKey(key)).getSemanticsData().tooltip;

      expect(tooltip(rowRemove(0)), 'Remover categoria 1');
      expect(tooltip(rowRemove(1)), 'Remover categoria 2');
      expect(find.text('Adicionar categoria'), findsOneWidget);
      expect(find.text('Categoria 1'), findsWidgets);
      expect(find.text('Valor 1'), findsWidgets);
      handle.dispose();
    });

    testWidgets(
      'keyboard: Tab reaches the amount field and Enter-free typing works',
      (tester) async {
        await _pump(tester, _backend());
        await openSplit(tester, 1);

        await tester.tap(find.byKey(rowAmount(0)));
        await tester.pump();
        await tester.enterText(find.byKey(rowAmount(0)), '12,5');
        await tester.sendKeyEvent(LogicalKeyboardKey.tab);
        await tester.pump();

        expect(
          tester.widget<TextField>(find.byKey(rowAmount(0))).controller!.text,
          '12,5',
        );
        expect(
          FocusManager.instance.primaryFocus,
          isNot(
            same(tester.widget<TextField>(find.byKey(rowAmount(0))).focusNode),
          ),
          reason: 'Tab moves focus on to the next control',
        );
      },
    );
  });
}
