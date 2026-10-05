import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/features/finance/financial_operation_date_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_transfer_reversal_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';
import 'package:meufinanceiro_app/features/finance/financial_registration_time_format.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

final financialOperationClockProvider = Provider<DateTime Function()>(
  (ref) => DateTime.now,
);

class FinancialAccountDetailScreen extends ConsumerStatefulWidget {
  const FinancialAccountDetailScreen({required this.accountId, super.key});

  final String accountId;

  static const titleKey = Key('financial-account-detail-title');
  static const refreshButtonKey = Key('financial-account-detail-refresh');
  static const openingBalanceKey = Key(
    'financial-account-detail-opening-balance',
  );
  static const balanceKey = Key('financial-account-detail-balance');
  static const actionsKey = Key('financial-account-detail-actions');
  static const statementKey = Key('financial-account-detail-statement');
  static const movementsKey = statementKey;
  static const createOpeningButtonKey = Key(
    'financial-account-detail-create-opening',
  );
  static const incomeButtonKey = Key('financial-account-detail-income');
  static const expenseButtonKey = Key('financial-account-detail-expense');
  static const transferButtonKey = Key('financial-account-detail-transfer');
  static const untrustedNoticeKey = Key(
    'financial-account-detail-classification-untrusted',
  );
  static const unknownCategoryNoticeKey = Key(
    'financial-account-detail-category-unknown',
  );

  @override
  ConsumerState<FinancialAccountDetailScreen> createState() =>
      _FinancialAccountDetailScreenState();
}

class _FinancialAccountDetailScreenState
    extends ConsumerState<FinancialAccountDetailScreen> {
  final _headingFocusNode = FocusNode(
    debugLabel: 'financial-account-detail-heading',
  );

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _headingFocusNode.requestFocus();
      unawaited(
        ref
            .read(
              financialAccountDetailControllerProvider(
                widget.accountId,
              ).notifier,
            )
            .load(),
      );
    });
  }

  @override
  void dispose() {
    _headingFocusNode.dispose();
    super.dispose();
  }

  Future<void> _createOpeningBalance(FinancialAccount account) async {
    final result = await showDialog<FinancialOpeningBalanceCreateInput>(
      context: context,
      builder: (context) => _OpeningBalanceDialog(account: account),
    );
    if (result == null || !mounted) return;
    final created = await ref
        .read(
          financialAccountDetailControllerProvider(widget.accountId).notifier,
        )
        .createOpeningBalance(result);
    if (!mounted) return;
    final message = created
        ? 'Saldo inicial cadastrado.'
        : 'O detalhe foi atualizado com o estado persistido.';
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _createManualEntry(
    FinancialAccount account,
    FinancialManualEntryKind kind,
    String initialDate,
  ) async {
    final result = await showDialog<FinancialManualEntryCreateInput>(
      context: context,
      builder: (context) => _ManualEntryDialog(
        account: account,
        kind: kind,
        initialDate: initialDate,
      ),
    );
    if (result == null || !mounted) return;
    final created = await ref
        .read(
          financialAccountDetailControllerProvider(widget.accountId).notifier,
        )
        .createManualEntry(kind, result);
    if (!mounted) return;
    final label = kind == FinancialManualEntryKind.income
        ? 'Receita'
        : 'Despesa';
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          created
              ? '$label registrada.'
              : 'Não foi possível registrar $label. Verifique os dados e tente novamente.',
        ),
      ),
    );
  }

  Future<void> _createTransfer(
    FinancialAccount account,
    List<FinancialAccount> destinations,
    String initialDate,
  ) async {
    final result = await showDialog<FinancialTransferCreateInput>(
      context: context,
      builder: (context) => _TransferDialog(
        account: account,
        destinations: destinations,
        initialDate: initialDate,
      ),
    );
    if (result == null || !mounted) return;
    final created = await ref
        .read(
          financialAccountDetailControllerProvider(widget.accountId).notifier,
        )
        .createTransfer(result);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          created
              ? 'Transferência registrada.'
              : 'Não foi possível registrar a transferência.',
        ),
      ),
    );
  }

  Future<void> _classifyMovement(
    FinancialAccount account,
    FinancialMovement movement,
    String? operatorId,
  ) async {
    final categoryId = await showDialog<String>(
      context: context,
      builder: (context) => _ClassifyMovementDialog(
        accountId: widget.accountId,
        account: account,
        movement: movement,
        operatorId: operatorId,
      ),
    );
    if (categoryId == null || !mounted) return;
    final outcome = await ref
        .read(
          financialAccountDetailControllerProvider(widget.accountId).notifier,
        )
        .classifyMovement(
          movementId: movement.movementId,
          categoryId: categoryId,
        );
    if (!mounted) return;
    final trusted = ref
        .read(financialAccountDetailControllerProvider(widget.accountId))
        .classificationTrusted;
    final message = !trusted
        ? 'Não foi possível confirmar o estado das classificações. '
              'Use Atualizar antes de classificar novamente.'
        : switch (outcome) {
            FinancialMutationOutcome.success => 'Lançamento classificado.',
            FinancialMutationOutcome.conflictReconciled =>
              'O lançamento foi atualizado com a classificação persistida. '
                  'Nada foi aplicado; revise e tente novamente se desejar.',
            FinancialMutationOutcome.rejected =>
              'A classificação não foi aceita. Atualize a tela e confira a categoria.',
            FinancialMutationOutcome.temporarilyUnavailable =>
              'Não foi possível classificar agora. Tente novamente.',
            FinancialMutationOutcome.invalidResponse =>
              'Não foi possível validar a resposta. Atualize o detalhe antes de tentar novamente.',
            FinancialMutationOutcome.accessBlocked =>
              'O acesso necessário para classificar não está disponível.',
            FinancialMutationOutcome.notAllowed =>
              'Este lançamento não pode ser classificado agora.',
            FinancialMutationOutcome.unknownOutcomeReconciled =>
              'O estado das classificações foi reconciliado com o persistido. '
                  'Confira o lançamento antes de classificar novamente.',
          };
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _reverseMovement(
    FinancialMovement movement,
    String initialDate,
  ) async {
    final result = await showDialog<FinancialMovementReversalInput>(
      context: context,
      builder: (context) =>
          _MovementReversalDialog(movement: movement, initialDate: initialDate),
    );
    if (result == null || !mounted) return;
    final reversed = await ref
        .read(
          financialAccountDetailControllerProvider(widget.accountId).notifier,
        )
        .reverseMovement(movement.movementId, result);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          reversed
              ? 'Lançamento revertido.'
              : 'Não foi possível reverter o lançamento.',
        ),
      ),
    );
  }

  Future<void> _reverseTransfer(
    FinancialTransfer transfer,
    FinancialMovement movement,
    String initialDate,
  ) async {
    final result = await showDialog<FinancialTransferReversalInput>(
      context: context,
      builder: (context) =>
          _TransferReversalDialog(movement: movement, initialDate: initialDate),
    );
    if (result == null || !mounted) return;
    final reversed = await ref
        .read(
          financialAccountDetailControllerProvider(widget.accountId).notifier,
        )
        .reverseTransfer(transfer.transferId, result);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          reversed
              ? 'Transferência revertida.'
              : 'Não foi possível reverter a transferência.',
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provider = financialAccountDetailControllerProvider(widget.accountId);
    final state = ref.watch(provider);
    final account = state.account;
    final operatorId = ref.watch(
      operatorSessionControllerProvider.select(
        (session) => session.principal?.operatorId,
      ),
    );
    final initialOperationDate = financialOperationInitialDate(
      now: ref.watch(financialOperationClockProvider)(),
      openingBalanceDate: state.openingBalance?.effectiveDate,
      movementEffectiveDates: state.movements.map(
        (movement) => movement.effectiveDate,
      ),
    );
    final transferDestinations = account == null
        ? const <FinancialAccount>[]
        : state.accounts
              .where(
                (candidate) =>
                    candidate.accountId != account.accountId &&
                    candidate.status == FinancialAccountStatus.active &&
                    candidate.currency == account.currency,
              )
              .toList(growable: false);
    final refreshEnabled =
        !state.isBusy &&
        state.phase != FinancialLoadPhase.authenticationRequired &&
        state.phase != FinancialLoadPhase.forbidden &&
        state.phase != FinancialLoadPhase.primaryResidenceRequired;

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
                      'Finanças · Conta',
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
                          account?.name ?? 'Detalhes da conta',
                          key: FinancialAccountDetailScreen.titleKey,
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Text(
                      'Saldo corrente e extrato são derivados do saldo inicial e do ledger canônico de Movements.',
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                        color: AppTokens.neutral700,
                      ),
                    ),
                  ],
                ),
              ),
              OutlinedButton.icon(
                key: FinancialAccountDetailScreen.refreshButtonKey,
                onPressed: refreshEnabled
                    ? () => unawaited(ref.read(provider.notifier).refresh())
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
          if (state.refreshFailure != FinancialRefreshFailure.none) ...[
            _RefreshNotice(failure: state.refreshFailure),
            const SizedBox(height: AppTokens.space16),
          ],
          if (account != null && !state.classificationTrusted) ...[
            const _StateNotice(
              noticeKey: FinancialAccountDetailScreen.untrustedNoticeKey,
              message:
                  'As classificações exibidas podem estar desatualizadas. '
                  'Use Atualizar para voltar a classificar lançamentos.',
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (account != null && state.categoryCreationUnknown) ...[
            const _StateNotice(
              noticeKey: FinancialAccountDetailScreen.unknownCategoryNoticeKey,
              message:
                  'O resultado da última criação de categoria é desconhecido. '
                  'Use Atualizar antes de criar outra categoria.',
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (account == null)
            _FailureOrLoading(
              phase: state.phase,
              onRetry: () => unawaited(ref.read(provider.notifier).refresh()),
            )
          else ...[
            _AccountIdentityCard(account: account),
            if (state.balance != null) ...[
              const SizedBox(height: AppTokens.space16),
              _BalanceCard(balance: state.balance!),
            ],
            const SizedBox(height: AppTokens.space16),
            _FinanceActionsCard(
              account: account,
              destinations: transferDestinations,
              enabled:
                  account.status == FinancialAccountStatus.active &&
                  !state.operationMutationInFlight &&
                  !state.classificationMutationInFlight,
              mutationInFlight: state.operationMutationInFlight,
              onIncome: () => unawaited(
                _createManualEntry(
                  account,
                  FinancialManualEntryKind.income,
                  initialOperationDate,
                ),
              ),
              onExpense: () => unawaited(
                _createManualEntry(
                  account,
                  FinancialManualEntryKind.expense,
                  initialOperationDate,
                ),
              ),
              onTransfer: transferDestinations.isEmpty
                  ? null
                  : () => unawaited(
                      _createTransfer(
                        account,
                        transferDestinations,
                        initialOperationDate,
                      ),
                    ),
            ),
            const SizedBox(height: AppTokens.space16),
            _OpeningBalanceCard(
              account: account,
              openingBalance: state.openingBalance,
              mutationInFlight: state.openingBalanceMutationInFlight,
              onCreate:
                  state.openingBalance == null &&
                      account.status == FinancialAccountStatus.active
                  ? () => unawaited(_createOpeningBalance(account))
                  : null,
            ),
            if (state.statement != null) ...[
              const SizedBox(height: AppTokens.space16),
              _StatementCard(
                statement: state.statement!,
                transfers: state.transfers,
                account: account,
                categoryIndex: state.categoryIndex,
                currentAllocations: state.currentAllocations,
                operatorId: operatorId,
                allowClassification:
                    !state.isBusy && state.classificationTrusted,
                onClassify: (movement) =>
                    unawaited(_classifyMovement(account, movement, operatorId)),
                allowReversal:
                    account.status == FinancialAccountStatus.active &&
                    !state.operationMutationInFlight &&
                    !state.classificationMutationInFlight,
                onReverseMovement: (movement) => unawaited(
                  _reverseMovement(
                    movement,
                    financialOperationInitialDate(
                      now: ref.read(financialOperationClockProvider)(),
                      openingBalanceDate: state.openingBalance?.effectiveDate,
                      movementEffectiveDates: state.movements.map(
                        (item) => item.effectiveDate,
                      ),
                      targetMovementDate: movement.effectiveDate,
                    ),
                  ),
                ),
                onReverseTransfer: (transfer, movement) => unawaited(
                  _reverseTransfer(
                    transfer,
                    movement,
                    financialOperationInitialDate(
                      now: ref.read(financialOperationClockProvider)(),
                      openingBalanceDate: state.openingBalance?.effectiveDate,
                      movementEffectiveDates: state.movements.map(
                        (item) => item.effectiveDate,
                      ),
                      targetMovementDate: movement.effectiveDate,
                    ),
                  ),
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class _AccountIdentityCard extends StatelessWidget {
  const _AccountIdentityCard({required this.account});
  final FinancialAccount account;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Wrap(
          spacing: AppTokens.space24,
          runSpacing: AppTokens.space12,
          children: [
            _Metadata(label: 'Tipo', value: _typeLabel(account.accountType)),
            _Metadata(label: 'Moeda', value: account.currency),
            _Metadata(
              label: 'Visibilidade',
              value: _visibilityLabel(account.visibilityScope),
            ),
            _Metadata(
              label: 'Status',
              value: account.status == FinancialAccountStatus.active
                  ? 'Ativa'
                  : 'Arquivada',
            ),
          ],
        ),
      ),
    );
  }
}

class _OpeningBalanceCard extends StatelessWidget {
  const _OpeningBalanceCard({
    required this.account,
    required this.openingBalance,
    required this.mutationInFlight,
    required this.onCreate,
  });

  final FinancialAccount account;
  final FinancialOpeningBalance? openingBalance;
  final bool mutationInFlight;
  final VoidCallback? onCreate;

  @override
  Widget build(BuildContext context) {
    final opening = openingBalance;
    return Card(
      key: FinancialAccountDetailScreen.openingBalanceKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Saldo inicial',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: AppTokens.space8),
            if (opening == null) ...[
              Text(
                'Saldo inicial não informado.',
                style: Theme.of(context).textTheme.bodyLarge,
              ),
              const SizedBox(height: AppTokens.space4),
              Text(
                'A ausência de registro não significa saldo zero.',
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
              ),
              if (onCreate != null) ...[
                const SizedBox(height: AppTokens.space16),
                FilledButton.icon(
                  key: FinancialAccountDetailScreen.createOpeningButtonKey,
                  onPressed: mutationInFlight ? null : onCreate,
                  icon: mutationInFlight
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.add_rounded),
                  label: const Text('Informar saldo inicial'),
                ),
              ],
            ] else
              Wrap(
                spacing: AppTokens.space24,
                runSpacing: AppTokens.space12,
                children: [
                  _Metadata(
                    label: 'Valor',
                    value: formatFinancialMoney(opening.money),
                  ),
                  _Metadata(
                    label: 'Data efetiva',
                    value: _dateLabel(opening.effectiveDate),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

class _BalanceCard extends StatelessWidget {
  const _BalanceCard({required this.balance});

  final FinancialBalanceSnapshot balance;

  @override
  Widget build(BuildContext context) {
    return Card(
      key: FinancialAccountDetailScreen.balanceKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Saldo atual', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: AppTokens.space16),
            Wrap(
              spacing: AppTokens.space24,
              runSpacing: AppTokens.space12,
              children: [
                _Metadata(
                  label: 'Saldo corrente',
                  value: formatFinancialMoney(balance.currentBalance),
                ),
                _Metadata(
                  label: 'Movimentação líquida',
                  value: formatFinancialMoney(balance.movementNet),
                ),
                _Metadata(
                  label: 'Movimentos',
                  value: balance.movementCount.toString(),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _FinanceActionsCard extends StatelessWidget {
  const _FinanceActionsCard({
    required this.account,
    required this.destinations,
    required this.enabled,
    required this.mutationInFlight,
    required this.onIncome,
    required this.onExpense,
    required this.onTransfer,
  });

  final FinancialAccount account;
  final List<FinancialAccount> destinations;
  final bool enabled;
  final bool mutationInFlight;
  final VoidCallback onIncome;
  final VoidCallback onExpense;
  final VoidCallback? onTransfer;

  @override
  Widget build(BuildContext context) {
    final canTransfer = enabled && onTransfer != null;
    return Card(
      key: FinancialAccountDetailScreen.actionsKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Operações', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: AppTokens.space8),
            Text(
              enabled
                  ? 'Registre lançamentos ou transfira valores sem editar o ledger diretamente.'
                  : 'Operações indisponíveis enquanto esta conta não estiver ativa.',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
            ),
            const SizedBox(height: AppTokens.space16),
            Wrap(
              spacing: AppTokens.space12,
              runSpacing: AppTokens.space12,
              children: [
                FilledButton.icon(
                  key: FinancialAccountDetailScreen.incomeButtonKey,
                  onPressed: enabled && !mutationInFlight ? onIncome : null,
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('Nova receita'),
                ),
                FilledButton.tonalIcon(
                  key: FinancialAccountDetailScreen.expenseButtonKey,
                  onPressed: enabled && !mutationInFlight ? onExpense : null,
                  icon: const Icon(Icons.remove_rounded),
                  label: const Text('Nova despesa'),
                ),
                OutlinedButton.icon(
                  key: FinancialAccountDetailScreen.transferButtonKey,
                  onPressed: canTransfer && !mutationInFlight
                      ? onTransfer
                      : null,
                  icon: const Icon(Icons.swap_horiz_rounded),
                  label: const Text('Transferir'),
                ),
              ],
            ),
            if (enabled && destinations.isEmpty) ...[
              const SizedBox(height: AppTokens.space12),
              Text(
                'Não há outra conta ativa em ${account.currency} disponível para transferência.',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: AppTokens.neutral700),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _StatementCard extends StatelessWidget {
  const _StatementCard({
    required this.statement,
    required this.transfers,
    required this.account,
    required this.categoryIndex,
    required this.currentAllocations,
    required this.operatorId,
    required this.allowClassification,
    required this.onClassify,
    required this.allowReversal,
    required this.onReverseMovement,
    required this.onReverseTransfer,
  });

  final FinancialStatement statement;
  final List<FinancialTransfer> transfers;
  final FinancialAccount account;
  final FinancialCategoryIndex categoryIndex;
  final Map<String, FinancialMovementAllocation> currentAllocations;
  final String? operatorId;
  final bool allowClassification;
  final ValueChanged<FinancialMovement> onClassify;
  final bool allowReversal;
  final ValueChanged<FinancialMovement> onReverseMovement;
  final void Function(FinancialTransfer, FinancialMovement) onReverseTransfer;

  @override
  Widget build(BuildContext context) {
    final reversedMovementIds = statement.entries
        .map((entry) => entry.movement.reversalOfId)
        .whereType<String>()
        .toSet();
    return Card(
      key: FinancialAccountDetailScreen.statementKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Extrato', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: AppTokens.space8),
            Text(
              'STANDARD e REVERSAL permanecem separados; o saldo após cada evento é derivado pelo backend.',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
            ),
            const SizedBox(height: AppTokens.space16),
            if (statement.entries.isEmpty)
              const Text('Nenhuma movimentação registrada nesta conta.')
            else
              ...statement.entries.map((entry) {
                final movement = entry.movement;
                final reversibleMovement =
                    allowReversal &&
                    movement.role == FinancialMovementRole.standard &&
                    movement.resultEffect != FinancialResultEffect.neutral &&
                    !reversedMovementIds.contains(movement.movementId);
                final reversibleTransfer = allowReversal
                    ? reversibleTransferForMovement(
                        movement: movement,
                        transfers: transfers,
                      )
                    : null;
                final allocation = currentAllocations[movement.movementId];
                final canClassify =
                    allowClassification &&
                    canClassifyFinancialMovementSimply(
                      account: account,
                      movement: movement,
                      currentAllocation: allocation,
                      operatorId: operatorId,
                    );
                String classificationLabel;
                try {
                  classificationLabel = financialMovementClassificationLabel(
                    movement: movement,
                    allocation: allocation,
                    index: categoryIndex,
                  );
                } on FormatException {
                  classificationLabel = 'Categoria indisponível';
                }
                return Padding(
                  padding: const EdgeInsets.only(bottom: AppTokens.space12),
                  child: _StatementRow(
                    entry: entry,
                    classificationLabel: classificationLabel,
                    onClassify: canClassify ? () => onClassify(movement) : null,
                    transferId: reversibleTransfer?.transferId,
                    onReverseMovement: reversibleMovement
                        ? () => onReverseMovement(movement)
                        : null,
                    onReverseTransfer: reversibleTransfer == null
                        ? null
                        : () => onReverseTransfer(reversibleTransfer, movement),
                  ),
                );
              }),
          ],
        ),
      ),
    );
  }
}

class _StatementRow extends StatelessWidget {
  const _StatementRow({
    required this.entry,
    required this.classificationLabel,
    required this.onClassify,
    required this.transferId,
    required this.onReverseMovement,
    required this.onReverseTransfer,
  });

  final FinancialStatementEntry entry;
  final String classificationLabel;
  final VoidCallback? onClassify;
  final String? transferId;
  final VoidCallback? onReverseMovement;
  final VoidCallback? onReverseTransfer;

  @override
  Widget build(BuildContext context) {
    final movement = entry.movement;
    final reversal = movement.role == FinancialMovementRole.reversal;
    final label = reversal
        ? movement.reversalReason ?? 'Reversão'
        : movement.description ?? 'Movimentação';
    return Container(
      padding: const EdgeInsets.all(AppTokens.space16),
      decoration: BoxDecoration(
        border: Border.all(color: AppTokens.neutral200),
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
      ),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: AppTokens.space16,
        runSpacing: AppTokens.space12,
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: AppTokens.space4),
                Text(
                  '${_dateLabel(movement.effectiveDate)} · ${_effectLabel(movement.resultEffect)} · ${reversal ? 'Reversão' : 'Original'}',
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: AppTokens.neutral700),
                ),
                const SizedBox(height: AppTokens.space4),
                Text(
                  formatFinancialRegistrationTime(
                    createdAt: movement.createdAt,
                    effectiveDate: movement.effectiveDate,
                  ),
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: AppTokens.neutral700),
                ),
                const SizedBox(height: AppTokens.space4),
                Text(
                  'Categoria: $classificationLabel',
                  key: Key(
                    'financial-movement-classification-${movement.movementId}',
                  ),
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: AppTokens.space4),
                Text(
                  'Saldo após evento: ${formatFinancialMoney(entry.balanceAfter)}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Semantics(
                label:
                    '${reversal ? 'Reversão' : 'Movimento'}: ${formatFinancialMoney(movement.money)}',
                child: Text(
                  formatFinancialMoney(movement.money),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              if (onClassify != null) ...[
                const SizedBox(height: AppTokens.space8),
                FilledButton.tonalIcon(
                  key: Key(
                    'financial-movement-classify-${movement.movementId}',
                  ),
                  onPressed: onClassify,
                  icon: const Icon(Icons.sell_outlined),
                  label: const Text('Classificar'),
                ),
              ],
              if (onReverseMovement != null) ...[
                const SizedBox(height: AppTokens.space8),
                TextButton.icon(
                  key: Key('financial-movement-reverse-${movement.movementId}'),
                  onPressed: onReverseMovement,
                  icon: const Icon(Icons.undo_rounded),
                  label: const Text('Reverter lançamento'),
                ),
              ],
              if (onReverseTransfer != null && transferId != null) ...[
                const SizedBox(height: AppTokens.space8),
                TextButton.icon(
                  key: Key('financial-transfer-reverse-$transferId'),
                  onPressed: onReverseTransfer,
                  icon: const Icon(Icons.undo_rounded),
                  label: const Text('Reverter transferência'),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }
}

class _ClassifyMovementDialog extends ConsumerStatefulWidget {
  const _ClassifyMovementDialog({
    required this.accountId,
    required this.account,
    required this.movement,
    required this.operatorId,
  });

  final String accountId;
  final FinancialAccount account;
  final FinancialMovement movement;
  final String? operatorId;

  static const dialogKey = Key('financial-classify-dialog');
  static const confirmKey = Key('financial-classify-confirm');
  static const newCategoryKey = Key('financial-classify-new-category');
  static const errorKey = Key('financial-classify-error');
  static const noticeKey = Key('financial-classify-notice');
  static const unknownKey = Key('financial-classify-category-unknown');
  static const reconcileKey = Key('financial-classify-reconcile-categories');

  @override
  ConsumerState<_ClassifyMovementDialog> createState() =>
      _ClassifyMovementDialogState();
}

class _ClassifyMovementDialogState
    extends ConsumerState<_ClassifyMovementDialog> {
  String? _selectedCategoryId;
  String? _error;
  String? _notice;

  Future<void> _createCategory() async {
    final operatorId = widget.operatorId;
    if (operatorId == null) return;
    final state = ref.read(
      financialAccountDetailControllerProvider(widget.accountId),
    );
    final input = await showDialog<FinancialCategoryCreateInput>(
      context: context,
      builder: (context) => _CategoryCreateDialog(
        account: widget.account,
        index: state.categoryIndex,
        operatorId: operatorId,
      ),
    );
    if (input == null || !mounted) return;
    final result = await ref
        .read(
          financialAccountDetailControllerProvider(widget.accountId).notifier,
        )
        .createCategory(input);
    if (!mounted) return;
    setState(() {
      _notice = null;
      switch (result.outcome) {
        case FinancialMutationOutcome.success:
          _error = null;
          final created = result.category;
          if (created != null &&
              isFinancialCategoryEligibleForAccount(
                category: created,
                account: widget.account,
              )) {
            _selectedCategoryId = created.categoryId;
          }
        case FinancialMutationOutcome.rejected:
          _error = 'A categoria não foi aceita. Revise nome, escopo e pai.';
        case FinancialMutationOutcome.notAllowed:
          _error = 'Esta categoria não pode ser criada neste contexto.';
        case FinancialMutationOutcome.unknownOutcomeReconciled:
          _error = null;
          final matches = result.matches.length;
          _notice = matches == 0
              ? 'Não foi possível confirmar se a categoria foi criada. A lista '
                    'foi atualizada: confira se ela já existe antes de tentar '
                    'novamente.'
              : 'Não foi possível confirmar a criação, mas há '
                    '${matches == 1 ? 'uma categoria compatível' : '$matches categorias compatíveis'} '
                    'na lista atualizada. Selecione a correta; nenhuma será '
                    'escolhida automaticamente.';
        case FinancialMutationOutcome.temporarilyUnavailable:
        case FinancialMutationOutcome.invalidResponse:
          _error =
              'O resultado da criação é desconhecido e não pôde ser '
              'conferido. Atualize as categorias antes de tentar novamente.';
        case FinancialMutationOutcome.accessBlocked ||
            FinancialMutationOutcome.conflictReconciled:
          _error = 'A categoria não foi criada.';
      }
    });
  }

  Future<void> _reconcileCategories() async {
    final outcome = await ref
        .read(
          financialAccountDetailControllerProvider(widget.accountId).notifier,
        )
        .reconcileCategories();
    if (!mounted) return;
    setState(() {
      if (outcome == FinancialMutationOutcome.success) {
        _error = null;
        _notice =
            'Categorias atualizadas. Confira a lista antes de criar outra '
            'categoria.';
      } else {
        _error = 'Não foi possível atualizar as categorias agora.';
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(
      financialAccountDetailControllerProvider(widget.accountId),
    );
    final eligible = eligibleFinancialCategories(
      index: state.categoryIndex,
      account: widget.account,
    );
    final selected =
        eligible.any((item) => item.categoryId == _selectedCategoryId)
        ? _selectedCategoryId
        : null;
    final busy = state.classificationMutationInFlight;
    final description = widget.movement.description ?? 'Lançamento selecionado';
    return AlertDialog(
      key: _ClassifyMovementDialog.dialogKey,
      title: const Text('Classificar lançamento'),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '$description · ${formatFinancialMoney(widget.movement.money)}',
                style: Theme.of(context).textTheme.bodyLarge,
              ),
              const SizedBox(height: AppTokens.space4),
              Text(
                'O valor total do lançamento será classificado na categoria escolhida.',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: AppTokens.neutral700),
              ),
              const SizedBox(height: AppTokens.space16),
              if (eligible.isEmpty)
                const Text(
                  'Nenhuma categoria disponível para este lançamento. Crie uma nova categoria.',
                )
              else
                RadioGroup<String>(
                  groupValue: selected,
                  onChanged: (value) =>
                      setState(() => _selectedCategoryId = value),
                  child: Column(
                    children: [
                      for (final category in eligible)
                        RadioListTile<String>(
                          key: Key(
                            'financial-classify-category-${category.categoryId}',
                          ),
                          value: category.categoryId,
                          title: Text(
                            state.categoryIndex.pathLabel(
                                  category.categoryId,
                                ) ??
                                category.name,
                          ),
                          subtitle: Text(
                            category.visibilityScope ==
                                    FinancialVisibilityScope.personal
                                ? 'Pessoal'
                                : 'Residência',
                          ),
                        ),
                    ],
                  ),
                ),
              const SizedBox(height: AppTokens.space8),
              if (widget.operatorId != null)
                TextButton.icon(
                  key: _ClassifyMovementDialog.newCategoryKey,
                  onPressed: busy || state.categoryCreationUnknown
                      ? null
                      : _createCategory,
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('Nova categoria'),
                ),
              if (state.categoryCreationUnknown) ...[
                const SizedBox(height: AppTokens.space8),
                Text(
                  'O resultado da última criação de categoria é desconhecido. '
                  'Atualize as categorias antes de criar outra.',
                  key: _ClassifyMovementDialog.unknownKey,
                ),
                TextButton.icon(
                  key: _ClassifyMovementDialog.reconcileKey,
                  onPressed: busy ? null : _reconcileCategories,
                  icon: const Icon(Icons.refresh_rounded),
                  label: const Text('Atualizar categorias'),
                ),
              ],
              if (_notice != null) ...[
                const SizedBox(height: AppTokens.space8),
                Text(_notice!, key: _ClassifyMovementDialog.noticeKey),
              ],
              if (_error != null) ...[
                const SizedBox(height: AppTokens.space8),
                Text(
                  _error!,
                  key: _ClassifyMovementDialog.errorKey,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: _ClassifyMovementDialog.confirmKey,
          onPressed: selected == null || busy
              ? null
              : () => Navigator.of(context).pop(selected),
          child: const Text('Confirmar'),
        ),
      ],
    );
  }
}

class _CategoryCreateDialog extends StatefulWidget {
  const _CategoryCreateDialog({
    required this.account,
    required this.index,
    required this.operatorId,
  });

  final FinancialAccount account;
  final FinancialCategoryIndex index;
  final String operatorId;

  static const nameKey = Key('financial-category-name');
  static const scopeKey = Key('financial-category-scope');
  static const confirmKey = Key('financial-category-create-confirm');

  @override
  State<_CategoryCreateDialog> createState() => _CategoryCreateDialogState();
}

class _CategoryCreateDialogState extends State<_CategoryCreateDialog> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  late FinancialVisibilityScope _scope;
  String? _parentId;

  @override
  void initState() {
    super.initState();
    _scope = financialCategoryCreationScopes(widget.account).first;
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    try {
      Navigator.of(context).pop(
        FinancialCategoryCreateInput(
          name: _nameController.text,
          visibilityScope: _scope,
          parentId: _parentId,
        ),
      );
    } on FormatException {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Revise os dados da categoria.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final scopes = financialCategoryCreationScopes(widget.account);
    final parents = eligibleFinancialCategoryParents(
      index: widget.index,
      scope: _scope,
      operatorId: widget.operatorId,
    );
    return AlertDialog(
      title: const Text('Nova categoria'),
      content: SizedBox(
        width: 460,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  key: _CategoryCreateDialog.nameKey,
                  controller: _nameController,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: 'Nome'),
                  validator: (value) {
                    final text = (value ?? '').trim();
                    if (text.isEmpty ||
                        text.length > 96 ||
                        text.codeUnits.any((u) => u < 32 || u == 127)) {
                      return 'Informe um nome de até 96 caracteres.';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: AppTokens.space16),
                DropdownButtonFormField<FinancialVisibilityScope>(
                  key: _CategoryCreateDialog.scopeKey,
                  initialValue: _scope,
                  decoration: const InputDecoration(labelText: 'Visibilidade'),
                  items: [
                    for (final scope in scopes)
                      DropdownMenuItem(
                        value: scope,
                        child: Text(
                          scope == FinancialVisibilityScope.personal
                              ? 'Pessoal'
                              : 'Residência',
                        ),
                      ),
                  ],
                  onChanged: (value) {
                    if (value == null) return;
                    setState(() {
                      _scope = value;
                      _parentId = null;
                    });
                  },
                ),
                const SizedBox(height: AppTokens.space16),
                DropdownButtonFormField<String?>(
                  key: ValueKey('financial-category-parent-${_scope.name}'),
                  initialValue: _parentId,
                  decoration: const InputDecoration(
                    labelText: 'Categoria pai (opcional)',
                  ),
                  items: [
                    const DropdownMenuItem<String?>(
                      value: null,
                      child: Text('Sem categoria pai'),
                    ),
                    for (final parent in parents)
                      DropdownMenuItem<String?>(
                        value: parent.categoryId,
                        child: Text(
                          widget.index.pathLabel(parent.categoryId) ??
                              parent.name,
                        ),
                      ),
                  ],
                  onChanged: (value) => setState(() => _parentId = value),
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: _CategoryCreateDialog.confirmKey,
          onPressed: _submit,
          child: const Text('Criar categoria'),
        ),
      ],
    );
  }
}

class _OpeningBalanceDialog extends StatefulWidget {
  const _OpeningBalanceDialog({required this.account});
  final FinancialAccount account;

  @override
  State<_OpeningBalanceDialog> createState() => _OpeningBalanceDialogState();
}

class _OpeningBalanceDialogState extends State<_OpeningBalanceDialog> {
  final _formKey = GlobalKey<FormState>();
  final _amountController = TextEditingController();
  late final TextEditingController _dateController;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _dateController = TextEditingController(
      text:
          '${now.year.toString().padLeft(4, '0')}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}',
    );
  }

  @override
  void dispose() {
    _amountController.dispose();
    _dateController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    try {
      Navigator.of(context).pop(
        FinancialOpeningBalanceCreateInput(
          amount: normalizeFinancialMoneyInput(_amountController.text),
          currency: widget.account.currency,
          effectiveDate: _dateController.text,
        ),
      );
    } on FormatException {
      _formKey.currentState?.validate();
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Informar saldo inicial'),
      content: SizedBox(
        width: 460,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _amountController,
                autofocus: true,
                decoration: InputDecoration(
                  labelText: 'Valor em ${widget.account.currency}',
                  helperText: 'Use vírgula ou ponto decimal, ex.: 1250,50',
                ),
                validator: (value) =>
                    validateFinancialMoneyInput(value, requirePositive: false),
              ),
              const SizedBox(height: AppTokens.space16),
              TextFormField(
                controller: _dateController,
                decoration: const InputDecoration(
                  labelText: 'Data efetiva',
                  helperText: 'Formato AAAA-MM-DD',
                ),
                validator: (value) =>
                    RegExp(
                      r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$',
                    ).hasMatch(value ?? '')
                    ? null
                    : 'Informe a data no formato AAAA-MM-DD.',
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Salvar')),
      ],
    );
  }
}

class _ManualEntryDialog extends StatefulWidget {
  const _ManualEntryDialog({
    required this.account,
    required this.kind,
    required this.initialDate,
  });

  final FinancialAccount account;
  final FinancialManualEntryKind kind;
  final String initialDate;

  @override
  State<_ManualEntryDialog> createState() => _ManualEntryDialogState();
}

class _ManualEntryDialogState extends State<_ManualEntryDialog> {
  final _formKey = GlobalKey<FormState>();
  final _amountController = TextEditingController();
  final _descriptionController = TextEditingController();
  late final TextEditingController _effectiveDateController;
  late final TextEditingController _competenceDateController;

  @override
  void initState() {
    super.initState();
    _effectiveDateController = TextEditingController(text: widget.initialDate);
    _competenceDateController = TextEditingController(text: widget.initialDate);
  }

  @override
  void dispose() {
    _amountController.dispose();
    _descriptionController.dispose();
    _effectiveDateController.dispose();
    _competenceDateController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    try {
      Navigator.of(context).pop(
        FinancialManualEntryCreateInput(
          amount: normalizeFinancialMoneyInput(_amountController.text),
          currency: widget.account.currency,
          effectiveDate: _effectiveDateController.text,
          competenceDate: _competenceDateController.text,
          description: _descriptionController.text,
        ),
      );
    } on FormatException {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Revise os dados informados.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final income = widget.kind == FinancialManualEntryKind.income;
    return AlertDialog(
      title: Text(income ? 'Nova receita' : 'Nova despesa'),
      content: SizedBox(
        width: 480,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  controller: _amountController,
                  autofocus: true,
                  decoration: InputDecoration(
                    labelText: 'Valor em ${widget.account.currency}',
                    helperText: 'Informe um valor positivo, ex.: 125,50',
                  ),
                  validator: _validatePositiveMoney,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _descriptionController,
                  decoration: const InputDecoration(labelText: 'Descrição'),
                  validator: _validateDescription,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _effectiveDateController,
                  decoration: const InputDecoration(
                    labelText: 'Data efetiva',
                    helperText: 'Formato AAAA-MM-DD',
                  ),
                  validator: _validateDate,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _competenceDateController,
                  decoration: const InputDecoration(
                    labelText: 'Data de competência',
                    helperText: 'Formato AAAA-MM-DD',
                  ),
                  validator: _validateDate,
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: _submit,
          child: Text(income ? 'Registrar receita' : 'Registrar despesa'),
        ),
      ],
    );
  }
}

class _TransferDialog extends StatefulWidget {
  const _TransferDialog({
    required this.account,
    required this.destinations,
    required this.initialDate,
  });

  final FinancialAccount account;
  final List<FinancialAccount> destinations;
  final String initialDate;

  @override
  State<_TransferDialog> createState() => _TransferDialogState();
}

class _TransferDialogState extends State<_TransferDialog> {
  final _formKey = GlobalKey<FormState>();
  final _amountController = TextEditingController();
  final _descriptionController = TextEditingController();
  late final TextEditingController _effectiveDateController;
  late final TextEditingController _competenceDateController;
  late String _destinationId;

  @override
  void initState() {
    super.initState();
    _destinationId = widget.destinations.first.accountId;
    _effectiveDateController = TextEditingController(text: widget.initialDate);
    _competenceDateController = TextEditingController(text: widget.initialDate);
  }

  @override
  void dispose() {
    _amountController.dispose();
    _descriptionController.dispose();
    _effectiveDateController.dispose();
    _competenceDateController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    try {
      Navigator.of(context).pop(
        FinancialTransferCreateInput(
          sourceAccountId: widget.account.accountId,
          destinationAccountId: _destinationId,
          amount: normalizeFinancialMoneyInput(_amountController.text),
          currency: widget.account.currency,
          effectiveDate: _effectiveDateController.text,
          competenceDate: _competenceDateController.text,
          description: _descriptionController.text,
        ),
      );
    } on FormatException {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Revise os dados da transferência.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Transferir entre contas'),
      content: SizedBox(
        width: 500,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: _destinationId,
                  decoration: const InputDecoration(labelText: 'Conta destino'),
                  items: widget.destinations
                      .map(
                        (account) => DropdownMenuItem(
                          value: account.accountId,
                          child: Text(account.name),
                        ),
                      )
                      .toList(growable: false),
                  onChanged: (value) {
                    if (value != null) setState(() => _destinationId = value);
                  },
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _amountController,
                  autofocus: true,
                  decoration: InputDecoration(
                    labelText: 'Valor em ${widget.account.currency}',
                    helperText: 'Informe um valor positivo, ex.: 125,50',
                  ),
                  validator: _validatePositiveMoney,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _descriptionController,
                  decoration: const InputDecoration(labelText: 'Descrição'),
                  validator: _validateDescription,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _effectiveDateController,
                  decoration: const InputDecoration(
                    labelText: 'Data efetiva',
                    helperText: 'Formato AAAA-MM-DD',
                  ),
                  validator: _validateDate,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _competenceDateController,
                  decoration: const InputDecoration(
                    labelText: 'Data de competência',
                    helperText: 'Formato AAAA-MM-DD',
                  ),
                  validator: _validateDate,
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Transferir')),
      ],
    );
  }
}

class _MovementReversalDialog extends StatefulWidget {
  const _MovementReversalDialog({
    required this.movement,
    required this.initialDate,
  });

  final FinancialMovement movement;
  final String initialDate;

  @override
  State<_MovementReversalDialog> createState() =>
      _MovementReversalDialogState();
}

class _MovementReversalDialogState extends State<_MovementReversalDialog> {
  final _formKey = GlobalKey<FormState>();
  final _reasonController = TextEditingController();
  late final TextEditingController _effectiveDateController;
  late final TextEditingController _competenceDateController;

  @override
  void initState() {
    super.initState();
    _effectiveDateController = TextEditingController(text: widget.initialDate);
    _competenceDateController = TextEditingController(text: widget.initialDate);
  }

  @override
  void dispose() {
    _reasonController.dispose();
    _effectiveDateController.dispose();
    _competenceDateController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    try {
      Navigator.of(context).pop(
        FinancialMovementReversalInput(
          effectiveDate: _effectiveDateController.text,
          competenceDate: _competenceDateController.text,
          reason: _reasonController.text,
        ),
      );
    } on FormatException {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Revise os dados da reversão.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Reverter lançamento'),
      content: SizedBox(
        width: 480,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  widget.movement.description ?? 'Lançamento selecionado',
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _reasonController,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: 'Motivo'),
                  validator: _validateDescription,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _effectiveDateController,
                  decoration: const InputDecoration(
                    labelText: 'Data efetiva da reversão',
                    helperText: 'Formato AAAA-MM-DD',
                  ),
                  validator: _validateDate,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _competenceDateController,
                  decoration: const InputDecoration(
                    labelText: 'Data de competência',
                    helperText: 'Formato AAAA-MM-DD',
                  ),
                  validator: _validateDate,
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: _submit,
          child: const Text('Confirmar reversão'),
        ),
      ],
    );
  }
}

class _TransferReversalDialog extends StatefulWidget {
  const _TransferReversalDialog({
    required this.movement,
    required this.initialDate,
  });

  final FinancialMovement movement;
  final String initialDate;

  @override
  State<_TransferReversalDialog> createState() =>
      _TransferReversalDialogState();
}

class _TransferReversalDialogState extends State<_TransferReversalDialog> {
  final _formKey = GlobalKey<FormState>();
  final _reasonController = TextEditingController();
  late final TextEditingController _effectiveDateController;
  late final TextEditingController _competenceDateController;

  @override
  void initState() {
    super.initState();
    _effectiveDateController = TextEditingController(text: widget.initialDate);
    _competenceDateController = TextEditingController(text: widget.initialDate);
  }

  @override
  void dispose() {
    _reasonController.dispose();
    _effectiveDateController.dispose();
    _competenceDateController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    try {
      Navigator.of(context).pop(
        FinancialTransferReversalInput(
          effectiveDate: _effectiveDateController.text,
          competenceDate: _competenceDateController.text,
          reason: _reasonController.text,
        ),
      );
    } on FormatException {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Revise os dados da reversão da transferência.'),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Reverter transferência'),
      content: SizedBox(
        width: 480,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  widget.movement.description ?? 'Transferência selecionada',
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _reasonController,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: 'Motivo'),
                  validator: _validateDescription,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _effectiveDateController,
                  decoration: const InputDecoration(
                    labelText: 'Data efetiva da reversão',
                    helperText: 'Formato AAAA-MM-DD',
                  ),
                  validator: _validateDate,
                ),
                const SizedBox(height: AppTokens.space16),
                TextFormField(
                  controller: _competenceDateController,
                  decoration: const InputDecoration(
                    labelText: 'Data de competência',
                    helperText: 'Formato AAAA-MM-DD',
                  ),
                  validator: _validateDate,
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: _submit,
          child: const Text('Confirmar reversão'),
        ),
      ],
    );
  }
}

class _Metadata extends StatelessWidget {
  const _Metadata({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(minWidth: 140),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: AppTokens.space4),
          Text(value, style: Theme.of(context).textTheme.bodyLarge),
        ],
      ),
    );
  }
}

class _StateNotice extends StatelessWidget {
  const _StateNotice({required this.noticeKey, required this.message});

  final Key noticeKey;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Card(
      key: noticeKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Row(
          children: [
            const Icon(Icons.info_outline_rounded),
            const SizedBox(width: AppTokens.space12),
            Expanded(child: Text(message)),
          ],
        ),
      ),
    );
  }
}

class _RefreshNotice extends StatelessWidget {
  const _RefreshNotice({required this.failure});
  final FinancialRefreshFailure failure;

  @override
  Widget build(BuildContext context) {
    final message = switch (failure) {
      FinancialRefreshFailure.temporarilyUnavailable =>
        'O detalhe atual foi preservado, mas não foi possível atualizá-lo.',
      FinancialRefreshFailure.invalidResponse =>
        'O detalhe atual foi preservado porque a nova resposta não pôde ser validada.',
      FinancialRefreshFailure.none => '',
    };
    return message.isEmpty
        ? const SizedBox.shrink()
        : Card(
            child: Padding(
              padding: const EdgeInsets.all(AppTokens.space16),
              child: Text(message),
            ),
          );
  }
}

class _FailureOrLoading extends StatelessWidget {
  const _FailureOrLoading({required this.phase, required this.onRetry});
  final FinancialLoadPhase phase;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    if (phase == FinancialLoadPhase.idle ||
        phase == FinancialLoadPhase.loading) {
      return const Card(
        child: Padding(
          padding: EdgeInsets.all(AppTokens.space24),
          child: Row(
            children: [
              SizedBox.square(
                dimension: 24,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              ),
              SizedBox(width: AppTokens.space16),
              Expanded(child: Text('Carregando detalhes financeiros…')),
            ],
          ),
        ),
      );
    }
    final content = switch (phase) {
      FinancialLoadPhase.notFound => (
        'Conta não encontrada',
        'A conta não existe ou não está visível para esta sessão.',
        false,
      ),
      FinancialLoadPhase.authenticationRequired => (
        'Sessão necessária',
        'Entre novamente para acessar a conta.',
        false,
      ),
      FinancialLoadPhase.forbidden => (
        'Acesso não permitido',
        'Sua sessão não possui acesso a esta conta.',
        false,
      ),
      FinancialLoadPhase.primaryResidenceRequired => (
        'Residência principal necessária',
        'Configure uma residência principal para usar Finanças.',
        false,
      ),
      FinancialLoadPhase.invalidResponse => (
        'Resposta inválida',
        'A resposta recebida não pôde ser validada com segurança.',
        true,
      ),
      _ => (
        'Serviço temporariamente indisponível',
        'Não foi possível carregar a conta agora.',
        true,
      ),
    };
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(content.$1, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: AppTokens.space8),
            Text(content.$2),
            if (content.$3) ...[
              const SizedBox(height: AppTokens.space16),
              OutlinedButton(
                onPressed: onRetry,
                child: const Text('Tentar novamente'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

String? _validatePositiveMoney(String? value) =>
    validateFinancialMoneyInput(value, requirePositive: true);

String? _validateDescription(String? value) {
  final source = value ?? '';
  if (source.isEmpty ||
      source.length > 256 ||
      source != source.trim() ||
      source.codeUnits.any((unit) => unit < 32 || unit == 127)) {
    return 'Informe um texto válido de até 256 caracteres.';
  }
  return null;
}

String? _validateDate(String? value) {
  final source = value ?? '';
  if (!RegExp(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$').hasMatch(source)) {
    return 'Informe a data no formato AAAA-MM-DD.';
  }
  final parsed = DateTime.tryParse('${source}T00:00:00Z');
  final canonical = parsed == null
      ? null
      : '${parsed.year.toString().padLeft(4, '0')}-'
            '${parsed.month.toString().padLeft(2, '0')}-'
            '${parsed.day.toString().padLeft(2, '0')}';
  return canonical == source ? null : 'Informe uma data válida.';
}

String _dateLabel(String value) {
  final parts = value.split('-');
  return parts.length == 3 ? '${parts[2]}/${parts[1]}/${parts[0]}' : value;
}

String _typeLabel(FinancialAccountType type) => switch (type) {
  FinancialAccountType.checking => 'Conta corrente',
  FinancialAccountType.savings => 'Poupança',
  FinancialAccountType.cash => 'Dinheiro',
  FinancialAccountType.digitalWallet => 'Carteira digital',
  FinancialAccountType.investment => 'Investimento',
  FinancialAccountType.benefit => 'Benefício',
  FinancialAccountType.custom => 'Personalizada',
};

String _visibilityLabel(FinancialVisibilityScope scope) => switch (scope) {
  FinancialVisibilityScope.personal => 'Pessoal',
  FinancialVisibilityScope.shared => 'Compartilhada',
  FinancialVisibilityScope.household => 'Residência',
};

String _effectLabel(FinancialResultEffect effect) => switch (effect) {
  FinancialResultEffect.income => 'Receita',
  FinancialResultEffect.expense => 'Despesa',
  FinancialResultEffect.neutral => 'Neutro',
};
