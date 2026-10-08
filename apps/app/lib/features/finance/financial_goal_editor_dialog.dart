import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// The built, validated request the editor hands back. The caller sends it once.
sealed class FinancialGoalEditorResult {
  const FinancialGoalEditorResult();
}

class FinancialGoalEditorCreate extends FinancialGoalEditorResult {
  const FinancialGoalEditorCreate(this.input);
  final FinancialGoalCreateInput input;
}

class FinancialGoalEditorReplace extends FinancialGoalEditorResult {
  const FinancialGoalEditorReplace(this.input);
  final FinancialGoalReplaceInput input;
}

/// Create/edit form of a goal's planning data. It holds only a local draft;
/// nothing is sent until the user confirms. It never decides a financial rule:
/// the server validates audience, currency, date and amounts again, and editing
/// the target never touches what was already allocated.
class FinancialGoalEditorDialog extends StatefulWidget {
  const FinancialGoalEditorDialog({
    required this.today,
    this.existing,
    super.key,
  });

  /// The local calendar day, used only to mirror the target-date range.
  final DateTime today;

  /// Non-null when editing: scope, owner and currency are immutable.
  final FinancialGoal? existing;

  static const dialogKey = Key('financial-goal-editor');
  static const titleKey = Key('financial-goal-editor-title');
  static const descriptionKey = Key('financial-goal-editor-description');
  static const scopeKey = Key('financial-goal-editor-scope');
  static const currencyKey = Key('financial-goal-editor-currency');
  static const targetKey = Key('financial-goal-editor-target');
  static const dateKey = Key('financial-goal-editor-date');
  static const issuesKey = Key('financial-goal-editor-issues');
  static const noticeKey = Key('financial-goal-editor-notice');
  static const saveKey = Key('financial-goal-editor-save');
  static const cancelKey = Key('financial-goal-editor-cancel');

  @override
  State<FinancialGoalEditorDialog> createState() =>
      _FinancialGoalEditorDialogState();
}

class _FinancialGoalEditorDialogState extends State<FinancialGoalEditorDialog> {
  late final TextEditingController _title;
  late final TextEditingController _description;
  late final TextEditingController _currency;
  late final TextEditingController _target;
  late final TextEditingController _date;
  late FinancialVisibilityScope _scope;

  bool get _editing => widget.existing != null;

  @override
  void initState() {
    super.initState();
    final existing = widget.existing;
    _title = TextEditingController(text: existing?.title ?? '');
    _description = TextEditingController(text: existing?.description ?? '');
    _currency = TextEditingController(text: existing?.currency ?? 'BRL');
    _target = TextEditingController(text: existing?.target.amount ?? '');
    _date = TextEditingController(text: existing?.targetDate ?? '');
    _scope = existing?.visibilityScope ?? FinancialVisibilityScope.household;
  }

  @override
  void dispose() {
    _title.dispose();
    _description.dispose();
    _currency.dispose();
    _target.dispose();
    _date.dispose();
    super.dispose();
  }

  List<FinancialGoalDraftIssue> get _issues => validateFinancialGoalDraft(
    title: _title.text,
    description: _description.text,
    currency: _currency.text,
    targetText: _target.text.trim(),
    targetDateText: _date.text,
    today: widget.today,
    existingTargetDate: widget.existing?.targetDate,
  );

  void _submit() {
    if (_issues.isNotEmpty) return;
    try {
      final target = normalizeFinancialMoneyInput(_target.text.trim());
      final date = _date.text.trim().isEmpty ? null : _date.text.trim();
      final existing = widget.existing;
      final result = existing == null
          ? FinancialGoalEditorCreate(
              FinancialGoalCreateInput(
                title: _title.text,
                description: _description.text,
                visibilityScope: _scope,
                currency: _currency.text,
                targetAmount: target,
                targetDate: date,
              ),
            )
          : FinancialGoalEditorReplace(
              FinancialGoalReplaceInput(
                expectedVersion: existing.version,
                title: _title.text,
                description: _description.text,
                currency: existing.currency,
                targetAmount: target,
                targetDate: date,
              ),
            );
      Navigator.of(context).pop(result);
    } on FormatException {
      // The validators above make this unreachable; stay in the form.
      setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) {
    final issues = _issues;
    final canSave = issues.isEmpty;
    final muted = Theme.of(
      context,
    ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700);
    return AlertDialog(
      key: FinancialGoalEditorDialog.dialogKey,
      title: Text(_editing ? 'Editar meta' : 'Nova meta'),
      content: SizedBox(
        width: 640,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                key: FinancialGoalEditorDialog.noticeKey,
                padding: const EdgeInsets.all(AppTokens.space12),
                decoration: BoxDecoration(
                  color: AppTokens.blue50,
                  border: Border.all(color: AppTokens.blue700),
                  borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
                ),
                child: const Text(
                  '$financialGoalVirtualNotice O valor-alvo é apenas '
                  'planejamento: só conta como destinado o que você destinar '
                  'explicitamente a partir do saldo de uma conta.',
                ),
              ),
              const SizedBox(height: AppTokens.space16),
              TextField(
                key: FinancialGoalEditorDialog.titleKey,
                controller: _title,
                maxLength: financialGoalTitleMaxLength,
                decoration: const InputDecoration(labelText: 'Título'),
                onChanged: (_) => setState(() {}),
              ),
              TextField(
                key: FinancialGoalEditorDialog.descriptionKey,
                controller: _description,
                maxLength: financialGoalDescriptionMaxLength,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: 'Descrição (opcional)',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppTokens.space8),
              _identityFields(muted),
              const SizedBox(height: AppTokens.space12),
              Wrap(
                spacing: AppTokens.space16,
                runSpacing: AppTokens.space12,
                children: [
                  SizedBox(
                    width: 240,
                    child: TextField(
                      key: FinancialGoalEditorDialog.targetKey,
                      controller: _target,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      inputFormatters: [
                        FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]')),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'Valor-alvo',
                        hintText: '0,00',
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                  SizedBox(
                    width: 240,
                    child: TextField(
                      key: FinancialGoalEditorDialog.dateKey,
                      controller: _date,
                      keyboardType: TextInputType.datetime,
                      inputFormatters: [
                        FilteringTextInputFormatter.allow(RegExp(r'[0-9-]')),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'Prazo (opcional)',
                        hintText: 'AAAA-MM-DD',
                      ),
                      onChanged: (_) => setState(() {}),
                    ),
                  ),
                ],
              ),
              if (_editing) ...[
                const SizedBox(height: AppTokens.space8),
                Text(
                  'Editar o alvo ou o prazo não apaga nem altera nenhuma '
                  'destinação já feita. Se o alvo ficar abaixo do destinado, '
                  'a meta passa a aparecer como acima do alvo, sem ajuste '
                  'automático.',
                  style: muted,
                ),
              ],
              if (issues.isNotEmpty) ...[
                const SizedBox(height: AppTokens.space12),
                Column(
                  key: FinancialGoalEditorDialog.issuesKey,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final issue in {...issues})
                      Text(financialGoalDraftIssueLabel(issue)),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: FinancialGoalEditorDialog.cancelKey,
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialGoalEditorDialog.saveKey,
          onPressed: canSave ? _submit : null,
          child: Text(_editing ? 'Salvar alterações' : 'Criar meta'),
        ),
      ],
    );
  }

  Widget _identityFields(TextStyle? muted) {
    if (_editing) {
      final existing = widget.existing!;
      return Wrap(
        spacing: AppTokens.space8,
        runSpacing: AppTokens.space8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Chip(label: Text(financialGoalScopeLabel(existing.visibilityScope))),
          Chip(label: Text(existing.currency)),
          Text('Audiência e moeda não mudam depois de criadas.', style: muted),
        ],
      );
    }
    return Wrap(
      spacing: AppTokens.space16,
      runSpacing: AppTokens.space12,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        SizedBox(
          width: 220,
          child: InputDecorator(
            decoration: const InputDecoration(labelText: 'Audiência'),
            child: DropdownButtonHideUnderline(
              child: DropdownButton<FinancialVisibilityScope>(
                key: FinancialGoalEditorDialog.scopeKey,
                value: _scope,
                isExpanded: true,
                items: [
                  for (final scope in financialGoalCreationScopes)
                    DropdownMenuItem(
                      value: scope,
                      child: Text(financialGoalScopeLabel(scope)),
                    ),
                ],
                onChanged: (scope) {
                  if (scope != null) setState(() => _scope = scope);
                },
              ),
            ),
          ),
        ),
        SizedBox(
          width: 120,
          child: TextField(
            key: FinancialGoalEditorDialog.currencyKey,
            controller: _currency,
            maxLength: 3,
            textCapitalization: TextCapitalization.characters,
            inputFormatters: [
              FilteringTextInputFormatter.allow(RegExp('[A-Za-z]')),
              TextInputFormatter.withFunction(
                (old, value) => value.copyWith(text: value.text.toUpperCase()),
              ),
            ],
            decoration: const InputDecoration(labelText: 'Moeda'),
            onChanged: (_) => setState(() {}),
          ),
        ),
        Text(
          _scope == FinancialVisibilityScope.household
              ? 'Meta da casa: todos os membros ativos veem; só você edita e '
                    'destina, usando suas contas da casa.'
              : 'Meta pessoal: só você vê, edita e destina, usando suas contas '
                    'pessoais.',
          style: muted,
        ),
      ],
    );
  }
}
