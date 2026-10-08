import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// `Destinar` / `Liberar` form. It holds only a local draft; nothing is sent
/// until the user confirms and the dialog hands back a validated request that the
/// caller sends exactly once. It never checks availability: the server compares
/// the amount with the canonical balance under a lock and answers.
class FinancialGoalAllocationDialog extends StatefulWidget {
  const FinancialGoalAllocationDialog({
    required this.operation,
    required this.goal,
    required this.options,
    super.key,
  });

  final FinancialGoalOperation operation;
  final FinancialGoal goal;

  /// Eligible accounts (destinar) or accounts holding a value (liberar).
  final List<FinancialGoalAccountOption> options;

  static const dialogKey = Key('financial-goal-allocation');
  static const noticeKey = Key('financial-goal-allocation-notice');
  static const accountKey = Key('financial-goal-allocation-account');
  static const amountKey = Key('financial-goal-allocation-amount');
  static const noAccountKey = Key('financial-goal-allocation-no-account');
  static const issuesKey = Key('financial-goal-allocation-issues');
  static const saveKey = Key('financial-goal-allocation-save');
  static const cancelKey = Key('financial-goal-allocation-cancel');

  @override
  State<FinancialGoalAllocationDialog> createState() =>
      _FinancialGoalAllocationDialogState();
}

class _FinancialGoalAllocationDialogState
    extends State<FinancialGoalAllocationDialog> {
  final _amount = TextEditingController();
  String? _accountId;

  bool get _allocating => widget.operation == FinancialGoalOperation.allocate;

  @override
  void initState() {
    super.initState();
    if (widget.options.length == 1) {
      _accountId = widget.options.single.accountId;
    }
  }

  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  List<FinancialGoalAllocationIssue> get _issues =>
      validateFinancialGoalAllocation(
        accountId: _accountId,
        amountText: _amount.text.trim(),
      );

  void _submit() {
    if (_issues.isNotEmpty) return;
    try {
      Navigator.of(context).pop(
        FinancialGoalAllocationInput(
          operation: widget.operation,
          accountId: _accountId!,
          amount: normalizeFinancialMoneyInput(_amount.text.trim()),
          currency: widget.goal.currency,
        ),
      );
    } on FormatException {
      // The validators above make this unreachable; stay in the form.
      setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) {
    final issues = _issues;
    final muted = Theme.of(
      context,
    ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700);
    FinancialGoalAccountOption? selected;
    for (final option in widget.options) {
      if (option.accountId == _accountId) selected = option;
    }
    return AlertDialog(
      key: FinancialGoalAllocationDialog.dialogKey,
      title: Text(_allocating ? 'Destinar à meta' : 'Liberar da meta'),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                key: FinancialGoalAllocationDialog.noticeKey,
                padding: const EdgeInsets.all(AppTokens.space12),
                decoration: BoxDecoration(
                  color: AppTokens.blue50,
                  border: Border.all(color: AppTokens.blue700),
                  borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      financialGoalVirtualNotice,
                      style: Theme.of(context).textTheme.labelLarge,
                    ),
                    const SizedBox(height: AppTokens.space4),
                    Text(
                      _allocating
                          ? 'Você marca parte do saldo atual da conta como '
                                'reservada para "${widget.goal.title}". O '
                                'servidor confere o saldo disponível no momento '
                                'de confirmar.'
                          : 'Você devolve ao saldo livre parte do que estava '
                                'destinado a "${widget.goal.title}". Nada sai da '
                                'conta.',
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppTokens.space16),
              if (widget.options.isEmpty)
                Text(
                  key: FinancialGoalAllocationDialog.noAccountKey,
                  _allocating
                      ? 'Nenhuma conta elegível: é preciso uma conta ativa, '
                            'sua, na mesma moeda e com a mesma audiência da '
                            'meta (contas compartilhadas não servem).'
                      : 'Esta meta não tem nada destinado para liberar.',
                  style: muted,
                )
              else ...[
                InputDecorator(
                  decoration: const InputDecoration(labelText: 'Conta'),
                  child: DropdownButtonHideUnderline(
                    child: DropdownButton<String>(
                      key: FinancialGoalAllocationDialog.accountKey,
                      value: _accountId,
                      isExpanded: true,
                      hint: const Text('Escolha a conta'),
                      items: [
                        for (final option in widget.options)
                          DropdownMenuItem(
                            value: option.accountId,
                            child: Text(option.label),
                          ),
                      ],
                      onChanged: (value) => setState(() => _accountId = value),
                    ),
                  ),
                ),
                if (selected?.detail != null) ...[
                  const SizedBox(height: AppTokens.space4),
                  Text(selected!.detail!, style: muted),
                ],
                const SizedBox(height: AppTokens.space12),
                TextField(
                  key: FinancialGoalAllocationDialog.amountKey,
                  controller: _amount,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  inputFormatters: [
                    FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
                  ],
                  decoration: InputDecoration(
                    labelText: 'Valor (${widget.goal.currency})',
                    hintText: '0,00',
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                if (issues.isNotEmpty &&
                    (_amount.text.isNotEmpty || _accountId != null)) ...[
                  const SizedBox(height: AppTokens.space8),
                  Column(
                    key: FinancialGoalAllocationDialog.issuesKey,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      for (final issue in issues)
                        Text(financialGoalAllocationIssueLabel(issue)),
                    ],
                  ),
                ],
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: FinancialGoalAllocationDialog.cancelKey,
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialGoalAllocationDialog.saveKey,
          onPressed: widget.options.isNotEmpty && issues.isEmpty
              ? _submit
              : null,
          child: Text(_allocating ? 'Destinar' : 'Liberar'),
        ),
      ],
    );
  }
}
