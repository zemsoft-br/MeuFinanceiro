part of 'financial_core_api.dart';

// Financial goals (#260, ADR-0029). A goal is planning and an allocation is a
// virtual, append-only event: not a Movement, not a transfer, not blocked money.
// This file only validates wire shapes and builds requests. The destinado,
// restante, progress, surplus and backing status are decided by the backend on
// every read; nothing here computes a financial rule. Money is always decimal
// text, never double.

const _goalKeys = <String>{
  'id',
  'ownerOperatorId',
  'visibilityScope',
  'title',
  'description',
  'currency',
  'target',
  'targetDate',
  'version',
  'createdAt',
  'updatedAt',
  'canEdit',
};
const _goalsKeys = <String>{'items'};
const _goalListItemKeys = <String>{
  'goal',
  'allocated',
  'remainingTarget',
  'progressPercent',
  'progressStatus',
};
const _goalEventKeys = <String>{
  'id',
  'goalId',
  'accountId',
  'operation',
  'amount',
  'actorOperatorId',
  'createdAt',
};
const _goalAccountKeys = <String>{
  'accountId',
  'accountStatus',
  'allocated',
  'accountBalance',
  'accountAllocatedTotal',
  'backingStatus',
  'shortfall',
};
const _goalSummaryKeys = <String>{
  'goal',
  'target',
  'allocated',
  'remainingTarget',
  'surplus',
  'progressPercent',
  'progressStatus',
  'hasInsufficientBacking',
  'accounts',
  'events',
};
final _goalPercentPattern = RegExp(r'^[0-9]{1,18}\.[0-9]{2}$');

/// Explicit server-side bounds. Reads beyond them are rejected, never truncated.
const financialGoalsMax = 1000;
const financialGoalAccountsMax = 25;
const financialGoalEventsMax = 500;
const financialGoalTitleMaxLength = 96;
const financialGoalDescriptionMaxLength = 280;

enum FinancialGoalOperation {
  allocate('ALLOCATE'),
  release('RELEASE');

  const FinancialGoalOperation(this.wireValue);
  final String wireValue;

  static FinancialGoalOperation parse(Object? value) =>
      _enumByWire(values, value, 'operation', (item) => item.wireValue);
}

/// Allocated compared with the target. A statement of fact, derived by the server.
enum FinancialGoalProgressStatus {
  notStarted('NOT_STARTED'),
  inProgress('IN_PROGRESS'),
  reached('REACHED'),
  exceeded('EXCEEDED');

  const FinancialGoalProgressStatus(this.wireValue);
  final String wireValue;

  static FinancialGoalProgressStatus parse(Object? value) =>
      _enumByWire(values, value, 'progressStatus', (item) => item.wireValue);
}

/// Whether the account balance still covers everything allocated on it (all
/// goals). Reported, never repaired: no event is rewritten when it is lacking.
enum FinancialGoalBackingStatus {
  covered('COVERED'),
  insufficient('INSUFFICIENT');

  const FinancialGoalBackingStatus(this.wireValue);
  final String wireValue;

  static FinancialGoalBackingStatus parse(Object? value) =>
      _enumByWire(values, value, 'backingStatus', (item) => item.wireValue);
}

class FinancialGoal {
  const FinancialGoal({
    required this.id,
    required this.ownerOperatorId,
    required this.visibilityScope,
    required this.title,
    required this.description,
    required this.currency,
    required this.target,
    required this.targetDate,
    required this.version,
    required this.createdAt,
    required this.updatedAt,
    required this.canEdit,
  });

  final String id;
  final String ownerOperatorId;
  final FinancialVisibilityScope visibilityScope;
  final String title;
  final String? description;
  final String currency;
  final FinancialMoneyWire target;

  /// `YYYY-MM-DD` or null.
  final String? targetDate;

  /// CAS token: the only valid `expectedVersion` of the next edit.
  final int version;
  final DateTime createdAt;
  final DateTime updatedAt;

  /// Decided by the server: the operator owns this goal. Reading a HOUSEHOLD
  /// goal never implies write access.
  final bool canEdit;
}

/// A goal with what it holds, as the server derived it from the events.
class FinancialGoalListItem {
  const FinancialGoalListItem({
    required this.goal,
    required this.allocated,
    required this.remainingTarget,
    required this.progressPercent,
    required this.progressStatus,
  });

  final FinancialGoal goal;
  final FinancialMoneyWire allocated;
  final FinancialMoneyWire remainingTarget;

  /// Decimal text with two places, e.g. `30.00`; may exceed `100.00`.
  final String progressPercent;
  final FinancialGoalProgressStatus progressStatus;
}

class FinancialGoalEvent {
  const FinancialGoalEvent({
    required this.id,
    required this.goalId,
    required this.accountId,
    required this.operation,
    required this.amount,
    required this.actorOperatorId,
    required this.createdAt,
  });

  final String id;
  final String goalId;
  final String accountId;
  final FinancialGoalOperation operation;

  /// Positive magnitude; the operation gives the direction.
  final FinancialMoneyWire amount;
  final String actorOperatorId;
  final DateTime createdAt;
}

class FinancialGoalAccountSummary {
  const FinancialGoalAccountSummary({
    required this.accountId,
    required this.accountStatus,
    required this.allocated,
    required this.accountBalance,
    required this.accountAllocatedTotal,
    required this.backingStatus,
    required this.shortfall,
  });

  final String accountId;
  final FinancialAccountStatus accountStatus;

  /// What this goal holds on this account.
  final FinancialMoneyWire allocated;

  /// The canonical derived balance of the account.
  final FinancialMoneyWire accountBalance;

  /// Everything allocated on the account by every goal.
  final FinancialMoneyWire accountAllocatedTotal;
  final FinancialGoalBackingStatus backingStatus;
  final FinancialMoneyWire shortfall;
}

class FinancialGoalSummary {
  const FinancialGoalSummary({
    required this.goal,
    required this.target,
    required this.allocated,
    required this.remainingTarget,
    required this.surplus,
    required this.progressPercent,
    required this.progressStatus,
    required this.hasInsufficientBacking,
    required this.accounts,
    required this.events,
  });

  final FinancialGoal goal;
  final FinancialMoneyWire target;
  final FinancialMoneyWire allocated;
  final FinancialMoneyWire remainingTarget;
  final FinancialMoneyWire surplus;
  final String progressPercent;
  final FinancialGoalProgressStatus progressStatus;
  final bool hasInsufficientBacking;
  final List<FinancialGoalAccountSummary> accounts;
  final List<FinancialGoalEvent> events;
}

String? _checkedGoalDescription(String? value) {
  if (value == null) return null;
  final trimmed = value.trim();
  if (trimmed.isEmpty) return null;
  return _boundedText(
    trimmed,
    'description',
    maxLength: financialGoalDescriptionMaxLength,
  );
}

String? _checkedGoalDate(String? value) =>
    value == null || value.isEmpty ? null : _date(value, 'targetDate');

class FinancialGoalCreateInput {
  FinancialGoalCreateInput({
    required String title,
    String? description,
    required this.visibilityScope,
    required String currency,
    required String targetAmount,
    String? targetDate,
    String? idempotencyKey,
  }) : title = _boundedText(
         title.trim(),
         'title',
         maxLength: financialGoalTitleMaxLength,
       ),
       description = _checkedGoalDescription(description),
       currency = _currency(currency, 'currency'),
       targetAmount = _positiveDecimalAmount(targetAmount, 'targetAmount'),
       targetDate = _checkedGoalDate(targetDate),
       idempotencyKey = idempotencyKey == null
           ? _newUuidV4()
           : _idempotencyKey(idempotencyKey) {
    if (visibilityScope == FinancialVisibilityScope.shared) {
      throw const FormatException('visibilityScope is not supported.');
    }
  }

  final String title;
  final String? description;
  final FinancialVisibilityScope visibilityScope;
  final String currency;
  final String targetAmount;
  final String? targetDate;
  final String idempotencyKey;

  /// The same request under another idempotency key (an explicit, identical
  /// retry of an attempt whose outcome is unknown reuses the original key).
  FinancialGoalCreateInput withIdempotencyKey(String key) =>
      FinancialGoalCreateInput(
        title: title,
        description: description,
        visibilityScope: visibilityScope,
        currency: currency,
        targetAmount: targetAmount,
        targetDate: targetDate,
        idempotencyKey: key,
      );

  /// The logical attempt: same material, same key on an explicit retry.
  String get attemptKey => [
    title,
    description ?? '',
    visibilityScope.wireValue,
    currency,
    _canonicalDecimal(targetAmount),
    targetDate ?? '',
  ].join('\u001f');

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'title': title,
    'description': description,
    'visibilityScope': visibilityScope.wireValue,
    'currency': currency,
    'targetAmount': targetAmount,
    'targetDate': targetDate,
  };
}

class FinancialGoalReplaceInput {
  FinancialGoalReplaceInput({
    required this.expectedVersion,
    required String title,
    String? description,
    required String currency,
    required String targetAmount,
    String? targetDate,
  }) : title = _boundedText(
         title.trim(),
         'title',
         maxLength: financialGoalTitleMaxLength,
       ),
       description = _checkedGoalDescription(description),
       currency = _currency(currency, 'currency'),
       targetAmount = _positiveDecimalAmount(targetAmount, 'targetAmount'),
       targetDate = _checkedGoalDate(targetDate) {
    if (expectedVersion < 1) {
      throw const FormatException('expectedVersion is invalid.');
    }
  }

  final int expectedVersion;
  final String title;
  final String? description;
  final String currency;
  final String targetAmount;
  final String? targetDate;

  Map<String, Object?> toJson() => {
    'expectedVersion': expectedVersion,
    'title': title,
    'description': description,
    'currency': currency,
    'targetAmount': targetAmount,
    'targetDate': targetDate,
  };
}

class FinancialGoalAllocationInput {
  FinancialGoalAllocationInput({
    required this.operation,
    required String accountId,
    required String amount,
    required String currency,
    String? idempotencyKey,
  }) : accountId = _financialResourceId(accountId, 'accountId'),
       amount = _positiveDecimalAmount(amount, 'amount'),
       currency = _currency(currency, 'currency'),
       idempotencyKey = idempotencyKey == null
           ? _newUuidV4()
           : _idempotencyKey(idempotencyKey);

  final FinancialGoalOperation operation;
  final String accountId;
  final String amount;
  final String currency;
  final String idempotencyKey;

  FinancialGoalAllocationInput withIdempotencyKey(String key) =>
      FinancialGoalAllocationInput(
        operation: operation,
        accountId: accountId,
        amount: amount,
        currency: currency,
        idempotencyKey: key,
      );

  /// The logical attempt: same material, same key on an explicit retry.
  String get attemptKey => [
    operation.wireValue,
    accountId,
    currency,
    _canonicalDecimal(amount),
  ].join('\u001f');

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'operation': operation.wireValue,
    'accountId': accountId,
    'amount': amount,
    'currency': currency,
  };
}

extension FinancialGoalApiCalls on FinancialCoreApi {
  /// Every goal visible to the operator, each with what it holds.
  Future<List<FinancialGoalListItem>> listGoals() async {
    final response = await client.get('finance/goals');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _goalsKeys,
      label: 'goals response',
    );
    final raw = root['items'];
    if (raw is! List || raw.length > financialGoalsMax) {
      throw const FormatException('items is invalid.');
    }
    final items = List<FinancialGoalListItem>.unmodifiable(
      raw.map(_parseGoalListItem),
    );
    if (items.map((item) => item.goal.id).toSet().length != items.length) {
      throw const FormatException('duplicate goal.');
    }
    return items;
  }

  /// Creates the goal. The response is cross-checked against the request:
  /// anything that does not mirror it is an invalid (ambiguous) answer.
  Future<FinancialGoal> createGoal(FinancialGoalCreateInput input) async {
    final response = await client.post(
      'finance/goals',
      jsonBody: input.toJson(),
    );
    final goal = _parseGoal(_decodeJsonObject(response.body, 'goal response'));
    if (goal.visibilityScope != input.visibilityScope ||
        goal.currency != input.currency ||
        goal.title != input.title ||
        goal.description != input.description ||
        goal.targetDate != input.targetDate ||
        _canonicalDecimal(goal.target.amount) !=
            _canonicalDecimal(input.targetAmount)) {
      throw const FormatException('goal response mismatch.');
    }
    return goal;
  }

  /// One compare-and-swap replacement under `expectedVersion`. A stale version
  /// is a `409` that wrote nothing; the caller must re-read and decide.
  Future<FinancialGoal> replaceGoal(
    String goalId,
    FinancialGoalReplaceInput input,
  ) async {
    final id = _financialResourceId(goalId, 'goalId');
    final response = await client.put(
      'finance/goals/$id',
      jsonBody: input.toJson(),
    );
    final goal = _parseGoal(_decodeJsonObject(response.body, 'goal response'));
    if (goal.id != id ||
        goal.version != input.expectedVersion + 1 ||
        goal.currency != input.currency ||
        goal.title != input.title ||
        goal.description != input.description ||
        goal.targetDate != input.targetDate ||
        _canonicalDecimal(goal.target.amount) !=
            _canonicalDecimal(input.targetAmount)) {
      throw const FormatException('goal response mismatch.');
    }
    return goal;
  }

  /// Target, destinado, restante, progress and backing from one consistent
  /// server snapshot. Never cached.
  Future<FinancialGoalSummary> getGoalSummary(String goalId) async {
    final id = _financialResourceId(goalId, 'goalId');
    final response = await client.get('finance/goals/$id/summary');
    final summary = _parseGoalSummary(
      _decodeJsonObject(response.body, 'goal summary response'),
    );
    if (summary.goal.id != id) {
      throw const FormatException('goal summary mismatch.');
    }
    return summary;
  }

  /// One explicit virtual `ALLOCATE` / `RELEASE`. The response is the appended
  /// event and is cross-checked against the request. Nothing is optimistic: the
  /// caller reads the summary again.
  Future<FinancialGoalEvent> allocateGoal(
    String goalId,
    FinancialGoalAllocationInput input,
  ) async {
    final id = _financialResourceId(goalId, 'goalId');
    final response = await client.post(
      'finance/goals/$id/allocations',
      jsonBody: input.toJson(),
    );
    final event = _parseGoalEvent(
      _decodeJsonObject(response.body, 'goal allocation response'),
    );
    if (event.goalId != id ||
        event.accountId != input.accountId ||
        event.operation != input.operation ||
        event.amount.currency != input.currency ||
        _canonicalDecimal(event.amount.amount) !=
            _canonicalDecimal(input.amount)) {
      throw const FormatException('goal allocation response mismatch.');
    }
    return event;
  }
}

FinancialGoal _parseGoal(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _goalKeys, label: 'goal');
  final scope = FinancialVisibilityScope.parse(values['visibilityScope']);
  if (scope == FinancialVisibilityScope.shared) {
    throw const FormatException('goal visibilityScope is invalid.');
  }
  final version = values['version'];
  final canEdit = values['canEdit'];
  if (version is! int || version < 1) {
    throw const FormatException('version is invalid.');
  }
  if (canEdit is! bool) throw const FormatException('canEdit is invalid.');
  final currency = _currency(values['currency'], 'currency');
  final target = _parseMoney(values['target']);
  if (target.currency != currency || target.isNegative || target.isZero) {
    throw const FormatException('goal target is invalid.');
  }
  final rawDate = values['targetDate'];
  return FinancialGoal(
    id: _financialResourceId(values['id'], 'id'),
    ownerOperatorId: _uuid(values['ownerOperatorId'], 'ownerOperatorId'),
    visibilityScope: scope,
    title: _boundedText(
      values['title'],
      'title',
      maxLength: financialGoalTitleMaxLength,
    ),
    description: _optionalBoundedText(
      values['description'],
      'description',
      maxLength: financialGoalDescriptionMaxLength,
    ),
    currency: currency,
    target: target,
    targetDate: rawDate == null ? null : _date(rawDate, 'targetDate'),
    version: version,
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
    updatedAt: _timestamp(values['updatedAt'], 'updatedAt'),
    canEdit: canEdit,
  );
}

String _goalPercent(Object? value) {
  if (value is! String || !_goalPercentPattern.hasMatch(value)) {
    throw const FormatException('progressPercent is invalid.');
  }
  return value;
}

FinancialMoneyWire _goalMoney(Object? raw, String currency, String label) {
  final money = _parseMoney(raw);
  if (money.currency != currency || money.isNegative) {
    throw FormatException('$label is invalid.');
  }
  return money;
}

FinancialGoalListItem _parseGoalListItem(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _goalListItemKeys,
    label: 'goal list item',
  );
  final goal = _parseGoal(values['goal']);
  return FinancialGoalListItem(
    goal: goal,
    allocated: _goalMoney(values['allocated'], goal.currency, 'allocated'),
    remainingTarget: _goalMoney(
      values['remainingTarget'],
      goal.currency,
      'remainingTarget',
    ),
    progressPercent: _goalPercent(values['progressPercent']),
    progressStatus: FinancialGoalProgressStatus.parse(values['progressStatus']),
  );
}

FinancialGoalEvent _parseGoalEvent(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _goalEventKeys,
    label: 'goal event',
  );
  final amount = _parseMoney(values['amount']);
  if (amount.isNegative || amount.isZero) {
    throw const FormatException('goal event amount is invalid.');
  }
  return FinancialGoalEvent(
    id: _financialResourceId(values['id'], 'id'),
    goalId: _financialResourceId(values['goalId'], 'goalId'),
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    operation: FinancialGoalOperation.parse(values['operation']),
    amount: amount,
    actorOperatorId: _uuid(values['actorOperatorId'], 'actorOperatorId'),
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
  );
}

FinancialGoalAccountSummary _parseGoalAccount(Object? raw, String currency) {
  final values = _strictMap(
    raw,
    allowedKeys: _goalAccountKeys,
    label: 'goal account',
  );
  final backing = FinancialGoalBackingStatus.parse(values['backingStatus']);
  final shortfall = _goalMoney(values['shortfall'], currency, 'shortfall');
  // A statement of shape, not arithmetic: a covered account has no shortfall and
  // an insufficient one always has one.
  if ((backing == FinancialGoalBackingStatus.covered) != shortfall.isZero) {
    throw const FormatException('goal account backing is inconsistent.');
  }
  final balance = _parseMoney(values['accountBalance']);
  if (balance.currency != currency) {
    throw const FormatException('accountBalance is invalid.');
  }
  return FinancialGoalAccountSummary(
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    accountStatus: FinancialAccountStatus.parse(values['accountStatus']),
    allocated: _goalMoney(values['allocated'], currency, 'allocated'),
    accountBalance: balance,
    accountAllocatedTotal: _goalMoney(
      values['accountAllocatedTotal'],
      currency,
      'accountAllocatedTotal',
    ),
    backingStatus: backing,
    shortfall: shortfall,
  );
}

FinancialGoalSummary _parseGoalSummary(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _goalSummaryKeys,
    label: 'goal summary',
  );
  final goal = _parseGoal(values['goal']);
  final currency = goal.currency;
  final target = _goalMoney(values['target'], currency, 'target');
  if (_canonicalDecimal(target.amount) !=
      _canonicalDecimal(goal.target.amount)) {
    throw const FormatException('summary target does not match the goal.');
  }
  final rawAccounts = values['accounts'];
  final rawEvents = values['events'];
  final insufficient = values['hasInsufficientBacking'];
  if (rawAccounts is! List ||
      rawAccounts.length > financialGoalAccountsMax ||
      rawEvents is! List ||
      rawEvents.length > financialGoalEventsMax ||
      insufficient is! bool) {
    throw const FormatException('goal summary is invalid.');
  }
  final accounts = List<FinancialGoalAccountSummary>.unmodifiable(
    rawAccounts.map((item) => _parseGoalAccount(item, currency)),
  );
  if (accounts.map((account) => account.accountId).toSet().length !=
      accounts.length) {
    throw const FormatException('duplicate goal account.');
  }
  final events = List<FinancialGoalEvent>.unmodifiable(
    rawEvents.map(_parseGoalEvent),
  );
  final accountIds = accounts.map((account) => account.accountId).toSet();
  for (final event in events) {
    if (event.goalId != goal.id ||
        event.amount.currency != currency ||
        !accountIds.contains(event.accountId)) {
      throw const FormatException('goal event does not match the goal.');
    }
  }
  if (events.map((event) => event.id).toSet().length != events.length) {
    throw const FormatException('duplicate goal event.');
  }
  final anyInsufficient = accounts.any(
    (account) =>
        account.backingStatus == FinancialGoalBackingStatus.insufficient,
  );
  if (insufficient != anyInsufficient) {
    throw const FormatException('hasInsufficientBacking is inconsistent.');
  }
  return FinancialGoalSummary(
    goal: goal,
    target: target,
    allocated: _goalMoney(values['allocated'], currency, 'allocated'),
    remainingTarget: _goalMoney(
      values['remainingTarget'],
      currency,
      'remainingTarget',
    ),
    surplus: _goalMoney(values['surplus'], currency, 'surplus'),
    progressPercent: _goalPercent(values['progressPercent']),
    progressStatus: FinancialGoalProgressStatus.parse(values['progressStatus']),
    hasInsufficientBacking: insufficient,
    accounts: accounts,
    events: events,
  );
}
