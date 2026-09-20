import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

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
  ) async {
    final result = await showDialog<FinancialManualEntryCreateInput>(
      context: context,
      builder: (context) => _ManualEntryDialog(account: account, kind: kind),
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
  ) async {
    final result = await showDialog<FinancialTransferCreateInput>(
      context: context,
      builder: (context) =>
          _TransferDialog(account: account, destinations: destinations),
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

  Future<void> _reverseMovement(FinancialMovement movement) async {
    final result = await showDialog<FinancialMovementReversalInput>(
      context: context,
      builder: (context) => _MovementReversalDialog(movement: movement),
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

  @override
  Widget build(BuildContext context) {
    final provider = financialAccountDetailControllerProvider(widget.accountId);
    final state = ref.watch(provider);
    final account = state.account;
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
                  state.openingBalance != null &&
                  !state.operationMutationInFlight,
              mutationInFlight: state.operationMutationInFlight,
              onIncome: () => unawaited(
                _createManualEntry(account, FinancialManualEntryKind.income),
              ),
              onExpense: () => unawaited(
                _createManualEntry(account, FinancialManualEntryKind.expense),
              ),
              onTransfer: transferDestinations.isEmpty
                  ? null
                  : () => unawaited(
                      _createTransfer(account, transferDestinations),
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
                allowReversal:
                    account.status == FinancialAccountStatus.active &&
                    !state.operationMutationInFlight,
                onReverse: (movement) => unawaited(_reverseMovement(movement)),
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
                  _Metadata(label: 'Valor', value: _moneyLabel(opening.money)),
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
                  value: _moneyLabel(balance.currentBalance),
                ),
                _Metadata(
                  label: 'Movimentação líquida',
                  value: _moneyLabel(balance.movementNet),
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
                  : 'Informe o saldo inicial para liberar novas operações nesta conta.',
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
    required this.allowReversal,
    required this.onReverse,
  });

  final FinancialStatement statement;
  final bool allowReversal;
  final ValueChanged<FinancialMovement> onReverse;

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
                final reversible =
                    allowReversal &&
                    movement.role == FinancialMovementRole.standard &&
                    movement.resultEffect != FinancialResultEffect.neutral &&
                    !reversedMovementIds.contains(movement.movementId);
                return Padding(
                  padding: const EdgeInsets.only(bottom: AppTokens.space12),
                  child: _StatementRow(
                    entry: entry,
                    onReverse: reversible ? () => onReverse(movement) : null,
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
  const _StatementRow({required this.entry, required this.onReverse});

  final FinancialStatementEntry entry;
  final VoidCallback? onReverse;

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
                  'Saldo após evento: ${_moneyLabel(entry.balanceAfter)}',
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
                    '${reversal ? 'Reversão' : 'Movimento'}: ${_moneyLabel(movement.money)}',
                child: Text(
                  _moneyLabel(movement.money),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              if (onReverse != null) ...[
                const SizedBox(height: AppTokens.space8),
                TextButton.icon(
                  key: Key('financial-movement-reverse-${movement.movementId}'),
                  onPressed: onReverse,
                  icon: const Icon(Icons.undo_rounded),
                  label: const Text('Reverter lançamento'),
                ),
              ],
            ],
          ),
        ],
      ),
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
          amount: _amountController.text,
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
                  helperText: 'Use ponto como separador decimal, ex.: 1250.50',
                ),
                validator: (value) {
                  final source = value ?? '';
                  return RegExp(
                        r'^-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$',
                      ).hasMatch(source)
                      ? null
                      : 'Informe um valor decimal válido.';
                },
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
  const _ManualEntryDialog({required this.account, required this.kind});

  final FinancialAccount account;
  final FinancialManualEntryKind kind;

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
    final today = _todayDateText();
    _effectiveDateController = TextEditingController(text: today);
    _competenceDateController = TextEditingController(text: today);
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
          amount: _amountController.text,
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
                    helperText: 'Informe um valor positivo, ex.: 125.50',
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
  const _TransferDialog({required this.account, required this.destinations});

  final FinancialAccount account;
  final List<FinancialAccount> destinations;

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
    final today = _todayDateText();
    _effectiveDateController = TextEditingController(text: today);
    _competenceDateController = TextEditingController(text: today);
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
          amount: _amountController.text,
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
                    helperText: 'Informe um valor positivo, ex.: 125.50',
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
  const _MovementReversalDialog({required this.movement});

  final FinancialMovement movement;

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
    final today = _todayDateText();
    _effectiveDateController = TextEditingController(text: today);
    _competenceDateController = TextEditingController(text: today);
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

String _todayDateText() {
  final now = DateTime.now();
  return '${now.year.toString().padLeft(4, '0')}-'
      '${now.month.toString().padLeft(2, '0')}-'
      '${now.day.toString().padLeft(2, '0')}';
}

String? _validatePositiveMoney(String? value) {
  final source = value ?? '';
  final valid = RegExp(
    r'^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$',
  ).hasMatch(source);
  if (!valid || RegExp(r'^0(?:\.0{1,8})?$').hasMatch(source)) {
    return 'Informe um valor positivo válido.';
  }
  return null;
}

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

String _moneyLabel(FinancialMoneyWire money) =>
    '${money.currency} ${money.amount.replaceFirst('.', ',')}';

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
