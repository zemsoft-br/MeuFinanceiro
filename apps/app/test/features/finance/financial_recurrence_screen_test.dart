import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_editor_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_realize_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_screen.dart';

import '../../support/fake_finance_backend.dart';
import '../../support/fake_recurrence_backend.dart';

final _account = recurrenceTestAccountId(1);

FakeRecurrenceBackend _backend({
  String operatorId = financeTestOwnerId,
  List<FakeRule>? rules,
}) {
  final backend = FakeRecurrenceBackend(
    operatorId: operatorId,
    rules: rules ?? [FakeRule(index: 1, accountId: _account)],
  );
  return backend;
}

Future<GoRouter> _pump(
  WidgetTester tester,
  FakeRecurrenceBackend backend, {
  String operatorId = financeTestOwnerId,
}) async {
  tester.view.physicalSize = const Size(1400, 6000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final router = GoRouter(
    initialLocation: '/recurrences',
    routes: [
      GoRoute(
        path: '/recurrences',
        builder: (_, _) => const Scaffold(
          body: SingleChildScrollView(child: FinancialRecurrenceScreen()),
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
      overrides: recurrenceTestOverrides(backend, operatorId: operatorId),
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

Future<void> _type(WidgetTester tester, Key key, String text) async {
  await tester.enterText(_key(key), text);
  await tester.pump();
}

String _snack(WidgetTester tester) {
  final texts = tester
      .widgetList<SnackBar>(find.byType(SnackBar))
      .map((bar) => (bar.content as Text).data ?? '')
      .toList();
  return texts.isEmpty ? '' : texts.last;
}

void main() {
  group('states', () {
    testWidgets('shows active and paused rules and the forecast notice', (
      tester,
    ) async {
      final backend = _backend(
        rules: [
          FakeRule(index: 1, accountId: _account),
          FakeRule(
            index: 2,
            accountId: _account,
            description: 'Academia',
            status: 'PAUSED',
          ),
        ],
      );
      await _pump(tester, backend);
      expect(_key(FinancialRecurrenceScreen.titleKey), findsOneWidget);
      expect(_key(FinancialRecurrenceScreen.forecastNoticeKey), findsOneWidget);
      expect(
        find.textContaining('Previsto não altera o saldo'),
        findsOneWidget,
      );
      expect(_key(FinancialRecurrenceScreen.activeSectionKey), findsOneWidget);
      expect(_key(FinancialRecurrenceScreen.pausedSectionKey), findsOneWidget);
      expect(find.text('Ativas (1)'), findsOneWidget);
      expect(find.text('Pausadas (1)'), findsOneWidget);
      expect(find.text('Internet'), findsOneWidget);
      expect(find.text('Academia'), findsOneWidget);
      expect(find.textContaining('Esperado BRL 120,00'), findsNWidgets(2));
      expect(find.textContaining('Todo dia 10'), findsNWidgets(2));
      expect(
        _key(FinancialRecurrenceScreen.ruleStatusKey(recurrenceTestId(2))),
        findsOneWidget,
      );
      expect(find.text('Pausada'), findsOneWidget);
      expect(
        _key(FinancialRecurrenceScreen.occurrencesEmptyKey),
        findsOneWidget,
      );
      expect(backend.totalWrites, 0);
    });

    testWidgets('loading, then the empty state invites the first rule', (
      tester,
    ) async {
      final backend = _backend(rules: []);
      backend.listGate = Completer<void>();
      tester.view.physicalSize = const Size(1400, 4000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        ProviderScope(
          overrides: recurrenceTestOverrides(backend),
          child: const MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(child: FinancialRecurrenceScreen()),
            ),
          ),
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(_key(FinancialRecurrenceScreen.loadingKey), findsOneWidget);
      backend.listGate!.complete();
      await tester.pumpAndSettle();
      expect(_key(FinancialRecurrenceScreen.emptyKey), findsOneWidget);
      expect(_key(FinancialRecurrenceScreen.createEmptyKey), findsOneWidget);
    });

    testWidgets('an unavailable backend shows an explicit retry, never auto', (
      tester,
    ) async {
      final backend = _backend()..listStatus = 503;
      await _pump(tester, backend);
      expect(_key(FinancialRecurrenceScreen.errorKey), findsOneWidget);
      expect(find.text('Recorrências indisponíveis'), findsOneWidget);
      final reads = backend.listReads;
      await tester.pump(const Duration(seconds: 5));
      expect(backend.listReads, reads); // nothing retried by itself
      backend.listStatus = null;
      await _tap(tester, FinancialRecurrenceScreen.retryKey);
      expect(find.text('Internet'), findsOneWidget);
      expect(backend.listReads, reads + 1);
    });

    testWidgets('permission and session failures have no retry', (
      tester,
    ) async {
      final forbidden = _backend()..listStatus = 403;
      await _pump(tester, forbidden);
      expect(find.text('Acesso indisponível'), findsOneWidget);
      expect(_key(FinancialRecurrenceScreen.retryKey), findsNothing);
    });

    testWidgets('an invalid response is not rendered', (tester) async {
      final backend = _backend()..listBodyOverride = '{"items":[{"id":"x"}]}';
      await _pump(tester, backend);
      expect(find.text('Resposta inválida'), findsOneWidget);
      expect(find.text('Internet'), findsNothing);
    });

    testWidgets('a rule of another owner is read-only with no actions', (
      tester,
    ) async {
      final backend = _backend(operatorId: financeTestOtherOperatorId);
      await _pump(tester, backend, operatorId: financeTestOtherOperatorId);
      final id = recurrenceTestId(1);
      expect(_key(FinancialRecurrenceScreen.readOnlyKey(id)), findsOneWidget);
      expect(_key(FinancialRecurrenceScreen.editKey(id)), findsNothing);
      expect(_key(FinancialRecurrenceScreen.pauseKey(id)), findsNothing);
      expect(_key(FinancialRecurrenceScreen.generateKey(id)), findsNothing);
    });

    testWidgets('the back button returns to Finanças', (tester) async {
      final router = await _pump(tester, _backend());
      await tester.tap(find.text('Voltar para Finanças'));
      await tester.pumpAndSettle();
      expect(router.state.uri.path, '/app/financas');
    });
  });

  group('forecasts', () {
    testWidgets('Gerar is explicit and a forecast does not move the balance', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      final id = recurrenceTestId(1);
      expect(backend.occurrences, isEmpty);
      await _tap(tester, FinancialRecurrenceScreen.generateKey(id));
      expect(find.text('Prevista'), findsOneWidget);
      expect(
        find.textContaining('Previsão: não afeta o saldo até ser registrada.'),
        findsOneWidget,
      );
      expect(find.textContaining('Previsto BRL 120,00'), findsOneWidget);
      expect(find.textContaining('10/10/2026'), findsWidgets);
      expect(backend.ledger, isEmpty);
      expect(backend.balanceOf(_account), '1000');
      expect(_snack(tester), contains('Previsto não altera o saldo'));
    });

    testWidgets('months can be browsed without writing anything', (
      tester,
    ) async {
      final backend = _backend();
      backend.addOccurrence(backend.rules.single, '2026-11');
      await _pump(tester, backend);
      expect(find.text('outubro de 2026'), findsOneWidget);
      await _tap(tester, FinancialRecurrenceScreen.nextMonthKey);
      expect(find.text('novembro de 2026'), findsOneWidget);
      expect(find.text('Prevista'), findsOneWidget);
      expect(backend.totalWrites, 0);
    });
  });

  group('Registrar', () {
    testWidgets(
      'confirms actual amount and dates, then shows expected x actual',
      (tester) async {
        final backend = _backend();
        final occurrence = backend.addOccurrence(
          backend.rules.single,
          '2026-10',
        );
        await _pump(tester, backend);
        await _tap(
          tester,
          FinancialRecurrenceScreen.registerKey(occurrence.id),
        );
        expect(
          _key(FinancialRecurrenceRealizeDialog.dialogKey),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: _key(FinancialRecurrenceRealizeDialog.noticeKey),
            matching: find.textContaining('Registrar cria um lançamento real'),
          ),
          findsOneWidget,
        );
        // Pre-filled with the forecast; the user decides the real values.
        final amount = tester.widget<TextField>(
          _key(FinancialRecurrenceRealizeDialog.amountKey),
        );
        expect(amount.controller!.text, '120');
        await _type(
          tester,
          FinancialRecurrenceRealizeDialog.amountKey,
          '127,50',
        );
        await _type(
          tester,
          FinancialRecurrenceRealizeDialog.effectiveDateKey,
          '2026-10-11',
        );
        await _type(
          tester,
          FinancialRecurrenceRealizeDialog.competenceDateKey,
          '2026-10-01',
        );
        expect(backend.ledger, isEmpty); // nothing before the confirmation
        await _tap(tester, FinancialRecurrenceRealizeDialog.confirmKey);

        expect(backend.ledger, hasLength(1));
        expect(backend.balanceOf(_account), '872.5');
        expect(find.text('Registrada'), findsOneWidget);
        final actual = find.byKey(
          FinancialRecurrenceScreen.occurrenceActualKey(occurrence.id),
        );
        expect(actual, findsOneWidget);
        expect(find.textContaining('Real BRL 127,50'), findsOneWidget);
        expect(find.textContaining('Previsto BRL 120,00'), findsOneWidget);
        expect(find.textContaining('Lançamento ativo'), findsOneWidget);
        expect(
          _key(FinancialRecurrenceScreen.registerKey(occurrence.id)),
          findsNothing,
        );
        expect(_snack(tester), contains('Lançamento registrado'));
        expect(backend.realizeCalls, 1);
      },
    );

    testWidgets('an invalid amount or date cannot be confirmed', (
      tester,
    ) async {
      final backend = _backend();
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceScreen.registerKey(occurrence.id));
      await _type(tester, FinancialRecurrenceRealizeDialog.amountKey, '0');
      expect(
        tester
            .widget<FilledButton>(
              _key(FinancialRecurrenceRealizeDialog.confirmKey),
            )
            .onPressed,
        isNull,
      );
      expect(find.text('Informe o valor real, positivo.'), findsOneWidget);
      await _type(tester, FinancialRecurrenceRealizeDialog.amountKey, '10');
      await _type(
        tester,
        FinancialRecurrenceRealizeDialog.effectiveDateKey,
        '2026-02-30',
      );
      expect(
        find.text('Informe a data efetiva no formato AAAA-MM-DD.'),
        findsOneWidget,
      );
      expect(backend.realizeCalls, 0);
    });

    testWidgets('cancelling sends nothing', (tester) async {
      final backend = _backend();
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceScreen.registerKey(occurrence.id));
      await _tap(tester, FinancialRecurrenceRealizeDialog.cancelKey);
      expect(backend.totalWrites, 0);
      expect(find.text('Prevista'), findsOneWidget);
    });

    testWidgets('an ambiguous answer is never resent and says so', (
      tester,
    ) async {
      final backend = _backend();
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await _pump(tester, backend);
      backend.writeCommitsThenFails = true;
      await _tap(tester, FinancialRecurrenceScreen.registerKey(occurrence.id));
      await _tap(tester, FinancialRecurrenceRealizeDialog.confirmKey);
      expect(backend.realizeCalls, 1);
      expect(_snack(tester), contains('não será reenviado automaticamente'));
      await tester.pump(const Duration(seconds: 5));
      expect(backend.realizeCalls, 1);
      expect(backend.ledger, hasLength(1));
    });

    testWidgets('a reversed Movement keeps the occurrence registered', (
      tester,
    ) async {
      final backend = _backend();
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceScreen.registerKey(occurrence.id));
      await _tap(tester, FinancialRecurrenceRealizeDialog.confirmKey);
      backend.reverseMovementOf(occurrence.id);
      await _tap(tester, FinancialRecurrenceScreen.refreshKey);
      expect(find.text('Registrada'), findsOneWidget);
      expect(find.textContaining('Lançamento estornado'), findsOneWidget);
      expect(
        _key(FinancialRecurrenceScreen.registerKey(occurrence.id)),
        findsNothing,
      );
    });
  });

  group('Pular', () {
    testWidgets('asks first, then creates no Movement', (tester) async {
      final backend = _backend();
      final occurrence = backend.addOccurrence(backend.rules.single, '2026-10');
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceScreen.skipKey(occurrence.id));
      expect(find.textContaining('Nenhum lançamento é criado'), findsOneWidget);
      await _tap(tester, FinancialRecurrenceScreen.skipCancelKey);
      expect(backend.skipCalls, 0);
      await _tap(tester, FinancialRecurrenceScreen.skipKey(occurrence.id));
      await _tap(tester, FinancialRecurrenceScreen.skipConfirmKey);
      expect(backend.skipCalls, 1);
      expect(find.text('Pulada'), findsOneWidget);
      expect(backend.ledger, isEmpty);
      expect(backend.balanceOf(_account), '1000');
      expect(_snack(tester), contains('Nenhum lançamento foi criado'));
    });
  });

  group('pause and resume', () {
    testWidgets('pausing moves the rule and removes Gerar, keeping history', (
      tester,
    ) async {
      final backend = _backend();
      backend.addOccurrence(backend.rules.single, '2026-10');
      await _pump(tester, backend);
      final id = recurrenceTestId(1);
      await _tap(tester, FinancialRecurrenceScreen.pauseKey(id));
      expect(find.text('Pausadas (1)'), findsOneWidget);
      expect(find.text('Ativas (0)'), findsOneWidget);
      expect(_key(FinancialRecurrenceScreen.generateKey(id)), findsNothing);
      expect(
        find.textContaining(
          'não gera novas previsões. O histórico foi mantido',
        ),
        findsWidgets,
      );
      expect(find.text('Prevista'), findsOneWidget); // history stays
      await _tap(tester, FinancialRecurrenceScreen.resumeKey(id));
      expect(find.text('Ativas (1)'), findsOneWidget);
      expect(_key(FinancialRecurrenceScreen.generateKey(id)), findsOneWidget);
      expect(backend.generateCalls, 0); // resuming generated nothing
    });
  });

  group('create and edit', () {
    testWidgets('creates a monthly rule from the form', (tester) async {
      final backend = _backend(rules: []);
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceScreen.createEmptyKey);
      expect(_key(FinancialRecurrenceEditorDialog.dialogKey), findsOneWidget);
      // Nothing to send yet.
      expect(
        tester
            .widget<FilledButton>(_key(FinancialRecurrenceEditorDialog.saveKey))
            .onPressed,
        isNull,
      );
      await _type(
        tester,
        FinancialRecurrenceEditorDialog.descriptionKey,
        'Aluguel',
      );
      await _tap(tester, FinancialRecurrenceEditorDialog.accountKey);
      await tester.tap(find.text('Conta Corrente · BRL').last);
      await tester.pumpAndSettle();
      await _type(tester, FinancialRecurrenceEditorDialog.amountKey, '1500,00');
      await _type(tester, FinancialRecurrenceEditorDialog.dayKey, '5');
      await _tap(tester, FinancialRecurrenceEditorDialog.saveKey);

      expect(backend.rules, hasLength(1));
      final rule = backend.rules.single;
      expect(rule.description, 'Aluguel');
      expect(rule.expected, '1500');
      expect(rule.dayOfMonth, 5);
      expect(rule.effect, 'EXPENSE');
      expect(find.text('Aluguel'), findsOneWidget);
      expect(_snack(tester), contains('Nenhuma previsão foi gerada ainda'));
      expect(backend.occurrences, isEmpty);
      expect(backend.ledger, isEmpty);
    });

    testWidgets('only the operator\'s active accounts are offered', (
      tester,
    ) async {
      final backend = _backend(rules: []);
      backend.accounts
        ..add(
          FakeAccount(
            id: recurrenceTestAccountId(2),
            name: 'Conta de outro',
            owner: financeTestOtherOperatorId,
          ),
        )
        ..add(
          FakeAccount(
            id: recurrenceTestAccountId(3),
            name: 'Conta arquivada',
            status: 'ARCHIVED',
          ),
        );
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceScreen.createEmptyKey);
      await _tap(tester, FinancialRecurrenceEditorDialog.accountKey);
      expect(find.text('Conta Corrente · BRL'), findsWidgets);
      expect(find.text('Conta de outro · BRL'), findsNothing);
      expect(find.text('Conta arquivada · BRL'), findsNothing);
    });

    testWidgets('the form states why it cannot be saved', (tester) async {
      await _pump(tester, _backend(rules: []));
      await _tap(tester, FinancialRecurrenceScreen.createEmptyKey);
      await _type(tester, FinancialRecurrenceEditorDialog.descriptionKey, 'x');
      await _type(tester, FinancialRecurrenceEditorDialog.amountKey, '0');
      await _type(tester, FinancialRecurrenceEditorDialog.dayKey, '40');
      expect(_key(FinancialRecurrenceEditorDialog.issuesKey), findsOneWidget);
      expect(find.text('Escolha a conta.'), findsOneWidget);
      expect(find.text('Informe um valor esperado positivo.'), findsOneWidget);
      expect(find.text('Informe o dia do mês, de 1 a 31.'), findsOneWidget);
    });

    testWidgets(
      'editing keeps the identity read-only and explains superseding',
      (tester) async {
        final backend = _backend();
        backend.addOccurrence(backend.rules.single, '2026-11');
        await _pump(tester, backend);
        final id = recurrenceTestId(1);
        await _tap(tester, FinancialRecurrenceScreen.editKey(id));
        expect(
          _key(FinancialRecurrenceEditorDialog.immutableKey),
          findsOneWidget,
        );
        expect(_key(FinancialRecurrenceEditorDialog.accountKey), findsNothing);
        expect(
          _key(FinancialRecurrenceEditorDialog.supersedeNoticeKey),
          findsOneWidget,
        );
        await _type(tester, FinancialRecurrenceEditorDialog.amountKey, '135');
        await _tap(tester, FinancialRecurrenceEditorDialog.saveKey);
        expect(backend.rules.single.expected, '135');
        expect(backend.rules.single.version, 2);
        expect(_snack(tester), contains('Recorrência atualizada'));
        expect(find.textContaining('Esperado BRL 135,00'), findsOneWidget);
      },
    );

    testWidgets('a lost compare-and-swap is explained, never re-applied', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      final rule = backend.rules.single;
      final id = recurrenceTestId(1);
      backend.beforeWrite = () => rule.version += 1;
      await _tap(tester, FinancialRecurrenceScreen.editKey(id));
      await _type(tester, FinancialRecurrenceEditorDialog.amountKey, '999');
      await _tap(tester, FinancialRecurrenceEditorDialog.saveKey);
      expect(_key(FinancialRecurrenceScreen.conflictKey), findsOneWidget);
      expect(find.textContaining('Conflito: o estado mudou'), findsOneWidget);
      expect(find.textContaining('Esperado BRL 120,00'), findsOneWidget);
      expect(backend.writes(AuthHttpMethod.put), 1);
      await _tap(tester, FinancialRecurrenceScreen.conflictDismissKey);
      expect(_key(FinancialRecurrenceScreen.conflictKey), findsNothing);
    });

    testWidgets('a refresh that fails blocks writes until it succeeds', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      backend.listStatus = 503;
      await _tap(tester, FinancialRecurrenceScreen.refreshKey);
      expect(_key(FinancialRecurrenceScreen.untrustedKey), findsOneWidget);
      expect(_key(FinancialRecurrenceScreen.refreshNoticeKey), findsOneWidget);
      expect(find.text('Internet'), findsOneWidget); // still shown
      expect(
        tester
            .widget<FilledButton>(_key(FinancialRecurrenceScreen.createKey))
            .onPressed,
        isNull,
      );
      backend.listStatus = null;
      await _tap(tester, FinancialRecurrenceScreen.refreshKey);
      expect(_key(FinancialRecurrenceScreen.untrustedKey), findsNothing);
    });
  });
}
