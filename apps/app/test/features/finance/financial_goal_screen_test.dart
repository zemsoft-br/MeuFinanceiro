import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_allocation_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_editor_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_screen.dart';

import '../../support/fake_finance_backend.dart';
import '../../support/fake_goal_backend.dart';

FakeGoalBackend _backend({
  List<FakeGoal>? goals,
  List<FakeGoalAccount>? accounts,
  String operatorId = financeTestOwnerId,
}) => FakeGoalBackend(
  goals:
      goals ??
      [FakeGoal(index: 1, title: 'Reserva de emergência', target: '1000')],
  accounts:
      accounts ??
      [
        FakeGoalAccount(index: 1, name: 'Conta da casa', balance: '1000'),
        FakeGoalAccount(
          index: 2,
          name: 'Conta pessoal',
          scope: 'PERSONAL',
          balance: '700',
        ),
        FakeGoalAccount(
          index: 3,
          name: 'Conta do outro',
          owner: financeTestOtherOperatorId,
        ),
        FakeGoalAccount(index: 4, name: 'Conta em dólar', currency: 'USD'),
        FakeGoalAccount(
          index: 5,
          name: 'Conta antiga',
          status: 'ARCHIVED',
          balance: '300',
        ),
      ],
  operatorId: operatorId,
);

Future<GoRouter> _pump(
  WidgetTester tester,
  FakeGoalBackend backend, {
  String operatorId = financeTestOwnerId,
}) async {
  tester.view.physicalSize = const Size(1400, 4000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final router = GoRouter(
    initialLocation: '/goals',
    routes: [
      GoRoute(
        path: '/goals',
        builder: (_, _) => const Scaffold(
          body: SingleChildScrollView(child: FinancialGoalScreen()),
        ),
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
      overrides: goalTestOverrides(backend, operatorId: operatorId),
      child: MaterialApp.router(routerConfig: router),
    ),
  );
  await tester.pumpAndSettle();
  return router;
}

Finder _key(Key key) => find.byKey(key);

Future<void> _tap(WidgetTester tester, Key key) async {
  await tester.ensureVisible(_key(key));
  await tester.tap(_key(key));
  await tester.pumpAndSettle();
}

Future<void> _chooseAccount(WidgetTester tester, String label) async {
  await tester.tap(_key(FinancialGoalAllocationDialog.accountKey));
  await tester.pumpAndSettle();
  await tester.tap(find.text(label).last);
  await tester.pumpAndSettle();
}

Future<void> _enterAmount(WidgetTester tester, String value) async {
  await tester.enterText(_key(FinancialGoalAllocationDialog.amountKey), value);
  await tester.pumpAndSettle();
}

void main() {
  group('states', () {
    testWidgets('loading, then the goal, planned vs virtually allocated', (
      tester,
    ) async {
      final backend = _backend();
      backend.seed(
        backend.goals.single,
        backend.accounts[0],
        'ALLOCATE',
        '250',
      );
      backend.listGate = Completer<void>();
      tester.view.physicalSize = const Size(1400, 4000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        ProviderScope(
          overrides: goalTestOverrides(backend),
          child: const MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(child: FinancialGoalScreen()),
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(_key(FinancialGoalScreen.loadingKey), findsOneWidget);
      backend.listGate!.complete();
      await tester.pumpAndSettle();

      expect(find.text('Metas'), findsOneWidget);
      expect(find.text('Reserva de emergência'), findsWidgets);
      expect(find.text('Da casa'), findsWidgets);
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.targetKey),
          matching: find.text('BRL 1000,00'),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.allocatedKey),
          matching: find.text('BRL 250,00 (25%)'),
        ),
        findsOneWidget,
      );
      expect(find.text('Planejado (alvo)'), findsOneWidget);
      expect(find.text('Destinado virtualmente'), findsOneWidget);
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.remainingKey),
          matching: find.text('BRL 750,00'),
        ),
        findsOneWidget,
      );
      expect(find.text('Em andamento'), findsOneWidget);
      expect(backend.perItemRequests, 0);
    });

    testWidgets('the virtual allocation notice is always on screen', (
      tester,
    ) async {
      final backend = _backend(goals: []);
      await _pump(tester, backend);
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.virtualNoticeKey),
          matching: find.text(
            'Destinação virtual; não transfere nem bloqueia dinheiro.',
          ),
        ),
        findsOneWidget,
      );
      expect(
        find.textContaining('não há garantia bancária', findRichText: true),
        findsWidgets,
      );
    });

    testWidgets('empty state offers the first goal', (tester) async {
      final backend = _backend(goals: []);
      await _pump(tester, backend);
      expect(_key(FinancialGoalScreen.emptyKey), findsOneWidget);
      expect(find.text('Nenhuma meta ainda'), findsOneWidget);
      expect(_key(FinancialGoalScreen.createEmptyKey), findsOneWidget);
    });

    testWidgets('a failure shows an error with retry', (tester) async {
      final backend = _backend()..listStatus = 503;
      await _pump(tester, backend);
      expect(_key(FinancialGoalScreen.errorKey), findsOneWidget);
      expect(find.text('Metas indisponíveis'), findsOneWidget);
      backend.listStatus = null;
      await _tap(tester, FinancialGoalScreen.retryKey);
      expect(_key(FinancialGoalScreen.errorKey), findsNothing);
      expect(find.text('Reserva de emergência'), findsWidgets);
    });

    testWidgets('an expired session has no retry', (tester) async {
      final backend = _backend()..listStatus = 401;
      await _pump(tester, backend);
      expect(find.text('Sessão expirada'), findsOneWidget);
      expect(_key(FinancialGoalScreen.retryKey), findsNothing);
    });

    testWidgets('a summary failure keeps the goal and retries alone', (
      tester,
    ) async {
      final backend = _backend()..summaryStatus = 503;
      await _pump(tester, backend);
      expect(_key(FinancialGoalScreen.summaryErrorKey), findsOneWidget);
      expect(find.text('Resumo indisponível'), findsOneWidget);
      expect(find.text('Reserva de emergência'), findsWidgets);
      backend.summaryStatus = null;
      await _tap(tester, FinancialGoalScreen.summaryRetryKey);
      expect(_key(FinancialGoalScreen.summaryErrorKey), findsNothing);
      expect(_key(FinancialGoalScreen.accountsKey), findsOneWidget);
      expect(backend.listReads, 1);
    });

    testWidgets('a failed refresh keeps the goals and says they may be stale', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      backend.listThrows = true;
      await _tap(tester, FinancialGoalScreen.refreshKey);
      expect(_key(FinancialGoalScreen.refreshNoticeKey), findsOneWidget);
      expect(_key(FinancialGoalScreen.untrustedKey), findsOneWidget);
      expect(find.text('Reserva de emergência'), findsWidgets);
      final create = tester.widget<FilledButton>(
        _key(FinancialGoalScreen.createKey),
      );
      expect(create.onPressed, isNull);
    });

    testWidgets('the back button returns to Finanças', (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      await tester.tap(find.text('Voltar para Finanças'));
      await tester.pumpAndSettle();
      expect(find.text('TELA-FINANCAS'), findsOneWidget);
    });
  });

  group('create and edit', () {
    testWidgets('creates a goal and shows the server answer after a re-read', (
      tester,
    ) async {
      final backend = _backend(goals: []);
      await _pump(tester, backend);
      await _tap(tester, FinancialGoalScreen.createEmptyKey);
      expect(_key(FinancialGoalEditorDialog.dialogKey), findsOneWidget);
      expect(_key(FinancialGoalEditorDialog.noticeKey), findsOneWidget);

      final save = tester.widget<FilledButton>(
        _key(FinancialGoalEditorDialog.saveKey),
      );
      expect(save.onPressed, isNull);

      await tester.enterText(
        _key(FinancialGoalEditorDialog.titleKey),
        'Viagem',
      );
      await tester.enterText(
        _key(FinancialGoalEditorDialog.targetKey),
        '2500,50',
      );
      await tester.enterText(
        _key(FinancialGoalEditorDialog.dateKey),
        '2027-06-01',
      );
      await tester.pumpAndSettle();
      await _tap(tester, FinancialGoalEditorDialog.saveKey);

      expect(backend.creates, 1);
      expect(backend.postBodies.single['targetAmount'], '2500.50');
      expect(backend.postBodies.single['visibilityScope'], 'HOUSEHOLD');
      expect(backend.listReads, 2);
      expect(find.text('Viagem'), findsWidgets);
      expect(find.text('Prazo 01/06/2027'), findsOneWidget);
      expect(
        find.text('Meta criada. As metas foram atualizadas.'),
        findsOneWidget,
      );
    });

    testWidgets('an invalid draft explains itself and cannot be saved', (
      tester,
    ) async {
      final backend = _backend(goals: []);
      await _pump(tester, backend);
      await _tap(tester, FinancialGoalScreen.createEmptyKey);
      await tester.enterText(_key(FinancialGoalEditorDialog.titleKey), 'Meta');
      await tester.enterText(_key(FinancialGoalEditorDialog.targetKey), '0');
      await tester.enterText(
        _key(FinancialGoalEditorDialog.dateKey),
        '2020-01-01',
      );
      await tester.pumpAndSettle();

      expect(_key(FinancialGoalEditorDialog.issuesKey), findsOneWidget);
      expect(
        find.text('Informe um valor-alvo positivo válido.'),
        findsOneWidget,
      );
      expect(
        find.text('O prazo não pode estar no passado nem a mais de 100 anos.'),
        findsOneWidget,
      );
      final save = tester.widget<FilledButton>(
        _key(FinancialGoalEditorDialog.saveKey),
      );
      expect(save.onPressed, isNull);
      await _tap(tester, FinancialGoalEditorDialog.cancelKey);
      expect(backend.creates, 0);
    });

    testWidgets(
      'editing never sends the immutable fields and sends the version',
      (tester) async {
        final backend = _backend();
        await _pump(tester, backend);
        await _tap(tester, FinancialGoalScreen.editKey);
        expect(_key(FinancialGoalEditorDialog.scopeKey), findsNothing);
        expect(_key(FinancialGoalEditorDialog.currencyKey), findsNothing);
        await tester.enterText(
          _key(FinancialGoalEditorDialog.titleKey),
          'Novo nome',
        );
        await tester.pumpAndSettle();
        await _tap(tester, FinancialGoalEditorDialog.saveKey);

        expect(backend.puts, 1);
        expect(backend.putBodies.single['expectedVersion'], 1);
        expect(
          backend.putBodies.single.containsKey('visibilityScope'),
          isFalse,
        );
        expect(find.text('Novo nome'), findsWidgets);
      },
    );

    testWidgets(
      'a lost compare-and-swap shows the conflict and the current state',
      (tester) async {
        final backend = _backend();
        await _pump(tester, backend);
        backend.beforePut = () => backend.goals.single.version = 4;
        await _tap(tester, FinancialGoalScreen.editKey);
        await tester.enterText(
          _key(FinancialGoalEditorDialog.titleKey),
          'Perdida',
        );
        await tester.pumpAndSettle();
        await _tap(tester, FinancialGoalEditorDialog.saveKey);

        expect(backend.puts, 1);
        expect(_key(FinancialGoalScreen.conflictKey), findsOneWidget);
        expect(find.text('Perdida'), findsNothing);
        expect(find.text('Reserva de emergência'), findsWidgets);
        await _tap(tester, FinancialGoalScreen.conflictDismissKey);
        expect(_key(FinancialGoalScreen.conflictKey), findsNothing);
        expect(backend.puts, 1);
      },
    );
  });

  group('destinar e liberar', () {
    testWidgets(
      'only eligible accounts are offered and the notice is in the dialog',
      (tester) async {
        final backend = _backend();
        await _pump(tester, backend);
        await _tap(tester, FinancialGoalScreen.allocateKey);

        expect(_key(FinancialGoalAllocationDialog.noticeKey), findsOneWidget);
        expect(
          find.descendant(
            of: _key(FinancialGoalAllocationDialog.noticeKey),
            matching: find.text(
              'Destinação virtual; não transfere nem bloqueia dinheiro.',
            ),
          ),
          findsOneWidget,
        );
        await tester.tap(_key(FinancialGoalAllocationDialog.accountKey));
        await tester.pumpAndSettle();
        expect(find.text('Conta da casa'), findsWidgets);
        for (final excluded in [
          'Conta pessoal',
          'Conta do outro',
          'Conta em dólar',
          'Conta antiga',
        ]) {
          expect(find.text(excluded), findsNothing, reason: excluded);
        }
      },
    );

    testWidgets('allocates once, never optimistically, and re-reads', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _tap(tester, FinancialGoalScreen.allocateKey);
      await _chooseAccount(tester, 'Conta da casa');
      await _enterAmount(tester, '300,5');
      await _tap(tester, FinancialGoalAllocationDialog.saveKey);

      expect(backend.allocationPosts, 1);
      final body = backend.allocationBodies.single;
      expect(body['operation'], 'ALLOCATE');
      expect(body['amount'], '300.5');
      expect(body['accountId'], goalTestAccountId(1));
      expect(backend.events.single.amount, '300.5');
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.allocatedKey),
          matching: find.text('BRL 300,50 (30.05%)'),
        ),
        findsOneWidget,
      );
      expect(
        find.textContaining('Valor destinado virtualmente à meta'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Destinação · BRL 300,50 · Conta da casa'),
        findsOneWidget,
      );
    });

    testWidgets('an invalid amount cannot be sent', (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _tap(tester, FinancialGoalScreen.allocateKey);
      await _chooseAccount(tester, 'Conta da casa');
      await _enterAmount(tester, '0');
      expect(find.text('Informe um valor positivo válido.'), findsOneWidget);
      final save = tester.widget<FilledButton>(
        _key(FinancialGoalAllocationDialog.saveKey),
      );
      expect(save.onPressed, isNull);
      await _tap(tester, FinancialGoalAllocationDialog.cancelKey);
      expect(backend.allocationPosts, 0);
    });

    testWidgets(
      'more than the available balance is a conflict that writes nothing',
      (tester) async {
        final backend = _backend();
        await _pump(tester, backend);
        await _tap(tester, FinancialGoalScreen.allocateKey);
        await _chooseAccount(tester, 'Conta da casa');
        await _enterAmount(tester, '1000,01');
        await _tap(tester, FinancialGoalAllocationDialog.saveKey);

        expect(backend.allocationPosts, 1);
        expect(backend.events, isEmpty);
        expect(_key(FinancialGoalScreen.conflictKey), findsOneWidget);
        expect(find.textContaining('Nada foi gravado'), findsWidgets);
      },
    );

    testWidgets('releases what the goal holds, archived accounts included', (
      tester,
    ) async {
      final backend = _backend();
      backend.seed(
        backend.goals.single,
        backend.accounts[0],
        'ALLOCATE',
        '400',
      );
      backend.seed(
        backend.goals.single,
        backend.accounts[4],
        'ALLOCATE',
        '100',
      );
      await _pump(tester, backend);

      await _tap(tester, FinancialGoalScreen.releaseKey);
      await tester.tap(_key(FinancialGoalAllocationDialog.accountKey));
      await tester.pumpAndSettle();
      expect(find.text('Conta antiga (arquivada)'), findsWidgets);
      await tester.tap(find.text('Conta antiga (arquivada)').last);
      await tester.pumpAndSettle();
      expect(find.text('Destinado a esta meta BRL 100,00'), findsOneWidget);
      await _enterAmount(tester, '60');
      await _tap(tester, FinancialGoalAllocationDialog.saveKey);

      expect(backend.allocationBodies.single['operation'], 'RELEASE');
      expect(find.textContaining('Valor liberado da meta'), findsOneWidget);
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.allocatedKey),
          matching: find.text('BRL 440,00 (44%)'),
        ),
        findsOneWidget,
      );
    });

    testWidgets('release is disabled when nothing is allocated', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      final release = tester.widget<OutlinedButton>(
        _key(FinancialGoalScreen.releaseKey),
      );
      expect(release.onPressed, isNull);
    });

    testWidgets(
      'no eligible account is explained instead of hiding the action',
      (tester) async {
        final backend = _backend(
          accounts: [
            FakeGoalAccount(index: 2, name: 'Conta pessoal', scope: 'PERSONAL'),
          ],
        );
        await _pump(tester, backend);
        final allocate = tester.widget<FilledButton>(
          _key(FinancialGoalScreen.allocateKey),
        );
        expect(allocate.onPressed, isNull);
      },
    );

    testWidgets('a personal goal offers only the owner personal accounts', (
      tester,
    ) async {
      final backend = _backend(
        goals: [FakeGoal(index: 1, scope: 'PERSONAL', title: 'Minha meta')],
      );
      await _pump(tester, backend);
      await _tap(tester, FinancialGoalScreen.allocateKey);
      await tester.tap(_key(FinancialGoalAllocationDialog.accountKey));
      await tester.pumpAndSettle();
      expect(find.text('Conta pessoal'), findsWidgets);
      expect(find.text('Conta da casa'), findsNothing);
    });
  });

  group('backing and audience', () {
    testWidgets('a balance that fell is flagged in text, with no repair', (
      tester,
    ) async {
      final backend = _backend();
      backend.seed(
        backend.goals.single,
        backend.accounts[0],
        'ALLOCATE',
        '800',
      );
      backend.accounts[0].balance = '300';
      await _pump(tester, backend);

      expect(_key(FinancialGoalScreen.backingAlertKey), findsOneWidget);
      expect(find.textContaining('garantia bancária'), findsWidgets);
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.accountBackingKey(goalTestAccountId(1))),
          matching: find.text('Destinações acima do saldo'),
        ),
        findsOneWidget,
      );
      expect(find.textContaining('Faltam BRL 500,00'), findsOneWidget);
      // The destinado is still exactly what was allocated.
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.allocatedKey),
          matching: find.text('BRL 800,00 (80%)'),
        ),
        findsOneWidget,
      );
      expect(backend.events, hasLength(1));
    });

    testWidgets('a covered account shows no alert', (tester) async {
      final backend = _backend();
      backend.seed(
        backend.goals.single,
        backend.accounts[0],
        'ALLOCATE',
        '200',
      );
      await _pump(tester, backend);
      expect(_key(FinancialGoalScreen.backingAlertKey), findsNothing);
      expect(find.text('Com lastro'), findsOneWidget);
    });

    testWidgets('a household member reads a goal but cannot change it', (
      tester,
    ) async {
      final backend = _backend(
        goals: [FakeGoal(index: 1, owner: financeTestOtherOperatorId)],
      );
      backend.seed(backend.goals.single, backend.accounts[2], 'ALLOCATE', '10');
      await _pump(tester, backend);

      expect(_key(FinancialGoalScreen.readOnlyKey), findsOneWidget);
      expect(find.text('Somente leitura'), findsWidgets);
      expect(_key(FinancialGoalScreen.allocateKey), findsNothing);
      expect(_key(FinancialGoalScreen.releaseKey), findsNothing);
      expect(_key(FinancialGoalScreen.editKey), findsNothing);
      expect(find.textContaining('só quem a criou'), findsOneWidget);
      expect(_key(FinancialGoalScreen.accountsKey), findsOneWidget);
    });

    testWidgets('target reached and exceeded are spelled out', (tester) async {
      final backend = _backend(
        goals: [FakeGoal(index: 1, title: 'Meta cheia', target: '100')],
      );
      backend.seed(
        backend.goals.single,
        backend.accounts[0],
        'ALLOCATE',
        '100',
      );
      await _pump(tester, backend);
      expect(find.text('Meta atingida'), findsWidgets);

      backend.goals.single.target = '60';
      await _tap(tester, FinancialGoalScreen.refreshKey);
      expect(find.text('Acima do alvo'), findsWidgets);
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.surplusKey),
          matching: find.text('BRL 40,00'),
        ),
        findsOneWidget,
      );
    });
  });

  group('selection and cost', () {
    testWidgets('selecting a goal reads only its summary', (tester) async {
      final backend = _backend(
        goals: [
          FakeGoal(index: 1, title: 'Primeira'),
          FakeGoal(index: 2, title: 'Segunda', target: '500'),
        ],
      );
      await _pump(tester, backend);
      expect(backend.summaryReads, 1);
      await _tap(tester, FinancialGoalScreen.rowKey(goalTestId(2)));
      expect(backend.summaryReads, 2);
      expect(backend.listReads, 1);
      expect(
        find.descendant(
          of: _key(FinancialGoalScreen.targetKey),
          matching: find.text('BRL 500,00'),
        ),
        findsOneWidget,
      );
    });
  });
}
