import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_editor_dialog.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_realize_dialog.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/components/app_badge.dart';
import 'package:meufinanceiro_app/theme/components/app_state_panel.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Manual monthly recurrences (#254): rules, their forecasts and explicit
/// registration.
///
/// A recurrence is planning and a forecast is not a fact: "previsto" never changes
/// the balance or the statement. Only Registrar creates a real Movement, and only
/// after the user confirms the actual amount and dates. Nothing is optimistic: the
/// screen is read again after every write, a write is sent once (never retried
/// automatically), and a conflict is explained, never silently re-applied.
class FinancialRecurrenceScreen extends ConsumerStatefulWidget {
  const FinancialRecurrenceScreen({super.key});

  static const titleKey = Key('financial-recurrence-title');
  static const refreshKey = Key('financial-recurrence-refresh');
  static const createKey = Key('financial-recurrence-create');
  static const createEmptyKey = Key('financial-recurrence-create-empty');
  static const forecastNoticeKey = Key('financial-recurrence-forecast-notice');
  static const previousMonthKey = Key('financial-recurrence-month-previous');
  static const nextMonthKey = Key('financial-recurrence-month-next');
  static const monthLabelKey = Key('financial-recurrence-month-label');
  static const loadingKey = Key('financial-recurrence-loading');
  static const emptyKey = Key('financial-recurrence-empty');
  static const errorKey = Key('financial-recurrence-error');
  static const retryKey = Key('financial-recurrence-retry');
  static const refreshNoticeKey = Key('financial-recurrence-refresh-notice');
  static const untrustedKey = Key('financial-recurrence-untrusted');
  static const conflictKey = Key('financial-recurrence-conflict');
  static const conflictDismissKey = Key(
    'financial-recurrence-conflict-dismiss',
  );
  static const activeSectionKey = Key('financial-recurrence-active');
  static const pausedSectionKey = Key('financial-recurrence-paused');
  static const occurrencesKey = Key('financial-recurrence-occurrences');
  static const occurrencesEmptyKey = Key(
    'financial-recurrence-occurrences-empty',
  );
  static const skipConfirmKey = Key('financial-recurrence-skip-confirm');
  static const skipCancelKey = Key('financial-recurrence-skip-cancel');
  static Key ruleKey(String id) => Key('financial-recurrence-rule-$id');
  static Key ruleStatusKey(String id) =>
      Key('financial-recurrence-rule-status-$id');
  static Key editKey(String id) => Key('financial-recurrence-edit-$id');
  static Key pauseKey(String id) => Key('financial-recurrence-pause-$id');
  static Key resumeKey(String id) => Key('financial-recurrence-resume-$id');
  static Key generateKey(String id) => Key('financial-recurrence-generate-$id');
  static Key readOnlyKey(String id) => Key('financial-recurrence-readonly-$id');
  static Key occurrenceKey(String id) =>
      Key('financial-recurrence-occurrence-$id');
  static Key occurrenceStatusKey(String id) =>
      Key('financial-recurrence-occurrence-status-$id');
  static Key occurrenceActualKey(String id) =>
      Key('financial-recurrence-occurrence-actual-$id');
  static Key registerKey(String id) => Key('financial-recurrence-register-$id');
  static Key skipKey(String id) => Key('financial-recurrence-skip-$id');

  @override
  ConsumerState<FinancialRecurrenceScreen> createState() =>
      _FinancialRecurrenceScreenState();
}

class _FinancialRecurrenceScreenState
    extends ConsumerState<FinancialRecurrenceScreen> {
  final _headingFocusNode = FocusNode(
    debugLabel: 'financial-recurrence-heading',
  );

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _headingFocusNode.requestFocus();
      unawaited(
        ref.read(financialRecurrencesControllerProvider.notifier).load(),
      );
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

  String? get _operatorId =>
      ref.read(operatorSessionControllerProvider).principal?.operatorId;

  String _today() {
    final now = ref.read(financialRecurrenceClockProvider)();
    return '${now.year.toString().padLeft(4, '0')}-'
        '${now.month.toString().padLeft(2, '0')}-'
        '${now.day.toString().padLeft(2, '0')}';
  }

  Future<void> _openEditor(
    FinancialRecurrencesState state, {
    FinancialRecurrence? existing,
  }) async {
    final operatorId = _operatorId;
    if (operatorId == null) return;
    final result = await showDialog<FinancialRecurrenceEditorResult>(
      context: context,
      builder: (_) => FinancialRecurrenceEditorDialog(
        accounts: eligibleFinancialRecurrenceAccounts(
          accounts: state.accounts,
          operatorId: operatorId,
        ),
        initialStartDate: _today(),
        existing: existing,
        existingAccountName: existing == null
            ? null
            : state.accountById(existing.accountId)?.name,
      ),
    );
    if (result == null || !mounted) return;
    final controller = ref.read(
      financialRecurrencesControllerProvider.notifier,
    );
    final outcome = switch (result) {
      FinancialRecurrenceEditorCreate(:final input) =>
        await controller.createRecurrence(input),
      FinancialRecurrenceEditorReplace(:final input) =>
        await controller.replaceRecurrence(existing!.id, input),
    };
    if (!mounted) return;
    _announce(_message(outcome));
  }

  Future<void> _register(
    FinancialRecurrencesState state,
    FinancialRecurrenceOccurrence occurrence,
  ) async {
    final input = await showDialog<FinancialRecurrenceRealizeInput>(
      context: context,
      builder: (_) => FinancialRecurrenceRealizeDialog(
        occurrence: occurrence,
        accountName: state.accountById(occurrence.accountId)?.name,
      ),
    );
    if (input == null || !mounted) return;
    final result = await ref
        .read(financialRecurrencesControllerProvider.notifier)
        .realize(occurrence.id, input);
    if (!mounted) return;
    _announce(_message(result));
  }

  Future<void> _skip(FinancialRecurrenceOccurrence occurrence) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Pular esta previsão?'),
        content: Text(
          '${occurrence.description} de '
          '${financialRecurrenceDateLabel(occurrence.scheduledDate)} será '
          'marcada como pulada. Nenhum lançamento é criado e o saldo não muda.',
        ),
        actions: [
          TextButton(
            key: FinancialRecurrenceScreen.skipCancelKey,
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            key: FinancialRecurrenceScreen.skipConfirmKey,
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Pular previsão'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final result = await ref
        .read(financialRecurrencesControllerProvider.notifier)
        .skip(occurrence.id);
    if (!mounted) return;
    _announce(_message(result));
  }

  Future<void> _run(Future<FinancialRecurrenceActionResult> action) async {
    final result = await action;
    if (!mounted) return;
    _announce(_message(result));
  }

  String _message(FinancialRecurrenceActionResult result) {
    const stale =
        ' O que está na tela pode estar desatualizado: use Atualizar antes de continuar.';
    final base = switch (result.outcome) {
      FinancialRecurrenceActionOutcome.created =>
        'Recorrência criada. Nenhuma previsão foi gerada ainda: use Gerar no '
            'mês desejado.',
      FinancialRecurrenceActionOutcome.updated =>
        result.supersededCount == null || result.supersededCount == 0
            ? 'Recorrência atualizada.'
            : 'Recorrência atualizada. ${result.supersededCount} previsão(ões) '
                  'futura(s) foi(ram) substituída(s): gere o mês de novo se '
                  'precisar.',
      FinancialRecurrenceActionOutcome.paused =>
        'Recorrência pausada. Ela não gera novas previsões e o histórico foi '
            'mantido.',
      FinancialRecurrenceActionOutcome.resumed =>
        'Recorrência retomada. Gere o mês para criar previsões.',
      FinancialRecurrenceActionOutcome.generated =>
        result.createdCount == 0
            ? 'As previsões deste mês já existiam. Nada foi criado.'
            : '${result.createdCount} previsão(ões) gerada(s). Previsto não '
                  'altera o saldo.',
      FinancialRecurrenceActionOutcome.skipped =>
        'Previsão pulada. Nenhum lançamento foi criado.',
      FinancialRecurrenceActionOutcome.realized =>
        'Lançamento registrado e ligado à previsão. O saldo da conta foi '
            'atualizado.',
      FinancialRecurrenceActionOutcome.conflict =>
        'O estado mudou desde que você abriu esta tela (versão antiga, '
            'recorrência pausada ou previsão já tratada). Nada foi gravado: '
            'revise o estado atual.',
      FinancialRecurrenceActionOutcome.rejected =>
        'O pedido foi recusado e nada foi gravado.',
      FinancialRecurrenceActionOutcome.readOnly =>
        'Isto é somente leitura para você. Nada foi gravado.',
      FinancialRecurrenceActionOutcome.unknownOutcome =>
        'Não foi possível confirmar o resultado e o pedido não será reenviado '
            'automaticamente. Confira o estado atual.',
      FinancialRecurrenceActionOutcome.notAllowed =>
        'Esta ação não está disponível agora.',
      FinancialRecurrenceActionOutcome.accessBlocked => 'Acesso indisponível.',
    };
    final refreshed = result.reconciled ? ' A tela foi atualizada.' : stale;
    return switch (result.outcome) {
      FinancialRecurrenceActionOutcome.notAllowed ||
      FinancialRecurrenceActionOutcome.accessBlocked => base,
      _ => '$base$refreshed',
    };
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(financialRecurrencesControllerProvider);
    final controller = ref.read(
      financialRecurrencesControllerProvider.notifier,
    );
    final blocked =
        state.phase == FinancialLoadPhase.authenticationRequired ||
        state.phase == FinancialLoadPhase.forbidden ||
        state.phase == FinancialLoadPhase.primaryResidenceRequired;
    final refreshEnabled = !state.isBusy && !blocked;
    final writable =
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
                      'Finanças · Planejamento',
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
                          'Recorrências',
                          key: FinancialRecurrenceScreen.titleKey,
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Text(
                      'Receitas e despesas mensais que você espera. Cada mês '
                      'vira uma previsão só quando você pede; registrar é um '
                      'ato seu.',
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
                    key: FinancialRecurrenceScreen.refreshKey,
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
                    key: FinancialRecurrenceScreen.createKey,
                    onPressed: writable
                        ? () => unawaited(_openEditor(state))
                        : null,
                    icon: const Icon(Icons.add_rounded),
                    label: const Text('Nova recorrência'),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppTokens.space16),
          const _ForecastNotice(),
          const SizedBox(height: AppTokens.space16),
          if (state.refreshFailure != FinancialRefreshFailure.none) ...[
            Card(
              key: FinancialRecurrenceScreen.refreshNoticeKey,
              child: Padding(
                padding: const EdgeInsets.all(AppTokens.space16),
                child: Text(
                  state.refreshFailure ==
                          FinancialRefreshFailure.invalidResponse
                      ? 'O que estava na tela foi preservado porque a nova '
                            'resposta não pôde ser validada.'
                      : 'O que estava na tela foi preservado, mas não foi '
                            'possível atualizar.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (state.isLoaded && !state.trusted) ...[
            const Card(
              key: FinancialRecurrenceScreen.untrustedKey,
              child: Padding(
                padding: EdgeInsets.all(AppTokens.space16),
                child: Text(
                  'O que está na tela pode estar desatualizado. Use Atualizar '
                  'antes de criar, editar ou registrar.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (state.isLoaded && state.conflictNotice) ...[
            Card(
              key: FinancialRecurrenceScreen.conflictKey,
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
                        'Conflito: o estado mudou desde que você abriu esta '
                        'tela (versão antiga, recorrência pausada ou previsão '
                        'já tratada). Sua ação não foi aplicada e nada foi '
                        'reenviado. O que está na tela é o estado atual; faça '
                        'de novo se ainda for necessário.',
                      ),
                    ),
                    TextButton(
                      key: FinancialRecurrenceScreen.conflictDismissKey,
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
            writable: writable,
            onRetry: () => unawaited(controller.refresh()),
            onCreate: writable ? () => unawaited(_openEditor(state)) : null,
            onEdit: (rule) => unawaited(_openEditor(state, existing: rule)),
            onPause: (rule) => unawaited(_run(controller.pause(rule.id))),
            onResume: (rule) => unawaited(_run(controller.resume(rule.id))),
            onGenerate: (rule) =>
                unawaited(_run(controller.generateForShownMonth(rule.id))),
            onRegister: (occurrence) => unawaited(_register(state, occurrence)),
            onSkip: (occurrence) => unawaited(_skip(occurrence)),
            onPrevious: () => unawaited(controller.previousMonth()),
            onNext: () => unawaited(controller.nextMonth()),
          ),
        ],
      ),
    );
  }
}

class _ForecastNotice extends StatelessWidget {
  const _ForecastNotice();

  @override
  Widget build(BuildContext context) {
    return Container(
      key: FinancialRecurrenceScreen.forecastNoticeKey,
      padding: const EdgeInsets.all(AppTokens.space12),
      decoration: BoxDecoration(
        color: AppTokens.blue50,
        border: Border.all(color: AppTokens.blue700),
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline_rounded, color: AppTokens.blue700),
          SizedBox(width: AppTokens.space12),
          Expanded(child: Text(financialRecurrenceForecastNotice)),
        ],
      ),
    );
  }
}

class _Content extends StatelessWidget {
  const _Content({
    required this.state,
    required this.writable,
    required this.onRetry,
    required this.onCreate,
    required this.onEdit,
    required this.onPause,
    required this.onResume,
    required this.onGenerate,
    required this.onRegister,
    required this.onSkip,
    required this.onPrevious,
    required this.onNext,
  });

  final FinancialRecurrencesState state;
  final bool writable;
  final VoidCallback onRetry;
  final VoidCallback? onCreate;
  final ValueChanged<FinancialRecurrence> onEdit;
  final ValueChanged<FinancialRecurrence> onPause;
  final ValueChanged<FinancialRecurrence> onResume;
  final ValueChanged<FinancialRecurrence> onGenerate;
  final ValueChanged<FinancialRecurrenceOccurrence> onRegister;
  final ValueChanged<FinancialRecurrenceOccurrence> onSkip;
  final VoidCallback onPrevious;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    if (state.phase == FinancialLoadPhase.idle ||
        state.phase == FinancialLoadPhase.loading) {
      return const KeyedSubtree(
        key: FinancialRecurrenceScreen.loadingKey,
        child: AppStatePanel(
          kind: AppStateKind.loading,
          title: 'Carregando recorrências…',
          description: 'Buscando as regras e as previsões do mês.',
        ),
      );
    }
    if (!state.isLoaded) {
      return _PhasePanel(phase: state.phase, onRetry: onRetry);
    }
    if (state.recurrences.isEmpty) {
      return Column(
        key: FinancialRecurrenceScreen.emptyKey,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const AppStatePanel(
            kind: AppStateKind.empty,
            title: 'Nenhuma recorrência',
            description:
                'Crie uma recorrência mensal, como aluguel ou internet, para '
                'ver as previsões de cada mês sem lançar nada ainda.',
          ),
          const SizedBox(height: AppTokens.space12),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.icon(
              key: FinancialRecurrenceScreen.createEmptyKey,
              onPressed: onCreate,
              icon: const Icon(Icons.add_rounded),
              label: const Text('Criar a primeira recorrência'),
            ),
          ),
        ],
      );
    }
    final active = state.recurrences.where((rule) => !rule.isPaused).toList();
    final paused = state.recurrences.where((rule) => rule.isPaused).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _RuleSection(
          sectionKey: FinancialRecurrenceScreen.activeSectionKey,
          title: 'Ativas (${active.length})',
          rules: active,
          state: state,
          writable: writable,
          onEdit: onEdit,
          onPause: onPause,
          onResume: onResume,
          onGenerate: onGenerate,
        ),
        if (paused.isNotEmpty) ...[
          const SizedBox(height: AppTokens.space16),
          _RuleSection(
            sectionKey: FinancialRecurrenceScreen.pausedSectionKey,
            title: 'Pausadas (${paused.length})',
            rules: paused,
            state: state,
            writable: writable,
            onEdit: onEdit,
            onPause: onPause,
            onResume: onResume,
            onGenerate: onGenerate,
          ),
        ],
        const SizedBox(height: AppTokens.space24),
        _OccurrencesSection(
          state: state,
          writable: writable,
          onRegister: onRegister,
          onSkip: onSkip,
          onPrevious: onPrevious,
          onNext: onNext,
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
        'Entre novamente para ver as recorrências.',
        false,
      ),
      FinancialLoadPhase.forbidden => (
        'Acesso indisponível',
        'Você não tem acesso às recorrências desta residência.',
        false,
      ),
      FinancialLoadPhase.primaryResidenceRequired => (
        'Residência principal necessária',
        'Defina uma residência principal para ver as recorrências.',
        false,
      ),
      FinancialLoadPhase.invalidResponse => (
        'Resposta inválida',
        'A resposta do servidor não pôde ser validada e nada foi exibido.',
        true,
      ),
      _ => (
        'Recorrências indisponíveis',
        'Não foi possível carregar as recorrências agora.',
        true,
      ),
    };
    return Column(
      key: FinancialRecurrenceScreen.errorKey,
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
              key: FinancialRecurrenceScreen.retryKey,
              onPressed: onRetry,
              child: const Text('Tentar novamente'),
            ),
          ),
        ],
      ],
    );
  }
}

class _RuleSection extends StatelessWidget {
  const _RuleSection({
    required this.sectionKey,
    required this.title,
    required this.rules,
    required this.state,
    required this.writable,
    required this.onEdit,
    required this.onPause,
    required this.onResume,
    required this.onGenerate,
  });

  final Key sectionKey;
  final String title;
  final List<FinancialRecurrence> rules;
  final FinancialRecurrencesState state;
  final bool writable;
  final ValueChanged<FinancialRecurrence> onEdit;
  final ValueChanged<FinancialRecurrence> onPause;
  final ValueChanged<FinancialRecurrence> onResume;
  final ValueChanged<FinancialRecurrence> onGenerate;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: sectionKey,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          header: true,
          child: Text(title, style: Theme.of(context).textTheme.titleLarge),
        ),
        const SizedBox(height: AppTokens.space8),
        if (rules.isEmpty)
          const Text('Nenhuma.')
        else
          for (final rule in rules) ...[
            _RuleCard(
              rule: rule,
              accountName: state.accountById(rule.accountId)?.name,
              period: state.period,
              writable: writable,
              onEdit: () => onEdit(rule),
              onPause: () => onPause(rule),
              onResume: () => onResume(rule),
              onGenerate: () => onGenerate(rule),
            ),
            const SizedBox(height: AppTokens.space12),
          ],
      ],
    );
  }
}

class _RuleCard extends StatelessWidget {
  const _RuleCard({
    required this.rule,
    required this.accountName,
    required this.period,
    required this.writable,
    required this.onEdit,
    required this.onPause,
    required this.onResume,
    required this.onGenerate,
  });

  final FinancialRecurrence rule;
  final String? accountName;
  final String period;
  final bool writable;
  final VoidCallback onEdit;
  final VoidCallback onPause;
  final VoidCallback onResume;
  final VoidCallback onGenerate;

  @override
  Widget build(BuildContext context) {
    final canAct = writable && rule.canEdit;
    return Card(
      key: FinancialRecurrenceScreen.ruleKey(rule.id),
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
                  rule.description,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                AppBadge(
                  label: financialRecurrenceEffectLabel(rule.resultEffect),
                  tone: rule.resultEffect == FinancialResultEffect.income
                      ? AppBadgeTone.positive
                      : AppBadgeTone.neutral,
                ),
                AppBadge(
                  key: FinancialRecurrenceScreen.ruleStatusKey(rule.id),
                  label: financialRecurrenceStatusLabel(rule.status),
                  tone: rule.isPaused
                      ? AppBadgeTone.warning
                      : AppBadgeTone.info,
                ),
                if (!rule.canEdit)
                  AppBadge(
                    key: FinancialRecurrenceScreen.readOnlyKey(rule.id),
                    label: 'Somente leitura',
                    tone: AppBadgeTone.warning,
                  ),
              ],
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              'Esperado ${formatFinancialMoney(rule.expected)} · '
              '${financialRecurrenceScheduleLabel(rule.dayOfMonth)}',
            ),
            Text(
              'Desde ${financialRecurrenceDateLabel(rule.startDate)}'
              '${rule.endDate == null ? '' : ' até ${financialRecurrenceDateLabel(rule.endDate!)}'}'
              '${accountName == null ? '' : ' · $accountName'}',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
            ),
            if (rule.isPaused)
              Padding(
                padding: const EdgeInsets.only(top: AppTokens.space4),
                child: Text(
                  'Pausada: não gera novas previsões. O histórico foi mantido.',
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: AppTokens.amber700),
                ),
              ),
            if (!rule.canEdit)
              Padding(
                padding: const EdgeInsets.only(top: AppTokens.space4),
                child: Text(
                  'Você pode ver esta recorrência, mas só quem é dono da conta '
                  'pode alterá-la.',
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
                ),
              ),
            if (rule.canEdit) ...[
              const SizedBox(height: AppTokens.space12),
              Wrap(
                spacing: AppTokens.space8,
                runSpacing: AppTokens.space8,
                children: [
                  OutlinedButton.icon(
                    key: FinancialRecurrenceScreen.editKey(rule.id),
                    onPressed: canAct ? onEdit : null,
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('Editar'),
                  ),
                  if (rule.isPaused)
                    OutlinedButton.icon(
                      key: FinancialRecurrenceScreen.resumeKey(rule.id),
                      onPressed: canAct ? onResume : null,
                      icon: const Icon(Icons.play_arrow_rounded),
                      label: const Text('Retomar'),
                    )
                  else ...[
                    OutlinedButton.icon(
                      key: FinancialRecurrenceScreen.generateKey(rule.id),
                      onPressed: canAct ? onGenerate : null,
                      icon: const Icon(Icons.event_available_outlined),
                      label: Text(
                        'Gerar ${financialBudgetPeriodLabel(period)}',
                      ),
                    ),
                    OutlinedButton.icon(
                      key: FinancialRecurrenceScreen.pauseKey(rule.id),
                      onPressed: canAct ? onPause : null,
                      icon: const Icon(Icons.pause_rounded),
                      label: const Text('Pausar'),
                    ),
                  ],
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _OccurrencesSection extends StatelessWidget {
  const _OccurrencesSection({
    required this.state,
    required this.writable,
    required this.onRegister,
    required this.onSkip,
    required this.onPrevious,
    required this.onNext,
  });

  final FinancialRecurrencesState state;
  final bool writable;
  final ValueChanged<FinancialRecurrenceOccurrence> onRegister;
  final ValueChanged<FinancialRecurrenceOccurrence> onSkip;
  final VoidCallback onPrevious;
  final VoidCallback onNext;

  @override
  Widget build(BuildContext context) {
    final navigationEnabled = !state.isBusy;
    return Column(
      key: FinancialRecurrenceScreen.occurrencesKey,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          header: true,
          child: Text(
            'Previsões e registros',
            style: Theme.of(context).textTheme.titleLarge,
          ),
        ),
        const SizedBox(height: AppTokens.space8),
        Card(
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppTokens.space8,
              vertical: AppTokens.space8,
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                IconButton(
                  key: FinancialRecurrenceScreen.previousMonthKey,
                  tooltip: 'Mês anterior',
                  onPressed: navigationEnabled ? onPrevious : null,
                  icon: const Icon(Icons.chevron_left_rounded),
                ),
                Semantics(
                  liveRegion: true,
                  child: Text(
                    financialBudgetPeriodLabel(state.period),
                    key: FinancialRecurrenceScreen.monthLabelKey,
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
                IconButton(
                  key: FinancialRecurrenceScreen.nextMonthKey,
                  tooltip: 'Próximo mês',
                  onPressed: navigationEnabled ? onNext : null,
                  icon: const Icon(Icons.chevron_right_rounded),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: AppTokens.space12),
        if (state.occurrences.isEmpty)
          const AppStatePanel(
            key: FinancialRecurrenceScreen.occurrencesEmptyKey,
            kind: AppStateKind.empty,
            title: 'Nenhuma previsão neste mês',
            description:
                'Use Gerar em uma recorrência ativa para criar a previsão do '
                'mês. Nada é gerado sozinho.',
            compact: true,
          )
        else
          for (final occurrence in state.occurrences) ...[
            _OccurrenceTile(
              occurrence: occurrence,
              accountName: state.accountById(occurrence.accountId)?.name,
              writable: writable,
              onRegister: () => onRegister(occurrence),
              onSkip: () => onSkip(occurrence),
            ),
            const SizedBox(height: AppTokens.space12),
          ],
      ],
    );
  }
}

class _OccurrenceTile extends StatelessWidget {
  const _OccurrenceTile({
    required this.occurrence,
    required this.accountName,
    required this.writable,
    required this.onRegister,
    required this.onSkip,
  });

  final FinancialRecurrenceOccurrence occurrence;
  final String? accountName;
  final bool writable;
  final VoidCallback onRegister;
  final VoidCallback onSkip;

  @override
  Widget build(BuildContext context) {
    final pending = occurrence.status == FinancialOccurrenceStatus.pending;
    final link = occurrence.realization;
    final canAct = writable && occurrence.canEdit && pending;
    final tone = switch (occurrence.status) {
      FinancialOccurrenceStatus.pending => AppBadgeTone.info,
      FinancialOccurrenceStatus.realized => AppBadgeTone.positive,
      FinancialOccurrenceStatus.skipped => AppBadgeTone.neutral,
      FinancialOccurrenceStatus.superseded => AppBadgeTone.neutral,
    };
    return Card(
      key: FinancialRecurrenceScreen.occurrenceKey(occurrence.id),
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
                  '${financialRecurrenceDateLabel(occurrence.scheduledDate)} · '
                  '${occurrence.description}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                AppBadge(
                  key: FinancialRecurrenceScreen.occurrenceStatusKey(
                    occurrence.id,
                  ),
                  label: financialOccurrenceStatusLabel(occurrence.status),
                  tone: tone,
                ),
                AppBadge(
                  label: financialRecurrenceEffectLabel(
                    occurrence.resultEffect,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              'Previsto ${formatFinancialMoney(occurrence.expected)}'
              '${accountName == null ? '' : ' · $accountName'}',
            ),
            if (link != null)
              Padding(
                key: FinancialRecurrenceScreen.occurrenceActualKey(
                  occurrence.id,
                ),
                padding: const EdgeInsets.only(top: AppTokens.space4),
                child: Text(
                  'Real ${formatFinancialMoney(link.actual)} · efetivo em '
                  '${financialRecurrenceDateLabel(link.effectiveDate)} · '
                  'competência ${financialRecurrenceDateLabel(link.competenceDate)} · '
                  '${financialOccurrenceMovementStateLabel(link.movementState)}',
                ),
              ),
            const SizedBox(height: AppTokens.space4),
            Text(
              financialOccurrenceStatusHint(occurrence.status),
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
            ),
            if (pending && occurrence.canEdit) ...[
              const SizedBox(height: AppTokens.space12),
              Wrap(
                spacing: AppTokens.space8,
                runSpacing: AppTokens.space8,
                children: [
                  FilledButton.icon(
                    key: FinancialRecurrenceScreen.registerKey(occurrence.id),
                    onPressed: canAct ? onRegister : null,
                    icon: const Icon(Icons.check_circle_outline_rounded),
                    label: const Text('Registrar'),
                  ),
                  OutlinedButton.icon(
                    key: FinancialRecurrenceScreen.skipKey(occurrence.id),
                    onPressed: canAct ? onSkip : null,
                    icon: const Icon(Icons.skip_next_rounded),
                    label: const Text('Pular'),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
