import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';

/// Ergonomic mirror of the budget contract (ADR-0026). The backend stays the
/// final authority on audience, ownership, category eligibility, the CAS
/// version, the currency and every amount; this only keeps obviously invalid
/// options out of the UI. It never computes a realized amount, a remaining
/// value, a status or a percentage.

const _monthNames = <String>[
  'janeiro',
  'fevereiro',
  'março',
  'abril',
  'maio',
  'junho',
  'julho',
  'agosto',
  'setembro',
  'outubro',
  'novembro',
  'dezembro',
];

/// `YYYY-MM` of [now] (local calendar).
String currentFinancialBudgetPeriod(DateTime now) =>
    '${now.year.toString().padLeft(4, '0')}-${now.month.toString().padLeft(2, '0')}';

/// The month [delta] months away from [period] (`YYYY-MM`). Calendar math only.
String shiftFinancialBudgetPeriod(String period, int delta) {
  final year = int.parse(period.substring(0, 4));
  final month = int.parse(period.substring(5, 7));
  final index = year * 12 + (month - 1) + delta;
  final shiftedYear = index ~/ 12;
  final shiftedMonth = index % 12 + 1;
  return '${shiftedYear.toString().padLeft(4, '0')}-${shiftedMonth.toString().padLeft(2, '0')}';
}

/// "outubro de 2026".
String financialBudgetPeriodLabel(String period) {
  final year = period.substring(0, 4);
  final month = int.parse(period.substring(5, 7));
  return '${_monthNames[month - 1]} de $year';
}

String financialBudgetScopeLabel(FinancialVisibilityScope scope) =>
    switch (scope) {
      FinancialVisibilityScope.personal => 'Pessoal',
      FinancialVisibilityScope.household => 'Da casa',
      FinancialVisibilityScope.shared => 'Compartilhado',
    };

String financialBudgetBasisLabel(FinancialBudgetDateBasis basis) =>
    switch (basis) {
      FinancialBudgetDateBasis.cash => 'Caixa',
      FinancialBudgetDateBasis.competence => 'Competência',
    };

String financialBudgetBasisHint(FinancialBudgetDateBasis basis) =>
    switch (basis) {
      FinancialBudgetDateBasis.cash => 'pela data efetiva (caixa)',
      FinancialBudgetDateBasis.competence => 'pela data de competência',
    };

String financialBudgetEffectLabel(FinancialResultEffect effect) =>
    switch (effect) {
      FinancialResultEffect.income => 'Receita',
      FinancialResultEffect.expense => 'Despesa',
      FinancialResultEffect.neutral => 'Neutro',
    };

/// Status text that never depends on colour. "Acima" is a fact about the plan,
/// so an INCOME line that is over reads as above the forecast, not as a problem.
String financialBudgetStatusLabel(
  FinancialResultEffect effect,
  FinancialBudgetLineStatus status,
) => switch ((effect, status)) {
  (FinancialResultEffect.expense, FinancialBudgetLineStatus.under) =>
    'Dentro do planejado',
  (FinancialResultEffect.expense, FinancialBudgetLineStatus.at) => 'No limite',
  (FinancialResultEffect.expense, FinancialBudgetLineStatus.over) =>
    'Estourou o planejado',
  (_, FinancialBudgetLineStatus.under) => 'Abaixo do previsto',
  (_, FinancialBudgetLineStatus.at) => 'Meta atingida',
  (_, FinancialBudgetLineStatus.over) => 'Acima do previsto',
};

/// Fraction of the bar, `0..1`, from the server's `progressPercent` text using
/// integer parsing only (no money arithmetic, no `double` parsing of amounts).
double financialBudgetProgressFraction(String progressPercent) {
  final negative = progressPercent.startsWith('-');
  if (negative) return 0;
  final digits = progressPercent.replaceAll('.', '');
  final hundredths = int.tryParse(digits);
  if (hundredths == null) return 0;
  if (hundredths >= 10000) return 1;
  return hundredths / 10000;
}

/// "30%" style label from the server text (drops a redundant `.00`).
String financialBudgetProgressLabel(String progressPercent) {
  final trimmed = progressPercent.endsWith('.00')
      ? progressPercent.substring(0, progressPercent.length - 3)
      : progressPercent;
  return '$trimmed%';
}

/// A line category must be ACTIVE and match the budget audience exactly:
/// PERSONAL budget -> PERSONAL category of the same owner; HOUSEHOLD budget ->
/// HOUSEHOLD category. Descendants are never implied (exact category only).
bool isFinancialCategoryEligibleForBudget({
  required FinancialCategory category,
  required FinancialVisibilityScope scope,
  required String ownerOperatorId,
}) {
  if (!category.isActive) return false;
  return switch (scope) {
    FinancialVisibilityScope.household =>
      category.visibilityScope == FinancialVisibilityScope.household,
    FinancialVisibilityScope.personal =>
      category.visibilityScope == FinancialVisibilityScope.personal &&
          category.ownerOperatorId == ownerOperatorId,
    FinancialVisibilityScope.shared => false,
  };
}

List<FinancialCategory> eligibleFinancialBudgetCategories({
  required FinancialCategoryIndex index,
  required FinancialVisibilityScope scope,
  required String ownerOperatorId,
}) {
  final eligible = index.all
      .where(
        (category) => isFinancialCategoryEligibleForBudget(
          category: category,
          scope: scope,
          ownerOperatorId: ownerOperatorId,
        ),
      )
      .toList();
  eligible.sort((a, b) {
    final byPath = (index.pathLabel(a.categoryId) ?? a.name)
        .toLowerCase()
        .compareTo((index.pathLabel(b.categoryId) ?? b.name).toLowerCase());
    return byPath != 0 ? byPath : a.categoryId.compareTo(b.categoryId);
  });
  return List.unmodifiable(eligible);
}

/// Audiences a new budget may be created for. SHARED does not exist in v1.
const financialBudgetCreationScopes = <FinancialVisibilityScope>[
  FinancialVisibilityScope.personal,
  FinancialVisibilityScope.household,
];

/// One editable line of the draft. Amount is the user's text.
class FinancialBudgetDraftLine {
  const FinancialBudgetDraftLine({
    this.categoryId,
    this.resultEffect = FinancialResultEffect.expense,
    this.plannedText = '',
  });

  final String? categoryId;
  final FinancialResultEffect resultEffect;
  final String plannedText;

  FinancialBudgetDraftLine copyWith({
    Object? categoryId = _unset,
    FinancialResultEffect? resultEffect,
    String? plannedText,
  }) => FinancialBudgetDraftLine(
    categoryId: identical(categoryId, _unset)
        ? this.categoryId
        : categoryId as String?,
    resultEffect: resultEffect ?? this.resultEffect,
    plannedText: plannedText ?? this.plannedText,
  );
}

const Object _unset = Object();

/// Why a draft cannot be sent. Empty when it can.
enum FinancialBudgetDraftIssue {
  nameRequired,
  noLines,
  tooManyLines,
  categoryRequired,
  categoryUnavailable,
  plannedInvalid,
  duplicateLine,
}

List<FinancialBudgetDraftIssue> validateFinancialBudgetDraft({
  required String name,
  required List<FinancialBudgetDraftLine> lines,
  required FinancialVisibilityScope scope,
  required String ownerOperatorId,
  required FinancialCategoryIndex index,
}) {
  final issues = <FinancialBudgetDraftIssue>[];
  final trimmed = name.trim();
  if (trimmed.isEmpty || trimmed.length > financialBudgetNameMaxLength) {
    issues.add(FinancialBudgetDraftIssue.nameRequired);
  }
  if (lines.isEmpty) issues.add(FinancialBudgetDraftIssue.noLines);
  if (lines.length > financialBudgetLinesMax) {
    issues.add(FinancialBudgetDraftIssue.tooManyLines);
  }
  final seen = <String>{};
  var duplicate = false;
  for (final line in lines) {
    final id = line.categoryId;
    if (id == null) {
      issues.add(FinancialBudgetDraftIssue.categoryRequired);
    } else {
      final category = index.byId(id);
      if (category == null ||
          !isFinancialCategoryEligibleForBudget(
            category: category,
            scope: scope,
            ownerOperatorId: ownerOperatorId,
          )) {
        issues.add(FinancialBudgetDraftIssue.categoryUnavailable);
      }
      if (!seen.add('$id|${line.resultEffect.wireValue}')) duplicate = true;
    }
    if (validateFinancialMoneyInput(line.plannedText, requirePositive: true) !=
        null) {
      issues.add(FinancialBudgetDraftIssue.plannedInvalid);
    }
  }
  if (duplicate) issues.add(FinancialBudgetDraftIssue.duplicateLine);
  return issues;
}

String financialBudgetDraftIssueLabel(FinancialBudgetDraftIssue issue) =>
    switch (issue) {
      FinancialBudgetDraftIssue.nameRequired =>
        'Informe um nome de até $financialBudgetNameMaxLength caracteres.',
      FinancialBudgetDraftIssue.noLines => 'Adicione ao menos uma linha.',
      FinancialBudgetDraftIssue.tooManyLines =>
        'No máximo $financialBudgetLinesMax linhas.',
      FinancialBudgetDraftIssue.categoryRequired =>
        'Escolha a categoria de cada linha.',
      FinancialBudgetDraftIssue.categoryUnavailable =>
        'Há uma categoria indisponível: troque por uma categoria ativa '
            'compatível com este orçamento.',
      FinancialBudgetDraftIssue.plannedInvalid =>
        'Informe um valor planejado positivo em cada linha.',
      FinancialBudgetDraftIssue.duplicateLine =>
        'Cada categoria só pode ter uma linha por tipo (receita/despesa).',
    };
