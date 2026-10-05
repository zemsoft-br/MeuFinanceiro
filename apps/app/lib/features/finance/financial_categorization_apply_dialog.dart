import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/features/finance/financial_categorization_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Preview → explicit confirmation → real backend summary, for one account.
///
/// The preview is read-only and never a promise. Confirming sends exactly the
/// previewed Movement/rule pairs once; the summary shown afterwards is the
/// backend response, and anything short of "all requested classified" is
/// presented as a partial result. A failed or unknown write is never retried.
class FinancialCategorizationApplyDialog extends ConsumerStatefulWidget {
  const FinancialCategorizationApplyDialog({
    required this.account,
    required this.movements,
    required this.categoryIndex,
    super.key,
  });

  final FinancialAccount account;
  final Map<String, FinancialMovement> movements;
  final FinancialCategoryIndex categoryIndex;

  static const dialogKey = Key('financial-categorization-apply-dialog');
  static const loadingKey = Key('financial-categorization-apply-loading');
  static const confirmKey = Key('financial-categorization-apply-confirm');
  static const refreshKey = Key('financial-categorization-apply-refresh');
  static const closeKey = Key('financial-categorization-apply-close');
  static const headlineKey = Key('financial-categorization-apply-headline');
  static const partialNoticeKey = Key('financial-categorization-apply-partial');
  static const unknownNoticeKey = Key('financial-categorization-apply-unknown');
  static const failureNoticeKey = Key('financial-categorization-apply-failure');
  static const truncatedNoticeKey = Key(
    'financial-categorization-apply-truncated',
  );
  static const emptyNoticeKey = Key('financial-categorization-apply-empty');

  static Key previewCountKey(String name) =>
      Key('financial-categorization-preview-count-$name');
  static Key resultCountKey(String name) =>
      Key('financial-categorization-result-count-$name');
  static Key candidateKey(String movementId) =>
      Key('financial-categorization-candidate-$movementId');
  static Key ambiguousKey(String movementId) =>
      Key('financial-categorization-ambiguous-$movementId');

  @override
  ConsumerState<FinancialCategorizationApplyDialog> createState() =>
      _FinancialCategorizationApplyDialogState();
}

class _FinancialCategorizationApplyDialogState
    extends ConsumerState<FinancialCategorizationApplyDialog> {
  @override
  void initState() {
    super.initState();
    // Opening the dialog is the explicit operator action; the preview itself is
    // read-only.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      unawaited(
        ref
            .read(
              financialCategorizationApplyControllerProvider(
                widget.account.accountId,
              ).notifier,
            )
            .preview(),
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final provider = financialCategorizationApplyControllerProvider(
      widget.account.accountId,
    );
    ref.listen<FinancialCategorizationApplyState>(provider, (previous, next) {
      final reachedServer =
          next.phase == FinancialCategorizationApplyPhase.applied ||
          next.phase == FinancialCategorizationApplyPhase.unknownOutcome;
      final wasWaiting =
          previous?.phase == FinancialCategorizationApplyPhase.applying;
      if (reachedServer && wasWaiting) {
        // Bulk refresh of the canonical classification (and provenance) after
        // the write attempt: one statement/allocation/origin read, no per-row
        // requests, and no assumption about what was persisted.
        unawaited(
          ref
              .read(
                financialAccountDetailControllerProvider(
                  widget.account.accountId,
                ).notifier,
              )
              .refresh(),
        );
      }
    });
    final state = ref.watch(provider);
    final controller = ref.read(provider.notifier);

    return AlertDialog(
      key: FinancialCategorizationApplyDialog.dialogKey,
      title: const Text('Aplicar regras de categorização'),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'A pré-visualização é somente leitura. Nada é gravado até você '
                'confirmar, e lançamentos já classificados nunca são alterados '
                'por regras.',
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
              ),
              const SizedBox(height: AppTokens.space16),
              ..._body(context, state),
            ],
          ),
        ),
      ),
      actions: _actions(context, state, controller),
    );
  }

  List<Widget> _body(
    BuildContext context,
    FinancialCategorizationApplyState state,
  ) {
    switch (state.phase) {
      case FinancialCategorizationApplyPhase.idle:
      case FinancialCategorizationApplyPhase.previewing:
        return const [_Progress('Avaliando lançamentos…')];
      case FinancialCategorizationApplyPhase.applying:
        return const [_Progress('Aplicando classificações…')];
      case FinancialCategorizationApplyPhase.previewed:
        return _previewBody(context, state.preview!);
      case FinancialCategorizationApplyPhase.applied:
        return _appliedBody(context, state.outcome!);
      case FinancialCategorizationApplyPhase.unknownOutcome:
        return [
          _Notice(
            key: FinancialCategorizationApplyDialog.unknownNoticeKey,
            icon: Icons.help_outline_rounded,
            message:
                'Não foi possível confirmar o resultado. Nada foi reenviado '
                'automaticamente e as classificações foram recarregadas. Faça '
                'uma nova pré-visualização para ver o que ainda falta.',
          ),
        ];
      case FinancialCategorizationApplyPhase.failed:
        return [
          _Notice(
            key: FinancialCategorizationApplyDialog.failureNoticeKey,
            icon: Icons.error_outline_rounded,
            message: switch (state.failure) {
              FinancialCategorizationApplyFailure.notFound =>
                'A conta não está disponível para aplicar regras.',
              FinancialCategorizationApplyFailure.accessBlocked =>
                'Sua sessão não permite aplicar regras agora.',
              FinancialCategorizationApplyFailure.rejected =>
                'O pedido foi recusado. Nada foi alterado.',
              FinancialCategorizationApplyFailure.invalidResponse =>
                'A resposta não pôde ser validada com segurança.',
              _ => 'Serviço temporariamente indisponível. Nada foi alterado.',
            },
          ),
        ];
    }
  }

  List<Widget> _previewBody(
    BuildContext context,
    FinancialCategorizationPreview preview,
  ) {
    final counts = preview.counts;
    // Only what a confirmation would actually send is listed.
    final candidates = preview
        .itemsWithStatus(FinancialCategorizationPreviewStatus.matched)
        .take(financialCategorizationMaxApplyItems)
        .toList(growable: false);
    final ambiguous = preview.itemsWithStatus(
      FinancialCategorizationPreviewStatus.ambiguous,
    );
    return [
      _CountRow(
        key: FinancialCategorizationApplyDialog.previewCountKey('matched'),
        label: 'Serão classificados por uma regra',
        value: counts.matched,
        emphasize: counts.matched > 0,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.previewCountKey('ambiguous'),
        label: 'Ambíguos (empate de prioridade) — não serão classificados',
        value: counts.ambiguous,
        emphasize: counts.ambiguous > 0,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.previewCountKey(
          'alreadyClassified',
        ),
        label: 'Já classificados — não serão alterados',
        value: counts.alreadyClassified,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.previewCountKey('noMatch'),
        label: 'Sem regra correspondente',
        value: counts.noMatch,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.previewCountKey('ineligible'),
        label: 'Não aplicável (transferências e reversões)',
        value: counts.ineligible,
      ),
      const SizedBox(height: AppTokens.space12),
      if (counts.matched == 0)
        const _Notice(
          key: FinancialCategorizationApplyDialog.emptyNoticeKey,
          icon: Icons.info_outline_rounded,
          message: 'Nenhum lançamento seria classificado por regras agora.',
        ),
      if (preview.applicableTruncated)
        const _Notice(
          key: FinancialCategorizationApplyDialog.truncatedNoticeKey,
          icon: Icons.info_outline_rounded,
          message:
              'Há mais lançamentos do que podem ser aplicados de uma vez. Aplique '
              'os listados e faça uma nova pré-visualização para os demais.',
        ),
      for (final item in candidates)
        Padding(
          padding: const EdgeInsets.only(top: AppTokens.space8),
          child: Text(
            '${_movementLabel(item.movementId)} → '
            '${_categoryLabel(item.targetCategoryId)}',
            key: FinancialCategorizationApplyDialog.candidateKey(
              item.movementId,
            ),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      for (final item in ambiguous)
        Padding(
          padding: const EdgeInsets.only(top: AppTokens.space8),
          child: Text(
            '${_movementLabel(item.movementId)} — mais de uma regra com a '
            'mesma prioridade; nada será aplicado',
            key: FinancialCategorizationApplyDialog.ambiguousKey(
              item.movementId,
            ),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
    ];
  }

  List<Widget> _appliedBody(
    BuildContext context,
    FinancialCategorizationApplyOutcome outcome,
  ) {
    final counts = outcome.counts;
    final full = outcome.isFullSuccess;
    return [
      Text(
        full
            ? 'Concluído: ${counts.classified} de ${outcome.requested} '
                  'lançamentos classificados.'
            : 'Resultado parcial: ${counts.classified} de ${outcome.requested} '
                  'lançamentos classificados.',
        key: FinancialCategorizationApplyDialog.headlineKey,
        style: Theme.of(context).textTheme.titleMedium,
      ),
      const SizedBox(height: AppTokens.space12),
      _CountRow(
        key: FinancialCategorizationApplyDialog.resultCountKey('classified'),
        label: 'Classificados',
        value: counts.classified,
        emphasize: counts.classified > 0,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.resultCountKey(
          'alreadyClassified',
        ),
        label: 'Já classificados (não alterados)',
        value: counts.alreadyClassified,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.resultCountKey('ambiguous'),
        label: 'Ambíguos (nada aplicado)',
        value: counts.ambiguous,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.resultCountKey('noMatch'),
        label: 'Sem regra correspondente agora',
        value: counts.noMatch,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.resultCountKey('ineligible'),
        label: 'Não aplicáveis',
        value: counts.ineligible,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.resultCountKey('conflict'),
        label: 'Em conflito — o estado mudou, nada foi alterado',
        value: counts.conflict,
        emphasize: counts.conflict > 0,
      ),
      _CountRow(
        key: FinancialCategorizationApplyDialog.resultCountKey('failed'),
        label: 'Falharam — nada foi confirmado para estes lançamentos',
        value: counts.failed,
        emphasize: counts.failed > 0,
      ),
      if (!full) ...[
        const SizedBox(height: AppTokens.space12),
        const _Notice(
          key: FinancialCategorizationApplyDialog.partialNoticeKey,
          icon: Icons.warning_amber_rounded,
          message:
              'Nem todos os lançamentos foram classificados. Faça uma nova '
              'pré-visualização para ver o que ainda falta.',
        ),
      ],
    ];
  }

  List<Widget> _actions(
    BuildContext context,
    FinancialCategorizationApplyState state,
    FinancialCategorizationApplyController controller,
  ) {
    final busy = state.isBusy;
    final close = TextButton(
      key: FinancialCategorizationApplyDialog.closeKey,
      onPressed: busy ? null : () => Navigator.of(context).pop(),
      child: const Text('Fechar'),
    );
    final repreview = OutlinedButton(
      key: FinancialCategorizationApplyDialog.refreshKey,
      onPressed: busy ? null : () => unawaited(controller.preview()),
      child: Text(
        state.phase == FinancialCategorizationApplyPhase.previewed
            ? 'Atualizar pré-visualização'
            : 'Nova pré-visualização',
      ),
    );
    final matched = state.preview?.applicableItems.length ?? 0;
    return [
      close,
      if (state.phase != FinancialCategorizationApplyPhase.idle &&
          state.phase != FinancialCategorizationApplyPhase.previewing)
        repreview,
      if (state.phase == FinancialCategorizationApplyPhase.previewed ||
          state.phase == FinancialCategorizationApplyPhase.applying)
        FilledButton(
          key: FinancialCategorizationApplyDialog.confirmKey,
          onPressed: state.canApply
              ? () => unawaited(controller.apply())
              : null,
          child: Text(
            matched == 1
                ? 'Confirmar e aplicar 1 classificação'
                : 'Confirmar e aplicar $matched classificações',
          ),
        ),
    ];
  }

  String _movementLabel(String movementId) {
    final movement = widget.movements[movementId];
    if (movement == null) return 'Lançamento';
    final description = movement.description ?? 'Movimentação';
    return '$description (${formatFinancialMoney(movement.money)})';
  }

  String _categoryLabel(String? categoryId) =>
      (categoryId == null
          ? null
          : widget.categoryIndex.pathLabel(categoryId)) ??
      'Categoria indisponível';
}

class _Progress extends StatelessWidget {
  const _Progress(this.message);
  final String message;

  @override
  Widget build(BuildContext context) {
    return Row(
      key: FinancialCategorizationApplyDialog.loadingKey,
      children: [
        const SizedBox.square(
          dimension: 20,
          child: CircularProgressIndicator(strokeWidth: 2.5),
        ),
        const SizedBox(width: AppTokens.space12),
        Expanded(child: Text(message)),
      ],
    );
  }
}

class _CountRow extends StatelessWidget {
  const _CountRow({
    required this.label,
    required this.value,
    this.emphasize = false,
    super.key,
  });

  final String label;
  final int value;
  final bool emphasize;

  @override
  Widget build(BuildContext context) {
    final style = emphasize
        ? Theme.of(context).textTheme.titleSmall
        : Theme.of(context).textTheme.bodyMedium;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppTokens.space4),
      child: Row(
        children: [
          Expanded(child: Text(label, style: style)),
          const SizedBox(width: AppTokens.space12),
          Text('$value', style: style),
        ],
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({required this.icon, required this.message, super.key});

  final IconData icon;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppTokens.space8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20),
          const SizedBox(width: AppTokens.space12),
          Expanded(child: Text(message)),
        ],
      ),
    );
  }
}
