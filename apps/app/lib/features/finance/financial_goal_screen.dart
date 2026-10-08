import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_allocation_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_editor_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/components/app_badge.dart';
import 'package:meufinanceiro_app/theme/components/app_state_panel.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Financial goals (#260): a target, and what was *virtually* allocated to it.
///
/// A goal is planning and an allocation is a virtual, append-only event: it does
/// not transfer, spend or block money, and it never creates a Movement. Every
/// number shown here (destinado, restante, progresso, lastro) comes from the
/// server on every read; nothing is computed, cached or patched on the client.
/// Nothing is optimistic: after any write the goals are read again. A stale edit
/// (409) is never retried: the current state is shown and the user acts again
/// explicitly.
class FinancialGoalScreen extends ConsumerStatefulWidget {
  const FinancialGoalScreen({super.key});

  static const titleKey = Key('financial-goal-title');
  static const refreshKey = Key('financial-goal-refresh');
  static const createKey = Key('financial-goal-create');
  static const createEmptyKey = Key('financial-goal-create-empty');
  static const virtualNoticeKey = Key('financial-goal-virtual-notice');
  static const loadingKey = Key('financial-goal-loading');
  static const emptyKey = Key('financial-goal-empty');
  static const errorKey = Key('financial-goal-error');
  static const retryKey = Key('financial-goal-retry');
  static const refreshNoticeKey = Key('financial-goal-refresh-notice');
  static const untrustedKey = Key('financial-goal-untrusted');
  static const conflictKey = Key('financial-goal-conflict');
  static const conflictDismissKey = Key('financial-goal-conflict-dismiss');
  static const listKey = Key('financial-goal-list');
  static const detailKey = Key('financial-goal-detail');
  static const summaryLoadingKey = Key('financial-goal-summary-loading');
  static const summaryErrorKey = Key('financial-goal-summary-error');
  static const summaryRetryKey = Key('financial-goal-summary-retry');
  static const readOnlyKey = Key('financial-goal-readonly');
  static const editKey = Key('financial-goal-edit');
  static const allocateKey = Key('financial-goal-allocate');
  static const releaseKey = Key('financial-goal-release');
  static const progressKey = Key('financial-goal-progress');
  static const progressStatusKey = Key('financial-goal-progress-status');
  static const allocatedKey = Key('financial-goal-allocated');
  static const targetKey = Key('financial-goal-target');
  static const remainingKey = Key('financial-goal-remaining');
  static const surplusKey = Key('financial-goal-surplus');
  static const backingAlertKey = Key('financial-goal-backing-alert');
  static const accountsKey = Key('financial-goal-accounts');
  static const eventsKey = Key('financial-goal-events');
  static const noEventsKey = Key('financial-goal-no-events');
  static Key rowKey(String goalId) => Key('financial-goal-row-$goalId');
  static Key rowProgressKey(String goalId) =>
      Key('financial-goal-row-progress-$goalId');
  static Key accountKey(String accountId) =>
      Key('financial-goal-account-$accountId');
  static Key accountBackingKey(String accountId) =>
      Key('financial-goal-account-backing-$accountId');
  static Key eventKey(String eventId) => Key('financial-goal-event-$eventId');

  @override
  ConsumerState<FinancialGoalScreen> createState() =>
      _FinancialGoalScreenState();
}

class _FinancialGoalScreenState extends ConsumerState<FinancialGoalScreen> {
  final _headingFocusNode = FocusNode(debugLabel: 'financial-goal-heading');

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _headingFocusNode.requestFocus();
      unawaited(ref.read(financialGoalsControllerProvider.notifier).load());
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

  Future<void> _openEditor({FinancialGoal? existing}) async {
    final now = ref.read(financialGoalClockProvider)();
    final result = await showDialog<FinancialGoalEditorResult>(
      context: context,
      builder: (_) => FinancialGoalEditorDialog(today: now, existing: existing),
    );
    if (result == null || !mounted) return;
    final controller = ref.read(financialGoalsControllerProvider.notifier);
    final outcome = switch (result) {
      FinancialGoalEditorCreate(:final input) => await controller.createGoal(
        input,
      ),
      FinancialGoalEditorReplace(:final input) => await controller.replaceGoal(
        existing!.id,
        input,
      ),
    };
    if (!mounted) return;
    _announce(_message(outcome));
  }

  Future<void> _openAllocation(
    FinancialGoalsState state,
    FinancialGoal goal,
    FinancialGoalOperation operation,
  ) async {
    final summary = state.summary;
    final options = operation == FinancialGoalOperation.allocate
        ? financialGoalAllocationOptions(
            goal: goal,
            accounts: state.accounts,
            summary: summary,
          )
        : (summary == null
              ? const <FinancialGoalAccountOption>[]
              : financialGoalReleaseOptions(
                  accounts: state.accounts,
                  summary: summary,
                ));
    final input = await showDialog<FinancialGoalAllocationInput>(
      context: context,
      builder: (_) => FinancialGoalAllocationDialog(
        operation: operation,
        goal: goal,
        options: options,
      ),
    );
    if (input == null || !mounted) return;
    final outcome = await ref
        .read(financialGoalsControllerProvider.notifier)
        .allocate(goal.id, input);
    if (!mounted) return;
    _announce(_message(outcome));
  }

  String _message(FinancialGoalActionResult result) {
    const stale =
        ' O estado exibido pode estar desatualizado: use Atualizar antes de continuar.';
    final base = switch (result.outcome) {
      FinancialGoalActionOutcome.created => 'Meta criada.',
      FinancialGoalActionOutcome.updated => 'Meta atualizada.',
      FinancialGoalActionOutcome.allocated =>
        'Valor destinado virtualmente à meta. Nenhum dinheiro foi movimentado.',
      FinancialGoalActionOutcome.released =>
        'Valor liberado da meta. Nenhum dinheiro foi movimentado.',
      FinancialGoalActionOutcome.conflict =>
        'O pedido conflita com o estado atual (a meta mudou, o saldo '
            'disponível ou o valor destinado não comporta o valor, ou um limite '
            'foi atingido). Nada foi gravado: revise os valores atuais.',
      FinancialGoalActionOutcome.rejected =>
        'O pedido foi recusado e nada foi gravado.',
      FinancialGoalActionOutcome.readOnly =>
        'Esta meta é somente leitura para você. Nada foi gravado.',
      FinancialGoalActionOutcome.unknownOutcome =>
        'Não foi possível confirmar o resultado e o pedido não será reenviado '
            'automaticamente. Confira o estado atual.',
      FinancialGoalActionOutcome.notAllowed =>
        'Esta ação não está disponível agora.',
      FinancialGoalActionOutcome.accessBlocked => 'Acesso indisponível.',
    };
    final refreshed = result.reconciled
        ? ' As metas foram atualizadas.'
        : stale;
    return switch (result.outcome) {
      FinancialGoalActionOutcome.notAllowed ||
      FinancialGoalActionOutcome.accessBlocked => base,
      _ => '$base$refreshed',
    };
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(financialGoalsControllerProvider);
    final controller = ref.read(financialGoalsControllerProvider.notifier);
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
                          'Metas',
                          key: FinancialGoalScreen.titleKey,
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Text(
                      'Defina um alvo e acompanhe quanto do seu saldo atual foi '
                      'destinado a ele. O alvo é só planejamento: apenas o que '
                      'você destina explicitamente conta como destinado.',
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
                    key: FinancialGoalScreen.refreshKey,
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
                    key: FinancialGoalScreen.createKey,
                    onPressed: canCreate
                        ? () => unawaited(_openEditor())
                        : null,
                    icon: const Icon(Icons.add_rounded),
                    label: const Text('Nova meta'),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppTokens.space16),
          const _VirtualNotice(),
          const SizedBox(height: AppTokens.space16),
          if (state.refreshFailure != FinancialRefreshFailure.none) ...[
            Card(
              key: FinancialGoalScreen.refreshNoticeKey,
              child: Padding(
                padding: const EdgeInsets.all(AppTokens.space16),
                child: Text(
                  state.refreshFailure ==
                          FinancialRefreshFailure.invalidResponse
                      ? 'As metas atuais foram preservadas porque a nova '
                            'resposta não pôde ser validada.'
                      : 'As metas atuais foram preservadas, mas não foi '
                            'possível atualizá-las.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (state.isLoaded && !state.trusted) ...[
            const Card(
              key: FinancialGoalScreen.untrustedKey,
              child: Padding(
                padding: EdgeInsets.all(AppTokens.space16),
                child: Text(
                  'O estado exibido pode estar desatualizado. Use Atualizar '
                  'antes de criar, editar, destinar ou liberar.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (state.isLoaded && state.conflictNotice) ...[
            Card(
              key: FinancialGoalScreen.conflictKey,
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
                        'Conflito: o pedido não pôde ser aplicado ao estado '
                        'atual (a meta mudou, o saldo disponível ou o valor '
                        'destinado não comporta o valor, ou um limite foi '
                        'atingido). Nada foi gravado e nada foi reenviado. O '
                        'que está na tela é o estado atual; tente de novo se '
                        'ainda for necessário.',
                      ),
                    ),
                    TextButton(
                      key: FinancialGoalScreen.conflictDismissKey,
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
            onCreate: canCreate ? () => unawaited(_openEditor()) : null,
            onEdit: (goal) => unawaited(_openEditor(existing: goal)),
            onAllocate: (goal, operation) =>
                unawaited(_openAllocation(state, goal, operation)),
          ),
        ],
      ),
    );
  }
}

/// The permanent statement that an allocation is virtual.
class _VirtualNotice extends StatelessWidget {
  const _VirtualNotice();

  @override
  Widget build(BuildContext context) {
    return Container(
      key: FinancialGoalScreen.virtualNoticeKey,
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
            semanticLabel: 'Destinação virtual',
          ),
          const SizedBox(width: AppTokens.space12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  financialGoalVirtualNotice,
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                const SizedBox(height: AppTokens.space4),
                const Text(financialGoalVirtualExplanation),
              ],
            ),
          ),
        ],
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
    required this.onAllocate,
  });

  final FinancialGoalsState state;
  final VoidCallback onRetry;
  final ValueChanged<String> onSelect;
  final VoidCallback onRetrySummary;
  final VoidCallback? onCreate;
  final ValueChanged<FinancialGoal> onEdit;
  final void Function(FinancialGoal goal, FinancialGoalOperation operation)
  onAllocate;

  @override
  Widget build(BuildContext context) {
    if (state.phase == FinancialLoadPhase.idle ||
        state.phase == FinancialLoadPhase.loading) {
      return const KeyedSubtree(
        key: FinancialGoalScreen.loadingKey,
        child: AppStatePanel(
          kind: AppStateKind.loading,
          title: 'Carregando metas…',
          description: 'Buscando suas metas e o que foi destinado a cada uma.',
        ),
      );
    }
    if (!state.isLoaded) {
      return _PhasePanel(phase: state.phase, onRetry: onRetry);
    }
    if (state.goals.isEmpty) {
      return Column(
        key: FinancialGoalScreen.emptyKey,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const AppStatePanel(
            kind: AppStateKind.empty,
            title: 'Nenhuma meta ainda',
            description:
                'Crie uma meta (reserva de emergência, viagem…) e destine '
                'virtualmente parte do saldo de uma conta a ela.',
          ),
          const SizedBox(height: AppTokens.space12),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(
              key: FinancialGoalScreen.createEmptyKey,
              onPressed: onCreate,
              icon: const Icon(Icons.add_rounded),
              label: const Text('Criar primeira meta'),
            ),
          ),
        ],
      );
    }
    final selected = state.selected;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Column(
          key: FinancialGoalScreen.listKey,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (final item in state.goals)
              _GoalRow(
                item: item,
                selected: item.goal.id == state.selectedGoalId,
                enabled: !state.isBusy,
                onSelect: () => onSelect(item.goal.id),
              ),
          ],
        ),
        const SizedBox(height: AppTokens.space16),
        if (selected != null)
          _GoalDetail(
            state: state,
            item: selected,
            onRetrySummary: onRetrySummary,
            onEdit: onEdit,
            onAllocate: onAllocate,
          ),
      ],
    );
  }
}

class _GoalRow extends StatelessWidget {
  const _GoalRow({
    required this.item,
    required this.selected,
    required this.enabled,
    required this.onSelect,
  });

  final FinancialGoalListItem item;
  final bool selected;
  final bool enabled;
  final VoidCallback onSelect;

  @override
  Widget build(BuildContext context) {
    final goal = item.goal;
    return Card(
      key: FinancialGoalScreen.rowKey(goal.id),
      color: selected ? AppTokens.forest50 : null,
      shape: selected
          ? RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
              side: const BorderSide(color: AppTokens.forest700, width: 2),
            )
          : null,
      child: InkWell(
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
        onTap: enabled && !selected ? onSelect : null,
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.space16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                spacing: AppTokens.space8,
                runSpacing: AppTokens.space8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    goal.title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  AppBadge(
                    label: financialGoalScopeLabel(goal.visibilityScope),
                    tone: AppBadgeTone.info,
                  ),
                  AppBadge(label: goal.currency),
                  if (!goal.canEdit)
                    const AppBadge(
                      label: 'Somente leitura',
                      tone: AppBadgeTone.warning,
                    ),
                ],
              ),
              const SizedBox(height: AppTokens.space8),
              LinearProgressIndicator(
                key: FinancialGoalScreen.rowProgressKey(goal.id),
                value: financialGoalProgressFraction(item.progressPercent),
                semanticsLabel:
                    'Progresso destinado de ${goal.title}: '
                    '${financialGoalProgressLabel(item.progressPercent)}',
              ),
              const SizedBox(height: AppTokens.space8),
              Text(
                'Destinado virtualmente ${formatFinancialMoney(item.allocated)} '
                'de ${formatFinancialMoney(goal.target)} '
                '(${financialGoalProgressLabel(item.progressPercent)}) · '
                '${financialGoalProgressStatusLabel(item.progressStatus)}',
              ),
            ],
          ),
        ),
      ),
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
        'Entre novamente para ver as metas.',
        false,
      ),
      FinancialLoadPhase.forbidden => (
        'Acesso indisponível',
        'Você não tem acesso às metas desta residência.',
        false,
      ),
      FinancialLoadPhase.primaryResidenceRequired => (
        'Residência principal necessária',
        'Defina uma residência principal para ver as metas.',
        false,
      ),
      FinancialLoadPhase.invalidResponse => (
        'Resposta inválida',
        'A resposta do servidor não pôde ser validada e nada foi exibido.',
        true,
      ),
      _ => (
        'Metas indisponíveis',
        'Não foi possível carregar as metas agora.',
        true,
      ),
    };
    return Column(
      key: FinancialGoalScreen.errorKey,
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
              key: FinancialGoalScreen.retryKey,
              onPressed: onRetry,
              child: const Text('Tentar novamente'),
            ),
          ),
        ],
      ],
    );
  }
}

class _GoalDetail extends StatelessWidget {
  const _GoalDetail({
    required this.state,
    required this.item,
    required this.onRetrySummary,
    required this.onEdit,
    required this.onAllocate,
  });

  final FinancialGoalsState state;
  final FinancialGoalListItem item;
  final VoidCallback onRetrySummary;
  final ValueChanged<FinancialGoal> onEdit;
  final void Function(FinancialGoal goal, FinancialGoalOperation operation)
  onAllocate;

  @override
  Widget build(BuildContext context) {
    final goal = item.goal;
    final summary = state.summaryPhase == FinancialGoalSummaryPhase.ready
        ? state.summary
        : null;
    final canAct = state.trusted && !state.isBusy && goal.canEdit;
    final canAllocate =
        canAct &&
        financialGoalAllocationOptions(
          goal: goal,
          accounts: state.accounts,
          summary: summary,
        ).isNotEmpty;
    final canRelease =
        canAct &&
        summary != null &&
        releasableFinancialGoalAccounts(summary).isNotEmpty;
    return Card(
      key: FinancialGoalScreen.detailKey,
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
                      goal.title,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Wrap(
                      spacing: AppTokens.space8,
                      runSpacing: AppTokens.space8,
                      children: [
                        AppBadge(
                          label: financialGoalScopeLabel(goal.visibilityScope),
                          tone: AppBadgeTone.info,
                        ),
                        AppBadge(label: goal.currency),
                        if (goal.targetDate != null)
                          AppBadge(
                            label:
                                'Prazo ${financialGoalDateLabel(goal.targetDate!)}',
                          ),
                        if (!goal.canEdit)
                          const AppBadge(
                            key: FinancialGoalScreen.readOnlyKey,
                            label: 'Somente leitura',
                            tone: AppBadgeTone.warning,
                          ),
                      ],
                    ),
                  ],
                ),
                Wrap(
                  spacing: AppTokens.space8,
                  runSpacing: AppTokens.space8,
                  children: [
                    if (goal.canEdit) ...[
                      FilledButton.icon(
                        key: FinancialGoalScreen.allocateKey,
                        onPressed: canAllocate
                            ? () => onAllocate(
                                goal,
                                FinancialGoalOperation.allocate,
                              )
                            : null,
                        icon: const Icon(Icons.savings_outlined),
                        label: const Text('Destinar'),
                      ),
                      OutlinedButton.icon(
                        key: FinancialGoalScreen.releaseKey,
                        onPressed: canRelease
                            ? () => onAllocate(
                                goal,
                                FinancialGoalOperation.release,
                              )
                            : null,
                        icon: const Icon(Icons.undo_rounded),
                        label: const Text('Liberar'),
                      ),
                      OutlinedButton.icon(
                        key: FinancialGoalScreen.editKey,
                        onPressed: state.trusted && !state.isBusy
                            ? () => onEdit(goal)
                            : null,
                        icon: const Icon(Icons.edit_outlined),
                        label: const Text('Editar'),
                      ),
                    ],
                  ],
                ),
              ],
            ),
            if (goal.description != null) ...[
              const SizedBox(height: AppTokens.space8),
              Text(goal.description!),
            ],
            if (!goal.canEdit) ...[
              const SizedBox(height: AppTokens.space8),
              Text(
                'Você pode ver esta meta, mas só quem a criou pode editá-la, '
                'destinar ou liberar valores.',
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
              ),
            ],
            const SizedBox(height: AppTokens.space16),
            _Progress(item: item, summary: summary),
            const SizedBox(height: AppTokens.space16),
            if (state.summaryPhase == FinancialGoalSummaryPhase.loading)
              const KeyedSubtree(
                key: FinancialGoalScreen.summaryLoadingKey,
                child: AppStatePanel(
                  kind: AppStateKind.loading,
                  title: 'Carregando o resumo…',
                  description:
                      'Lendo as contas, o saldo e o histórico da meta.',
                  compact: true,
                ),
              )
            else if (summary == null)
              Column(
                key: FinancialGoalScreen.summaryErrorKey,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  AppStatePanel(
                    kind: AppStateKind.unavailable,
                    title: 'Resumo indisponível',
                    description:
                        state.summaryPhase ==
                            FinancialGoalSummaryPhase.invalidResponse
                        ? 'A resposta do servidor não pôde ser validada. Os '
                              'dados da meta continuam acima, sem o detalhe por '
                              'conta e sem o histórico.'
                        : 'Não foi possível ler o resumo agora. Os dados da '
                              'meta continuam acima, sem o detalhe por conta e '
                              'sem o histórico.',
                    compact: true,
                  ),
                  const SizedBox(height: AppTokens.space12),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: FilledButton(
                      key: FinancialGoalScreen.summaryRetryKey,
                      onPressed: state.isBusy ? null : onRetrySummary,
                      child: const Text('Tentar novamente'),
                    ),
                  ),
                ],
              )
            else ...[
              if (summary.hasInsufficientBacking) ...[
                const _BackingAlert(),
                const SizedBox(height: AppTokens.space16),
              ],
              _Accounts(summary: summary, accounts: state.accounts),
              const SizedBox(height: AppTokens.space16),
              _Events(summary: summary, accounts: state.accounts),
            ],
          ],
        ),
      ),
    );
  }
}

/// Planned (the target) versus virtually allocated, as the server reported them.
class _Progress extends StatelessWidget {
  const _Progress({required this.item, required this.summary});

  final FinancialGoalListItem item;
  final FinancialGoalSummary? summary;

  @override
  Widget build(BuildContext context) {
    final goal = item.goal;
    final allocated = summary?.allocated ?? item.allocated;
    final remaining = summary?.remainingTarget ?? item.remainingTarget;
    final percent = summary?.progressPercent ?? item.progressPercent;
    final status = summary?.progressStatus ?? item.progressStatus;
    final surplus = summary?.surplus;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        LinearProgressIndicator(
          key: FinancialGoalScreen.progressKey,
          minHeight: 10,
          value: financialGoalProgressFraction(percent),
          semanticsLabel:
              'Progresso destinado: ${financialGoalProgressLabel(percent)}',
        ),
        const SizedBox(height: AppTokens.space12),
        Wrap(
          spacing: AppTokens.space24,
          runSpacing: AppTokens.space12,
          children: [
            _Figure(
              key: FinancialGoalScreen.targetKey,
              label: 'Planejado (alvo)',
              value: formatFinancialMoney(goal.target),
            ),
            _Figure(
              key: FinancialGoalScreen.allocatedKey,
              label: 'Destinado virtualmente',
              value:
                  '${formatFinancialMoney(allocated)} (${financialGoalProgressLabel(percent)})',
            ),
            _Figure(
              key: FinancialGoalScreen.remainingKey,
              label: 'Falta para o alvo',
              value: formatFinancialMoney(remaining),
            ),
            if (surplus != null && !surplus.isZero)
              _Figure(
                key: FinancialGoalScreen.surplusKey,
                label: 'Acima do alvo',
                value: formatFinancialMoney(surplus),
              ),
          ],
        ),
        const SizedBox(height: AppTokens.space8),
        Text(
          financialGoalProgressStatusLabel(status),
          key: FinancialGoalScreen.progressStatusKey,
          style: Theme.of(context).textTheme.labelLarge,
        ),
      ],
    );
  }
}

class _Figure extends StatelessWidget {
  const _Figure({required this.label, required this.value, super.key});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
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

class _BackingAlert extends StatelessWidget {
  const _BackingAlert();

  @override
  Widget build(BuildContext context) {
    return Container(
      key: FinancialGoalScreen.backingAlertKey,
      padding: const EdgeInsets.all(AppTokens.space16),
      decoration: BoxDecoration(
        color: AppTokens.amber50,
        border: Border.all(color: AppTokens.amber700),
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            Icons.warning_amber_rounded,
            color: AppTokens.amber700,
            semanticLabel: 'Atenção',
          ),
          SizedBox(width: AppTokens.space12),
          Expanded(child: Text(financialGoalInsufficientBackingNotice)),
        ],
      ),
    );
  }
}

class _Accounts extends StatelessWidget {
  const _Accounts({required this.summary, required this.accounts});

  final FinancialGoalSummary summary;
  final List<FinancialAccount> accounts;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: FinancialGoalScreen.accountsKey,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Contas', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: AppTokens.space8),
        if (summary.accounts.isEmpty)
          Text(
            'Nenhum valor destinado ainda. Use Destinar para reservar '
            'virtualmente parte do saldo de uma conta.',
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
          )
        else
          for (final account in summary.accounts)
            Padding(
              padding: const EdgeInsets.only(bottom: AppTokens.space12),
              child: Column(
                key: FinancialGoalScreen.accountKey(account.accountId),
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(
                    spacing: AppTokens.space8,
                    runSpacing: AppTokens.space8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(
                        financialGoalAccountName(accounts, account.accountId),
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      if (account.accountStatus ==
                          FinancialAccountStatus.archived)
                        const AppBadge(label: 'Arquivada'),
                      AppBadge(
                        key: FinancialGoalScreen.accountBackingKey(
                          account.accountId,
                        ),
                        label: financialGoalBackingStatusLabel(
                          account.backingStatus,
                        ),
                        tone:
                            account.backingStatus ==
                                FinancialGoalBackingStatus.covered
                            ? AppBadgeTone.positive
                            : AppBadgeTone.warning,
                      ),
                    ],
                  ),
                  Text(
                    'Destinado a esta meta ${formatFinancialMoney(account.allocated)}'
                    ' · saldo atual ${formatFinancialMoney(account.accountBalance)}'
                    ' · destinado em todas as metas '
                    '${formatFinancialMoney(account.accountAllocatedTotal)}',
                  ),
                  if (account.backingStatus ==
                      FinancialGoalBackingStatus.insufficient)
                    Text(
                      'Faltam ${formatFinancialMoney(account.shortfall)} de '
                      'saldo para cobrir tudo o que foi destinado nesta conta.',
                    ),
                ],
              ),
            ),
      ],
    );
  }
}

class _Events extends StatelessWidget {
  const _Events({required this.summary, required this.accounts});

  final FinancialGoalSummary summary;
  final List<FinancialAccount> accounts;

  @override
  Widget build(BuildContext context) {
    final events = summary.events.reversed.toList(growable: false);
    return Column(
      key: FinancialGoalScreen.eventsKey,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Histórico', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: AppTokens.space8),
        if (events.isEmpty)
          Text(
            'Sem movimentações virtuais ainda.',
            key: FinancialGoalScreen.noEventsKey,
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
          )
        else
          for (final event in events)
            Padding(
              key: FinancialGoalScreen.eventKey(event.id),
              padding: const EdgeInsets.only(bottom: AppTokens.space4),
              child: Text(
                '${financialGoalOperationLabel(event.operation)} · '
                '${formatFinancialMoney(event.amount)} · '
                '${financialGoalAccountName(accounts, event.accountId)} · '
                '${_eventDate(event.createdAt)}',
              ),
            ),
      ],
    );
  }
}

String _eventDate(DateTime value) {
  final local = value.toLocal();
  return '${local.day.toString().padLeft(2, '0')}/'
      '${local.month.toString().padLeft(2, '0')}/'
      '${local.year.toString().padLeft(4, '0')}';
}
