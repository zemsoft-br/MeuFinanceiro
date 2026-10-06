import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_editor_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/components/app_badge.dart';
import 'package:meufinanceiro_app/theme/components/app_state_panel.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Monthly category budgets (#252): planned vs realized, per month.
///
/// A budget is planning, never a ledger. The realized/remaining/status/percent
/// shown here come from the server on every read; nothing is computed, cached or
/// patched on the client. Nothing is optimistic: after any plan write the month
/// is read again. A stale edit (409) is never retried: the current plan is shown
/// and the user edits again explicitly.
class FinancialBudgetScreen extends ConsumerStatefulWidget {
  const FinancialBudgetScreen({super.key});

  static const titleKey = Key('financial-budget-title');
  static const refreshKey = Key('financial-budget-refresh');
  static const createKey = Key('financial-budget-create');
  static const createEmptyKey = Key('financial-budget-create-empty');
  static const previousMonthKey = Key('financial-budget-month-previous');
  static const nextMonthKey = Key('financial-budget-month-next');
  static const monthLabelKey = Key('financial-budget-month-label');
  static const loadingKey = Key('financial-budget-loading');
  static const emptyKey = Key('financial-budget-empty');
  static const errorKey = Key('financial-budget-error');
  static const retryKey = Key('financial-budget-retry');
  static const refreshNoticeKey = Key('financial-budget-refresh-notice');
  static const untrustedKey = Key('financial-budget-untrusted');
  static const conflictKey = Key('financial-budget-conflict');
  static const conflictDismissKey = Key('financial-budget-conflict-dismiss');
  static const summaryKey = Key('financial-budget-summary');
  static const summaryLoadingKey = Key('financial-budget-summary-loading');
  static const summaryErrorKey = Key('financial-budget-summary-error');
  static const summaryRetryKey = Key('financial-budget-summary-retry');
  static const readOnlyKey = Key('financial-budget-readonly');
  static const scopeNoticeKey = Key('financial-budget-scope-notice');
  static const editKey = Key('financial-budget-edit');
  static const coverageKey = Key('financial-budget-coverage');
  static const coverageActionKey = Key('financial-budget-coverage-action');
  static const linesKey = Key('financial-budget-lines');
  static Key selectorKey(String budgetId) =>
      Key('financial-budget-select-$budgetId');
  static Key lineKey(String categoryId, FinancialResultEffect effect) =>
      Key('financial-budget-line-$categoryId-${effect.wireValue}');
  static Key lineStatusKey(String categoryId, FinancialResultEffect effect) =>
      Key('financial-budget-status-$categoryId-${effect.wireValue}');
  static Key lineProgressKey(String categoryId, FinancialResultEffect effect) =>
      Key('financial-budget-progress-$categoryId-${effect.wireValue}');

  @override
  ConsumerState<FinancialBudgetScreen> createState() =>
      _FinancialBudgetScreenState();
}

class _FinancialBudgetScreenState extends ConsumerState<FinancialBudgetScreen> {
  final _headingFocusNode = FocusNode(debugLabel: 'financial-budget-heading');

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _headingFocusNode.requestFocus();
      unawaited(ref.read(financialBudgetsControllerProvider.notifier).load());
    });
  }

  @override
  void dispose() {
    _headingFocusNode.dispose();
    super.dispose();
  }

  void _announce(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _openEditor(
    FinancialBudgetsState state, {
    FinancialBudget? existing,
  }) async {
    final operatorId = ref
        .read(operatorSessionControllerProvider)
        .principal
        ?.operatorId;
    if (operatorId == null) return;
    final result = await showDialog<FinancialBudgetEditorResult>(
      context: context,
      builder: (_) => FinancialBudgetEditorDialog(
        period: state.period,
        operatorId: operatorId,
        index: state.categoryIndex,
        existing: existing,
      ),
    );
    if (result == null || !mounted) return;
    final controller = ref.read(financialBudgetsControllerProvider.notifier);
    final outcome = switch (result) {
      FinancialBudgetEditorCreate(:final input) =>
        await controller.createBudget(input),
      FinancialBudgetEditorReplace(:final input) =>
        await controller.replaceBudget(existing!.id, input),
    };
    if (!mounted) return;
    _announce(_message(outcome));
  }

  String _message(FinancialBudgetActionResult result) {
    const stale =
        ' O orçamento exibido pode estar desatualizado: use Atualizar antes de continuar.';
    final base = switch (result.outcome) {
      FinancialBudgetActionOutcome.created => 'Orçamento criado.',
      FinancialBudgetActionOutcome.updated => 'Orçamento atualizado.',
      FinancialBudgetActionOutcome.conflict =>
        'O orçamento mudou desde que você o abriu (ou já existe um igual para '
            'este mês). Nada foi gravado: revise o plano atual e edite de novo.',
      FinancialBudgetActionOutcome.rejected =>
        'O pedido foi recusado e nada foi gravado.',
      FinancialBudgetActionOutcome.readOnly =>
        'Este orçamento é somente leitura para você. Nada foi gravado.',
      FinancialBudgetActionOutcome.unknownOutcome =>
        'Não foi possível confirmar o resultado e o pedido não será reenviado '
            'automaticamente. Confira o estado atual.',
      FinancialBudgetActionOutcome.notAllowed =>
        'Esta ação não está disponível agora.',
      FinancialBudgetActionOutcome.accessBlocked => 'Acesso indisponível.',
    };
    final refreshed = result.reconciled ? ' O mês foi atualizado.' : stale;
    return switch (result.outcome) {
      FinancialBudgetActionOutcome.notAllowed ||
      FinancialBudgetActionOutcome.accessBlocked => base,
      _ => '$base$refreshed',
    };
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(financialBudgetsControllerProvider);
    final controller = ref.read(financialBudgetsControllerProvider.notifier);
    final blocked =
        state.phase == FinancialLoadPhase.authenticationRequired ||
        state.phase == FinancialLoadPhase.forbidden ||
        state.phase == FinancialLoadPhase.primaryResidenceRequired;
    final refreshEnabled = !state.isBusy && !blocked;
    final canCreate =
        state.isLoaded &&
        state.phase != FinancialLoadPhase.refreshing &&
        state.trusted &&
        !state.isBusy;

    return FocusTraversalGroup(
      policy: ReadingOrderTraversalPolicy(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => context.go(AppRoutes.financePath),
              icon: const Icon(Icons.arrow_back_rounded),
              label: const Text('Voltar para Finanças'),
            ),
          ),
          const SizedBox(height: AppTokens.space12),
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: AppTokens.space16,
            runSpacing: AppTokens.space16,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Finanças · Organização',
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: AppTokens.forest700,
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Focus(
                      focusNode: _headingFocusNode,
                      child: Semantics(
                        header: true,
                        child: Text(
                          'Orçamentos',
                          key: FinancialBudgetScreen.titleKey,
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Text(
                      'Planejamento mensal por categoria. O realizado é '
                      'calculado a partir do extrato e da classificação atual '
                      'das contas do escopo de cada orçamento (informado em '
                      'cada um deles): um orçamento nunca cria lançamentos '
                      'nem altera saldos.',
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                        color: AppTokens.neutral700,
                      ),
                    ),
                  ],
                ),
              ),
              Wrap(
                spacing: AppTokens.space12,
                runSpacing: AppTokens.space12,
                children: [
                  OutlinedButton.icon(
                    key: FinancialBudgetScreen.refreshKey,
                    onPressed: refreshEnabled
                        ? () => unawaited(controller.refresh())
                        : null,
                    icon: state.phase == FinancialLoadPhase.refreshing
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.refresh_rounded),
                    label: const Text('Atualizar'),
                  ),
                  FilledButton.icon(
                    key: FinancialBudgetScreen.createKey,
                    onPressed: canCreate
                        ? () => unawaited(_openEditor(state))
                        : null,
                    icon: const Icon(Icons.add_rounded),
                    label: const Text('Novo orçamento'),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppTokens.space24),
          _MonthNavigator(
            period: state.period,
            enabled: !state.isBusy && !blocked,
            onPrevious: () => unawaited(controller.previousMonth()),
            onNext: () => unawaited(controller.nextMonth()),
          ),
          const SizedBox(height: AppTokens.space16),
          if (state.refreshFailure != FinancialRefreshFailure.none) ...[
            Card(
              key: FinancialBudgetScreen.refreshNoticeKey,
              child: Padding(
                padding: const EdgeInsets.all(AppTokens.space16),
                child: Text(
                  state.refreshFailure ==
                          FinancialRefreshFailure.invalidResponse
                      ? 'O orçamento atual foi preservado porque a nova '
                            'resposta não pôde ser validada.'
                      : 'O orçamento atual foi preservado, mas não foi possível '
                            'atualizá-lo.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (state.isLoaded && !state.trusted) ...[
            const Card(
              key: FinancialBudgetScreen.untrustedKey,
              child: Padding(
                padding: EdgeInsets.all(AppTokens.space16),
                child: Text(
                  'O orçamento exibido pode estar desatualizado. Use Atualizar '
                  'antes de criar ou editar.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (state.isLoaded && state.conflictNotice) ...[
            Card(
              key: FinancialBudgetScreen.conflictKey,
              color: AppTokens.amber50,
              child: Padding(
                padding: const EdgeInsets.all(AppTokens.space16),
                child: Row(
                  children: [
                    const Icon(
                      Icons.warning_amber_rounded,
                      color: AppTokens.amber700,
                      semanticLabel: 'Conflito',
                    ),
                    const SizedBox(width: AppTokens.space12),
                    const Expanded(
                      child: Text(
                        'Conflito de edição: o orçamento mudou desde que você '
                        'o abriu (ou já existe um igual para este mês). Sua '
                        'alteração não foi aplicada e nada foi reenviado. '
                        'O plano exibido é o atual; edite de novo se ainda '
                        'for necessário.',
                      ),
                    ),
                    TextButton(
                      key: FinancialBudgetScreen.conflictDismissKey,
                      onPressed: controller.dismissConflictNotice,
                      child: const Text('Entendi'),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          _Content(
            state: state,
            onRetry: () => unawaited(controller.refresh()),
            onSelect: (id) => unawaited(controller.select(id)),
            onRetrySummary: () => unawaited(controller.reloadSummary()),
            onCreate: canCreate ? () => unawaited(_openEditor(state)) : null,
            onEdit: (budget) => unawaited(_openEditor(state, existing: budget)),
          ),
        ],
      ),
    );
  }
}

class _MonthNavigator extends StatelessWidget {
  const _MonthNavigator({
    required this.period,
    required this.enabled,
    required this.onPrevious,
    required this.onNext,
  });

  final String period;
  final bool enabled;
  final VoidCallback onPrevious;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppTokens.space8,
          vertical: AppTokens.space8,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            IconButton(
              key: FinancialBudgetScreen.previousMonthKey,
              tooltip: 'Mês anterior',
              onPressed: enabled ? onPrevious : null,
              icon: const Icon(Icons.chevron_left_rounded),
            ),
            Semantics(
              liveRegion: true,
              child: Text(
                financialBudgetPeriodLabel(period),
                key: FinancialBudgetScreen.monthLabelKey,
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            IconButton(
              key: FinancialBudgetScreen.nextMonthKey,
              tooltip: 'Próximo mês',
              onPressed: enabled ? onNext : null,
              icon: const Icon(Icons.chevron_right_rounded),
            ),
          ],
        ),
      ),
    );
  }
}

class _Content extends StatelessWidget {
  const _Content({
    required this.state,
    required this.onRetry,
    required this.onSelect,
    required this.onRetrySummary,
    required this.onCreate,
    required this.onEdit,
  });

  final FinancialBudgetsState state;
  final VoidCallback onRetry;
  final ValueChanged<String> onSelect;
  final VoidCallback onRetrySummary;
  final VoidCallback? onCreate;
  final ValueChanged<FinancialBudget> onEdit;

  @override
  Widget build(BuildContext context) {
    if (state.phase == FinancialLoadPhase.idle ||
        state.phase == FinancialLoadPhase.loading) {
      return const KeyedSubtree(
        key: FinancialBudgetScreen.loadingKey,
        child: AppStatePanel(
          kind: AppStateKind.loading,
          title: 'Carregando orçamentos…',
          description: 'Buscando o plano do mês e o realizado do extrato.',
        ),
      );
    }
    if (!state.isLoaded) {
      return _PhasePanel(phase: state.phase, onRetry: onRetry);
    }
    if (state.budgets.isEmpty) {
      return Column(
        key: FinancialBudgetScreen.emptyKey,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          AppStatePanel(
            kind: AppStateKind.empty,
            title:
                'Nenhum orçamento em ${financialBudgetPeriodLabel(state.period)}',
            description:
                'Crie um plano mensal por categoria para comparar o que você '
                'planejou com o que realmente aconteceu.',
          ),
          const SizedBox(height: AppTokens.space12),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(
              key: FinancialBudgetScreen.createEmptyKey,
              onPressed: onCreate,
              icon: const Icon(Icons.add_rounded),
              label: const Text('Criar orçamento deste mês'),
            ),
          ),
        ],
      );
    }
    final selected = state.selected;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (state.budgets.length > 1) ...[
          _BudgetSelector(state: state, onSelect: onSelect),
          const SizedBox(height: AppTokens.space16),
        ],
        if (selected != null)
          _BudgetCard(
            state: state,
            budget: selected,
            onRetrySummary: onRetrySummary,
            onEdit: state.trusted && !state.isBusy && selected.canEdit
                ? () => onEdit(selected)
                : null,
          ),
      ],
    );
  }
}

class _BudgetSelector extends StatelessWidget {
  const _BudgetSelector({required this.state, required this.onSelect});

  final FinancialBudgetsState state;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: AppTokens.space8,
      runSpacing: AppTokens.space8,
      children: [
        for (final budget in state.budgets)
          ChoiceChip(
            key: FinancialBudgetScreen.selectorKey(budget.id),
            selected: budget.id == state.selectedBudgetId,
            onSelected: state.isBusy ? null : (_) => onSelect(budget.id),
            label: Text(
              '${budget.name} · ${financialBudgetScopeLabel(budget.visibilityScope)}'
              ' · ${financialBudgetBasisLabel(budget.dateBasis)} · ${budget.currency}',
            ),
          ),
      ],
    );
  }
}

class _PhasePanel extends StatelessWidget {
  const _PhasePanel({required this.phase, required this.onRetry});

  final FinancialLoadPhase phase;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final (title, message, retry) = switch (phase) {
      FinancialLoadPhase.authenticationRequired => (
        'Sessão expirada',
        'Entre novamente para ver os orçamentos.',
        false,
      ),
      FinancialLoadPhase.forbidden => (
        'Acesso indisponível',
        'Você não tem acesso aos orçamentos desta residência.',
        false,
      ),
      FinancialLoadPhase.primaryResidenceRequired => (
        'Residência principal necessária',
        'Defina uma residência principal para ver os orçamentos.',
        false,
      ),
      FinancialLoadPhase.invalidResponse => (
        'Resposta inválida',
        'A resposta do servidor não pôde ser validada e nada foi exibido.',
        true,
      ),
      _ => (
        'Orçamentos indisponíveis',
        'Não foi possível carregar os orçamentos agora.',
        true,
      ),
    };
    return Column(
      key: FinancialBudgetScreen.errorKey,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AppStatePanel(
          kind: retry ? AppStateKind.unavailable : AppStateKind.error,
          title: title,
          description: message,
        ),
        if (retry) ...[
          const SizedBox(height: AppTokens.space12),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton(
              key: FinancialBudgetScreen.retryKey,
              onPressed: onRetry,
              child: const Text('Tentar novamente'),
            ),
          ),
        ],
      ],
    );
  }
}

class _BudgetCard extends StatelessWidget {
  const _BudgetCard({
    required this.state,
    required this.budget,
    required this.onRetrySummary,
    required this.onEdit,
  });

  final FinancialBudgetsState state;
  final FinancialBudget budget;
  final VoidCallback onRetrySummary;
  final VoidCallback? onEdit;

  @override
  Widget build(BuildContext context) {
    final summary = state.summaryPhase == FinancialBudgetSummaryPhase.ready
        ? state.summary
        : null;
    final summaryById = {
      if (summary != null)
        for (final line in summary.lines)
          '${line.categoryId}|${line.resultEffect.wireValue}': line,
    };
    return Card(
      key: FinancialBudgetScreen.summaryKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: AppTokens.space12,
              runSpacing: AppTokens.space12,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      budget.name,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Wrap(
                      spacing: AppTokens.space8,
                      runSpacing: AppTokens.space8,
                      children: [
                        AppBadge(
                          label: financialBudgetScopeLabel(
                            budget.visibilityScope,
                          ),
                          tone: AppBadgeTone.info,
                        ),
                        AppBadge(
                          label: financialBudgetBasisLabel(budget.dateBasis),
                        ),
                        AppBadge(label: budget.currency),
                        if (!budget.canEdit)
                          const AppBadge(
                            key: FinancialBudgetScreen.readOnlyKey,
                            label: 'Somente leitura',
                            tone: AppBadgeTone.warning,
                          ),
                      ],
                    ),
                  ],
                ),
                if (budget.canEdit)
                  OutlinedButton.icon(
                    key: FinancialBudgetScreen.editKey,
                    onPressed: onEdit,
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('Editar'),
                  ),
              ],
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              budget.canEdit
                  ? 'Realizado ${financialBudgetBasisHint(budget.dateBasis)} em '
                        '${financialBudgetPeriodLabel(budget.period)}, calculado '
                        'pelo servidor a cada leitura.'
                  : 'Você pode ver este orçamento, mas só quem o criou pode '
                        'editá-lo. Realizado ${financialBudgetBasisHint(budget.dateBasis)} '
                        'em ${financialBudgetPeriodLabel(budget.period)}.',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
            ),
            const SizedBox(height: AppTokens.space12),
            _ScopeNotice(scope: budget.realizationAccountScope),
            const SizedBox(height: AppTokens.space16),
            if (state.summaryPhase == FinancialBudgetSummaryPhase.loading)
              const KeyedSubtree(
                key: FinancialBudgetScreen.summaryLoadingKey,
                child: AppStatePanel(
                  kind: AppStateKind.loading,
                  title: 'Calculando o realizado…',
                  description: 'Lendo o extrato e a classificação atual.',
                  compact: true,
                ),
              )
            else if (summary == null) ...[
              Column(
                key: FinancialBudgetScreen.summaryErrorKey,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  AppStatePanel(
                    kind: AppStateKind.unavailable,
                    title: 'Realizado indisponível',
                    description:
                        state.summaryPhase ==
                            FinancialBudgetSummaryPhase.invalidResponse
                        ? 'A resposta do servidor não pôde ser validada. O '
                              'plano continua abaixo, sem valores realizados.'
                        : 'Não foi possível calcular o realizado agora. O '
                              'plano continua abaixo, sem valores realizados.',
                    compact: true,
                  ),
                  const SizedBox(height: AppTokens.space12),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: FilledButton(
                      key: FinancialBudgetScreen.summaryRetryKey,
                      onPressed: state.isBusy ? null : onRetrySummary,
                      child: const Text('Tentar novamente'),
                    ),
                  ),
                ],
              ),
            ] else if (summary.coverage.isIncomplete) ...[
              _CoverageAlert(coverage: summary.coverage),
            ],
            const SizedBox(height: AppTokens.space16),
            _Lines(state: state, budget: budget, summaryById: summaryById),
          ],
        ),
      ),
    );
  }
}

/// Which accounts feed this budget, in plain text (never only a tooltip). The
/// scope shown is the one the server declared; nothing is derived here.
class _ScopeNotice extends StatelessWidget {
  const _ScopeNotice({required this.scope});

  final FinancialBudgetRealizationAccountScope scope;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: FinancialBudgetScreen.scopeNoticeKey,
      padding: const EdgeInsets.all(AppTokens.space12),
      decoration: BoxDecoration(
        color: AppTokens.blue50,
        border: Border.all(color: AppTokens.blue700),
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(
            Icons.info_outline_rounded,
            color: AppTokens.blue700,
            size: 20,
            semanticLabel: 'Escopo do realizado',
          ),
          const SizedBox(width: AppTokens.space12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  financialBudgetRealizationScopeLabel(scope),
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                const SizedBox(height: AppTokens.space4),
                Text(financialBudgetRealizationScopeNotice(scope)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CoverageAlert extends StatelessWidget {
  const _CoverageAlert({required this.coverage});

  final FinancialBudgetCoverage coverage;

  @override
  Widget build(BuildContext context) {
    final parts = <String>[
      if (coverage.unclassifiedExpenseCount > 0)
        '${coverage.unclassifiedExpenseCount} '
            '${coverage.unclassifiedExpenseCount == 1 ? 'despesa' : 'despesas'} '
            '(${formatFinancialMoney(coverage.unclassifiedExpenseAmount)})',
      if (coverage.unclassifiedIncomeCount > 0)
        '${coverage.unclassifiedIncomeCount} '
            '${coverage.unclassifiedIncomeCount == 1 ? 'receita' : 'receitas'} '
            '(${formatFinancialMoney(coverage.unclassifiedIncomeAmount)})',
    ];
    return Container(
      key: FinancialBudgetScreen.coverageKey,
      padding: const EdgeInsets.all(AppTokens.space16),
      decoration: BoxDecoration(
        color: AppTokens.amber50,
        border: Border.all(color: AppTokens.amber700),
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
      ),
      child: Wrap(
        spacing: AppTokens.space12,
        runSpacing: AppTokens.space8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          const Icon(
            Icons.warning_amber_rounded,
            color: AppTokens.amber700,
            semanticLabel: 'Atenção',
          ),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 640),
            child: Text(
              'O realizado pode estar incompleto: ${parts.join(' e ')} do '
              'período ainda não têm categoria e não entram em nenhuma linha.',
            ),
          ),
          OutlinedButton(
            key: FinancialBudgetScreen.coverageActionKey,
            onPressed: () => context.go(AppRoutes.financePendingPath),
            child: const Text('Abrir Pendências'),
          ),
        ],
      ),
    );
  }
}

class _Lines extends StatelessWidget {
  const _Lines({
    required this.state,
    required this.budget,
    required this.summaryById,
  });

  final FinancialBudgetsState state;
  final FinancialBudget budget;
  final Map<String, FinancialBudgetLineSummary> summaryById;

  @override
  Widget build(BuildContext context) {
    final ordered = [...budget.lines]
      ..sort((a, b) {
        final byEffect = a.resultEffect.wireValue.compareTo(
          b.resultEffect.wireValue,
        );
        if (byEffect != 0) return byEffect;
        final nameA =
            state.categoryIndex.pathLabel(a.categoryId)?.toLowerCase() ?? '';
        final nameB =
            state.categoryIndex.pathLabel(b.categoryId)?.toLowerCase() ?? '';
        final byName = nameA.compareTo(nameB);
        return byName != 0 ? byName : a.categoryId.compareTo(b.categoryId);
      });
    return Column(
      key: FinancialBudgetScreen.linesKey,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final line in ordered) ...[
          _LineCard(
            state: state,
            line: line,
            summary:
                summaryById['${line.categoryId}|${line.resultEffect.wireValue}'],
          ),
          const SizedBox(height: AppTokens.space12),
        ],
      ],
    );
  }
}

class _LineCard extends StatelessWidget {
  const _LineCard({
    required this.state,
    required this.line,
    required this.summary,
  });

  final FinancialBudgetsState state;
  final FinancialBudgetLine line;
  final FinancialBudgetLineSummary? summary;

  @override
  Widget build(BuildContext context) {
    final category = state.categoryIndex.byId(line.categoryId);
    final path = state.categoryIndex.pathLabel(line.categoryId);
    final label = category == null || path == null
        ? 'Categoria indisponível'
        : (category.isActive ? path : '$path (indisponível)');
    final summary = this.summary;
    final over = summary?.status == FinancialBudgetLineStatus.over;
    final overOnExpense =
        over && line.resultEffect == FinancialResultEffect.expense;
    return Container(
      key: FinancialBudgetScreen.lineKey(line.categoryId, line.resultEffect),
      padding: const EdgeInsets.all(AppTokens.space16),
      decoration: BoxDecoration(
        color: overOnExpense ? AppTokens.red50 : AppTokens.neutral50,
        border: Border.all(
          color: overOnExpense ? AppTokens.red700 : AppTokens.neutral200,
        ),
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: AppTokens.space12,
            runSpacing: AppTokens.space8,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(label, style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(width: AppTokens.space8),
                  AppBadge(
                    label: financialBudgetEffectLabel(line.resultEffect),
                    tone: line.resultEffect == FinancialResultEffect.income
                        ? AppBadgeTone.positive
                        : AppBadgeTone.neutral,
                  ),
                ],
              ),
              if (summary != null)
                Row(
                  key: FinancialBudgetScreen.lineStatusKey(
                    line.categoryId,
                    line.resultEffect,
                  ),
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      switch (summary.status) {
                        FinancialBudgetLineStatus.under =>
                          Icons.trending_flat_rounded,
                        FinancialBudgetLineStatus.at =>
                          Icons.check_circle_outline,
                        FinancialBudgetLineStatus.over =>
                          Icons.arrow_upward_rounded,
                      },
                      size: 18,
                      color: overOnExpense
                          ? AppTokens.red700
                          : AppTokens.neutral700,
                      semanticLabel: summary.status.wireValue,
                    ),
                    const SizedBox(width: AppTokens.space4),
                    Text(
                      financialBudgetStatusLabel(
                        line.resultEffect,
                        summary.status,
                      ),
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: overOnExpense
                            ? AppTokens.red700
                            : AppTokens.neutral700,
                      ),
                    ),
                  ],
                ),
            ],
          ),
          const SizedBox(height: AppTokens.space12),
          Wrap(
            spacing: AppTokens.space24,
            runSpacing: AppTokens.space8,
            children: [
              _Amount(
                label: 'Planejado',
                value: formatFinancialMoney(line.planned),
              ),
              _Amount(
                label: 'Realizado',
                value: summary == null
                    ? '—'
                    : formatFinancialMoney(summary.realized),
              ),
              _Amount(
                label: 'Restante',
                value: summary == null
                    ? '—'
                    : formatFinancialMoney(summary.remaining),
              ),
            ],
          ),
          if (summary != null) ...[
            const SizedBox(height: AppTokens.space12),
            Semantics(
              label:
                  'Progresso ${financialBudgetProgressLabel(summary.progressPercent)} do planejado',
              child: ClipRRect(
                borderRadius: BorderRadius.circular(999),
                child: LinearProgressIndicator(
                  key: FinancialBudgetScreen.lineProgressKey(
                    line.categoryId,
                    line.resultEffect,
                  ),
                  minHeight: 8,
                  value: financialBudgetProgressFraction(
                    summary.progressPercent,
                  ),
                  backgroundColor: AppTokens.neutral200,
                  color: overOnExpense ? AppTokens.red700 : AppTokens.forest700,
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space4),
            Text(
              '${financialBudgetProgressLabel(summary.progressPercent)} do planejado',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ],
      ),
    );
  }
}

class _Amount extends StatelessWidget {
  const _Amount({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          label,
          style: Theme.of(
            context,
          ).textTheme.labelMedium?.copyWith(color: AppTokens.neutral700),
        ),
        Text(value, style: Theme.of(context).textTheme.titleMedium),
      ],
    );
  }
}
