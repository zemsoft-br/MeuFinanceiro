import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// The built, validated request the editor hands back. The caller sends it once.
sealed class FinancialBudgetEditorResult {
  const FinancialBudgetEditorResult();
}

class FinancialBudgetEditorCreate extends FinancialBudgetEditorResult {
  const FinancialBudgetEditorCreate(this.input);
  final FinancialBudgetCreateInput input;
}

class FinancialBudgetEditorReplace extends FinancialBudgetEditorResult {
  const FinancialBudgetEditorReplace(this.input);
  final FinancialBudgetReplaceInput input;
}

/// Create/edit form of a monthly budget. It holds only a local draft; nothing
/// is sent until the user confirms, and the dialog never decides a financial
/// rule: eligible categories mirror the contract and the server validates again.
class FinancialBudgetEditorDialog extends StatefulWidget {
  const FinancialBudgetEditorDialog({
    required this.period,
    required this.operatorId,
    required this.index,
    this.existing,
    super.key,
  });

  /// The month the budget belongs to (`YYYY-MM`).
  final String period;
  final String operatorId;
  final FinancialCategoryIndex index;

  /// Non-null when editing: scope, currency, month and basis are immutable.
  final FinancialBudget? existing;

  static const dialogKey = Key('financial-budget-editor');
  static const nameKey = Key('financial-budget-editor-name');
  static const scopeKey = Key('financial-budget-editor-scope');
  static const currencyKey = Key('financial-budget-editor-currency');
  static const basisCashKey = Key('financial-budget-editor-basis-cash');
  static const basisCompetenceKey = Key(
    'financial-budget-editor-basis-competence',
  );
  static const addLineKey = Key('financial-budget-editor-add-line');
  static const issuesKey = Key('financial-budget-editor-issues');
  static const scopeNoticeKey = Key('financial-budget-editor-scope-notice');
  static const saveKey = Key('financial-budget-editor-save');
  static const cancelKey = Key('financial-budget-editor-cancel');
  static Key lineKey(int index) => Key('financial-budget-editor-line-$index');
  static Key effectKey(int index) =>
      Key('financial-budget-editor-effect-$index');
  static Key categoryKey(int index) =>
      Key('financial-budget-editor-category-$index');
  static Key plannedKey(int index) =>
      Key('financial-budget-editor-planned-$index');
  static Key removeKey(int index) =>
      Key('financial-budget-editor-remove-$index');
  static Key unavailableKey(int index) =>
      Key('financial-budget-editor-unavailable-$index');

  @override
  State<FinancialBudgetEditorDialog> createState() =>
      _FinancialBudgetEditorDialogState();
}

class _FinancialBudgetEditorDialogState
    extends State<FinancialBudgetEditorDialog> {
  late final TextEditingController _name;
  late final TextEditingController _currency;
  late FinancialVisibilityScope _scope;
  late FinancialBudgetDateBasis _basis;
  late List<FinancialBudgetDraftLine> _lines;
  late List<TextEditingController> _planned;

  bool get _editing => widget.existing != null;

  @override
  void initState() {
    super.initState();
    final existing = widget.existing;
    _name = TextEditingController(text: existing?.name ?? '');
    _currency = TextEditingController(text: existing?.currency ?? 'BRL');
    _scope = existing?.visibilityScope ?? FinancialVisibilityScope.household;
    _basis = existing?.dateBasis ?? FinancialBudgetDateBasis.cash;
    _lines = [
      if (existing != null)
        for (final line in existing.lines)
          FinancialBudgetDraftLine(
            categoryId: line.categoryId,
            resultEffect: line.resultEffect,
            plannedText: line.planned.amount,
          )
      else
        const FinancialBudgetDraftLine(),
    ];
    _planned = [
      for (final line in _lines) TextEditingController(text: line.plannedText),
    ];
  }

  @override
  void dispose() {
    _name.dispose();
    _currency.dispose();
    for (final controller in _planned) {
      controller.dispose();
    }
    super.dispose();
  }

  String get _owner => widget.existing?.ownerOperatorId ?? widget.operatorId;

  List<FinancialBudgetDraftIssue> get _issues => validateFinancialBudgetDraft(
    name: _name.text,
    lines: _lines,
    scope: _scope,
    ownerOperatorId: _owner,
    index: widget.index,
  );

  bool get _currencyValid => RegExp(r'^[A-Z]{3}$').hasMatch(_currency.text);

  void _setScope(FinancialVisibilityScope scope) {
    setState(() {
      _scope = scope;
      // A category of the other audience can never be used: drop it.
      _lines = [
        for (final line in _lines)
          line.categoryId != null &&
                  !_isEligible(line.categoryId!, scopeOverride: scope)
              ? line.copyWith(categoryId: null)
              : line,
      ];
    });
  }

  bool _isEligible(
    String categoryId, {
    FinancialVisibilityScope? scopeOverride,
  }) {
    final category = widget.index.byId(categoryId);
    return category != null &&
        isFinancialCategoryEligibleForBudget(
          category: category,
          scope: scopeOverride ?? _scope,
          ownerOperatorId: _owner,
        );
  }

  void _addLine() {
    if (_lines.length >= financialBudgetLinesMax) return;
    setState(() {
      _lines = [..._lines, const FinancialBudgetDraftLine()];
      _planned.add(TextEditingController());
    });
  }

  void _removeLine(int index) {
    setState(() {
      _lines = [..._lines]..removeAt(index);
      _planned.removeAt(index).dispose();
    });
  }

  void _updateLine(int index, FinancialBudgetDraftLine line) {
    setState(() => _lines = [..._lines]..[index] = line);
  }

  void _submit() {
    if (_issues.isNotEmpty || (!_editing && !_currencyValid)) return;
    try {
      final lines = [
        for (final line in _lines)
          FinancialBudgetLineInput(
            categoryId: line.categoryId!,
            resultEffect: line.resultEffect,
            plannedAmount: normalizeFinancialMoneyInput(
              line.plannedText.trim(),
            ),
          ),
      ];
      final existing = widget.existing;
      final result = existing == null
          ? FinancialBudgetEditorCreate(
              FinancialBudgetCreateInput(
                name: _name.text,
                visibilityScope: _scope,
                currency: _currency.text,
                period: widget.period,
                dateBasis: _basis,
                lines: lines,
              ),
            )
          : FinancialBudgetEditorReplace(
              FinancialBudgetReplaceInput(
                expectedVersion: existing.version,
                name: _name.text,
                currency: existing.currency,
                lines: lines,
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
    final canSave = issues.isEmpty && (_editing || _currencyValid);
    final period = financialBudgetPeriodLabel(widget.period);
    return AlertDialog(
      key: FinancialBudgetEditorDialog.dialogKey,
      title: Text(_editing ? 'Editar orçamento' : 'Novo orçamento'),
      content: SizedBox(
        width: 720,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Planejamento de $period. O realizado é sempre calculado a '
                'partir do extrato e da classificação atual; este orçamento '
                'não cria lançamentos nem altera saldos.',
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
              ),
              const SizedBox(height: AppTokens.space16),
              TextField(
                key: FinancialBudgetEditorDialog.nameKey,
                controller: _name,
                maxLength: financialBudgetNameMaxLength,
                decoration: const InputDecoration(labelText: 'Nome'),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppTokens.space12),
              _identityFields(),
              const SizedBox(height: AppTokens.space12),
              _scopeNotice(),
              const SizedBox(height: AppTokens.space16),
              Text('Linhas', style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: AppTokens.space8),
              for (var index = 0; index < _lines.length; index += 1)
                _lineEditor(index),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  key: FinancialBudgetEditorDialog.addLineKey,
                  onPressed: _lines.length >= financialBudgetLinesMax
                      ? null
                      : _addLine,
                  icon: const Icon(Icons.add_rounded),
                  label: const Text('Adicionar linha'),
                ),
              ),
              if (issues.isNotEmpty || (!_editing && !_currencyValid)) ...[
                const SizedBox(height: AppTokens.space8),
                Column(
                  key: FinancialBudgetEditorDialog.issuesKey,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (!_editing && !_currencyValid)
                      const Text('Informe a moeda com três letras (ex.: BRL).'),
                    for (final issue in {...issues})
                      Text(financialBudgetDraftIssueLabel(issue)),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: FinancialBudgetEditorDialog.cancelKey,
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialBudgetEditorDialog.saveKey,
          onPressed: canSave ? _submit : null,
          child: Text(_editing ? 'Salvar alterações' : 'Criar orçamento'),
        ),
      ],
    );
  }

  /// Which accounts will feed the realized, stated before anything is saved.
  /// While editing it is the scope the server declared; while creating it is the
  /// contract's mapping for the audience being chosen.
  Widget _scopeNotice() {
    final scope =
        widget.existing?.realizationAccountScope ??
        expectedBudgetRealizationAccountScope(_scope);
    return Container(
      key: FinancialBudgetEditorDialog.scopeNoticeKey,
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
            financialBudgetRealizationScopeLabel(scope),
            style: Theme.of(context).textTheme.labelLarge,
          ),
          const SizedBox(height: AppTokens.space4),
          Text(financialBudgetRealizationScopeNotice(scope)),
        ],
      ),
    );
  }

  Widget _identityFields() {
    if (_editing) {
      final existing = widget.existing!;
      return Wrap(
        spacing: AppTokens.space8,
        runSpacing: AppTokens.space8,
        children: [
          Chip(
            label: Text(financialBudgetScopeLabel(existing.visibilityScope)),
          ),
          Chip(label: Text(existing.currency)),
          Chip(label: Text(financialBudgetBasisLabel(existing.dateBasis))),
          const Text('Escopo, moeda, mês e base não mudam depois de criados.'),
        ],
      );
    }
    return Wrap(
      spacing: AppTokens.space16,
      runSpacing: AppTokens.space12,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        SizedBox(
          width: 200,
          child: InputDecorator(
            decoration: const InputDecoration(labelText: 'Escopo'),
            child: DropdownButtonHideUnderline(
              child: DropdownButton<FinancialVisibilityScope>(
                key: FinancialBudgetEditorDialog.scopeKey,
                value: _scope,
                isExpanded: true,
                items: [
                  for (final scope in financialBudgetCreationScopes)
                    DropdownMenuItem(
                      value: scope,
                      child: Text(financialBudgetScopeLabel(scope)),
                    ),
                ],
                onChanged: (scope) {
                  if (scope != null) _setScope(scope);
                },
              ),
            ),
          ),
        ),
        SizedBox(
          width: 120,
          child: TextField(
            key: FinancialBudgetEditorDialog.currencyKey,
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
        SegmentedButton<FinancialBudgetDateBasis>(
          segments: [
            ButtonSegment(
              value: FinancialBudgetDateBasis.cash,
              label: Text(
                financialBudgetBasisLabel(FinancialBudgetDateBasis.cash),
                key: FinancialBudgetEditorDialog.basisCashKey,
              ),
            ),
            ButtonSegment(
              value: FinancialBudgetDateBasis.competence,
              label: Text(
                financialBudgetBasisLabel(FinancialBudgetDateBasis.competence),
                key: FinancialBudgetEditorDialog.basisCompetenceKey,
              ),
            ),
          ],
          selected: {_basis},
          onSelectionChanged: (selection) =>
              setState(() => _basis = selection.single),
        ),
      ],
    );
  }

  Widget _lineEditor(int index) {
    final line = _lines[index];
    final categoryId = line.categoryId;
    final unavailable = categoryId != null && !_isEligible(categoryId);
    final options = eligibleFinancialBudgetCategories(
      index: widget.index,
      scope: _scope,
      ownerOperatorId: _owner,
    );
    final selectedUnavailable = unavailable
        ? widget.index.byId(categoryId)
        : null;
    return Padding(
      key: FinancialBudgetEditorDialog.lineKey(index),
      padding: const EdgeInsets.only(bottom: AppTokens.space12),
      child: Wrap(
        spacing: AppTokens.space12,
        runSpacing: AppTokens.space8,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          SizedBox(
            width: 140,
            child: InputDecorator(
              decoration: const InputDecoration(labelText: 'Tipo'),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<FinancialResultEffect>(
                  key: FinancialBudgetEditorDialog.effectKey(index),
                  value: line.resultEffect,
                  isExpanded: true,
                  items: const [
                    DropdownMenuItem(
                      value: FinancialResultEffect.expense,
                      child: Text('Despesa'),
                    ),
                    DropdownMenuItem(
                      value: FinancialResultEffect.income,
                      child: Text('Receita'),
                    ),
                  ],
                  onChanged: (effect) {
                    if (effect != null) {
                      _updateLine(index, line.copyWith(resultEffect: effect));
                    }
                  },
                ),
              ),
            ),
          ),
          SizedBox(
            width: 260,
            child: InputDecorator(
              decoration: const InputDecoration(labelText: 'Categoria'),
              child: DropdownButtonHideUnderline(
                child: DropdownButton<String>(
                  key: FinancialBudgetEditorDialog.categoryKey(index),
                  value: categoryId,
                  isExpanded: true,
                  hint: const Text('Escolha a categoria'),
                  items: [
                    if (selectedUnavailable != null)
                      DropdownMenuItem(
                        value: selectedUnavailable.categoryId,
                        child: Text(
                          '${widget.index.pathLabel(selectedUnavailable.categoryId) ?? selectedUnavailable.name} (indisponível)',
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    for (final category in options)
                      DropdownMenuItem(
                        value: category.categoryId,
                        child: Text(
                          widget.index.pathLabel(category.categoryId) ??
                              category.name,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                  onChanged: (selected) =>
                      _updateLine(index, line.copyWith(categoryId: selected)),
                ),
              ),
            ),
          ),
          SizedBox(
            width: 160,
            child: TextField(
              key: FinancialBudgetEditorDialog.plannedKey(index),
              controller: _planned[index],
              keyboardType: const TextInputType.numberWithOptions(
                decimal: true,
              ),
              decoration: InputDecoration(
                labelText: 'Planejado',
                prefixText: _editing
                    ? '${widget.existing!.currency} '
                    : (_currencyValid ? '${_currency.text} ' : null),
              ),
              onChanged: (text) =>
                  _updateLine(index, line.copyWith(plannedText: text)),
            ),
          ),
          IconButton(
            key: FinancialBudgetEditorDialog.removeKey(index),
            tooltip: 'Remover linha',
            onPressed: _lines.length > 1 ? () => _removeLine(index) : null,
            icon: const Icon(Icons.delete_outline_rounded),
          ),
          if (unavailable)
            Text(
              'Categoria indisponível para este orçamento: escolha outra.',
              key: FinancialBudgetEditorDialog.unavailableKey(index),
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: AppTokens.red700),
            ),
        ],
      ),
    );
  }
}
