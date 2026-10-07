import 'package:flutter/material.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_policy.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// The built, validated request the editor hands back. The caller sends it once.
sealed class FinancialRecurrenceEditorResult {
  const FinancialRecurrenceEditorResult();
}

class FinancialRecurrenceEditorCreate extends FinancialRecurrenceEditorResult {
  const FinancialRecurrenceEditorCreate(this.input);
  final FinancialRecurrenceCreateInput input;
}

class FinancialRecurrenceEditorReplace extends FinancialRecurrenceEditorResult {
  const FinancialRecurrenceEditorReplace(this.input);
  final FinancialRecurrenceReplaceInput input;
}

/// Create/edit form of a monthly recurrence. It holds only a local draft; nothing
/// is sent until the user confirms, and the dialog never decides a financial or
/// calendar rule: the server validates again and decides the scheduled dates.
class FinancialRecurrenceEditorDialog extends StatefulWidget {
  const FinancialRecurrenceEditorDialog({
    required this.accounts,
    required this.initialStartDate,
    this.existing,
    this.existingAccountName,
    super.key,
  });

  /// The operator's own ACTIVE accounts (only the owner writes).
  final List<FinancialAccount> accounts;

  /// Pre-filled start date (`YYYY-MM-DD`) of a new rule.
  final String initialStartDate;

  /// Non-null when editing: account, effect, currency and start are immutable.
  final FinancialRecurrence? existing;
  final String? existingAccountName;

  static const dialogKey = Key('financial-recurrence-editor');
  static const descriptionKey = Key('financial-recurrence-editor-description');
  static const accountKey = Key('financial-recurrence-editor-account');
  static const effectExpenseKey = Key('financial-recurrence-editor-expense');
  static const effectIncomeKey = Key('financial-recurrence-editor-income');
  static const amountKey = Key('financial-recurrence-editor-amount');
  static const startDateKey = Key('financial-recurrence-editor-start');
  static const dayKey = Key('financial-recurrence-editor-day');
  static const endDateKey = Key('financial-recurrence-editor-end');
  static const immutableKey = Key('financial-recurrence-editor-immutable');
  static const supersedeNoticeKey = Key(
    'financial-recurrence-editor-supersede-notice',
  );
  static const issuesKey = Key('financial-recurrence-editor-issues');
  static const saveKey = Key('financial-recurrence-editor-save');
  static const cancelKey = Key('financial-recurrence-editor-cancel');

  @override
  State<FinancialRecurrenceEditorDialog> createState() =>
      _FinancialRecurrenceEditorDialogState();
}

class _FinancialRecurrenceEditorDialogState
    extends State<FinancialRecurrenceEditorDialog> {
  late final TextEditingController _description;
  late final TextEditingController _amount;
  late final TextEditingController _startDate;
  late final TextEditingController _day;
  late final TextEditingController _endDate;
  String? _accountId;
  FinancialResultEffect _effect = FinancialResultEffect.expense;

  bool get _editing => widget.existing != null;

  @override
  void initState() {
    super.initState();
    final existing = widget.existing;
    _description = TextEditingController(text: existing?.description ?? '');
    _amount = TextEditingController(text: existing?.expected.amount ?? '');
    _startDate = TextEditingController(
      text: existing?.startDate ?? widget.initialStartDate,
    );
    _day = TextEditingController(text: existing?.dayOfMonth.toString() ?? '');
    _endDate = TextEditingController(text: existing?.endDate ?? '');
    _effect = existing?.resultEffect ?? FinancialResultEffect.expense;
    _accountId = existing?.accountId;
  }

  @override
  void dispose() {
    _description.dispose();
    _amount.dispose();
    _startDate.dispose();
    _day.dispose();
    _endDate.dispose();
    super.dispose();
  }

  FinancialAccount? get _account {
    final id = _accountId;
    if (id == null) return null;
    for (final account in widget.accounts) {
      if (account.accountId == id) return account;
    }
    return null;
  }

  List<FinancialRecurrenceDraftIssue> get _issues =>
      validateFinancialRecurrenceDraft(
        description: _description.text,
        accountId: _accountId,
        eligibleAccounts: widget.accounts,
        editing: _editing,
        amountText: _amount.text,
        startDate: _startDate.text,
        dayText: _day.text,
        endDate: _endDate.text,
      );

  void _save() {
    if (_issues.isNotEmpty) {
      setState(() {});
      return;
    }
    final existing = widget.existing;
    try {
      final amount = normalizeFinancialMoneyInput(_amount.text.trim());
      final day = int.parse(_day.text.trim());
      final end = _endDate.text.trim().isEmpty ? null : _endDate.text.trim();
      if (existing != null) {
        Navigator.of(context).pop(
          FinancialRecurrenceEditorReplace(
            FinancialRecurrenceReplaceInput(
              expectedVersion: existing.version,
              description: _description.text,
              expectedAmount: amount,
              dayOfMonth: day,
              endDate: end,
            ),
          ),
        );
        return;
      }
      final account = _account;
      if (account == null) {
        setState(() {});
        return;
      }
      Navigator.of(context).pop(
        FinancialRecurrenceEditorCreate(
          FinancialRecurrenceCreateInput(
            accountId: account.accountId,
            description: _description.text,
            resultEffect: _effect,
            expectedAmount: amount,
            currency: account.currency,
            startDate: _startDate.text.trim(),
            dayOfMonth: day,
            endDate: end,
          ),
        ),
      );
    } on FormatException {
      setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) {
    final existing = widget.existing;
    final issues = _issues;
    final currency = existing?.expected.currency ?? _account?.currency;
    return AlertDialog(
      key: FinancialRecurrenceEditorDialog.dialogKey,
      title: Text(_editing ? 'Editar recorrência' : 'Nova recorrência mensal'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(financialRecurrenceForecastNotice),
              const SizedBox(height: AppTokens.space16),
              TextField(
                key: FinancialRecurrenceEditorDialog.descriptionKey,
                controller: _description,
                maxLength: financialRecurrenceDescriptionMaxLength,
                decoration: const InputDecoration(
                  labelText: 'Descrição',
                  helperText:
                      'Também será a descrição do lançamento ao registrar.',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppTokens.space12),
              if (_editing)
                Container(
                  key: FinancialRecurrenceEditorDialog.immutableKey,
                  padding: const EdgeInsets.all(AppTokens.space12),
                  decoration: BoxDecoration(
                    color: AppTokens.neutral100,
                    borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
                  ),
                  child: Text(
                    'Conta: ${widget.existingAccountName ?? 'conta da recorrência'} · '
                    '${financialRecurrenceEffectLabel(existing!.resultEffect)} · '
                    '${existing.expected.currency} · início em '
                    '${financialRecurrenceDateLabel(existing.startDate)}. '
                    'Conta, tipo, moeda e início não mudam depois de criar.',
                  ),
                )
              else ...[
                InputDecorator(
                  decoration: const InputDecoration(labelText: 'Conta'),
                  child: DropdownButtonHideUnderline(
                    child: DropdownButton<String>(
                      key: FinancialRecurrenceEditorDialog.accountKey,
                      isExpanded: true,
                      value: _accountId,
                      hint: const Text('Escolha a conta'),
                      items: [
                        for (final account in widget.accounts)
                          DropdownMenuItem(
                            value: account.accountId,
                            child: Text(
                              '${account.name} · ${account.currency}',
                            ),
                          ),
                      ],
                      onChanged: (value) => setState(() => _accountId = value),
                    ),
                  ),
                ),
                const SizedBox(height: AppTokens.space12),
                SegmentedButton<FinancialResultEffect>(
                  segments: const [
                    ButtonSegment(
                      value: FinancialResultEffect.expense,
                      label: Text(
                        'Despesa',
                        key: FinancialRecurrenceEditorDialog.effectExpenseKey,
                      ),
                    ),
                    ButtonSegment(
                      value: FinancialResultEffect.income,
                      label: Text(
                        'Receita',
                        key: FinancialRecurrenceEditorDialog.effectIncomeKey,
                      ),
                    ),
                  ],
                  selected: {_effect},
                  onSelectionChanged: (selection) =>
                      setState(() => _effect = selection.first),
                ),
              ],
              const SizedBox(height: AppTokens.space12),
              TextField(
                key: FinancialRecurrenceEditorDialog.amountKey,
                controller: _amount,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: InputDecoration(
                  labelText:
                      'Valor esperado${currency == null ? '' : ' ($currency)'}',
                  helperText:
                      'É a previsão. O valor real é informado ao registrar.',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppTokens.space12),
              if (!_editing) ...[
                TextField(
                  key: FinancialRecurrenceEditorDialog.startDateKey,
                  controller: _startDate,
                  decoration: const InputDecoration(
                    labelText: 'Início (AAAA-MM-DD)',
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: AppTokens.space12),
              ],
              TextField(
                key: FinancialRecurrenceEditorDialog.dayKey,
                controller: _day,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Dia do mês (1 a 31)',
                  helperText:
                      'Se o dia não existir no mês, usa o último dia do mês.',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppTokens.space12),
              TextField(
                key: FinancialRecurrenceEditorDialog.endDateKey,
                controller: _endDate,
                decoration: const InputDecoration(
                  labelText: 'Término (AAAA-MM-DD, opcional)',
                ),
                onChanged: (_) => setState(() {}),
              ),
              if (_editing) ...[
                const SizedBox(height: AppTokens.space12),
                const Text(
                  'Ao salvar, previsões futuras que não combinarem mais com a '
                  'nova versão serão marcadas como substituídas; as já '
                  'registradas ou puladas não mudam. Gere o mês de novo '
                  'depois, se precisar.',
                  key: FinancialRecurrenceEditorDialog.supersedeNoticeKey,
                ),
              ],
              if (issues.isNotEmpty) ...[
                const SizedBox(height: AppTokens.space12),
                Column(
                  key: FinancialRecurrenceEditorDialog.issuesKey,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final issue in issues)
                      Text(
                        financialRecurrenceDraftIssueLabel(issue),
                        style: const TextStyle(color: AppTokens.red700),
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: FinancialRecurrenceEditorDialog.cancelKey,
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialRecurrenceEditorDialog.saveKey,
          onPressed: issues.isEmpty ? _save : null,
          child: Text(_editing ? 'Salvar alterações' : 'Criar recorrência'),
        ),
      ],
    );
  }
}
