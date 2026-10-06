import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';

/// Exact money arithmetic for allocation shares.
///
/// Amounts are decimal *text* on the wire. Here they become [BigInt] counts of
/// 10^-8 units (the contract allows at most 8 decimal places), so sums and
/// differences are exact. No `double`, no percentage and no rounding is ever
/// involved: a value that does not fit the scale is rejected, never rounded.
/// The backend stays the authority; this only drives ergonomics (Restante,
/// enabling Confirmar) and a last local refusal of obviously invalid requests.

const financialDecimalScale = 8;
const financialMaxAllocationShares = 50;

final BigInt _unitsPerOne = BigInt.from(10).pow(financialDecimalScale);

final _decimalPattern = RegExp(
  r'^(-?)(0|[1-9][0-9]{0,15})(?:\.([0-9]{1,8}))?$',
);

/// Parses a canonical wire decimal (no comma, no exponent) into scaled units.
BigInt parseFinancialDecimalUnits(String text) {
  final match = _decimalPattern.firstMatch(text);
  if (match == null) {
    throw const FormatException('financial decimal is invalid.');
  }
  final negative = match.group(1) == '-';
  final whole = BigInt.parse(match.group(2)!);
  final fraction = (match.group(3) ?? '').padRight(financialDecimalScale, '0');
  final units = whole * _unitsPerOne + BigInt.parse(fraction);
  return negative ? -units : units;
}

/// Wire text for scaled units. Trailing zeros beyond two decimals are dropped,
/// so `30000000` units is `0.30`, never `0.3` or `0.30000000`.
String formatFinancialDecimalUnits(BigInt units) {
  final negative = units.isNegative;
  final magnitude = units.abs();
  final whole = magnitude ~/ _unitsPerOne;
  var fraction = (magnitude % _unitsPerOne).toString().padLeft(
    financialDecimalScale,
    '0',
  );
  while (fraction.length > 2 && fraction.endsWith('0')) {
    fraction = fraction.substring(0, fraction.length - 1);
  }
  return '${negative ? '-' : ''}$whole.$fraction';
}

/// Same value, minimal text ("-75.250" and "-75.25" and "-75.2500" collapse).
/// Used for identity comparisons, never displayed.
String canonicalFinancialDecimal(String text) {
  final units = parseFinancialDecimalUnits(text);
  final negative = units.isNegative;
  final magnitude = units.abs();
  final whole = magnitude ~/ _unitsPerOne;
  var fraction = (magnitude % _unitsPerOne).toString().padLeft(
    financialDecimalScale,
    '0',
  );
  while (fraction.endsWith('0')) {
    fraction = fraction.substring(0, fraction.length - 1);
  }
  final body = fraction.isEmpty ? '$whole' : '$whole.$fraction';
  return negative ? '-$body' : body;
}

BigInt sumFinancialDecimalUnits(Iterable<String> amounts) => amounts.fold(
  BigInt.zero,
  (sum, amount) => sum + parseFinancialDecimalUnits(amount),
);

/// The sign of a Movement decides the sign of every share. A Movement is never
/// zero, so `negative` is a total classification.
bool isFinancialMoneyNegative(FinancialMoneyWire money) =>
    parseFinancialDecimalUnits(money.amount).isNegative;

/// Share wire amount from the ergonomic, unsigned magnitude typed by the user.
/// Deterministic and exact: `75,25` on an expense of `-75.25` is `-75.25`.
String financialShareWireAmount({
  required FinancialMoneyWire movementMoney,
  required String magnitudeText,
}) {
  final normalized = normalizeFinancialMoneyInput(magnitudeText.trim());
  if (normalized.startsWith('-')) {
    throw const FormatException('share magnitude must not be negative.');
  }
  final units = parseFinancialDecimalUnits(normalized);
  return formatFinancialDecimalUnits(
    isFinancialMoneyNegative(movementMoney) ? -units : units,
  );
}

/// Unsigned display text of a stored share ("-25.00" → "25.00").
String financialShareMagnitudeText(String wireAmount) {
  final units = parseFinancialDecimalUnits(wireAmount);
  return formatFinancialDecimalUnits(units.abs());
}

enum FinancialAllocationIssue {
  noShares,
  tooManyShares,
  missingCategory,
  duplicateCategory,
  invalidAmount,
  zeroAmount,
  categoryUnavailable,
  currencyMismatch,
  signMismatch,
  notClosed,
}

/// Why a [FinancialAllocationShareInput] list cannot be sent for a Movement.
/// Empty means the shares close exactly: `SUM(shares) == movement.money`.
Set<FinancialAllocationIssue> financialAllocationClosureIssues({
  required FinancialMoneyWire movementMoney,
  required List<FinancialAllocationShareInput> shares,
}) {
  final issues = <FinancialAllocationIssue>{};
  if (shares.isEmpty) return {FinancialAllocationIssue.noShares};
  if (shares.length > financialMaxAllocationShares) {
    issues.add(FinancialAllocationIssue.tooManyShares);
  }
  if (shares.map((share) => share.categoryId).toSet().length != shares.length) {
    issues.add(FinancialAllocationIssue.duplicateCategory);
  }
  final movementUnits = parseFinancialDecimalUnits(movementMoney.amount);
  var total = BigInt.zero;
  for (final share in shares) {
    if (share.currency != movementMoney.currency) {
      issues.add(FinancialAllocationIssue.currencyMismatch);
    }
    final units = parseFinancialDecimalUnits(share.amount);
    if (units == BigInt.zero) {
      issues.add(FinancialAllocationIssue.zeroAmount);
    } else if (units.isNegative != movementUnits.isNegative) {
      issues.add(FinancialAllocationIssue.signMismatch);
    }
    total += units;
  }
  if (total != movementUnits) issues.add(FinancialAllocationIssue.notClosed);
  return issues;
}

/// One editable line of the split editor, exactly as typed.
class FinancialAllocationDraftRow {
  const FinancialAllocationDraftRow({this.categoryId, this.amountText = ''});

  final String? categoryId;
  final String amountText;
}

class FinancialAllocationDraftRowReport {
  const FinancialAllocationDraftRowReport({
    required this.issues,
    required this.units,
  });

  /// Row-local problems (missing/duplicate/unavailable category, bad amount).
  final Set<FinancialAllocationIssue> issues;

  /// Signed share units when the amount parsed, otherwise null.
  final BigInt? units;
}

/// Evaluation of the whole editor: totals for "Total do lançamento / Total
/// rateado / Restante" and the shares to send when (and only when) every row
/// is valid and the sum closes exactly.
class FinancialAllocationDraftReport {
  const FinancialAllocationDraftReport({
    required this.movementUnits,
    required this.allocatedUnits,
    required this.rows,
    required this.issues,
    required this.shares,
  });

  final BigInt movementUnits;
  final BigInt allocatedUnits;
  final List<FinancialAllocationDraftRowReport> rows;
  final Set<FinancialAllocationIssue> issues;

  /// Non-null only when [isClosed].
  final List<FinancialAllocationShareInput>? shares;

  /// Signed: positive when value is still unallocated, negative when over.
  BigInt get remainingUnits => movementUnits - allocatedUnits;

  /// Magnitude texts for display ("75.25"), independent of the Movement sign.
  String get movementText => formatFinancialDecimalUnits(movementUnits.abs());
  String get allocatedText => formatFinancialDecimalUnits(allocatedUnits.abs());
  String get remainingText {
    final remaining = remainingUnits;
    final magnitude = formatFinancialDecimalUnits(remaining.abs());
    // Over-allocation reads as a negative remainder regardless of sign.
    final over = movementUnits.isNegative
        ? remaining > BigInt.zero
        : remaining.isNegative;
    return over ? '-$magnitude' : magnitude;
  }

  bool get isClosed => issues.isEmpty && shares != null;
}

FinancialAllocationDraftReport evaluateFinancialAllocationDraft({
  required FinancialMovement movement,
  required FinancialAccount account,
  required FinancialCategoryIndex index,
  required List<FinancialAllocationDraftRow> rows,
}) {
  final movementUnits = parseFinancialDecimalUnits(movement.money.amount);
  final issues = <FinancialAllocationIssue>{};
  if (rows.isEmpty) issues.add(FinancialAllocationIssue.noShares);
  if (rows.length > financialMaxAllocationShares) {
    issues.add(FinancialAllocationIssue.tooManyShares);
  }
  final seen = <String>{};
  final duplicated = <String>{};
  for (final row in rows) {
    final id = row.categoryId;
    if (id != null && !seen.add(id)) duplicated.add(id);
  }

  var allocated = BigInt.zero;
  final reports = <FinancialAllocationDraftRowReport>[];
  final shares = <FinancialAllocationShareInput>[];
  var allRowsValid = rows.isNotEmpty;
  for (final row in rows) {
    final rowIssues = <FinancialAllocationIssue>{};
    final id = row.categoryId;
    final category = id == null ? null : index.byId(id);
    if (id == null) {
      rowIssues.add(FinancialAllocationIssue.missingCategory);
    } else {
      if (duplicated.contains(id)) {
        rowIssues.add(FinancialAllocationIssue.duplicateCategory);
      }
      if (category == null ||
          !isFinancialCategoryEligibleForAccount(
            category: category,
            account: account,
          )) {
        rowIssues.add(FinancialAllocationIssue.categoryUnavailable);
      }
    }
    BigInt? units;
    String? wireAmount;
    try {
      wireAmount = financialShareWireAmount(
        movementMoney: movement.money,
        magnitudeText: row.amountText,
      );
      units = parseFinancialDecimalUnits(wireAmount);
      if (units == BigInt.zero) {
        rowIssues.add(FinancialAllocationIssue.zeroAmount);
      }
    } on FormatException {
      rowIssues.add(FinancialAllocationIssue.invalidAmount);
    }
    if (units != null) allocated += units;
    if (rowIssues.isNotEmpty) allRowsValid = false;
    issues.addAll(rowIssues);
    reports.add(
      FinancialAllocationDraftRowReport(issues: rowIssues, units: units),
    );
    if (rowIssues.isEmpty && id != null && wireAmount != null) {
      shares.add(
        FinancialAllocationShareInput(
          categoryId: id,
          amount: wireAmount,
          currency: movement.money.currency,
        ),
      );
    }
  }
  if (allocated != movementUnits) {
    issues.add(FinancialAllocationIssue.notClosed);
  }
  final closed =
      allRowsValid &&
      issues.isEmpty &&
      financialAllocationClosureIssues(
        movementMoney: movement.money,
        shares: shares,
      ).isEmpty;
  return FinancialAllocationDraftReport(
    movementUnits: movementUnits,
    allocatedUnits: allocated,
    rows: List.unmodifiable(reports),
    issues: Set.unmodifiable(issues),
    shares: closed ? List.unmodifiable(shares) : null,
  );
}

/// Material identity of one logical write attempt. Two attempts with the same
/// identity may share an idempotency key; any material difference (Movement,
/// predecessor, category, amount, currency) must not.
///
/// Shares are ordered by `categoryId`, so reordering rows on screen is not a
/// different attempt. Amounts are compared as values, not as text.
String financialAllocationAttemptIdentity({
  required String kind,
  required String movementId,
  String? supersedesId,
  required List<FinancialAllocationShareInput> shares,
}) {
  final ordered = [...shares]
    ..sort((a, b) => a.categoryId.compareTo(b.categoryId));
  final parts = [
    for (final share in ordered)
      '${share.categoryId}:${canonicalFinancialDecimal(share.amount)}:${share.currency}',
  ];
  return '$kind|$movementId|${supersedesId ?? '-'}|${parts.join(';')}';
}

/// Whether [shares] are exactly the shares of [current] (category by category,
/// amounts compared as values). A revision identical to the current set would
/// only append noise to the append-only history.
bool financialSharesMatchAllocation(
  FinancialMovementAllocation current,
  List<FinancialAllocationShareInput> shares,
) {
  if (current.allocations.length != shares.length) return false;
  final byCategory = {
    for (final share in current.allocations)
      share.categoryId: canonicalFinancialDecimal(share.money.amount),
  };
  return shares.every(
    (share) =>
        byCategory[share.categoryId] == canonicalFinancialDecimal(share.amount),
  );
}
