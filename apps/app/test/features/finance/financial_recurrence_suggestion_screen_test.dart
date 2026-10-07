import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_screen.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_suggestion_review_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_suggestions_section.dart';

import '../../support/fake_finance_backend.dart';
import '../../support/fake_recurrence_backend.dart';

final _account = recurrenceTestAccountId(1);
final _fp = suggestionTestFingerprint(1);
const _otherOperator = '30000000-0000-4000-8000-000000000009';

FakeRecurrenceBackend _backend({
  bool withRule = false,
  bool withSuggestion = true,
  String operatorId = financeTestOwnerId,
  List<FakeSuggestionEvidence>? evidence,
}) {
  final backend = FakeRecurrenceBackend(operatorId: operatorId);
  if (withRule) backend.rules.add(FakeRule(index: 1, accountId: _account));
  if (withSuggestion) {
    backend.suggestions.add(
      FakeSuggestion(index: 1, accountId: _account, evidence: evidence),
    );
  }
  return backend;
}

Future<void> _pump(
  WidgetTester tester,
  FakeRecurrenceBackend backend, {
  String operatorId = financeTestOwnerId,
}) async {
  tester.view.physicalSize = const Size(1400, 8000);
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
  group('the Sugestões section', () {
    testWidgets(
      'explains the pattern, shows evidence and reasons and creates nothing',
      (tester) async {
        final backend = _backend(withRule: true);
        await _pump(tester, backend);

        expect(
          _key(FinancialRecurrenceSuggestionsSection.sectionKey),
          findsOneWidget,
        );
        expect(find.text('Sugestões (1)'), findsOneWidget);
        expect(
          find.text(
            'Detectamos um padrão; nada será criado sem sua confirmação.',
          ),
          findsOneWidget,
        );
        expect(
          _key(FinancialRecurrenceSuggestionsSection.cardKey(_fp)),
          findsOneWidget,
        );
        expect(find.text('Streaming'), findsOneWidget);
        expect(
          find.textContaining('Conta Corrente · BRL · despesa'),
          findsOneWidget,
        );
        expect(
          tester
              .widget<Text>(
                _key(FinancialRecurrenceSuggestionsSection.patternKey(_fp)),
              )
              .data,
          contains('Todo dia 10 · 3 meses seguidos'),
        );
        for (final line in [
          '10/08/2026 · BRL 39,90',
          '10/09/2026 · BRL 39,90',
          '10/10/2026 · BRL 39,90',
        ]) {
          expect(find.text(line), findsOneWidget);
        }
        expect(find.text('Valor fixo'), findsOneWidget);
        expect(find.textContaining('Valor fixo: BRL 39,90.'), findsOneWidget);
        for (final reason in [
          'A descrição é igual em todas as cobranças',
          'As cobranças aconteceram em meses seguidos.',
          'Há uma única cobrança por mês.',
          'dias próximos do mês',
          'O valor é o mesmo em todas as cobranças.',
        ]) {
          expect(find.textContaining(reason), findsOneWidget);
        }
        // Reading wrote nothing and created no fact or forecast.
        expect(backend.totalWrites, 0);
        expect(backend.rules, hasLength(1));
        expect(backend.occurrences, isEmpty);
        expect(backend.ledger, isEmpty);
      },
    );

    testWidgets('a variable amount is explicit, with min, max and last', (
      tester,
    ) async {
      final backend = _backend(
        evidence: const [
          FakeSuggestionEvidence('2026-08-10', '100.00'),
          FakeSuggestionEvidence('2026-09-10', '120.50'),
          FakeSuggestionEvidence('2026-10-10', '110.25'),
        ],
      );
      await _pump(tester, backend);
      expect(find.text('Valor variável'), findsOneWidget);
      expect(
        tester
            .widget<Text>(
              _key(FinancialRecurrenceSuggestionsSection.amountKey(_fp)),
            )
            .data,
        contains('de BRL 100,00 a BRL 120,50; último BRL 110,25'),
      );
      expect(
        find.textContaining('O valor variou entre as cobranças.'),
        findsOneWidget,
      );
    });

    testWidgets('shows even when there is no recurrence yet', (tester) async {
      await _pump(tester, _backend());
      expect(_key(FinancialRecurrenceScreen.emptyKey), findsOneWidget);
      expect(
        _key(FinancialRecurrenceSuggestionsSection.cardKey(_fp)),
        findsOneWidget,
      );
    });

    testWidgets('no suggestion is an explicit empty state', (tester) async {
      await _pump(tester, _backend(withRule: true, withSuggestion: false));
      expect(
        _key(FinancialRecurrenceSuggestionsSection.emptyKey),
        findsOneWidget,
      );
      expect(find.text('Sugestões (0)'), findsOneWidget);
    });

    testWidgets(
      'a failing suggestions read says so and keeps the rules usable',
      (tester) async {
        final backend = _backend(withRule: true)..suggestionsStatus = 503;
        await _pump(tester, backend);
        expect(
          _key(FinancialRecurrenceSuggestionsSection.unavailableKey),
          findsOneWidget,
        );
        expect(
          _key(FinancialRecurrenceScreen.activeSectionKey),
          findsOneWidget,
        );
        expect(find.text('Internet'), findsOneWidget);
        expect(_key(FinancialRecurrenceScreen.createKey), findsOneWidget);
        expect(backend.suggestionReads, 1); // never retried automatically
      },
    );

    testWidgets(
      'a non-owner sees it read-only: no create, only a personal dismiss',
      (tester) async {
        final backend = _backend(operatorId: _otherOperator);
        await _pump(tester, backend, operatorId: _otherOperator);
        expect(
          _key(FinancialRecurrenceSuggestionsSection.readOnlyKey(_fp)),
          findsOneWidget,
        );
        expect(
          _key(FinancialRecurrenceSuggestionsSection.createKey(_fp)),
          findsNothing,
        );
        expect(
          _key(FinancialRecurrenceSuggestionsSection.dismissKey(_fp)),
          findsOneWidget,
        );
        expect(find.textContaining('só quem é dono da conta'), findsWidgets);
      },
    );
  });

  group('Criar recorrência', () {
    testWidgets(
      'opens a review with every field pre-filled and sends nothing yet',
      (tester) async {
        final backend = _backend();
        await _pump(tester, backend);
        await _tap(
          tester,
          FinancialRecurrenceSuggestionsSection.createKey(_fp),
        );

        expect(
          _key(FinancialRecurrenceSuggestionReviewDialog.dialogKey),
          findsOneWidget,
        );
        expect(
          find.textContaining(
            'Criar a recorrência não gera previsões nem lançamentos',
          ),
          findsOneWidget,
        );
        TextField field(Key key) => tester.widget<TextField>(_key(key));
        expect(
          field(
            FinancialRecurrenceSuggestionReviewDialog.descriptionKey,
          ).controller!.text,
          'Streaming',
        );
        expect(
          field(
            FinancialRecurrenceSuggestionReviewDialog.amountKey,
          ).controller!.text,
          '39.9',
        );
        expect(
          field(
            FinancialRecurrenceSuggestionReviewDialog.dayKey,
          ).controller!.text,
          '10',
        );
        expect(
          field(
            FinancialRecurrenceSuggestionReviewDialog.startDateKey,
          ).controller!.text,
          '2026-11-01',
        );
        expect(
          field(
            FinancialRecurrenceSuggestionReviewDialog.endDateKey,
          ).controller!.text,
          isEmpty,
        );
        expect(
          find.textContaining('Estes três dados vêm da sugestão'),
          findsOneWidget,
        );
        expect(backend.acceptCalls, 0);
      },
    );

    testWidgets('cancelling sends nothing', (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceSuggestionsSection.createKey(_fp));
      await _tap(tester, FinancialRecurrenceSuggestionReviewDialog.cancelKey);
      expect(backend.acceptCalls, 0);
      expect(backend.rules, isEmpty);
      expect(
        _key(FinancialRecurrenceSuggestionsSection.cardKey(_fp)),
        findsOneWidget,
      );
    });

    testWidgets('an invalid review cannot be confirmed and says why', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceSuggestionsSection.createKey(_fp));
      await _type(
        tester,
        FinancialRecurrenceSuggestionReviewDialog.amountKey,
        '0',
      );
      await _type(
        tester,
        FinancialRecurrenceSuggestionReviewDialog.dayKey,
        '40',
      );
      await _type(
        tester,
        FinancialRecurrenceSuggestionReviewDialog.startDateKey,
        '2026-13-01',
      );
      await _type(
        tester,
        FinancialRecurrenceSuggestionReviewDialog.descriptionKey,
        '   ',
      );
      expect(
        _key(FinancialRecurrenceSuggestionReviewDialog.issuesKey),
        findsOneWidget,
      );
      expect(
        find.textContaining('Informe um valor esperado positivo.'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Informe o dia do mês, de 1 a 31.'),
        findsOneWidget,
      );
      expect(find.textContaining('data de início'), findsOneWidget);
      final confirm = tester.widget<FilledButton>(
        _key(FinancialRecurrenceSuggestionReviewDialog.confirmKey),
      );
      expect(confirm.onPressed, isNull);
      expect(backend.acceptCalls, 0);
    });

    testWidgets(
      'confirming creates one recurrence, no forecast and no Movement',
      (tester) async {
        final backend = _backend();
        await _pump(tester, backend);
        final balance = backend.balanceOf(_account);
        await _tap(
          tester,
          FinancialRecurrenceSuggestionsSection.createKey(_fp),
        );
        await _type(
          tester,
          FinancialRecurrenceSuggestionReviewDialog.amountKey,
          '41,90',
        );
        await _type(
          tester,
          FinancialRecurrenceSuggestionReviewDialog.dayKey,
          '12',
        );
        await _tap(
          tester,
          FinancialRecurrenceSuggestionReviewDialog.confirmKey,
        );

        expect(backend.acceptCalls, 1);
        expect(backend.writeBodies.single.keys.toSet(), {
          'idempotencyKey',
          'description',
          'expectedAmount',
          'startDate',
          'dayOfMonth',
          'endDate',
        });
        expect(backend.writeBodies.single['expectedAmount'], '41.90');
        expect(backend.rules, hasLength(1));
        expect(backend.rules.single.dayOfMonth, 12);
        expect(backend.occurrences, isEmpty);
        expect(backend.ledger, isEmpty);
        expect(backend.balanceOf(_account), balance);
        expect(
          _snack(tester),
          contains('Recorrência criada a partir da sugestão'),
        );
        expect(_snack(tester), contains('A tela foi atualizada.'));
        // The canonical re-read replaced the section: the suggestion is gone.
        expect(
          _key(FinancialRecurrenceSuggestionsSection.cardKey(_fp)),
          findsNothing,
        );
        expect(find.text('Ativas (1)'), findsOneWidget);
      },
    );

    testWidgets('a conflict is explained, never re-applied or resent', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceSuggestionsSection.createKey(_fp));
      backend.suggestions.single.status = 'DISMISSED'; // decided elsewhere
      await _tap(tester, FinancialRecurrenceSuggestionReviewDialog.confirmKey);

      expect(backend.acceptCalls, 1);
      expect(backend.rules, isEmpty);
      expect(_snack(tester), contains('A sugestão mudou ou já foi decidida'));
      expect(_key(FinancialRecurrenceScreen.conflictKey), findsOneWidget);
      expect(
        _key(FinancialRecurrenceSuggestionsSection.cardKey(_fp)),
        findsNothing,
      );
    });

    testWidgets('an ambiguous answer is never resent and says so', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceSuggestionsSection.createKey(_fp));
      backend.writeStatus = 503;
      await _tap(tester, FinancialRecurrenceSuggestionReviewDialog.confirmKey);
      expect(backend.acceptCalls, 1);
      expect(_snack(tester), contains('não será reenviado automaticamente'));
      await tester.pump(const Duration(seconds: 10));
      expect(backend.acceptCalls, 1);
    });
  });

  group('writes are blocked while busy or untrusted', () {
    testWidgets('while a write is in flight both actions are disabled', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      final gate = Completer<void>();
      await _tap(tester, FinancialRecurrenceSuggestionsSection.createKey(_fp));
      backend.writeGate = gate;
      await tester.ensureVisible(
        _key(FinancialRecurrenceSuggestionReviewDialog.confirmKey),
      );
      await tester.tap(
        _key(FinancialRecurrenceSuggestionReviewDialog.confirmKey),
      );
      await tester.pump();
      await tester.pump();

      FilledButton create() => tester.widget<FilledButton>(
        _key(FinancialRecurrenceSuggestionsSection.createKey(_fp)),
      );
      OutlinedButton dismiss() => tester.widget<OutlinedButton>(
        _key(FinancialRecurrenceSuggestionsSection.dismissKey(_fp)),
      );
      expect(create().onPressed, isNull);
      expect(dismiss().onPressed, isNull);
      gate.complete();
      await tester.pumpAndSettle();
      expect(backend.acceptCalls, 1);
    });

    testWidgets('after a failed re-read the screen is untrusted: no actions', (
      tester,
    ) async {
      final backend = _backend(withRule: true);
      await _pump(tester, backend);
      backend.listStatus = 503; // the canonical re-read after the write fails
      await _tap(tester, FinancialRecurrenceSuggestionsSection.dismissKey(_fp));
      await _tap(
        tester,
        FinancialRecurrenceSuggestionsSection.dismissConfirmKey,
      );
      expect(_key(FinancialRecurrenceScreen.untrustedKey), findsOneWidget);
      expect(
        _key(FinancialRecurrenceSuggestionsSection.createKey(_fp)),
        findsOneWidget,
      );
      expect(
        tester
            .widget<FilledButton>(
              _key(FinancialRecurrenceSuggestionsSection.createKey(_fp)),
            )
            .onPressed,
        isNull,
      );
      expect(
        tester
            .widget<OutlinedButton>(
              _key(FinancialRecurrenceSuggestionsSection.dismissKey(_fp)),
            )
            .onPressed,
        isNull,
      );
    });
  });

  group('Dispensar', () {
    testWidgets('asks first, then hides it and creates nothing', (
      tester,
    ) async {
      final backend = _backend(withRule: true);
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceSuggestionsSection.dismissKey(_fp));
      expect(
        find.textContaining('deixa de ser sugerida só para você'),
        findsOneWidget,
      );
      expect(backend.dismissCalls, 0);
      await _tap(
        tester,
        FinancialRecurrenceSuggestionsSection.dismissConfirmKey,
      );

      expect(backend.dismissCalls, 1);
      expect(_snack(tester), contains('Sugestão dispensada só para você'));
      expect(
        _key(FinancialRecurrenceSuggestionsSection.cardKey(_fp)),
        findsNothing,
      );
      expect(backend.rules, hasLength(1));
      expect(backend.occurrences, isEmpty);
      expect(backend.ledger, isEmpty);
    });

    testWidgets('cancelling sends nothing', (tester) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceSuggestionsSection.dismissKey(_fp));
      await _tap(
        tester,
        FinancialRecurrenceSuggestionsSection.dismissCancelKey,
      );
      expect(backend.dismissCalls, 0);
      expect(
        _key(FinancialRecurrenceSuggestionsSection.cardKey(_fp)),
        findsOneWidget,
      );
    });

    testWidgets('a conflict is explained and the section is read again', (
      tester,
    ) async {
      final backend = _backend();
      await _pump(tester, backend);
      await _tap(tester, FinancialRecurrenceSuggestionsSection.dismissKey(_fp));
      backend.suggestions.single.status = 'ACCEPTED';
      await _tap(
        tester,
        FinancialRecurrenceSuggestionsSection.dismissConfirmKey,
      );
      expect(backend.dismissCalls, 1);
      expect(_snack(tester), contains('A sugestão mudou ou já foi decidida'));
      expect(
        _key(FinancialRecurrenceSuggestionsSection.cardKey(_fp)),
        findsNothing,
      );
    });
  });

  group('vertical smoke (Streaming, #256)', () {
    testWidgets(
      'suggested, reviewed, confirmed: one rule, no forecast, no Movement',
      (tester) async {
        final backend = _backend(withRule: false);
        await _pump(tester, backend);
        final balance = backend.balanceOf(_account);

        // The pattern is shown with evidence; nothing exists yet.
        expect(find.text('Sugestões (1)'), findsOneWidget);
        expect(find.text('10/10/2026 · BRL 39,90'), findsOneWidget);
        expect(backend.rules, isEmpty);

        // The owner reviews value and day, then confirms.
        await _tap(
          tester,
          FinancialRecurrenceSuggestionsSection.createKey(_fp),
        );
        await _type(
          tester,
          FinancialRecurrenceSuggestionReviewDialog.amountKey,
          '41.90',
        );
        await _type(
          tester,
          FinancialRecurrenceSuggestionReviewDialog.dayKey,
          '11',
        );
        await _tap(
          tester,
          FinancialRecurrenceSuggestionReviewDialog.confirmKey,
        );

        // Exactly one rule; zero forecasts and zero Movements; balance unchanged.
        expect(backend.acceptCalls, 1);
        expect(backend.rules, hasLength(1));
        expect(backend.rules.single.expected, '41.9');
        expect(backend.rules.single.dayOfMonth, 11);
        expect(backend.occurrences, isEmpty);
        expect(backend.ledger, isEmpty);
        expect(backend.balanceOf(_account), balance);
        // The suggestion is gone and the new rule is listed.
        expect(
          _key(FinancialRecurrenceSuggestionsSection.cardKey(_fp)),
          findsNothing,
        );
        expect(find.text('Ativas (1)'), findsOneWidget);
        expect(find.textContaining('Esperado BRL 41,90'), findsOneWidget);
        // Nothing else was sent: no retry, no extra write.
        expect(backend.totalWrites, 1);
      },
    );
  });
}
