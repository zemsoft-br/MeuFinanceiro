import 'package:flutter/material.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_policy.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Review of the recurrence a suggestion proposes. It holds only a local draft:
/// nothing is sent until the user confirms. Account, effect and currency come from
/// the suggestion and cannot be changed here; the server validates everything again
/// and decides the dates. The dialog never detects or computes a financial rule.
class FinancialRecurrenceSuggestionReviewDialog extends StatefulWidget {
  const FinancialRecurrenceSuggestionReviewDialog({
    required this.suggestion,
    required this.accountName,
    super.key,
  });

  final FinancialRecurrenceSuggestion suggestion;
  final String? accountName;

  static const dialogKey = Key('financial-suggestion-review');
  static const noticeKey = Key('financial-suggestion-review-notice');
  static const fixedKey = Key('financial-suggestion-review-fixed');
  static const descriptionKey = Key('financial-suggestion-review-description');
  static const amountKey = Key('financial-suggestion-review-amount');
  static const startDateKey = Key('financial-suggestion-review-start');
  static const dayKey = Key('financial-suggestion-review-day');
  static const endDateKey = Key('financial-suggestion-review-end');
  static const issuesKey = Key('financial-suggestion-review-issues');
  static const confirmKey = Key('financial-suggestion-review-confirm');
  static const cancelKey = Key('financial-suggestion-review-cancel');

  @override
  State<FinancialRecurrenceSuggestionReviewDialog> createState() =>
      _FinancialRecurrenceSuggestionReviewDialogState();
}

class _FinancialRecurrenceSuggestionReviewDialogState
    extends State<FinancialRecurrenceSuggestionReviewDialog> {
  late final TextEditingController _description;
  late final TextEditingController _amount;
  late final TextEditingController _startDate;
  late final TextEditingController _day;
  late final TextEditingController _endDate;

  @override
  void initState() {
    super.initState();
    final suggestion = widget.suggestion;
    _description = TextEditingController(text: suggestion.description);
    _amount = TextEditingController(
      text: suggestion.suggestedExpectedAmount.amount,
    );
    _startDate = TextEditingController(
      text: financialSuggestionDefaultStartDate(suggestion.lastObservedDate),
    );
    _day = TextEditingController(
      text: suggestion.suggestedDayOfMonth.toString(),
    );
    _endDate = TextEditingController();
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

  List<FinancialRecurrenceDraftIssue> get _issues {
    final issues = validateFinancialRecurrenceDraft(
      description: _description.text,
      accountId: widget.suggestion.accountId,
      eligibleAccounts: const [],
      editing: true,
      amountText: _amount.text,
      startDate: _startDate.text,
      dayText: _day.text,
      endDate: _endDate.text,
    );
    // `editing: true` skips the account and start checks (the account is fixed by
    // the suggestion), so the start date is validated here.
    if (!isFinancialRecurrenceDate(_startDate.text.trim())) {
      issues.add(FinancialRecurrenceDraftIssue.startDateInvalid);
    } else if (_endDate.text.trim().isNotEmpty &&
        isFinancialRecurrenceDate(_endDate.text.trim()) &&
        _endDate.text.trim().compareTo(_startDate.text.trim()) < 0 &&
        !issues.contains(FinancialRecurrenceDraftIssue.endBeforeStart)) {
      issues.add(FinancialRecurrenceDraftIssue.endBeforeStart);
    }
    return issues;
  }

  void _confirm() {
    if (_issues.isNotEmpty) {
      setState(() {});
      return;
    }
    final suggestion = widget.suggestion;
    try {
      final end = _endDate.text.trim().isEmpty ? null : _endDate.text.trim();
      Navigator.of(context).pop(
        FinancialRecurrenceSuggestionAcceptInput(
          fingerprint: suggestion.fingerprint,
          accountId: suggestion.accountId,
          currency: suggestion.currency,
          description: _description.text,
          expectedAmount: normalizeFinancialMoneyInput(_amount.text.trim()),
          startDate: _startDate.text.trim(),
          dayOfMonth: int.parse(_day.text.trim()),
          endDate: end,
        ),
      );
    } on FormatException {
      setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) {
    final issues = _issues;
    final suggestion = widget.suggestion;
    return AlertDialog(
      key: FinancialRecurrenceSuggestionReviewDialog.dialogKey,
      title: const Text('Criar recorrência a partir da sugestão'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                financialRecurrenceSuggestionReviewNotice,
                key: FinancialRecurrenceSuggestionReviewDialog.noticeKey,
              ),
              const SizedBox(height: AppTokens.space12),
              Container(
                key: FinancialRecurrenceSuggestionReviewDialog.fixedKey,
                padding: const EdgeInsets.all(AppTokens.space12),
                decoration: BoxDecoration(
                  color: AppTokens.neutral100,
                  borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
                ),
                child: Text(
                  'Conta: ${widget.accountName ?? 'conta da sugestão'} · '
                  'Despesa · ${suggestion.currency}. Estes três dados vêm da '
                  'sugestão e não mudam.',
                ),
              ),
              const SizedBox(height: AppTokens.space12),
              TextField(
                key: FinancialRecurrenceSuggestionReviewDialog.descriptionKey,
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
              TextField(
                key: FinancialRecurrenceSuggestionReviewDialog.amountKey,
                controller: _amount,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: InputDecoration(
                  labelText: 'Valor esperado (${suggestion.currency})',
                  helperText: suggestion.isVariable
                      ? 'O valor variou: confira o histórico antes de '
                            'confirmar. É só a previsão.'
                      : 'É a previsão. O valor real é informado ao registrar.',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppTokens.space12),
              TextField(
                key: FinancialRecurrenceSuggestionReviewDialog.startDateKey,
                controller: _startDate,
                decoration: const InputDecoration(
                  labelText: 'Início (AAAA-MM-DD)',
                  helperText:
                      'Sugerido: o mês seguinte à última cobrança observada.',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppTokens.space12),
              TextField(
                key: FinancialRecurrenceSuggestionReviewDialog.dayKey,
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
                key: FinancialRecurrenceSuggestionReviewDialog.endDateKey,
                controller: _endDate,
                decoration: const InputDecoration(
                  labelText: 'Término (AAAA-MM-DD, opcional)',
                ),
                onChanged: (_) => setState(() {}),
              ),
              if (issues.isNotEmpty) ...[
                const SizedBox(height: AppTokens.space12),
                Column(
                  key: FinancialRecurrenceSuggestionReviewDialog.issuesKey,
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
          key: FinancialRecurrenceSuggestionReviewDialog.cancelKey,
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialRecurrenceSuggestionReviewDialog.confirmKey,
          onPressed: issues.isEmpty ? _confirm : null,
          child: const Text('Criar recorrência'),
        ),
      ],
    );
  }
}
