part of 'financial_core_api.dart';

// Pending-classification inbox (#249). The inbox is a read model derived by the
// backend from the ledger and the classification state: this file only
// validates wire shapes and builds requests. It never decides what is pending,
// never matches rules and never ranks anything. There is no inbox write.

const _pendingPageKeys = <String>{'items', 'nextCursor'};
const _pendingItemKeys = <String>{
  'movementId',
  'accountId',
  'money',
  'resultEffect',
  'effectiveDate',
  'competenceDate',
  'description',
  'accountVisibilityScope',
  'accountOwnerOperatorId',
  'canClassify',
  'ruleStatus',
  'matchedRuleId',
  'suggestedCategoryId',
};
final _pendingCursorPattern = RegExp(r'^[A-Za-z0-9_-]{1,256}$');

/// Server-side caps: the client never asks for more.
const financialPendingPageLimitDefault = 50;
const financialPendingPageLimitMax = 100;

/// Derived suggestion state of one pending Movement (never persisted).
enum FinancialPendingRuleStatus {
  matched('MATCHED'),
  ambiguous('AMBIGUOUS'),
  noMatch('NO_MATCH');

  const FinancialPendingRuleStatus(this.wireValue);
  final String wireValue;

  static FinancialPendingRuleStatus parse(Object? value) =>
      _enumByWire(values, value, 'ruleStatus', (item) => item.wireValue);
}

/// One unclassified Movement as the inbox lists it.
class FinancialPendingMovement {
  const FinancialPendingMovement({
    required this.movementId,
    required this.accountId,
    required this.money,
    required this.resultEffect,
    required this.effectiveDate,
    required this.competenceDate,
    required this.description,
    required this.accountVisibilityScope,
    required this.accountOwnerOperatorId,
    required this.canClassify,
    required this.ruleStatus,
    required this.matchedRuleId,
    required this.suggestedCategoryId,
  });

  final String movementId;
  final String accountId;
  final FinancialMoneyWire money;
  final FinancialResultEffect resultEffect;
  final String effectiveDate;
  final String competenceDate;
  final String description;
  final FinancialVisibilityScope accountVisibilityScope;
  final String accountOwnerOperatorId;

  /// Whether the operator may classify it. A visible item can be read-only.
  final bool canClassify;
  final FinancialPendingRuleStatus ruleStatus;

  /// Only for [FinancialPendingRuleStatus.matched]: the single winning rule.
  final String? matchedRuleId;
  final String? suggestedCategoryId;

  bool get hasSuggestion => ruleStatus == FinancialPendingRuleStatus.matched;
}

/// One bounded keyset page. [nextCursor] is non-null when more candidates may
/// exist; with a status filter the page can be short or empty while it is set.
class FinancialPendingPage {
  const FinancialPendingPage({required this.items, required this.nextCursor});

  final List<FinancialPendingMovement> items;
  final String? nextCursor;
}

extension FinancialPendingApiCalls on FinancialCoreApi {
  /// One read of the inbox. The request and the response are cross-checked: an
  /// item that does not honour the requested filters, or a page larger than the
  /// requested limit, is an invalid response and never reaches the UI.
  Future<FinancialPendingPage> listPendingMovements({
    int limit = financialPendingPageLimitDefault,
    String? cursor,
    String? accountId,
    FinancialResultEffect? resultEffect,
    FinancialPendingRuleStatus? ruleStatus,
  }) async {
    if (limit < 1 || limit > financialPendingPageLimitMax) {
      throw const FormatException('limit is invalid.');
    }
    if (cursor != null && !_pendingCursorPattern.hasMatch(cursor)) {
      throw const FormatException('cursor is invalid.');
    }
    final account = accountId == null
        ? null
        : _financialResourceId(accountId, 'accountId');
    if (resultEffect == FinancialResultEffect.neutral) {
      throw const FormatException('resultEffect is invalid.');
    }
    final query = <String>[
      'limit=$limit',
      if (cursor != null) 'cursor=$cursor',
      if (account != null) 'accountId=$account',
      if (resultEffect != null) 'resultEffect=${resultEffect.wireValue}',
      if (ruleStatus != null) 'ruleStatus=${ruleStatus.wireValue}',
    ].join('&');
    final response = await client.get('finance/pending-movements?$query');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _pendingPageKeys,
      label: 'pending movements response',
    );
    final raw = root['items'];
    if (raw is! List || raw.length > limit) {
      throw const FormatException('items is invalid.');
    }
    final nextCursor = root['nextCursor'];
    if (nextCursor != null &&
        (nextCursor is! String ||
            !_pendingCursorPattern.hasMatch(nextCursor))) {
      throw const FormatException('nextCursor is invalid.');
    }
    final items = List<FinancialPendingMovement>.unmodifiable(
      raw.map(_parsePendingMovement),
    );
    if (items.map((item) => item.movementId).toSet().length != items.length) {
      throw const FormatException('duplicate pending movement.');
    }
    for (final item in items) {
      if ((account != null && item.accountId != account) ||
          (resultEffect != null && item.resultEffect != resultEffect) ||
          (ruleStatus != null && item.ruleStatus != ruleStatus)) {
        throw const FormatException('pending item violates the filters.');
      }
    }
    // Keyset order is part of the contract: newest effective date first.
    for (var index = 1; index < items.length; index += 1) {
      if (items[index - 1].effectiveDate.compareTo(items[index].effectiveDate) <
          0) {
        throw const FormatException('pending items are out of order.');
      }
    }
    if (nextCursor != null && nextCursor == cursor) {
      throw const FormatException('cursor did not advance.');
    }
    return FinancialPendingPage(
      items: items,
      nextCursor: nextCursor as String?,
    );
  }
}

FinancialPendingMovement _parsePendingMovement(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _pendingItemKeys,
    label: 'pending movement',
  );
  final effect = FinancialResultEffect.parse(values['resultEffect']);
  if (effect == FinancialResultEffect.neutral) {
    throw const FormatException('pending resultEffect is invalid.');
  }
  final money = _parseMoney(values['money']);
  if (money.isZero ||
      (effect == FinancialResultEffect.income && money.isNegative) ||
      (effect == FinancialResultEffect.expense && !money.isNegative)) {
    throw const FormatException('pending movement sign is invalid.');
  }
  final canClassify = values['canClassify'];
  if (canClassify is! bool) {
    throw const FormatException('canClassify is invalid.');
  }
  final status = FinancialPendingRuleStatus.parse(values['ruleStatus']);
  final matchedRuleId = values['matchedRuleId'] == null
      ? null
      : _financialResourceId(values['matchedRuleId'], 'matchedRuleId');
  final suggestedCategoryId = values['suggestedCategoryId'] == null
      ? null
      : _financialResourceId(
          values['suggestedCategoryId'],
          'suggestedCategoryId',
        );
  final matched = status == FinancialPendingRuleStatus.matched;
  if (matched != (matchedRuleId != null) ||
      matched != (suggestedCategoryId != null)) {
    throw const FormatException('pending suggestion shape is invalid.');
  }
  return FinancialPendingMovement(
    movementId: _financialResourceId(values['movementId'], 'movementId'),
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    money: money,
    resultEffect: effect,
    effectiveDate: _date(values['effectiveDate'], 'effectiveDate'),
    competenceDate: _date(values['competenceDate'], 'competenceDate'),
    description: _boundedText(
      values['description'],
      'description',
      maxLength: 256,
    ),
    accountVisibilityScope: FinancialVisibilityScope.parse(
      values['accountVisibilityScope'],
    ),
    accountOwnerOperatorId: _uuid(
      values['accountOwnerOperatorId'],
      'accountOwnerOperatorId',
    ),
    canClassify: canClassify,
    ruleStatus: status,
    matchedRuleId: matchedRuleId,
    suggestedCategoryId: suggestedCategoryId,
  );
}
