import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/features/finance/financial_pending_controller.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/components/app_badge.dart';
import 'package:meufinanceiro_app/theme/components/app_state_panel.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Pending-classification inbox (#249): unclassified income/expense Movements,
/// each with the derived suggestion state.
///
/// The list is a read model computed by the backend. Nothing here is removed
/// optimistically: an item leaves only when the canonical re-read after an
/// action no longer lists it. A rule is applied only after an explicit
/// confirmation, an ambiguous item never gets a rule chosen for it, and splitting
/// between categories stays in the account screen.
class FinancialPendingScreen extends ConsumerStatefulWidget {
  const FinancialPendingScreen({super.key});

  static const titleKey = Key('financial-pending-title');
  static const refreshKey = Key('financial-pending-refresh');
  static const loadingKey = Key('financial-pending-loading');
  static const listKey = Key('financial-pending-list');
  static const emptyKey = Key('financial-pending-empty');
  static const emptyMoreKey = Key('financial-pending-empty-more');
  static const errorKey = Key('financial-pending-error');
  static const retryKey = Key('financial-pending-retry');
  static const loadMoreKey = Key('financial-pending-load-more');
  static const loadMoreErrorKey = Key('financial-pending-load-more-error');
  static const untrustedKey = Key('financial-pending-untrusted');
  static const refreshNoticeKey = Key('financial-pending-refresh-notice');
  static const accountFilterKey = Key('financial-pending-filter-account');
  static const effectFilterKey = Key('financial-pending-filter-effect');
  static const statusFilterKey = Key('financial-pending-filter-status');
  static const clearFiltersKey = Key('financial-pending-filter-clear');
  static const confirmDialogKey = Key('financial-pending-apply-dialog');
  static const confirmApplyKey = Key('financial-pending-apply-confirm');
  static const cancelApplyKey = Key('financial-pending-apply-cancel');
  static const classifyDialogKey = Key('financial-pending-classify-dialog');
  static const classifyConfirmKey = Key('financial-pending-classify-confirm');
  static const classifyEmptyKey = Key('financial-pending-classify-empty');
  static const classifySplitKey = Key('financial-pending-classify-split');

  static Key itemKey(String movementId) => Key('financial-pending-$movementId');
  static Key badgeKey(String movementId) =>
      Key('financial-pending-badge-$movementId');
  static Key suggestionKey(String movementId) =>
      Key('financial-pending-suggestion-$movementId');
  static Key ambiguousKey(String movementId) =>
      Key('financial-pending-ambiguous-$movementId');
  static Key readOnlyKey(String movementId) =>
      Key('financial-pending-readonly-$movementId');
  static Key applyKey(String movementId) =>
      Key('financial-pending-apply-$movementId');
  static Key classifyKey(String movementId) =>
      Key('financial-pending-classify-$movementId');
  static Key busyKey(String movementId) =>
      Key('financial-pending-busy-$movementId');
  static Key categoryOptionKey(String categoryId) =>
      Key('financial-pending-category-$categoryId');

  @override
  ConsumerState<FinancialPendingScreen> createState() =>
      _FinancialPendingScreenState();
}

class _FinancialPendingScreenState
    extends ConsumerState<FinancialPendingScreen> {
  final _headingFocusNode = FocusNode(debugLabel: 'financial-pending-heading');

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _headingFocusNode.requestFocus();
      unawaited(ref.read(financialPendingControllerProvider.notifier).load());
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

  Future<void> _apply(
    FinancialPendingMovement item,
    FinancialPendingState state,
  ) async {
    final category = item.suggestedCategoryId;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => _ApplyConfirmDialog(
        item: item,
        accountLabel: _accountLabel(state, item.accountId),
        categoryLabel: category == null
            ? 'Categoria indisponível'
            : _categoryLabel(state.categoryIndex, category),
      ),
    );
    if (confirmed != true || !mounted) return;
    final result = await ref
        .read(financialPendingControllerProvider.notifier)
        .applySuggestion(item.movementId);
    if (!mounted) return;
    _announce(_message(result));
  }

  Future<void> _classify(
    FinancialPendingMovement item,
    FinancialPendingState state,
  ) async {
    final account = state.accountOf(item.accountId);
    if (account == null) return;
    final categoryId = await showDialog<String>(
      context: context,
      builder: (_) => _ClassifyDialog(
        item: item,
        account: account,
        index: state.categoryIndex,
        accountLabel: account.name,
      ),
    );
    if (categoryId == null || !mounted) return;
    final result = await ref
        .read(financialPendingControllerProvider.notifier)
        .classify(item.movementId, categoryId);
    if (!mounted) return;
    _announce(_message(result));
  }

  String _message(FinancialPendingActionResult result) {
    const stale =
        ' A lista pode estar desatualizada: use Atualizar antes de continuar.';
    final base = switch (result.outcome) {
      FinancialPendingActionOutcome.ruleApplied =>
        'Sugestão aplicada pelo servidor.',
      FinancialPendingActionOutcome.manuallyClassified =>
        'Lançamento classificado.',
      FinancialPendingActionOutcome.alreadyClassified =>
        'Este lançamento já tinha sido classificado; nada foi gravado agora.',
      FinancialPendingActionOutcome.stateChanged =>
        'O estado mudou e nada foi gravado. Revise o item na lista atual.',
      FinancialPendingActionOutcome.rejected =>
        'O pedido foi recusado e nada foi gravado.',
      FinancialPendingActionOutcome.failed =>
        'Falha ao gravar: nada foi confirmado para este lançamento.',
      FinancialPendingActionOutcome.unknownOutcome =>
        'Não foi possível confirmar o resultado e o pedido não será reenviado '
            'automaticamente. Confira o estado atual na lista.',
      FinancialPendingActionOutcome.notAllowed =>
        'Esta ação não está disponível agora.',
      FinancialPendingActionOutcome.accessBlocked => 'Acesso indisponível.',
    };
    final refreshed = result.reconciled ? ' A lista foi atualizada.' : stale;
    return switch (result.outcome) {
      FinancialPendingActionOutcome.notAllowed ||
      FinancialPendingActionOutcome.accessBlocked => base,
      _ => '$base$refreshed',
    };
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(financialPendingControllerProvider);
    final refreshEnabled =
        !state.isBusy &&
        state.phase != FinancialLoadPhase.authenticationRequired &&
        state.phase != FinancialLoadPhase.forbidden &&
        state.phase != FinancialLoadPhase.primaryResidenceRequired;
    final controller = ref.read(financialPendingControllerProvider.notifier);

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
                          'Pendências',
                          key: FinancialPendingScreen.titleKey,
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Text(
                      'Lançamentos de receita e despesa ainda sem categoria. A '
                      'lista é calculada a partir do extrato: classificar não '
                      'altera valores, saldos nem o extrato. Sugestões vêm das '
                      'regras e só são aplicadas quando você confirma.',
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                        color: AppTokens.neutral700,
                      ),
                    ),
                  ],
                ),
              ),
              OutlinedButton.icon(
                key: FinancialPendingScreen.refreshKey,
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
            ],
          ),
          const SizedBox(height: AppTokens.space24),
          if (state.isLoaded) ...[
            _Filters(
              state: state,
              onChanged: (filters) => unawaited(controller.setFilters(filters)),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (state.refreshFailure != FinancialRefreshFailure.none) ...[
            Card(
              key: FinancialPendingScreen.refreshNoticeKey,
              child: Padding(
                padding: const EdgeInsets.all(AppTokens.space16),
                child: Text(
                  state.refreshFailure ==
                          FinancialRefreshFailure.invalidResponse
                      ? 'A lista atual foi preservada porque a nova resposta '
                            'não pôde ser validada.'
                      : 'A lista atual foi preservada, mas não foi possível '
                            'atualizá-la.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (state.isLoaded && !state.trusted) ...[
            const Card(
              key: FinancialPendingScreen.untrustedKey,
              child: Padding(
                padding: EdgeInsets.all(AppTokens.space16),
                child: Text(
                  'A lista exibida pode estar desatualizada. Use Atualizar '
                  'antes de classificar ou aplicar sugestões.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          _Content(
            state: state,
            onRetry: () => unawaited(controller.refresh()),
            onLoadMore: () => unawaited(controller.loadMore()),
            onApply: (item) => unawaited(_apply(item, state)),
            onClassify: (item) => unawaited(_classify(item, state)),
          ),
        ],
      ),
    );
  }
}

String _accountLabel(FinancialPendingState state, String accountId) =>
    state.accountOf(accountId)?.name ?? 'Conta indisponível';

String _categoryLabel(FinancialCategoryIndex index, String categoryId) {
  final category = index.byId(categoryId);
  final path = index.pathLabel(categoryId);
  if (category == null || path == null) return 'Categoria indisponível';
  return category.isActive ? path : '$path (indisponível)';
}

String _formatDate(String isoDate) {
  final parts = isoDate.split('-');
  if (parts.length != 3) return isoDate;
  return '${parts[2]}/${parts[1]}/${parts[0]}';
}

class _Filters extends StatelessWidget {
  const _Filters({required this.state, required this.onChanged});

  final FinancialPendingState state;
  final ValueChanged<FinancialPendingFilters> onChanged;

  @override
  Widget build(BuildContext context) {
    final filters = state.filters;
    final enabled = !state.isBusy;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Wrap(
          spacing: AppTokens.space16,
          runSpacing: AppTokens.space12,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            SizedBox(
              width: 240,
              child: _FilterDropdown<String?>(
                dropdownKey: FinancialPendingScreen.accountFilterKey,
                label: 'Conta',
                value: filters.accountId,
                enabled: enabled,
                items: [
                  const DropdownMenuItem<String?>(
                    value: null,
                    child: Text('Todas as contas'),
                  ),
                  for (final account in state.accounts)
                    DropdownMenuItem<String?>(
                      value: account.accountId,
                      child: Text(
                        account.name,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                ],
                onChanged: (value) =>
                    onChanged(filters.copyWith(accountId: value)),
              ),
            ),
            SizedBox(
              width: 200,
              child: _FilterDropdown<FinancialResultEffect?>(
                dropdownKey: FinancialPendingScreen.effectFilterKey,
                label: 'Tipo',
                value: filters.resultEffect,
                enabled: enabled,
                items: const [
                  DropdownMenuItem<FinancialResultEffect?>(
                    value: null,
                    child: Text('Receitas e despesas'),
                  ),
                  DropdownMenuItem<FinancialResultEffect?>(
                    value: FinancialResultEffect.income,
                    child: Text('Receitas'),
                  ),
                  DropdownMenuItem<FinancialResultEffect?>(
                    value: FinancialResultEffect.expense,
                    child: Text('Despesas'),
                  ),
                ],
                onChanged: (value) =>
                    onChanged(filters.copyWith(resultEffect: value)),
              ),
            ),
            SizedBox(
              width: 220,
              child: _FilterDropdown<FinancialPendingRuleStatus?>(
                dropdownKey: FinancialPendingScreen.statusFilterKey,
                label: 'Sugestão',
                value: filters.ruleStatus,
                enabled: enabled,
                items: const [
                  DropdownMenuItem<FinancialPendingRuleStatus?>(
                    value: null,
                    child: Text('Todas'),
                  ),
                  DropdownMenuItem<FinancialPendingRuleStatus?>(
                    value: FinancialPendingRuleStatus.matched,
                    child: Text('Sugestão encontrada'),
                  ),
                  DropdownMenuItem<FinancialPendingRuleStatus?>(
                    value: FinancialPendingRuleStatus.ambiguous,
                    child: Text('Ambígua'),
                  ),
                  DropdownMenuItem<FinancialPendingRuleStatus?>(
                    value: FinancialPendingRuleStatus.noMatch,
                    child: Text('Sem sugestão'),
                  ),
                ],
                onChanged: (value) =>
                    onChanged(filters.copyWith(ruleStatus: value)),
              ),
            ),
            if (filters.isActive)
              TextButton(
                key: FinancialPendingScreen.clearFiltersKey,
                onPressed: enabled
                    ? () => onChanged(FinancialPendingFilters.none)
                    : null,
                child: const Text('Limpar filtros'),
              ),
          ],
        ),
      ),
    );
  }
}

/// A controlled dropdown: what it shows is always the controller's filter, never
/// a selection the user made that the list does not reflect (for example after a
/// failed reload that preserved the previous list).
class _FilterDropdown<T> extends StatelessWidget {
  const _FilterDropdown({
    required this.dropdownKey,
    required this.label,
    required this.value,
    required this.enabled,
    required this.items,
    required this.onChanged,
  });

  final Key dropdownKey;
  final String label;
  final T value;
  final bool enabled;
  final List<DropdownMenuItem<T>> items;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    return InputDecorator(
      decoration: InputDecoration(labelText: label),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<T>(
          key: dropdownKey,
          value: value,
          isExpanded: true,
          items: items,
          onChanged: enabled ? (selected) => onChanged(selected as T) : null,
        ),
      ),
    );
  }
}

class _Content extends StatelessWidget {
  const _Content({
    required this.state,
    required this.onRetry,
    required this.onLoadMore,
    required this.onApply,
    required this.onClassify,
  });

  final FinancialPendingState state;
  final VoidCallback onRetry;
  final VoidCallback onLoadMore;
  final ValueChanged<FinancialPendingMovement> onApply;
  final ValueChanged<FinancialPendingMovement> onClassify;

  @override
  Widget build(BuildContext context) {
    if (state.phase == FinancialLoadPhase.idle ||
        state.phase == FinancialLoadPhase.loading) {
      return const KeyedSubtree(
        key: FinancialPendingScreen.loadingKey,
        child: AppStatePanel(
          kind: AppStateKind.loading,
          title: 'Carregando pendências…',
          description:
              'Buscando somente os lançamentos visíveis na residência atual.',
        ),
      );
    }
    if (!state.isLoaded) {
      return _PhasePanel(phase: state.phase, onRetry: onRetry);
    }
    if (state.items.isEmpty) {
      if (state.hasMore) {
        return Column(
          key: FinancialPendingScreen.emptyMoreKey,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const AppStatePanel(
              kind: AppStateKind.empty,
              title: 'Nada encontrado até aqui',
              description:
                  'Nenhum lançamento deste filtro apareceu nesta etapa, mas '
                  'ainda há lançamentos a verificar.',
            ),
            const SizedBox(height: AppTokens.space12),
            _LoadMore(
              state: state,
              onLoadMore: onLoadMore,
              label: 'Continuar procurando',
            ),
          ],
        );
      }
      return KeyedSubtree(
        key: FinancialPendingScreen.emptyKey,
        child: AppStatePanel(
          kind: AppStateKind.empty,
          title: state.filters.isActive
              ? 'Nenhuma pendência com estes filtros'
              : 'Nenhuma pendência',
          description: state.filters.isActive
              ? 'Limpe os filtros para ver todas as pendências.'
              : 'Todos os lançamentos de receita e despesa visíveis já têm categoria.',
        ),
      );
    }
    return Column(
      key: FinancialPendingScreen.listKey,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final item in state.items)
          Padding(
            padding: const EdgeInsets.only(bottom: AppTokens.space12),
            child: _PendingCard(
              item: item,
              state: state,
              onApply: () => onApply(item),
              onClassify: () => onClassify(item),
            ),
          ),
        if (state.hasMore ||
            state.loadMoreFailure != FinancialRefreshFailure.none)
          _LoadMore(
            state: state,
            onLoadMore: onLoadMore,
            label: 'Carregar mais',
          ),
      ],
    );
  }
}

class _LoadMore extends StatelessWidget {
  const _LoadMore({
    required this.state,
    required this.onLoadMore,
    required this.label,
  });

  final FinancialPendingState state;
  final VoidCallback onLoadMore;
  final String label;

  @override
  Widget build(BuildContext context) {
    final failed = state.loadMoreFailure != FinancialRefreshFailure.none;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (failed)
          Padding(
            padding: const EdgeInsets.only(bottom: AppTokens.space8),
            child: Text(
              state.loadMoreFailure == FinancialRefreshFailure.invalidResponse
                  ? 'A próxima página não pôde ser validada. Os itens já '
                        'carregados foram mantidos.'
                  : 'Não foi possível carregar mais. Os itens já carregados '
                        'foram mantidos.',
              key: FinancialPendingScreen.loadMoreErrorKey,
            ),
          ),
        Align(
          alignment: Alignment.center,
          child: OutlinedButton.icon(
            key: FinancialPendingScreen.loadMoreKey,
            onPressed: state.isBusy || state.loadingMore || !state.hasMore
                ? null
                : onLoadMore,
            icon: state.loadingMore
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.expand_more_rounded),
            label: Text(failed ? 'Tentar novamente' : label),
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
        'Entre novamente para ver as pendências.',
        false,
      ),
      FinancialLoadPhase.forbidden => (
        'Acesso indisponível',
        'Você não tem acesso às pendências desta residência.',
        false,
      ),
      FinancialLoadPhase.primaryResidenceRequired => (
        'Residência principal necessária',
        'Defina uma residência principal para ver as pendências.',
        false,
      ),
      FinancialLoadPhase.invalidResponse => (
        'Resposta inválida',
        'A resposta do servidor não pôde ser validada e nada foi exibido.',
        true,
      ),
      _ => (
        'Pendências indisponíveis',
        'Não foi possível carregar as pendências agora.',
        true,
      ),
    };
    return Column(
      key: FinancialPendingScreen.errorKey,
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
              key: FinancialPendingScreen.retryKey,
              onPressed: onRetry,
              child: const Text('Tentar novamente'),
            ),
          ),
        ],
      ],
    );
  }
}

class _PendingCard extends StatelessWidget {
  const _PendingCard({
    required this.item,
    required this.state,
    required this.onApply,
    required this.onClassify,
  });

  final FinancialPendingMovement item;
  final FinancialPendingState state;
  final VoidCallback onApply;
  final VoidCallback onClassify;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final inFlight = state.mutationMovementId == item.movementId;
    final actionable = item.canClassify && !state.isBusy && state.trusted;
    final badge = switch (item.ruleStatus) {
      FinancialPendingRuleStatus.matched => (
        'Sugestão encontrada',
        AppBadgeTone.positive,
      ),
      FinancialPendingRuleStatus.ambiguous => ('Ambígua', AppBadgeTone.warning),
      FinancialPendingRuleStatus.noMatch => (
        'Sem sugestão',
        AppBadgeTone.neutral,
      ),
    };
    final account = state.accountOf(item.accountId);
    final readOnlyReason =
        account != null && account.status == FinancialAccountStatus.archived
        ? 'Somente leitura: a conta está arquivada.'
        : 'Somente leitura: este lançamento está em uma conta de outro membro.';
    return Card(
      key: FinancialPendingScreen.itemKey(item.movementId),
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: AppTokens.space16,
              runSpacing: AppTokens.space8,
              children: [
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 560),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(item.description, style: theme.textTheme.titleSmall),
                      const SizedBox(height: AppTokens.space4),
                      Text(
                        '${_formatDate(item.effectiveDate)} · '
                        '${_accountLabel(state, item.accountId)}',
                        style: theme.textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      formatFinancialMoney(item.money),
                      style: theme.textTheme.titleMedium,
                    ),
                    const SizedBox(height: AppTokens.space8),
                    KeyedSubtree(
                      key: FinancialPendingScreen.badgeKey(item.movementId),
                      child: AppBadge(label: badge.$1, tone: badge.$2),
                    ),
                  ],
                ),
              ],
            ),
            if (item.hasSuggestion && item.suggestedCategoryId != null) ...[
              const SizedBox(height: AppTokens.space12),
              Text(
                'Categoria sugerida: '
                '${_categoryLabel(state.categoryIndex, item.suggestedCategoryId!)}',
                key: FinancialPendingScreen.suggestionKey(item.movementId),
                style: theme.textTheme.bodyMedium,
              ),
            ],
            if (item.ruleStatus == FinancialPendingRuleStatus.ambiguous) ...[
              const SizedBox(height: AppTokens.space12),
              Text(
                'Mais de uma regra se aplica a este lançamento. Nenhuma foi '
                'escolhida automaticamente: classifique manualmente.',
                key: FinancialPendingScreen.ambiguousKey(item.movementId),
                style: theme.textTheme.bodyMedium,
              ),
            ],
            const SizedBox(height: AppTokens.space12),
            if (!item.canClassify)
              Text(
                readOnlyReason,
                key: FinancialPendingScreen.readOnlyKey(item.movementId),
                style: theme.textTheme.bodySmall?.copyWith(
                  color: AppTokens.neutral700,
                ),
              )
            else
              Wrap(
                spacing: AppTokens.space8,
                runSpacing: AppTokens.space8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  if (item.hasSuggestion)
                    FilledButton.icon(
                      key: FinancialPendingScreen.applyKey(item.movementId),
                      onPressed: actionable ? onApply : null,
                      icon: const Icon(Icons.check_rounded),
                      label: const Text('Aplicar sugestão'),
                    ),
                  OutlinedButton.icon(
                    key: FinancialPendingScreen.classifyKey(item.movementId),
                    onPressed: actionable ? onClassify : null,
                    icon: const Icon(Icons.label_outline_rounded),
                    label: const Text('Classificar'),
                  ),
                  if (inFlight)
                    SizedBox.square(
                      key: FinancialPendingScreen.busyKey(item.movementId),
                      dimension: 20,
                      child: const CircularProgressIndicator(strokeWidth: 2),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

/// Explicit confirmation before a rule writes a classification.
class _ApplyConfirmDialog extends StatelessWidget {
  const _ApplyConfirmDialog({
    required this.item,
    required this.accountLabel,
    required this.categoryLabel,
  });

  final FinancialPendingMovement item;
  final String accountLabel;
  final String categoryLabel;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: FinancialPendingScreen.confirmDialogKey,
      title: const Text('Aplicar sugestão'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(item.description),
          const SizedBox(height: AppTokens.space4),
          Text(
            '${formatFinancialMoney(item.money)} · '
            '${_formatDate(item.effectiveDate)} · $accountLabel',
          ),
          const SizedBox(height: AppTokens.space12),
          Text('Categoria: $categoryLabel'),
          const SizedBox(height: AppTokens.space12),
          const Text(
            'O servidor reavalia as regras antes de gravar. Se algo mudou, '
            'nada é gravado e você verá o estado atual. Valores e saldos não '
            'mudam.',
          ),
        ],
      ),
      actions: [
        TextButton(
          key: FinancialPendingScreen.cancelApplyKey,
          onPressed: () => Navigator.of(context).pop(false),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialPendingScreen.confirmApplyKey,
          onPressed: () => Navigator.of(context).pop(true),
          child: const Text('Aplicar'),
        ),
      ],
    );
  }
}

/// Simple manual classification: one category, 100% of the Movement, through
/// the same canonical endpoint as the statement. Splitting between categories
/// is done in the account screen.
class _ClassifyDialog extends StatefulWidget {
  const _ClassifyDialog({
    required this.item,
    required this.account,
    required this.index,
    required this.accountLabel,
  });

  final FinancialPendingMovement item;
  final FinancialAccount account;
  final FinancialCategoryIndex index;
  final String accountLabel;

  @override
  State<_ClassifyDialog> createState() => _ClassifyDialogState();
}

class _ClassifyDialogState extends State<_ClassifyDialog> {
  String? _selected;

  @override
  Widget build(BuildContext context) {
    final eligible = eligibleFinancialCategories(
      index: widget.index,
      account: widget.account,
    );
    return AlertDialog(
      key: FinancialPendingScreen.classifyDialogKey,
      title: const Text('Classificar lançamento'),
      content: SizedBox(
        width: 420,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.item.description),
            const SizedBox(height: AppTokens.space4),
            Text(
              '${formatFinancialMoney(widget.item.money)} · '
              '${_formatDate(widget.item.effectiveDate)} · '
              '${widget.accountLabel}',
            ),
            const SizedBox(height: AppTokens.space12),
            if (eligible.isEmpty)
              const Text(
                'Nenhuma categoria ativa está disponível para esta conta. '
                'Crie uma categoria na tela da conta.',
                key: FinancialPendingScreen.classifyEmptyKey,
              )
            else
              Flexible(
                child: SingleChildScrollView(
                  child: RadioGroup<String>(
                    groupValue: _selected,
                    onChanged: (value) => setState(() => _selected = value),
                    child: Column(
                      children: [
                        for (final category in eligible)
                          RadioListTile<String>(
                            key: FinancialPendingScreen.categoryOptionKey(
                              category.categoryId,
                            ),
                            value: category.categoryId,
                            title: Text(
                              widget.index.pathLabel(category.categoryId) ??
                                  category.name,
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            const SizedBox(height: AppTokens.space8),
            TextButton(
              key: FinancialPendingScreen.classifySplitKey,
              onPressed: () {
                Navigator.of(context).pop();
                context.go(
                  AppRoutes.financeAccountDetailLocation(widget.item.accountId),
                );
              },
              child: const Text('Ratear entre categorias na conta'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialPendingScreen.classifyConfirmKey,
          onPressed: _selected == null
              ? null
              : () => Navigator.of(context).pop(_selected),
          child: const Text('Classificar'),
        ),
      ],
    );
  }
}
