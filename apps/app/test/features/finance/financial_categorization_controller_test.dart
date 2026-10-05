import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_categorization_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

import '../../support/fake_finance_backend.dart';

final _category = financeTestCategoryId(1);
final _rulesProvider = financialCategorizationRulesControllerProvider;
final _applyProvider = financialCategorizationApplyControllerProvider(
  financeTestAccountId,
);
final _detail = financialAccountDetailControllerProvider(financeTestAccountId);

FakeFinanceBackend _backend({
  List<FakeMovementSpec>? movements,
  Map<String, String>? allocations,
  List<String>? rules,
}) {
  final backend = FakeFinanceBackend(
    movements:
        movements ??
        [
          FakeMovementSpec(
            id: financeTestMovementId(1),
            description: 'Padaria 1',
          ),
          FakeMovementSpec(
            id: financeTestMovementId(2),
            description: 'Padaria 2',
          ),
          FakeMovementSpec(
            id: financeTestMovementId(3),
            description: 'Padaria 3',
          ),
        ],
    allocations: allocations,
    categories: [
      fakeCategoryJson(id: _category, name: 'Mercado'),
      fakeCategoryJson(id: financeTestCategoryId(2), name: 'Lazer'),
    ],
  );
  backend.rules =
      rules ?? [fakeRuleJson(id: financeTestRuleId(1), categoryId: _category)];
  return backend;
}

ProviderContainer _container(FakeFinanceBackend backend) {
  final container = financeTestContainer(backend);
  addTearDown(container.dispose);
  container.listen(_rulesProvider, (previous, next) {}, fireImmediately: true);
  container.listen(_applyProvider, (previous, next) {}, fireImmediately: true);
  container.listen(_detail, (previous, next) {}, fireImmediately: true);
  return container;
}

FinancialCategorizationRuleCreateInput _input({
  String pattern = 'Mercado',
  int priority = 10,
}) => FinancialCategorizationRuleCreateInput(
  matcher: FinancialCategorizationMatcher.contains,
  pattern: pattern,
  targetCategoryId: _category,
  priority: priority,
);

void main() {
  group('rules list', () {
    test(
      'loads rules, categories and accounts: a fixed number of reads',
      () async {
        for (final count in [0, 1, 40]) {
          final backend = _backend(
            rules: [
              for (var i = 1; i <= count; i += 1)
                fakeRuleJson(id: financeTestRuleId(i), categoryId: _category),
            ],
          );
          final container = _container(backend);
          await container.read(_rulesProvider.notifier).load();
          final state = container.read(_rulesProvider);
          expect(state.phase, FinancialLoadPhase.loaded);
          expect(state.rules, hasLength(count));
          expect(backend.calls, hasLength(3));
          expect(backend.ruleReads, 1);
          expect(backend.categoryReads, 1);
        }
      },
    );

    test('a failed load never fakes an empty list', () async {
      final backend = _backend()..rulesReadStatus = 500;
      final container = _container(backend);
      await container.read(_rulesProvider.notifier).load();
      expect(
        container.read(_rulesProvider).phase,
        FinancialLoadPhase.temporarilyUnavailable,
      );
      expect(container.read(_rulesProvider).rules, isEmpty);
    });
  });

  group('rule creation', () {
    test('no optimistic state: the rule appears only after the 201', () async {
      final backend = _backend();
      final container = _container(backend);
      final controller = container.read(_rulesProvider.notifier);
      await controller.load();
      final before = container.read(_rulesProvider).rules.length;

      late FinancialCategorizationRulesState midFlight;
      backend.onRulePost = (_) => midFlight = container.read(_rulesProvider);
      final outcome = await controller.createRule(_input());

      expect(outcome, FinancialMutationOutcome.success);
      expect(midFlight.rules, hasLength(before));
      expect(midFlight.mutationInFlight, isTrue);
      final state = container.read(_rulesProvider);
      expect(state.rules, hasLength(before + 1));
      expect(state.mutationInFlight, isFalse);
      expect(backend.rulePosts, 1);
    });

    test(
      'an ambiguous write is read back once and never resent automatically',
      () async {
        final backend = _backend()..rulePostStatus = 503;
        final container = _container(backend);
        final controller = container.read(_rulesProvider.notifier);
        await controller.load();

        final outcome = await controller.createRule(_input());

        expect(outcome, FinancialMutationOutcome.unknownOutcomeReconciled);
        expect(backend.rulePosts, 1, reason: 'zero automatic retries');
        expect(backend.ruleReads, 2, reason: 'exactly one reconciliation read');
        expect(container.read(_rulesProvider).rules, hasLength(1));
      },
    );

    test(
      'an explicit identical retry reuses the key; other material does not',
      () async {
        final backend = _backend()..rulePostStatus = 503;
        final container = _container(backend);
        final controller = container.read(_rulesProvider.notifier);
        await controller.load();

        await controller.createRule(_input());
        await controller.createRule(_input());
        await controller.createRule(_input(priority: 11));
        backend.rulePostStatus = null;
        await controller.createRule(_input());

        final keys = backend.ruleBodies
            .map((b) => b['idempotencyKey'])
            .toList();
        expect(keys[0], keys[1], reason: 'same logical attempt, same key');
        expect(keys[2], isNot(keys[0]), reason: 'changed material, new key');
        expect(keys[3], keys[0], reason: 'the definitive retry still replays');
        // after the definitive answer the key is consumed
        await controller.createRule(_input());
        expect(backend.ruleBodies.last['idempotencyKey'], isNot(keys[0]));
      },
    );

    test(
      'a thrown transport failure is treated like an unknown outcome',
      () async {
        final backend = _backend()..rulePostThrows = true;
        final container = _container(backend);
        final controller = container.read(_rulesProvider.notifier);
        await controller.load();
        expect(
          await controller.createRule(_input()),
          FinancialMutationOutcome.unknownOutcomeReconciled,
        );
        expect(backend.rulePosts, 1);
      },
    );

    test(
      'unknown outcome with a failing reconciliation blocks further writes',
      () async {
        final backend = _backend()..rulePostStatus = 503;
        final container = _container(backend);
        final controller = container.read(_rulesProvider.notifier);
        await controller.load();
        backend.rulesReadStatus = 503;

        expect(
          await controller.createRule(_input()),
          FinancialMutationOutcome.temporarilyUnavailable,
        );
        expect(container.read(_rulesProvider).trusted, isFalse);
        final posts = backend.rulePosts;
        expect(
          await controller.createRule(_input(pattern: 'Outra')),
          FinancialMutationOutcome.notAllowed,
        );
        expect(backend.rulePosts, posts);

        backend.rulesReadStatus = null;
        await controller.refresh();
        expect(container.read(_rulesProvider).trusted, isTrue);
      },
    );

    test('422 is a rejection, 409 reconciles, 403 blocks access', () async {
      final backend = _backend();
      final container = _container(backend);
      final controller = container.read(_rulesProvider.notifier);
      await controller.load();

      backend.rulePostStatus = 422;
      expect(
        await controller.createRule(_input()),
        FinancialMutationOutcome.rejected,
      );
      expect(backend.ruleReads, 1, reason: '422 does not even re-read');

      backend.rulePostStatus = 409;
      expect(
        await controller.createRule(_input()),
        FinancialMutationOutcome.conflictReconciled,
      );
      expect(backend.ruleReads, 2);
      expect(backend.rulePosts, 2, reason: 'never resent');

      backend.rulePostStatus = 403;
      expect(
        await controller.createRule(_input()),
        FinancialMutationOutcome.accessBlocked,
      );
      expect(
        container.read(_rulesProvider).phase,
        FinancialLoadPhase.forbidden,
      );
    });

    test('only one write is in flight at a time', () async {
      final backend = _backend();
      final container = _container(backend);
      final controller = container.read(_rulesProvider.notifier);
      await controller.load();
      // the first call flips mutationInFlight synchronously
      final first = controller.createRule(_input());
      final second = await controller.createRule(_input(pattern: 'Outra'));
      expect(second, FinancialMutationOutcome.notAllowed);
      expect(await first, FinancialMutationOutcome.success);
      expect(backend.rulePosts, 1);
    });
  });

  group('rule disabling', () {
    test('replaces the rule with the server response only', () async {
      final backend = _backend();
      final container = _container(backend);
      final controller = container.read(_rulesProvider.notifier);
      await controller.load();

      expect(
        await controller.disableRule(financeTestRuleId(1)),
        FinancialMutationOutcome.success,
      );
      final rule = container.read(_rulesProvider).rules.single;
      expect(rule.isActive, isFalse);
      expect(rule.pattern, 'padaria', reason: 'semantics are untouched');
      expect(backend.disabledRuleIds, [financeTestRuleId(1)]);
      // already disabled: no request at all
      expect(
        await controller.disableRule(financeTestRuleId(1)),
        FinancialMutationOutcome.notAllowed,
      );
      expect(backend.disabledRuleIds, hasLength(1));
    });

    test(
      '404 re-reads, unknown outcome reconciles once, never retries',
      () async {
        final backend = _backend()..ruleDisableStatus = 404;
        final container = _container(backend);
        final controller = container.read(_rulesProvider.notifier);
        await controller.load();
        expect(
          await controller.disableRule(financeTestRuleId(1)),
          FinancialMutationOutcome.rejected,
        );

        backend.ruleDisableStatus = 503;
        final reads = backend.ruleReads;
        expect(
          await controller.disableRule(financeTestRuleId(1)),
          FinancialMutationOutcome.unknownOutcomeReconciled,
        );
        expect(backend.ruleReads, reads + 1);
        expect(
          backend.disabledRuleIds,
          hasLength(2),
          reason: 'one POST per user action',
        );
      },
    );

    test('an unknown rule is not allowed and sends nothing', () async {
      final backend = _backend();
      final container = _container(backend);
      final controller = container.read(_rulesProvider.notifier);
      await controller.load();
      expect(
        await controller.disableRule(financeTestRuleId(77)),
        FinancialMutationOutcome.notAllowed,
      );
      expect(backend.disabledRuleIds, isEmpty);
    });
  });

  group('preview and apply', () {
    Future<ProviderContainer> previewed(FakeFinanceBackend backend) async {
      final container = _container(backend);
      await container.read(_applyProvider.notifier).preview();
      return container;
    }

    test(
      'preview is read-only: one POST to preview and nothing else',
      () async {
        final backend = _backend();
        final container = await previewed(backend);
        final state = container.read(_applyProvider);
        expect(state.phase, FinancialCategorizationApplyPhase.previewed);
        expect(state.preview!.counts.matched, 3);
        expect(state.canApply, isTrue);
        expect(backend.previewPosts, 1);
        expect(backend.applyPosts, 0);
        expect(backend.allocations, isEmpty);
        expect(backend.origins, isEmpty);
      },
    );

    test(
      'apply without a preview or with nothing to apply sends nothing',
      () async {
        final backend = _backend(rules: []);
        final container = _container(backend);
        final controller = container.read(_applyProvider.notifier);
        await controller.apply();
        expect(backend.applyPosts, 0);
        await controller.preview();
        expect(container.read(_applyProvider).canApply, isFalse);
        await controller.apply();
        expect(backend.applyPosts, 0);
      },
    );

    test(
      'apply sends exactly the previewed pairs once and shows the backend result',
      () async {
        final backend = _backend();
        final container = await previewed(backend);
        final controller = container.read(_applyProvider.notifier);

        await controller.apply();

        expect(backend.applyPosts, 1);
        expect(backend.applyBodies.single['items'], [
          for (var i = 1; i <= 3; i += 1)
            {
              'movementId': financeTestMovementId(i),
              'ruleId': financeTestRuleId(1),
            },
        ]);
        final state = container.read(_applyProvider);
        expect(state.phase, FinancialCategorizationApplyPhase.applied);
        expect(state.outcome!.counts.classified, 3);
        expect(state.outcome!.isFullSuccess, isTrue);
        expect(backend.origins, hasLength(3));
        // a second tap is not even a request: the preview was consumed
        await controller.apply();
        expect(backend.applyPosts, 1);
      },
    );

    test(
      'only one apply is in flight and a double tap sends one POST',
      () async {
        final backend = _backend();
        final gate = Completer<void>();
        backend.applyGate = gate;
        final container = await previewed(backend);
        final controller = container.read(_applyProvider.notifier);

        final first = controller.apply();
        await Future<void>.delayed(Duration.zero);
        expect(
          container.read(_applyProvider).phase,
          FinancialCategorizationApplyPhase.applying,
        );
        await controller.apply();
        await controller.preview();
        gate.complete();
        await first;

        expect(backend.applyPosts, 1);
        expect(backend.previewPosts, 1, reason: 'no preview while applying');
      },
    );

    test('partial results are reported as such, never as full success', () async {
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
      final container = await previewed(backend);
      await container.read(_applyProvider.notifier).apply();
      final outcome = container.read(_applyProvider).outcome!;
      expect(outcome.isFullSuccess, isFalse);
      expect(outcome.counts.conflict, 1);
      expect(outcome.counts.alreadyClassified, 1);
    });

    test(
      'manual wins the preview-to-apply race: the result says so, nothing is overwritten',
      () async {
        final backend = _backend();
        final container = await previewed(backend);
        final manual = fakeAllocationJson(
          setId: financeTestAllocationSetId(900),
          movementId: financeTestMovementId(2),
          shares: [(financeTestCategoryId(2), '-75.25')],
        );
        backend.onApplyPost = (_) =>
            backend.allocations[financeTestMovementId(2)] = manual;

        await container.read(_applyProvider.notifier).apply();

        final outcome = container.read(_applyProvider).outcome!;
        expect(outcome.counts.classified, 2);
        expect(outcome.counts.alreadyClassified, 1);
        expect(backend.allocations[financeTestMovementId(2)], manual);
        expect(
          backend.origins.values.where(
            (o) => o.contains(financeTestMovementId(2)),
          ),
          isEmpty,
        );
      },
    );

    test(
      'an ambiguous write (5xx / transport / invalid 2xx) is never retried',
      () async {
        for (final setup in <void Function(FakeFinanceBackend)>[
          (b) => b.applyStatus = 502,
          (b) => b.applyThrows = true,
          (b) =>
              b.applyResponder = (_) =>
                  '{"accountId":"$financeTestAccountId","requested":1}',
        ]) {
          final backend = _backend();
          setup(backend);
          final container = await previewed(backend);
          final controller = container.read(_applyProvider.notifier);

          await controller.apply();

          final state = container.read(_applyProvider);
          expect(state.phase, FinancialCategorizationApplyPhase.unknownOutcome);
          expect(state.canApply, isFalse);
          expect(backend.applyPosts, 1, reason: 'zero automatic retries');
          await controller.apply();
          expect(
            backend.applyPosts,
            1,
            reason: 'nothing to resend without a new preview',
          );
        }
      },
    );

    test(
      'after an unknown outcome the operator previews again and sees the truth',
      () async {
        final backend = _backend()..applyThrows = true;
        final container = await previewed(backend);
        final controller = container.read(_applyProvider.notifier);
        await controller.apply();
        // the write actually reached the server
        backend.applyThrows = false;
        backend.applyResponder = null;
        // simulate the committed effect for two movements
        for (final i in [1, 2]) {
          backend.allocations[financeTestMovementId(i)] = fakeAllocationJson(
            setId: financeTestAllocationSetId(60 + i),
            movementId: financeTestMovementId(i),
            shares: [(_category, '-75.25')],
          );
        }
        await controller.preview();
        final preview = container.read(_applyProvider).preview!;
        expect(preview.counts.alreadyClassified, 2);
        expect(preview.counts.matched, 1);
      },
    );

    test('definitive rejections are failures, not unknown outcomes', () async {
      final expectations = {
        404: FinancialCategorizationApplyFailure.notFound,
        422: FinancialCategorizationApplyFailure.rejected,
        403: FinancialCategorizationApplyFailure.accessBlocked,
      };
      for (final entry in expectations.entries) {
        final backend = _backend()..applyStatus = entry.key;
        final container = await previewed(backend);
        await container.read(_applyProvider.notifier).apply();
        final state = container.read(_applyProvider);
        expect(state.phase, FinancialCategorizationApplyPhase.failed);
        expect(state.failure, entry.value);
        expect(backend.applyPosts, 1);
      }
    });

    test('a failing preview is a failure and never an empty success', () async {
      final backend = _backend()..previewStatus = 503;
      final container = _container(backend);
      await container.read(_applyProvider.notifier).preview();
      final state = container.read(_applyProvider);
      expect(state.phase, FinancialCategorizationApplyPhase.failed);
      expect(state.preview, isNull);
      expect(backend.applyPosts, 0);
    });
  });

  group('refresh after apply', () {
    test(
      'the detail read is a fixed bulk read: one origins read, no per-row requests',
      () async {
        for (final count in [0, 1, 25]) {
          final backend = _backend(
            movements: [
              for (var i = 1; i <= count; i += 1)
                FakeMovementSpec(
                  id: financeTestMovementId(i),
                  description: 'Padaria $i',
                ),
            ],
          );
          final container = _container(backend);
          await container.read(_detail.notifier).load();
          expect(backend.originReads, 1);
          expect(backend.bulkReads, 1);
          expect(backend.singleAllocationReads, 0);
          await container.read(_applyProvider.notifier).preview();
          if (count > 0) {
            await container.read(_applyProvider.notifier).apply();
          }
          await container.read(_detail.notifier).refresh();
          expect(backend.originReads, 2);
          expect(backend.bulkReads, 2);
          expect(backend.singleAllocationReads, 0);
          final state = container.read(_detail);
          expect(state.ruleOriginsBySetId, hasLength(count));
          for (final allocation in state.currentAllocations.values) {
            expect(
              state.ruleOriginsBySetId,
              contains(allocation.allocationSetId),
            );
          }
        }
      },
    );
  });
}
