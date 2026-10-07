import 'package:flutter/material.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_policy.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Confirmation that turns one forecast into a real Movement. It holds only a
/// local draft: nothing is sent until the user confirms, the amount may differ
/// from the forecast, and the dates are the user's (pre-filled, never implied).
class FinancialRecurrenceRealizeDialog extends StatefulWidget {
  const FinancialRecurrenceRealizeDialog({
    required this.occurrence,
    this.accountName,
    super.key,
  });

  final FinancialRecurrenceOccurrence occurrence;
  final String? accountName;

  static const dialogKey = Key('financial-recurrence-realize');
  static const noticeKey = Key('financial-recurrence-realize-notice');
  static const amountKey = Key('financial-recurrence-realize-amount');
  static const effectiveDateKey = Key('financial-recurrence-realize-effective');
  static const competenceDateKey = Key(
    'financial-recurrence-realize-competence',
  );
  static const issuesKey = Key('financial-recurrence-realize-issues');
  static const confirmKey = Key('financial-recurrence-realize-confirm');
  static const cancelKey = Key('financial-recurrence-realize-cancel');

  @override
  State<FinancialRecurrenceRealizeDialog> createState() =>
      _FinancialRecurrenceRealizeDialogState();
}

class _FinancialRecurrenceRealizeDialogState
    extends State<FinancialRecurrenceRealizeDialog> {
  late final TextEditingController _amount;
  late final TextEditingController _effective;
  late final TextEditingController _competence;

  @override
  void initState() {
    super.initState();
    final occurrence = widget.occurrence;
    _amount = TextEditingController(text: occurrence.expected.amount);
    _effective = TextEditingController(text: occurrence.scheduledDate);
    _competence = TextEditingController(text: occurrence.scheduledDate);
  }

  @override
  void dispose() {
    _amount.dispose();
    _effective.dispose();
    _competence.dispose();
    super.dispose();
  }

  List<FinancialRealizeDraftIssue> get _issues => validateFinancialRealizeDraft(
    amountText: _amount.text,
    effectiveDate: _effective.text,
    competenceDate: _competence.text,
  );

  void _confirm() {
    if (_issues.isNotEmpty) {
      setState(() {});
      return;
    }
    try {
      Navigator.of(context).pop(
        FinancialRecurrenceRealizeInput(
          actualAmount: normalizeFinancialMoneyInput(_amount.text.trim()),
          currency: widget.occurrence.expected.currency,
          effectiveDate: _effective.text.trim(),
          competenceDate: _competence.text.trim(),
        ),
      );
    } on FormatException {
      setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) {
    final occurrence = widget.occurrence;
    final issues = _issues;
    final effect = financialRecurrenceEffectLabel(occurrence.resultEffect);
    return AlertDialog(
      key: FinancialRecurrenceRealizeDialog.dialogKey,
      title: const Text('Registrar lançamento'),
      content: SizedBox(
        width: 480,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                occurrence.description,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: AppTokens.space4),
              Text(
                '$effect previsto para '
                '${financialRecurrenceDateLabel(occurrence.scheduledDate)} · '
                'previsto ${formatFinancialMoney(occurrence.expected)}'
                '${widget.accountName == null ? '' : ' · ${widget.accountName}'}',
              ),
              const SizedBox(height: AppTokens.space12),
              Container(
                key: FinancialRecurrenceRealizeDialog.noticeKey,
                padding: const EdgeInsets.all(AppTokens.space12),
                decoration: BoxDecoration(
                  color: AppTokens.amber50,
                  borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
                ),
                child: const Text(financialRecurrenceRealizeNotice),
              ),
              const SizedBox(height: AppTokens.space16),
              TextField(
                key: FinancialRecurrenceRealizeDialog.amountKey,
                controller: _amount,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: InputDecoration(
                  labelText: 'Valor real (${occurrence.expected.currency})',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppTokens.space12),
              TextField(
                key: FinancialRecurrenceRealizeDialog.effectiveDateKey,
                controller: _effective,
                decoration: const InputDecoration(
                  labelText: 'Data efetiva (AAAA-MM-DD)',
                  helperText: 'Quando o dinheiro entrou ou saiu da conta.',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppTokens.space12),
              TextField(
                key: FinancialRecurrenceRealizeDialog.competenceDateKey,
                controller: _competence,
                decoration: const InputDecoration(
                  labelText: 'Data de competência (AAAA-MM-DD)',
                  helperText: 'A que período este valor pertence.',
                ),
                onChanged: (_) => setState(() {}),
              ),
              if (issues.isNotEmpty) ...[
                const SizedBox(height: AppTokens.space12),
                Column(
                  key: FinancialRecurrenceRealizeDialog.issuesKey,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final issue in issues)
                      Text(
                        financialRealizeDraftIssueLabel(issue),
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
          key: FinancialRecurrenceRealizeDialog.cancelKey,
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialRecurrenceRealizeDialog.confirmKey,
          onPressed: issues.isEmpty ? _confirm : null,
          child: const Text('Registrar lançamento'),
        ),
      ],
    );
  }
}
