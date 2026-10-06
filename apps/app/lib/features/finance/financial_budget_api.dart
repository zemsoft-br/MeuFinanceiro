part of 'financial_core_api.dart';

// Monthly category budgets (#252). A budget is planning, never a ledger: this
// file only validates wire shapes and builds requests. Realized amounts,
// remaining, status and percent are decided by the backend (derived from the
// ledger and the current classification on every read); nothing here computes a
// financial rule. Money is always decimal text, never double.

const _budgetKeys = <String>{
  'id',
  'ownerOperatorId',
  'visibilityScope',
  'name',
  'currency',
  'periodKind',
  'periodStart',
  'periodEnd',
  'dateBasis',
  'version',
  'createdAt',
  'updatedAt',
  'canEdit',
  'lines',
};
const _budgetsKeys = <String>{'items'};
const _budgetLineKeys = <String>{'categoryId', 'resultEffect', 'planned'};
const _budgetSummaryKeys = <String>{'budget', 'lines', 'coverage'};
const _budgetLineSummaryKeys = <String>{
  'categoryId',
  'resultEffect',
  'planned',
  'realized',
  'remaining',
  'status',
  'progressPercent',
};
const _budgetCoverageKeys = <String>{
  'unclassifiedExpenseCount',
  'unclassifiedExpenseAmount',
  'unclassifiedIncomeCount',
  'unclassifiedIncomeAmount',
};
final _budgetPeriodPattern = RegExp(r'^[0-9]{4}-(0[1-9]|1[0-2])$');
final _budgetPercentPattern = RegExp(r'^-?[0-9]{1,18}\.[0-9]{2}$');

/// Server-side cap on lines per budget.
const financialBudgetLinesMax = 100;
const financialBudgetNameMaxLength = 96;

enum FinancialBudgetDateBasis {
  cash('CASH'),
  competence('COMPETENCE');

  const FinancialBudgetDateBasis(this.wireValue);
  final String wireValue;

  static FinancialBudgetDateBasis parse(Object? value) =>
      _enumByWire(values, value, 'dateBasis', (item) => item.wireValue);
}

/// Realized compared with planned. A statement of fact, not a judgement: an
/// INCOME line that is OVER is good news.
enum FinancialBudgetLineStatus {
  under('UNDER'),
  at('AT'),
  over('OVER');

  const FinancialBudgetLineStatus(this.wireValue);
  final String wireValue;

  static FinancialBudgetLineStatus parse(Object? value) =>
      _enumByWire(values, value, 'status', (item) => item.wireValue);
}

class FinancialBudgetLine {
  const FinancialBudgetLine({
    required this.categoryId,
    required this.resultEffect,
    required this.planned,
  });

  final String categoryId;
  final FinancialResultEffect resultEffect;
  final FinancialMoneyWire planned;
}

class FinancialBudget {
  const FinancialBudget({
    required this.id,
    required this.ownerOperatorId,
    required this.visibilityScope,
    required this.name,
    required this.currency,
    required this.periodStart,
    required this.periodEnd,
    required this.dateBasis,
    required this.version,
    required this.createdAt,
    required this.updatedAt,
    required this.canEdit,
    required this.lines,
  });

  final String id;
  final String ownerOperatorId;
  final FinancialVisibilityScope visibilityScope;
  final String name;
  final String currency;

  /// First day of the month (`YYYY-MM-DD`) and the exclusive end, both
  /// server-derived.
  final String periodStart;
  final String periodEnd;
  final FinancialBudgetDateBasis dateBasis;

  /// CAS token: the only valid `expectedVersion` of the next edit.
  final int version;
  final DateTime createdAt;
  final DateTime updatedAt;

  /// Decided by the server: the operator owns this budget. Reading a HOUSEHOLD
  /// budget never implies write access.
  final bool canEdit;
  final List<FinancialBudgetLine> lines;

  /// `YYYY-MM`.
  String get period => periodStart.substring(0, 7);
}

class FinancialBudgetLineSummary {
  const FinancialBudgetLineSummary({
    required this.categoryId,
    required this.resultEffect,
    required this.planned,
    required this.realized,
    required this.remaining,
    required this.status,
    required this.progressPercent,
  });

  final String categoryId;
  final FinancialResultEffect resultEffect;
  final FinancialMoneyWire planned;

  /// Derived by the server. May be zero, and negative when a reversal landed
  /// in a later month than the original.
  final FinancialMoneyWire realized;
  final FinancialMoneyWire remaining;
  final FinancialBudgetLineStatus status;

  /// Decimal text with two places, e.g. `30.00`; may exceed `100.00`.
  final String progressPercent;
}

/// Unclassified INCOME/EXPENSE in the period, currency and audience. Never
/// attributed to a line: it only says the realized may be incomplete.
class FinancialBudgetCoverage {
  const FinancialBudgetCoverage({
    required this.unclassifiedExpenseCount,
    required this.unclassifiedExpenseAmount,
    required this.unclassifiedIncomeCount,
    required this.unclassifiedIncomeAmount,
  });

  final int unclassifiedExpenseCount;
  final FinancialMoneyWire unclassifiedExpenseAmount;
  final int unclassifiedIncomeCount;
  final FinancialMoneyWire unclassifiedIncomeAmount;

  bool get isIncomplete =>
      unclassifiedExpenseCount > 0 || unclassifiedIncomeCount > 0;
}

class FinancialBudgetSummary {
  const FinancialBudgetSummary({
    required this.budget,
    required this.lines,
    required this.coverage,
  });

  final FinancialBudget budget;
  final List<FinancialBudgetLineSummary> lines;
  final FinancialBudgetCoverage coverage;
}

class FinancialBudgetLineInput {
  FinancialBudgetLineInput({
    required String categoryId,
    required this.resultEffect,
    required String plannedAmount,
  }) : categoryId = _financialResourceId(categoryId, 'categoryId'),
       plannedAmount = _positiveDecimalAmount(plannedAmount, 'plannedAmount') {
    if (resultEffect == FinancialResultEffect.neutral) {
      throw const FormatException('resultEffect is invalid.');
    }
    if (this.plannedAmount.startsWith('-')) {
      throw const FormatException('plannedAmount must be positive.');
    }
  }

  final String categoryId;
  final FinancialResultEffect resultEffect;
  final String plannedAmount;

  String get key => '$categoryId|${resultEffect.wireValue}';

  Map<String, Object?> toJson() => {
    'categoryId': categoryId,
    'resultEffect': resultEffect.wireValue,
    'plannedAmount': plannedAmount,
  };
}

List<FinancialBudgetLineInput> _checkedBudgetLines(
  List<FinancialBudgetLineInput> lines,
) {
  if (lines.isEmpty || lines.length > financialBudgetLinesMax) {
    throw const FormatException('lines is invalid.');
  }
  final keys = lines.map((line) => line.key).toSet();
  if (keys.length != lines.length) {
    throw const FormatException('budget lines must be unique.');
  }
  // Order never changes the meaning of a request: keep it canonical.
  final sorted = [...lines]..sort((a, b) => a.key.compareTo(b.key));
  return List.unmodifiable(sorted);
}

class FinancialBudgetCreateInput {
  FinancialBudgetCreateInput({
    required String name,
    required this.visibilityScope,
    required String currency,
    required String period,
    required this.dateBasis,
    required List<FinancialBudgetLineInput> lines,
    String? idempotencyKey,
  }) : name = _boundedText(
         name.trim(),
         'name',
         maxLength: financialBudgetNameMaxLength,
       ),
       currency = _currency(currency, 'currency'),
       period = _budgetPeriod(period),
       lines = _checkedBudgetLines(lines),
       idempotencyKey = idempotencyKey == null
           ? _newUuidV4()
           : _idempotencyKey(idempotencyKey) {
    if (visibilityScope == FinancialVisibilityScope.shared) {
      throw const FormatException('visibilityScope is not supported.');
    }
  }

  final String name;
  final FinancialVisibilityScope visibilityScope;
  final String currency;

  /// `YYYY-MM`.
  final String period;
  final FinancialBudgetDateBasis dateBasis;
  final List<FinancialBudgetLineInput> lines;
  final String idempotencyKey;

  /// The same request under another idempotency key (an explicit, identical
  /// retry of an attempt whose outcome is unknown reuses the original key).
  FinancialBudgetCreateInput withIdempotencyKey(String key) =>
      FinancialBudgetCreateInput(
        name: name,
        visibilityScope: visibilityScope,
        currency: currency,
        period: period,
        dateBasis: dateBasis,
        lines: lines,
        idempotencyKey: key,
      );

  /// The logical attempt: same material, same key on an explicit retry.
  String get attemptKey => [
    name,
    visibilityScope.wireValue,
    currency,
    period,
    dateBasis.wireValue,
    ...lines.map((line) => '${line.key}=${line.plannedAmount}'),
  ].join('\u001f');

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'name': name,
    'visibilityScope': visibilityScope.wireValue,
    'currency': currency,
    'period': period,
    'dateBasis': dateBasis.wireValue,
    'lines': lines.map((line) => line.toJson()).toList(),
  };
}

class FinancialBudgetReplaceInput {
  FinancialBudgetReplaceInput({
    required this.expectedVersion,
    required String name,
    required String currency,
    required List<FinancialBudgetLineInput> lines,
  }) : name = _boundedText(
         name.trim(),
         'name',
         maxLength: financialBudgetNameMaxLength,
       ),
       currency = _currency(currency, 'currency'),
       lines = _checkedBudgetLines(lines) {
    if (expectedVersion < 1) {
      throw const FormatException('expectedVersion is invalid.');
    }
  }

  final int expectedVersion;
  final String name;
  final String currency;
  final List<FinancialBudgetLineInput> lines;

  Map<String, Object?> toJson() => {
    'expectedVersion': expectedVersion,
    'name': name,
    'currency': currency,
    'lines': lines.map((line) => line.toJson()).toList(),
  };
}

String _budgetPeriod(String value) {
  if (!_budgetPeriodPattern.hasMatch(value)) {
    throw const FormatException('period is invalid.');
  }
  return value;
}

extension FinancialBudgetApiCalls on FinancialCoreApi {
  /// The budgets of one month visible to the operator.
  Future<List<FinancialBudget>> listBudgets(String period) async {
    final month = _budgetPeriod(period);
    final response = await client.get('finance/budgets?period=$month');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _budgetsKeys,
      label: 'budgets response',
    );
    final raw = root['items'];
    if (raw is! List || raw.length > 200) {
      throw const FormatException('items is invalid.');
    }
    final budgets = List<FinancialBudget>.unmodifiable(raw.map(_parseBudget));
    if (budgets.map((budget) => budget.id).toSet().length != budgets.length) {
      throw const FormatException('duplicate budget.');
    }
    for (final budget in budgets) {
      if (budget.period != month) {
        throw const FormatException('budget violates the requested period.');
      }
    }
    return budgets;
  }

  Future<FinancialBudget> getBudget(String budgetId) async {
    final id = _financialResourceId(budgetId, 'budgetId');
    final response = await client.get('finance/budgets/$id');
    final budget = _parseBudget(
      _decodeJsonObject(response.body, 'budget response'),
    );
    if (budget.id != id) {
      throw const FormatException('budget response mismatch.');
    }
    return budget;
  }

  /// Creates the budget. The response is cross-checked against the request:
  /// anything that does not mirror it is an invalid (ambiguous) answer.
  Future<FinancialBudget> createBudget(FinancialBudgetCreateInput input) async {
    final response = await client.post(
      'finance/budgets',
      jsonBody: input.toJson(),
    );
    final budget = _parseBudget(
      _decodeJsonObject(response.body, 'budget response'),
    );
    if (budget.visibilityScope != input.visibilityScope ||
        budget.currency != input.currency ||
        budget.period != input.period ||
        budget.dateBasis != input.dateBasis ||
        !_sameBudgetLines(budget.lines, input.lines)) {
      throw const FormatException('budget response mismatch.');
    }
    return budget;
  }

  /// One compare-and-swap replacement under `expectedVersion`. A stale version
  /// is a `409` that wrote nothing; the caller must re-read and decide.
  Future<FinancialBudget> replaceBudget(
    String budgetId,
    FinancialBudgetReplaceInput input,
  ) async {
    final id = _financialResourceId(budgetId, 'budgetId');
    final response = await client.put(
      'finance/budgets/$id',
      jsonBody: input.toJson(),
    );
    final budget = _parseBudget(
      _decodeJsonObject(response.body, 'budget response'),
    );
    if (budget.id != id ||
        budget.version != input.expectedVersion + 1 ||
        budget.currency != input.currency ||
        budget.name != input.name ||
        !_sameBudgetLines(budget.lines, input.lines)) {
      throw const FormatException('budget response mismatch.');
    }
    return budget;
  }

  /// Planned vs realized from one consistent server snapshot. Never cached.
  Future<FinancialBudgetSummary> getBudgetSummary(String budgetId) async {
    final id = _financialResourceId(budgetId, 'budgetId');
    final response = await client.get('finance/budgets/$id/summary');
    final summary = _parseBudgetSummary(
      _decodeJsonObject(response.body, 'budget summary response'),
    );
    if (summary.budget.id != id) {
      throw const FormatException('budget summary mismatch.');
    }
    return summary;
  }
}

bool _sameBudgetLines(
  List<FinancialBudgetLine> lines,
  List<FinancialBudgetLineInput> inputs,
) {
  if (lines.length != inputs.length) return false;
  final planned = {
    for (final line in lines)
      '${line.categoryId}|${line.resultEffect.wireValue}': _canonicalDecimal(
        line.planned.amount,
      ),
  };
  for (final input in inputs) {
    if (planned[input.key] != _canonicalDecimal(input.plannedAmount)) {
      return false;
    }
  }
  return true;
}

FinancialBudget _parseBudget(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _budgetKeys, label: 'budget');
  final scope = FinancialVisibilityScope.parse(values['visibilityScope']);
  if (scope == FinancialVisibilityScope.shared) {
    throw const FormatException('budget visibilityScope is invalid.');
  }
  if (values['periodKind'] != 'MONTHLY') {
    throw const FormatException('periodKind is invalid.');
  }
  final periodStart = _date(values['periodStart'], 'periodStart');
  final periodEnd = _date(values['periodEnd'], 'periodEnd');
  if (!periodStart.endsWith('-01') || !periodEnd.endsWith('-01')) {
    throw const FormatException('budget period is invalid.');
  }
  final version = values['version'];
  final canEdit = values['canEdit'];
  if (version is! int || version < 1) {
    throw const FormatException('version is invalid.');
  }
  if (canEdit is! bool) throw const FormatException('canEdit is invalid.');
  final currency = _currency(values['currency'], 'currency');
  final rawLines = values['lines'];
  if (rawLines is! List ||
      rawLines.isEmpty ||
      rawLines.length > financialBudgetLinesMax) {
    throw const FormatException('lines is invalid.');
  }
  final lines = List<FinancialBudgetLine>.unmodifiable(
    rawLines.map((item) => _parseBudgetLine(item, currency)),
  );
  final keys = lines
      .map((line) => '${line.categoryId}|${line.resultEffect.wireValue}')
      .toSet();
  if (keys.length != lines.length) {
    throw const FormatException('duplicate budget line.');
  }
  return FinancialBudget(
    id: _financialResourceId(values['id'], 'id'),
    ownerOperatorId: _uuid(values['ownerOperatorId'], 'ownerOperatorId'),
    visibilityScope: scope,
    name: _boundedText(
      values['name'],
      'name',
      maxLength: financialBudgetNameMaxLength,
    ),
    currency: currency,
    periodStart: periodStart,
    periodEnd: periodEnd,
    dateBasis: FinancialBudgetDateBasis.parse(values['dateBasis']),
    version: version,
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
    updatedAt: _timestamp(values['updatedAt'], 'updatedAt'),
    canEdit: canEdit,
    lines: lines,
  );
}

FinancialBudgetLine _parseBudgetLine(Object? raw, String currency) {
  final values = _strictMap(
    raw,
    allowedKeys: _budgetLineKeys,
    label: 'budget line',
  );
  final effect = FinancialResultEffect.parse(values['resultEffect']);
  if (effect == FinancialResultEffect.neutral) {
    throw const FormatException('budget line resultEffect is invalid.');
  }
  final planned = _parseMoney(values['planned']);
  if (planned.currency != currency || planned.isNegative || planned.isZero) {
    throw const FormatException('budget line planned is invalid.');
  }
  return FinancialBudgetLine(
    categoryId: _financialResourceId(values['categoryId'], 'categoryId'),
    resultEffect: effect,
    planned: planned,
  );
}

FinancialBudgetSummary _parseBudgetSummary(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _budgetSummaryKeys,
    label: 'budget summary',
  );
  final budget = _parseBudget(values['budget']);
  final rawLines = values['lines'];
  if (rawLines is! List || rawLines.length != budget.lines.length) {
    throw const FormatException('summary lines are invalid.');
  }
  final lines = List<FinancialBudgetLineSummary>.unmodifiable(
    rawLines.map((item) => _parseBudgetLineSummary(item, budget.currency)),
  );
  final planned = {
    for (final line in budget.lines)
      '${line.categoryId}|${line.resultEffect.wireValue}': line.planned.amount,
  };
  final seen = <String>{};
  for (final line in lines) {
    final key = '${line.categoryId}|${line.resultEffect.wireValue}';
    final plannedAmount = planned[key];
    if (plannedAmount == null ||
        !seen.add(key) ||
        _canonicalDecimal(plannedAmount) !=
            _canonicalDecimal(line.planned.amount)) {
      throw const FormatException('summary line does not match the budget.');
    }
  }
  return FinancialBudgetSummary(
    budget: budget,
    lines: lines,
    coverage: _parseBudgetCoverage(values['coverage'], budget.currency),
  );
}

FinancialBudgetLineSummary _parseBudgetLineSummary(
  Object? raw,
  String currency,
) {
  final values = _strictMap(
    raw,
    allowedKeys: _budgetLineSummaryKeys,
    label: 'budget line summary',
  );
  final effect = FinancialResultEffect.parse(values['resultEffect']);
  if (effect == FinancialResultEffect.neutral) {
    throw const FormatException('budget line resultEffect is invalid.');
  }
  final planned = _parseMoney(values['planned']);
  final realized = _parseMoney(values['realized']);
  final remaining = _parseMoney(values['remaining']);
  if (planned.currency != currency ||
      realized.currency != currency ||
      remaining.currency != currency ||
      planned.isNegative ||
      planned.isZero) {
    throw const FormatException('budget line amounts are invalid.');
  }
  final percent = values['progressPercent'];
  if (percent is! String || !_budgetPercentPattern.hasMatch(percent)) {
    throw const FormatException('progressPercent is invalid.');
  }
  return FinancialBudgetLineSummary(
    categoryId: _financialResourceId(values['categoryId'], 'categoryId'),
    resultEffect: effect,
    planned: planned,
    realized: realized,
    remaining: remaining,
    status: FinancialBudgetLineStatus.parse(values['status']),
    progressPercent: percent,
  );
}

FinancialBudgetCoverage _parseBudgetCoverage(Object? raw, String currency) {
  final values = _strictMap(
    raw,
    allowedKeys: _budgetCoverageKeys,
    label: 'budget coverage',
  );
  final expenseCount = values['unclassifiedExpenseCount'];
  final incomeCount = values['unclassifiedIncomeCount'];
  if (expenseCount is! int ||
      incomeCount is! int ||
      expenseCount < 0 ||
      incomeCount < 0) {
    throw const FormatException('coverage count is invalid.');
  }
  final expense = _parseMoney(values['unclassifiedExpenseAmount']);
  final income = _parseMoney(values['unclassifiedIncomeAmount']);
  if (expense.currency != currency || income.currency != currency) {
    throw const FormatException('coverage currency is invalid.');
  }
  return FinancialBudgetCoverage(
    unclassifiedExpenseCount: expenseCount,
    unclassifiedExpenseAmount: expense,
    unclassifiedIncomeCount: incomeCount,
    unclassifiedIncomeAmount: income,
  );
}
