import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_categorization_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

import '../../support/fake_finance_backend.dart';

/// Issue #247 vertical gate on the client, mirroring the issue's smoke:
/// categories -> CONTAINS rule -> unclassified expense -> unique-match preview
/// -> explicit apply -> current classification + provenance -> idempotent
/// replay -> manual override (#245 flow) -> apply again keeps the override ->
/// tied rules are AMBIGUOUS and write nothing. Movement, balance and statement
/// are identical at every step and no request is repeated automatically.

final _detail = financialAccountDetailControllerProvider(financeTestAccountId);
final _apply = financialCategorizationApplyControllerProvider(
  financeTestAccountId,
);
final _rulesProvider = financialCategorizationRulesControllerProvider;

Map<String, Object?> _economic(FinancialAccountDetailState state) {
  final balance = state.balance!;
  return {
    'movements': [
      for (final movement in state.movements)
        [
          movement.movementId,
          movement.money.amount,
          movement.money.currency,
          movement.resultEffect.name,
          movement.role.name,
          movement.effectiveDate,
          movement.competenceDate,
        ],
    ],
    'balance': [
      balance.currentBalance.amount,
      balance.movementNet.amount,
      balance.movementCount,
    ],
    'statement': [
      for (final entry in state.statement!.entries)
        [entry.movement.movementId, entry.balanceAfter.amount],
    ],
  };
}

void main() {
  test('vertical flow: rule, preview, apply, replay, manual override, ambiguity', () async {
    final backend = FakeFinanceBackend(
      movements: [],
      categories: [
        fakeCategoryJson(id: financeTestCategoryId(1), name: 'Mercado'),
        fakeCategoryJson(id: financeTestCategoryId(2), name: 'Lazer'),
      ],
    );
    final container = financeTestContainer(backend);
    addTearDown(container.dispose);
    for (final provider in [_detail, _apply, _rulesProvider]) {
      container.listen(provider, (previous, next) {}, fireImmediately: true);
    }
    final detail = container.read(_detail.notifier);
    final rules = container.read(_rulesProvider.notifier);
    final apply = container.read(_apply.notifier);

    await detail.load();
    await rules.load();

    // 1. a CONTAINS rule for the first category
    expect(
      await rules.createRule(
        FinancialCategorizationRuleCreateInput(
          matcher: FinancialCategorizationMatcher.contains,
          pattern: 'Padaria',
          targetCategoryId: financeTestCategoryId(1),
          priority: 10,
        ),
      ),
      FinancialMutationOutcome.success,
    );
    final rule = container.read(_rulesProvider).rules.single;
    expect(rule.isActive, isTrue);

    // 2. an unclassified manual expense
    expect(
      await detail.createManualEntry(
        FinancialManualEntryKind.expense,
        FinancialManualEntryCreateInput(
          amount: '37.45',
          currency: 'BRL',
          effectiveDate: '2026-09-20',
          competenceDate: '2026-09-20',
          description: 'Padaria Pão Quente',
        ),
      ),
      isTrue,
    );
    var state = container.read(_detail);
    final movementId = state.movements.single.movementId;
    expect(state.currentAllocations, isEmpty);
    final economic = _economic(state);

    // 3. the preview identifies a unique match and writes nothing
    await apply.preview();
    var applyState = container.read(_apply);
    expect(applyState.phase, FinancialCategorizationApplyPhase.previewed);
    expect(applyState.preview!.counts.matched, 1);
    expect(applyState.preview!.applicableItems.single.ruleId, rule.ruleId);
    expect(backend.applyPosts, 0);
    expect(backend.allocations, isEmpty);

    // 4. explicit apply: the backend result is the only truth
    await apply.apply();
    applyState = container.read(_apply);
    expect(applyState.phase, FinancialCategorizationApplyPhase.applied);
    expect(applyState.outcome!.isFullSuccess, isTrue);
    expect(backend.applyPosts, 1);
    await detail.refresh();
    state = container.read(_detail);
    final current = state.currentAllocations[movementId]!;
    expect(current.revision, 1);
    expect(current.supersedesId, isNull);
    expect(current.allocations.single.money.amount, '-37.45');
    expect(current.allocations.single.categoryId, financeTestCategoryId(1));
    expect(
      state.ruleOriginsBySetId[current.allocationSetId]!.ruleId,
      rule.ruleId,
    );
    expect(
      _economic(state),
      economic,
      reason: 'Movement and balance untouched',
    );

    // 5. replay: nothing new, the preview says it is already classified
    await apply.preview();
    applyState = container.read(_apply);
    expect(applyState.preview!.counts.alreadyClassified, 1);
    expect(applyState.preview!.counts.matched, 0);
    await apply.apply();
    expect(backend.applyPosts, 1, reason: 'nothing to apply, nothing sent');
    expect(backend.allocations, hasLength(1));

    // 6. manual override through the #245 flow appends a revision
    expect(
      await detail.reviseMovementClassification(
        movementId: movementId,
        supersedesId: current.allocationSetId,
        shares: [
          FinancialAllocationShareInput(
            categoryId: financeTestCategoryId(2),
            amount: '-37.45',
            currency: 'BRL',
          ),
        ],
      ),
      FinancialMutationOutcome.success,
    );
    await detail.refresh();
    state = container.read(_detail);
    final manual = state.currentAllocations[movementId]!;
    expect(manual.revision, 2);
    expect(manual.supersedesId, current.allocationSetId);
    expect(
      state.ruleOriginsBySetId.containsKey(manual.allocationSetId),
      isFalse,
      reason: 'a manual revision is not rule-applied',
    );

    // 7. applying again keeps the manual override
    await apply.preview();
    expect(container.read(_apply).preview!.counts.matched, 0);
    await apply.apply();
    await detail.refresh();
    expect(
      container.read(_detail).currentAllocations[movementId]!.allocationSetId,
      manual.allocationSetId,
    );
    expect(backend.applyPosts, 1);

    // 8. tied rules: AMBIGUOUS in the preview and in a confirmed apply, no write
    final tied = financeTestMovementId(950);
    backend.movements = [
      ...backend.movements,
      FakeMovementSpec(id: tied, description: 'Cinema Sábado'),
    ];
    backend.previewBody =
        '{"accountId":"$financeTestAccountId","totalMovements":2,'
        '"counts":{"matched":0,"noMatch":0,"ambiguous":1,"ineligible":0,"alreadyClassified":1},'
        '"items":[{"movementId":"$movementId","status":"ALREADY_CLASSIFIED","ruleId":null,"targetCategoryId":null},'
        '{"movementId":"$tied","status":"AMBIGUOUS","ruleId":null,"targetCategoryId":null}],'
        '"applicableTruncated":false}';
    await apply.preview();
    applyState = container.read(_apply);
    expect(applyState.preview!.counts.ambiguous, 1);
    expect(
      applyState.canApply,
      isFalse,
      reason: 'nothing to confirm for a tie',
    );
    await apply.apply();
    expect(backend.applyPosts, 1);
    expect(backend.allocations.containsKey(tied), isFalse);
    // even a hand-built confirmation of the tie is answered AMBIGUOUS, not applied
    backend.applyResponder = (items) =>
        '{"accountId":"$financeTestAccountId","requested":1,'
        '"counts":{"classified":0,"alreadyClassified":0,"ambiguous":1,"noMatch":0,'
        '"ineligible":0,"conflict":0,"failed":0},'
        '"results":[{"movementId":"${items.single['movementId']}","status":"AMBIGUOUS","ruleId":null,"allocationSetId":null}]}';
    final outcome = await container
        .read(financialCoreApiProvider)
        .applyCategorizationRules(financeTestAccountId, [
          FinancialCategorizationApplyItem(
            movementId: tied,
            ruleId: rule.ruleId,
          ),
        ]);
    expect(outcome.counts.ambiguous, 1);
    expect(outcome.isFullSuccess, isFalse);
    expect(backend.allocations.containsKey(tied), isFalse);

    // the whole flow never read a classification per Movement and never retried
    expect(backend.singleAllocationReads, 0);
    expect(backend.rulePosts, 1);
    expect(backend.revisionPosts, 1);
  });
}
