import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_pending_screen.dart';

import '../../support/fake_finance_backend.dart';
import '../../support/fake_pending_backend.dart';

final _mercado = financeTestCategoryId(1);
final _lazer = financeTestCategoryId(2);
final _rule = financeTestRuleId(1);

FakePendingBackend _backend({List<FakePendingItem>? items, int? pageSize}) =>
    FakePendingBackend(
      items:
          items ??
          [
            FakePendingItem(
              index: 1,
              description: 'Padaria Pão Quente',
              status: 'MATCHED',
              ruleId: _rule,
              categoryId: _mercado,
            ),
            FakePendingItem(
              index: 2,
              description: 'Mercado Sul',
              date: '2026-09-09',
              status: 'AMBIGUOUS',
            ),
            FakePendingItem(
              index: 3,
              description: 'Cinema',
              date: '2026-09-08',
            ),
          ],
      pageSize: pageSize,
      categories: [
        fakeCategoryJson(id: _mercado, name: 'Mercado'),
        fakeCategoryJson(id: _lazer, name: 'Lazer'),
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

Future<void> _pump(WidgetTester tester, FakePendingBackend backend) async {
  tester.view.physicalSize = const Size(1400, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: pendingTestOverrides(backend),
      child: const MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: FinancialPendingScreen()),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Finder _rows() => find.byWidgetPredicate(
  (widget) =>
      widget is Text && RegExp(r'^Lançamento \d$').hasMatch(widget.data ?? ''),
);

Finder _item(int index) =>
    find.byKey(FinancialPendingScreen.itemKey(pendingTestMovementId(index)));

String _id(int index) => pendingTestMovementId(index);

void main() {
  testWidgets('loading, then a list with the three badges and the suggestion', (
    tester,
  ) async {
    final backend = _backend();
    backend.pendingGate = Completer<void>();
    tester.view.physicalSize = const Size(1400, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      ProviderScope(
        overrides: pendingTestOverrides(backend),
        child: const MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: FinancialPendingScreen()),
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pump();
    expect(find.byKey(FinancialPendingScreen.loadingKey), findsOneWidget);
    backend.pendingGate!.complete();
    await tester.pumpAndSettle();

    expect(find.byKey(FinancialPendingScreen.listKey), findsOneWidget);
    expect(find.text('Pendências'), findsOneWidget);
    expect(find.text('Sugestão encontrada'), findsOneWidget);
    expect(find.text('Ambígua'), findsWidgets);
    expect(find.text('Sem sugestão'), findsWidgets);
    expect(find.text('Padaria Pão Quente'), findsOneWidget);
    expect(find.text('BRL -10,00'), findsNWidgets(3));
    expect(find.text('10/09/2026 · Conta Corrente'), findsOneWidget);
    expect(
      find.byKey(FinancialPendingScreen.suggestionKey(_id(1))),
      findsOneWidget,
    );
    expect(find.textContaining('Categoria sugerida: Mercado'), findsOneWidget);
    // Fixed cost: one inbox page + categories + accounts, nothing per row.
    expect(backend.calls, hasLength(3));
    expect(backend.perRowRequests, 0);
  });

  testWidgets('an ambiguous item says so and never offers a rule', (
    tester,
  ) async {
    final backend = _backend();
    await _pump(tester, backend);
    expect(
      find.byKey(FinancialPendingScreen.ambiguousKey(_id(2))),
      findsOneWidget,
    );
    expect(find.byKey(FinancialPendingScreen.applyKey(_id(2))), findsNothing);
    expect(
      find.byKey(FinancialPendingScreen.classifyKey(_id(2))),
      findsOneWidget,
    );
    // Only the matched item can apply a suggestion.
    expect(find.byKey(FinancialPendingScreen.applyKey(_id(1))), findsOneWidget);
    expect(find.byKey(FinancialPendingScreen.applyKey(_id(3))), findsNothing);
  });

  testWidgets('empty, filtered-empty and error states', (tester) async {
    final empty = _backend(items: []);
    await _pump(tester, empty);
    expect(find.byKey(FinancialPendingScreen.emptyKey), findsOneWidget);
    expect(find.text('Nenhuma pendência'), findsOneWidget);
  });

  testWidgets('a failed load shows an error and a manual retry', (
    tester,
  ) async {
    final backend = _backend()..pendingReadStatus = 503;
    await _pump(tester, backend);
    expect(find.byKey(FinancialPendingScreen.errorKey), findsOneWidget);
    expect(find.byKey(FinancialPendingScreen.listKey), findsNothing);
    expect(backend.pendingReads, hasLength(1), reason: 'no automatic retry');

    backend.pendingReadStatus = null;
    await tester.tap(find.byKey(FinancialPendingScreen.retryKey));
    await tester.pumpAndSettle();
    expect(find.byKey(FinancialPendingScreen.listKey), findsOneWidget);
  });

  testWidgets('forbidden access has no retry', (tester) async {
    final backend = _backend()..pendingReadStatus = 403;
    await _pump(tester, backend);
    expect(find.text('Acesso indisponível'), findsOneWidget);
    expect(find.byKey(FinancialPendingScreen.retryKey), findsNothing);
  });

  testWidgets('pagination appends pages without repeating rows', (
    tester,
  ) async {
    final backend = _backend(
      pageSize: 2,
      items: [
        for (var i = 1; i <= 5; i += 1)
          FakePendingItem(
            index: i,
            date: '2026-09-${10 + i}',
            description: 'Lançamento $i',
          ),
      ],
    );
    await _pump(tester, backend);
    expect(_rows(), findsNWidgets(2));
    expect(find.byKey(FinancialPendingScreen.loadMoreKey), findsOneWidget);

    await tester.tap(find.byKey(FinancialPendingScreen.loadMoreKey));
    await tester.pumpAndSettle();
    expect(_rows(), findsNWidgets(4));
    await tester.tap(find.byKey(FinancialPendingScreen.loadMoreKey));
    await tester.pumpAndSettle();
    expect(_rows(), findsNWidgets(5));
    for (var i = 1; i <= 5; i += 1) {
      expect(find.text('Lançamento $i'), findsOneWidget);
    }
    expect(find.byKey(FinancialPendingScreen.loadMoreKey), findsNothing);
    expect(backend.pendingReads, hasLength(3));
    expect(backend.perRowRequests, 0);
  });

  testWidgets(
    'a failed next page keeps the rows and offers an explicit retry',
    (tester) async {
      final backend = _backend(
        pageSize: 1,
        items: [
          FakePendingItem(
            index: 1,
            date: '2026-09-12',
            description: 'Primeiro',
          ),
          FakePendingItem(index: 2, date: '2026-09-11', description: 'Segundo'),
        ],
      );
      await _pump(tester, backend);
      backend
        ..failNextPendingReads = 1
        ..failNextPendingReadsStatus = 503;
      await tester.tap(find.byKey(FinancialPendingScreen.loadMoreKey));
      await tester.pumpAndSettle();
      expect(find.text('Primeiro'), findsOneWidget);
      expect(
        find.byKey(FinancialPendingScreen.loadMoreErrorKey),
        findsOneWidget,
      );
      await tester.tap(find.byKey(FinancialPendingScreen.loadMoreKey));
      await tester.pumpAndSettle();
      expect(find.text('Segundo'), findsOneWidget);
      expect(find.byKey(FinancialPendingScreen.loadMoreErrorKey), findsNothing);
    },
  );

  testWidgets('filters are sent to the server and listed rows follow', (
    tester,
  ) async {
    final backend = _backend();
    await _pump(tester, backend);
    await tester.tap(find.byKey(FinancialPendingScreen.statusFilterKey));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ambígua').last);
    await tester.pumpAndSettle();
    expect(
      backend.pendingReads.last.uri.queryParameters['ruleStatus'],
      'AMBIGUOUS',
    );
    expect(_item(2), findsOneWidget);
    expect(_item(1), findsNothing);
    expect(find.byKey(FinancialPendingScreen.clearFiltersKey), findsOneWidget);

    await tester.tap(find.byKey(FinancialPendingScreen.clearFiltersKey));
    await tester.pumpAndSettle();
    expect(_item(1), findsOneWidget);
    expect(backend.pendingReads.last.uri.queryParameters, {'limit': '50'});
  });

  testWidgets('a failed filter change leaves the controls matching the list', (
    tester,
  ) async {
    final backend = _backend();
    await _pump(tester, backend);
    backend.pendingReadStatus = 503;
    await tester.tap(find.byKey(FinancialPendingScreen.statusFilterKey));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Ambígua').last);
    await tester.pumpAndSettle();
    // The previous list (all three items) was preserved, so the filter control
    // must still hold "Todas" (null), not the value that failed to load.
    expect(_item(1), findsOneWidget);
    expect(_item(3), findsOneWidget);
    final dropdown = tester.widget<DropdownButton<FinancialPendingRuleStatus?>>(
      find.byKey(FinancialPendingScreen.statusFilterKey),
    );
    expect(dropdown.value, isNull);
    expect(find.text('Todas'), findsOneWidget);
    expect(find.byKey(FinancialPendingScreen.refreshNoticeKey), findsOneWidget);
  });

  testWidgets('a filter with no result says so and keeps a way back', (
    tester,
  ) async {
    final backend = _backend(items: [FakePendingItem(index: 1)]);
    await _pump(tester, backend);
    await tester.tap(find.byKey(FinancialPendingScreen.statusFilterKey));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Sugestão encontrada').last);
    await tester.pumpAndSettle();
    expect(find.text('Nenhuma pendência com estes filtros'), findsOneWidget);
    expect(find.byKey(FinancialPendingScreen.clearFiltersKey), findsOneWidget);
  });

  group('apply a suggestion', () {
    testWidgets('needs an explicit confirmation; cancelling sends nothing', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await tester.tap(find.byKey(FinancialPendingScreen.applyKey(_id(1))));
      await tester.pumpAndSettle();
      expect(
        find.byKey(FinancialPendingScreen.confirmDialogKey),
        findsOneWidget,
      );
      expect(find.text('Categoria: Mercado'), findsOneWidget);
      await tester.tap(find.byKey(FinancialPendingScreen.cancelApplyKey));
      await tester.pumpAndSettle();
      expect(backend.applyPosts, 0);
      expect(_item(1), findsOneWidget);
    });

    testWidgets('confirming applies once and the item leaves only after the '
        'canonical re-read', (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      await tester.tap(find.byKey(FinancialPendingScreen.applyKey(_id(1))));
      await tester.pumpAndSettle();

      backend.pendingGate = Completer<void>();
      await tester.tap(find.byKey(FinancialPendingScreen.confirmApplyKey));
      await tester.pump();
      await tester.pump();
      // The POST finished, the canonical read has not: the row is still there.
      expect(backend.applyPosts, 1);
      expect(_item(1), findsOneWidget);
      expect(
        find.byKey(FinancialPendingScreen.busyKey(_id(1))),
        findsOneWidget,
      );
      expect(
        tester
            .widget<OutlinedButton>(
              find.byKey(FinancialPendingScreen.classifyKey(_id(2))),
            )
            .onPressed,
        isNull,
        reason: 'every action is blocked while a write is in flight',
      );

      backend.pendingGate!.complete();
      await tester.pumpAndSettle();
      expect(_item(1), findsNothing);
      expect(
        find.textContaining('Sugestão aplicada pelo servidor.'),
        findsOneWidget,
      );
      expect(backend.applyPosts, 1);
      expect(backend.pendingReads, hasLength(2));
    });

    testWidgets(
      'a conflict is shown as it is: nothing written, state updated',
      (tester) async {
        final backend = _backend()..applyResultStatus = 'CONFLICT';
        backend.onApply = (_) {
          backend.items.firstWhere((item) => item.id == _id(1))
            ..status = 'AMBIGUOUS'
            ..ruleId = null
            ..categoryId = null;
        };
        await _pump(tester, backend);
        await tester.tap(find.byKey(FinancialPendingScreen.applyKey(_id(1))));
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(FinancialPendingScreen.confirmApplyKey));
        await tester.pumpAndSettle();
        expect(
          find.textContaining('O estado mudou e nada foi gravado.'),
          findsOneWidget,
        );
        expect(_item(1), findsOneWidget, reason: 'it is still pending');
        expect(
          find.byKey(FinancialPendingScreen.applyKey(_id(1))),
          findsNothing,
        );
        expect(
          find.byKey(FinancialPendingScreen.ambiguousKey(_id(1))),
          findsOneWidget,
        );
      },
    );

    testWidgets('a failed write never claims success and is not retried', (
      tester,
    ) async {
      final backend = _backend()..applyResultStatus = 'FAILED';
      await _pump(tester, backend);
      await tester.tap(find.byKey(FinancialPendingScreen.applyKey(_id(1))));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(FinancialPendingScreen.confirmApplyKey));
      await tester.pumpAndSettle();
      expect(find.textContaining('Falha ao gravar'), findsOneWidget);
      expect(_item(1), findsOneWidget);
      expect(backend.applyPosts, 1);
    });

    testWidgets('an unknown outcome is explained and never resent', (
      tester,
    ) async {
      final backend = _backend()..applyThrows = true;
      await _pump(tester, backend);
      await tester.tap(find.byKey(FinancialPendingScreen.applyKey(_id(1))));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(FinancialPendingScreen.confirmApplyKey));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('não será reenviado automaticamente'),
        findsOneWidget,
      );
      expect(backend.applyPosts, 1);
      expect(_item(1), findsOneWidget);
    });

    testWidgets('a stale list after the write blocks actions until refreshed', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await tester.tap(find.byKey(FinancialPendingScreen.applyKey(_id(1))));
      await tester.pumpAndSettle();
      backend
        ..failNextPendingReads = 1
        ..failNextPendingReadsStatus = 503;
      await tester.tap(find.byKey(FinancialPendingScreen.confirmApplyKey));
      await tester.pumpAndSettle();
      expect(find.byKey(FinancialPendingScreen.untrustedKey), findsOneWidget);
      expect(
        find.textContaining('A lista pode estar desatualizada'),
        findsOneWidget,
      );
      expect(
        _item(1),
        findsOneWidget,
        reason: 'no removal without a canonical read',
      );
      expect(
        tester
            .widget<OutlinedButton>(
              find.byKey(FinancialPendingScreen.classifyKey(_id(3))),
            )
            .onPressed,
        isNull,
      );

      await tester.tap(find.byKey(FinancialPendingScreen.refreshKey));
      await tester.pumpAndSettle();
      expect(find.byKey(FinancialPendingScreen.untrustedKey), findsNothing);
      expect(_item(1), findsNothing);
    });
  });

  group('manual classification', () {
    testWidgets('offers only the categories the account may use, then writes '
        'once and refreshes', (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      await tester.tap(find.byKey(FinancialPendingScreen.classifyKey(_id(2))));
      await tester.pumpAndSettle();
      expect(
        find.byKey(FinancialPendingScreen.classifyDialogKey),
        findsOneWidget,
      );
      expect(find.text('Mercado'), findsOneWidget);
      expect(find.text('Lazer'), findsOneWidget);
      expect(find.text('Do outro'), findsNothing);
      expect(find.text('Antiga'), findsNothing);
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(FinancialPendingScreen.classifyConfirmKey),
            )
            .onPressed,
        isNull,
        reason: 'nothing is chosen for the operator',
      );

      await tester.tap(
        find.byKey(FinancialPendingScreen.categoryOptionKey(_lazer)),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(FinancialPendingScreen.classifyConfirmKey));
      await tester.pumpAndSettle();

      expect(backend.allocationPosts, 1);
      expect(backend.allocationMovementIds, [_id(2)]);
      expect(backend.applyPosts, 0, reason: 'no rule was applied');
      expect(_item(2), findsNothing);
      expect(
        find.text('Lançamento classificado. A lista foi atualizada.'),
        findsOneWidget,
      );
    });

    testWidgets('resolving every item leaves an empty inbox', (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      for (final index in [2, 3]) {
        await tester.tap(
          find.byKey(FinancialPendingScreen.classifyKey(_id(index))),
        );
        await tester.pumpAndSettle();
        await tester.tap(
          find.byKey(FinancialPendingScreen.categoryOptionKey(_mercado)),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(FinancialPendingScreen.classifyConfirmKey));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.byKey(FinancialPendingScreen.applyKey(_id(1))));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(FinancialPendingScreen.confirmApplyKey));
      await tester.pumpAndSettle();
      expect(find.byKey(FinancialPendingScreen.emptyKey), findsOneWidget);
      expect(backend.items, isEmpty);
    });

    testWidgets(
      'a conflict while classifying is reported and the list refreshed',
      (tester) async {
        final backend = _backend()..allocationStatus = 409;
        backend.onAllocation = (id) => backend.items = backend.items
            .where((candidate) => candidate.id != id)
            .toList();
        await _pump(tester, backend);
        await tester.tap(
          find.byKey(FinancialPendingScreen.classifyKey(_id(3))),
        );
        await tester.pumpAndSettle();
        await tester.tap(
          find.byKey(FinancialPendingScreen.categoryOptionKey(_mercado)),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(FinancialPendingScreen.classifyConfirmKey));
        await tester.pumpAndSettle();
        expect(
          find.textContaining('O estado mudou e nada foi gravado.'),
          findsOneWidget,
        );
        expect(backend.allocationPosts, 1);
        expect(
          _item(3),
          findsNothing,
          reason: 'the canonical read no longer lists it',
        );
      },
    );

    testWidgets('splitting between categories stays in the account screen', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await tester.tap(find.byKey(FinancialPendingScreen.classifyKey(_id(3))));
      await tester.pumpAndSettle();
      expect(
        find.byKey(FinancialPendingScreen.classifySplitKey),
        findsOneWidget,
      );
    });
  });

  testWidgets('a read-only item shows why and offers no write', (tester) async {
    final backend = _backend(
      items: [
        FakePendingItem(
          index: 1,
          accountId: pendingTestAccountB,
          description: 'Do membro',
          status: 'MATCHED',
          ruleId: _rule,
          categoryId: _mercado,
          canClassify: false,
        ),
      ],
    );
    await _pump(tester, backend);
    expect(
      find.byKey(FinancialPendingScreen.readOnlyKey(_id(1))),
      findsOneWidget,
    );
    expect(find.textContaining('outro membro'), findsOneWidget);
    expect(find.byKey(FinancialPendingScreen.applyKey(_id(1))), findsNothing);
    expect(
      find.byKey(FinancialPendingScreen.classifyKey(_id(1))),
      findsNothing,
    );
    // The suggestion state is still informative.
    expect(find.text('Sugestão encontrada'), findsOneWidget);
  });

  testWidgets('a refresh failure keeps the list and says so', (tester) async {
    final backend = _backend();
    await _pump(tester, backend);
    backend.pendingReadStatus = 503;
    await tester.tap(find.byKey(FinancialPendingScreen.refreshKey));
    await tester.pumpAndSettle();
    expect(find.byKey(FinancialPendingScreen.refreshNoticeKey), findsOneWidget);
    expect(_item(1), findsOneWidget);
  });
}
