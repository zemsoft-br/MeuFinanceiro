part of 'financial_core_api.dart';

// Read-only cash flow (#265, ADR-0031). The projection, every balance, total,
// risk date and issue is decided by the backend from the canonical ledger and the
// recurrence model; this file only validates the wire shape and builds the query.
// Nothing here computes money or calls a write. Money is decimal text, never
// double.

/// Server-side caps mirrored only to reject a response that breaks them.
const financialCashFlowWindowMaxDays = 92;
const financialCashFlowAccountsMax = 50;
const financialCashFlowEventsMax = 2000;

/// Server default length when neither `through` nor `days` is sent.
const _cashFlowDefaultDays = 30;

const _cashFlowKeys = <String>{
  'referenceDate',
  'from',
  'through',
  'days',
  'calculatedAt',
  'excludedSources',
  'groups',
};
const _cashFlowGroupKeys = <String>{
  'currency',
  'projectionStatus',
  'issues',
  'startingBalance',
  'balanceAtReference',
  'closingBalance',
  'totals',
  'risk',
  'historicalRisk',
  'accounts',
  'days',
  'events',
};
const _cashFlowIssueKeys = <String>{'code', 'severity', 'count', 'accountIds'};
const _cashFlowRiskKeys = <String>{
  'minimumBalance',
  'minimumBalanceDate',
  'firstNegativeDate',
  'negativeDays',
  'evaluatedDays',
};
const _cashFlowTotalsKeys = <String>{
  'realizedIncome',
  'realizedExpense',
  'neutralIn',
  'neutralOut',
  'realizedNet',
  'expectedIncome',
  'expectedExpense',
  'expectedNet',
  'overdueCount',
  'overdueNet',
  'recurrenceRealizedCount',
  'recurrenceRealizedExpected',
  'recurrenceRealizedActual',
  'realizedCount',
  'expectedCount',
};
const _cashFlowAccountKeys = <String>{
  'accountId',
  'name',
  'accountType',
  'visibilityScope',
  'status',
  'hasOpeningBalance',
  'openingBalanceDate',
  'startingBalance',
  'balanceAtReference',
  'realizedNet',
  'expectedNet',
  'closingBalance',
  'risk',
  'historicalRisk',
};
const _cashFlowDayKeys = <String>{
  'date',
  'opening',
  'realizedIncome',
  'realizedExpense',
  'expectedIncome',
  'expectedExpense',
  'neutralNet',
  'closing',
  'projected',
  'anchored',
  'negative',
};
const _cashFlowEventKeys = <String>{
  'date',
  'kind',
  'accountId',
  'amount',
  'resultEffect',
  'description',
  'movementId',
  'movementRole',
  'reversalOfId',
  'transferId',
  'occurrenceId',
  'recurrenceId',
  'ruleVersion',
  'periodStart',
  'scheduledDate',
  'overdue',
  'expectedAmount',
  'balanceAfter',
  'accountBalanceAfter',
};

/// Where an event of the projection comes from.
enum FinancialCashFlowEventKind {
  /// A canonical Movement already in the ledger.
  realized('REALIZED'),

  /// A persisted PENDING recurrence occurrence (generated, not registered).
  expectedOccurrence('EXPECTED_OCCURRENCE'),

  /// A month of an active rule that has no occurrence yet (never persisted).
  expectedRule('EXPECTED_RULE');

  const FinancialCashFlowEventKind(this.wireValue);
  final String wireValue;

  bool get isExpected => this != realized;

  static FinancialCashFlowEventKind parse(Object? value) =>
      _enumByWire(values, value, 'kind', (item) => item.wireValue);
}

enum FinancialCashFlowProjectionStatus {
  complete('COMPLETE'),
  incomplete('INCOMPLETE'),
  notApplicable('NOT_APPLICABLE');

  const FinancialCashFlowProjectionStatus(this.wireValue);
  final String wireValue;

  static FinancialCashFlowProjectionStatus parse(Object? value) =>
      _enumByWire(values, value, 'projectionStatus', (item) => item.wireValue);
}

enum FinancialCashFlowIssueSeverity {
  incomplete('INCOMPLETE'),
  attention('ATTENTION');

  const FinancialCashFlowIssueSeverity(this.wireValue);
  final String wireValue;

  static FinancialCashFlowIssueSeverity parse(Object? value) =>
      _enumByWire(values, value, 'severity', (item) => item.wireValue);
}

enum FinancialCashFlowIssueCode {
  openingBalanceMissing('OPENING_BALANCE_MISSING'),
  openingBalanceAfterWindowStart('OPENING_BALANCE_AFTER_WINDOW_START'),
  ruleAccountInactive('RULE_ACCOUNT_INACTIVE'),
  overdueOccurrences('OVERDUE_OCCURRENCES'),
  ungeneratedPastOccurrences('UNGENERATED_PAST_OCCURRENCES'),
  pausedRules('PAUSED_RULES'),
  historicalWindow('HISTORICAL_WINDOW');

  const FinancialCashFlowIssueCode(this.wireValue);
  final String wireValue;

  static FinancialCashFlowIssueCode parse(Object? value) =>
      _enumByWire(values, value, 'code', (item) => item.wireValue);
}

/// Lowest closing balance and first deficit over the days the server evaluated.
///
/// Only anchored days (an opening balance effective on or before the day) are
/// evaluated. The prospective risk covers the projected days (from the
/// reference date on); the historical one the realized days before it. A risk
/// that is absent (`null` in its holder) means "not assessable", never "safe".
class FinancialCashFlowRisk {
  const FinancialCashFlowRisk({
    required this.minimumBalance,
    required this.minimumBalanceDate,
    required this.firstNegativeDate,
    required this.negativeDays,
    required this.evaluatedDays,
  });

  final FinancialMoneyWire minimumBalance;
  final String minimumBalanceDate;

  /// First evaluated day whose closing balance is below zero (`null`: none).
  final String? firstNegativeDate;
  final int negativeDays;

  /// Anchored days the server evaluated (never the pre-anchor ones).
  final int evaluatedDays;
}

class FinancialCashFlowIssue {
  const FinancialCashFlowIssue({
    required this.code,
    required this.severity,
    required this.count,
    required this.accountIds,
  });

  final FinancialCashFlowIssueCode code;
  final FinancialCashFlowIssueSeverity severity;
  final int count;
  final List<String> accountIds;
}

class FinancialCashFlowTotals {
  const FinancialCashFlowTotals({
    required this.realizedIncome,
    required this.realizedExpense,
    required this.neutralIn,
    required this.neutralOut,
    required this.realizedNet,
    required this.expectedIncome,
    required this.expectedExpense,
    required this.expectedNet,
    required this.overdueCount,
    required this.overdueNet,
    required this.recurrenceRealizedCount,
    required this.recurrenceRealizedExpected,
    required this.recurrenceRealizedActual,
    required this.realizedCount,
    required this.expectedCount,
  });

  final FinancialMoneyWire realizedIncome;
  final FinancialMoneyWire realizedExpense;
  final FinancialMoneyWire neutralIn;
  final FinancialMoneyWire neutralOut;
  final FinancialMoneyWire realizedNet;
  final FinancialMoneyWire expectedIncome;
  final FinancialMoneyWire expectedExpense;
  final FinancialMoneyWire expectedNet;
  final int overdueCount;
  final FinancialMoneyWire overdueNet;
  final int recurrenceRealizedCount;
  final FinancialMoneyWire recurrenceRealizedExpected;
  final FinancialMoneyWire recurrenceRealizedActual;
  final int realizedCount;
  final int expectedCount;
}

class FinancialCashFlowAccount {
  const FinancialCashFlowAccount({
    required this.accountId,
    required this.name,
    required this.accountType,
    required this.visibilityScope,
    required this.status,
    required this.hasOpeningBalance,
    required this.openingBalanceDate,
    required this.startingBalance,
    required this.balanceAtReference,
    required this.realizedNet,
    required this.expectedNet,
    required this.closingBalance,
    required this.risk,
    required this.historicalRisk,
  });

  final String accountId;
  final String name;
  final FinancialAccountType accountType;
  final FinancialVisibilityScope visibilityScope;
  final FinancialAccountStatus status;
  final bool hasOpeningBalance;
  final String? openingBalanceDate;
  final FinancialMoneyWire startingBalance;
  final FinancialMoneyWire balanceAtReference;
  final FinancialMoneyWire realizedNet;
  final FinancialMoneyWire expectedNet;
  final FinancialMoneyWire closingBalance;

  /// Prospective risk (from the reference date on); `null` when no projected
  /// day of this account is anchored.
  final FinancialCashFlowRisk? risk;

  /// Realized days before the reference date; `null` when none is anchored.
  final FinancialCashFlowRisk? historicalRisk;

  /// The account balance on [date] rests on its opening balance. Calendar
  /// comparison only.
  bool anchoredOn(String date) {
    final opening = openingBalanceDate;
    return opening != null && opening.compareTo(date) <= 0;
  }
}

class FinancialCashFlowDay {
  const FinancialCashFlowDay({
    required this.date,
    required this.opening,
    required this.realizedIncome,
    required this.realizedExpense,
    required this.expectedIncome,
    required this.expectedExpense,
    required this.neutralNet,
    required this.closing,
    required this.projected,
    required this.anchored,
    required this.negative,
  });

  final String date;
  final FinancialMoneyWire opening;
  final FinancialMoneyWire realizedIncome;
  final FinancialMoneyWire realizedExpense;
  final FinancialMoneyWire expectedIncome;
  final FinancialMoneyWire expectedExpense;
  final FinancialMoneyWire neutralNet;
  final FinancialMoneyWire closing;

  /// On or after the reference date of a non-historical window.
  final bool projected;

  /// Every account of the group has an opening balance effective on or before
  /// this day. Otherwise the balance is an estimate (an account without one
  /// starts from zero; before its effective date the opening amount is applied
  /// ahead of time): never a fact, and never used to assess risk.
  final bool anchored;
  final bool negative;

  /// The server reported any figure other than zero for the day.
  bool get hasActivity =>
      !realizedIncome.isZero ||
      !realizedExpense.isZero ||
      !expectedIncome.isZero ||
      !expectedExpense.isZero ||
      !neutralNet.isZero;
}

class FinancialCashFlowEvent {
  const FinancialCashFlowEvent({
    required this.date,
    required this.kind,
    required this.accountId,
    required this.amount,
    required this.resultEffect,
    required this.description,
    required this.movementId,
    required this.movementRole,
    required this.reversalOfId,
    required this.transferId,
    required this.occurrenceId,
    required this.recurrenceId,
    required this.ruleVersion,
    required this.periodStart,
    required this.scheduledDate,
    required this.overdue,
    required this.expectedAmount,
    required this.balanceAfter,
    required this.accountBalanceAfter,
  });

  /// Where the event is placed (an overdue expectation sits on the reference).
  final String date;
  final FinancialCashFlowEventKind kind;
  final String accountId;

  /// Signed: cash in is positive, cash out negative.
  final FinancialMoneyWire amount;
  final FinancialResultEffect resultEffect;
  final String? description;
  final String? movementId;
  final FinancialMovementRole? movementRole;
  final String? reversalOfId;
  final String? transferId;
  final String? occurrenceId;
  final String? recurrenceId;
  final int? ruleVersion;
  final String? periodStart;

  /// Original due date of the recurrence behind the event.
  final String? scheduledDate;
  final bool overdue;

  /// Signed expectation of the recurrence behind the event, when there is one.
  final FinancialMoneyWire? expectedAmount;
  final FinancialMoneyWire balanceAfter;
  final FinancialMoneyWire accountBalanceAfter;
}

class FinancialCashFlowGroup {
  const FinancialCashFlowGroup({
    required this.currency,
    required this.projectionStatus,
    required this.issues,
    required this.startingBalance,
    required this.balanceAtReference,
    required this.closingBalance,
    required this.totals,
    required this.risk,
    required this.historicalRisk,
    required this.accounts,
    required this.days,
    required this.events,
  });

  final String currency;
  final FinancialCashFlowProjectionStatus projectionStatus;
  final List<FinancialCashFlowIssue> issues;
  final FinancialMoneyWire startingBalance;

  /// Real (ledger) balance on the reference date.
  final FinancialMoneyWire balanceAtReference;

  /// Projected balance at the end of the window.
  final FinancialMoneyWire closingBalance;
  final FinancialCashFlowTotals totals;

  /// Prospective risk over the anchored projected days (`null`: not
  /// assessable, or no projected day at all).
  final FinancialCashFlowRisk? risk;

  /// Deficits that already happened, over the anchored days before the
  /// reference date (`null`: none of them anchored, or no past day).
  final FinancialCashFlowRisk? historicalRisk;
  final List<FinancialCashFlowAccount> accounts;
  final List<FinancialCashFlowDay> days;
  final List<FinancialCashFlowEvent> events;

  FinancialCashFlowAccount? account(String accountId) {
    for (final account in accounts) {
      if (account.accountId == accountId) return account;
    }
    return null;
  }

  /// The server flag of [date] (`false` outside the window).
  bool anchoredOn(String date) {
    for (final day in days) {
      if (day.date == date) return day.anchored;
    }
    return false;
  }

  int get projectedDays => days.where((day) => day.projected).length;

  int get pastDays => days.where((day) => !day.projected).length;
}

class FinancialCashFlow {
  const FinancialCashFlow({
    required this.referenceDate,
    required this.from,
    required this.through,
    required this.days,
    required this.calculatedAt,
    required this.excludedSources,
    required this.groups,
  });

  final String referenceDate;
  final String from;
  final String through;
  final int days;
  final DateTime calculatedAt;
  final List<String> excludedSources;

  /// One group per currency; currencies are never summed together.
  final List<FinancialCashFlowGroup> groups;

  bool get isHistorical => through.compareTo(referenceDate) < 0;
}

/// What to read. `null` fields keep the server defaults (from the reference
/// date, 30 days, every visible active account, every currency).
class FinancialCashFlowQuery {
  FinancialCashFlowQuery({
    String? from,
    String? through,
    int? days,
    List<String> accountIds = const [],
    String? currency,
  }) : from = from == null ? null : _date(from, 'from'),
       through = through == null ? null : _date(through, 'through'),
       days = _cashFlowRelativeDays(days, through),
       accountIds = _cashFlowAccountIds(accountIds),
       currency = currency == null ? null : _currency(currency, 'currency') {
    final start = this.from;
    final end = this.through;
    if (start != null && end != null) {
      if (end.compareTo(start) < 0) {
        throw const FormatException('through must not precede from.');
      }
      if (_cashFlowDaySpan(start, end) > financialCashFlowWindowMaxDays) {
        throw const FormatException('window is too long.');
      }
    }
  }

  final String? from;
  final String? through;

  /// Window length counted by the server from `from` (or its reference date):
  /// a relative window that needs no client-side reference date. Exclusive
  /// with [through].
  final int? days;
  final List<String> accountIds;
  final String? currency;

  String get path {
    final parameters = <String>[
      if (from != null) 'from=$from',
      if (through != null) 'through=$through',
      if (days != null) 'days=$days',
      for (final id in accountIds) 'accountId=$id',
      if (currency != null) 'currency=$currency',
    ];
    return parameters.isEmpty
        ? 'finance/cash-flow'
        : 'finance/cash-flow?${parameters.join('&')}';
  }
}

int? _cashFlowRelativeDays(int? days, String? through) {
  if (days == null) return null;
  if (through != null) {
    throw const FormatException('use through or days, not both.');
  }
  if (days < 1 || days > financialCashFlowWindowMaxDays) {
    throw const FormatException('days is invalid.');
  }
  return days;
}

List<String> _cashFlowAccountIds(List<String> ids) {
  if (ids.length > financialCashFlowAccountsMax) {
    throw const FormatException('too many accounts.');
  }
  final canonical = [
    for (final id in ids) _financialResourceId(id, 'accountId').toLowerCase(),
  ];
  if (canonical.toSet().length != canonical.length) {
    throw const FormatException('accounts must be unique.');
  }
  return List.unmodifiable(canonical);
}

/// Inclusive number of days between two canonical `YYYY-MM-DD` dates. Calendar
/// arithmetic only (UTC midnight), never money.
int _cashFlowDaySpan(String from, String through) =>
    DateTime.parse(
      '${through}T00:00:00Z',
    ).difference(DateTime.parse('${from}T00:00:00Z')).inDays +
    1;

String _cashFlowNextDay(String value) {
  final next = DateTime.parse(
    '${value}T00:00:00Z',
  ).add(const Duration(days: 1));
  return '${next.year.toString().padLeft(4, '0')}-'
      '${next.month.toString().padLeft(2, '0')}-'
      '${next.day.toString().padLeft(2, '0')}';
}

extension FinancialCashFlowApiCalls on FinancialCoreApi {
  /// The cash flow of one window, read from one consistent server snapshot.
  /// Never cached, never computed here.
  Future<FinancialCashFlow> getCashFlow(FinancialCashFlowQuery query) async {
    final response = await client.get(query.path);
    final cashFlow = _parseCashFlow(
      _strictJsonObject(
        response.body,
        allowedKeys: _cashFlowKeys,
        label: 'cash flow response',
      ),
    );
    // Omitted bounds are server defaults: `from` is the reference date and the
    // length is `days` (30 when neither `days` nor `through` is sent).
    final expectedDays =
        query.days ?? (query.through == null ? _cashFlowDefaultDays : null);
    if ((query.from != null && cashFlow.from != query.from) ||
        (query.from == null && cashFlow.from != cashFlow.referenceDate) ||
        (query.through != null && cashFlow.through != query.through) ||
        (expectedDays != null && cashFlow.days != expectedDays)) {
      throw const FormatException('cash flow window mismatch.');
    }
    for (final group in cashFlow.groups) {
      if (query.currency != null && group.currency != query.currency) {
        throw const FormatException('cash flow currency mismatch.');
      }
      if (query.accountIds.isNotEmpty &&
          group.accounts.any(
            (account) => !query.accountIds.contains(account.accountId),
          )) {
        throw const FormatException('cash flow account mismatch.');
      }
    }
    return cashFlow;
  }
}

FinancialCashFlow _parseCashFlow(Map<String, Object?> values) {
  final reference = _date(values['referenceDate'], 'referenceDate');
  final from = _date(values['from'], 'from');
  final through = _date(values['through'], 'through');
  final days = values['days'];
  if (days is! int ||
      days < 1 ||
      days > financialCashFlowWindowMaxDays ||
      through.compareTo(from) < 0 ||
      _cashFlowDaySpan(from, through) != days ||
      from.compareTo(reference) > 0) {
    throw const FormatException('cash flow window is invalid.');
  }
  final rawSources = values['excludedSources'];
  if (rawSources is! List || rawSources.length > 32) {
    throw const FormatException('excludedSources is invalid.');
  }
  final excluded = List<String>.unmodifiable(
    rawSources.map(
      (item) => _boundedText(item, 'excludedSources', maxLength: 32),
    ),
  );
  final rawGroups = values['groups'];
  if (rawGroups is! List || rawGroups.length > financialCashFlowAccountsMax) {
    throw const FormatException('groups is invalid.');
  }
  final groups = List<FinancialCashFlowGroup>.unmodifiable(
    rawGroups.map(
      (raw) => _parseCashFlowGroup(raw, reference, from, through, days),
    ),
  );
  final currencies = groups.map((group) => group.currency).toList();
  if (currencies.toSet().length != currencies.length) {
    throw const FormatException('duplicate cash flow currency.');
  }
  final events = groups.fold<int>(
    0,
    (total, group) => total + group.events.length,
  );
  final accounts = groups.fold<int>(
    0,
    (total, group) => total + group.accounts.length,
  );
  if (events > financialCashFlowEventsMax ||
      accounts > financialCashFlowAccountsMax) {
    throw const FormatException('cash flow exceeds the contract.');
  }
  return FinancialCashFlow(
    referenceDate: reference,
    from: from,
    through: through,
    days: days,
    calculatedAt: _timestamp(values['calculatedAt'], 'calculatedAt'),
    excludedSources: excluded,
    groups: groups,
  );
}

FinancialCashFlowGroup _parseCashFlowGroup(
  Object? raw,
  String reference,
  String from,
  String through,
  int dayCount,
) {
  final values = _strictMap(
    raw,
    allowedKeys: _cashFlowGroupKeys,
    label: 'cash flow group',
  );
  final currency = _currency(values['currency'], 'currency');
  FinancialMoneyWire money(Object? value) => _cashFlowMoney(value, currency);

  final rawDays = values['days'];
  if (rawDays is! List || rawDays.length != dayCount) {
    throw const FormatException('cash flow days are invalid.');
  }
  final days = List<FinancialCashFlowDay>.unmodifiable(
    rawDays.map((item) => _parseCashFlowDay(item, currency)),
  );
  var expected = from;
  for (final day in days) {
    if (day.date != expected) {
      throw const FormatException('cash flow days are not contiguous.');
    }
    // Projected means "on or after the reference date"; a past day is a fact.
    if (day.projected != (day.date.compareTo(reference) >= 0)) {
      throw const FormatException('projected flag contradicts the date.');
    }
    expected = _cashFlowNextDay(expected);
  }

  final rawAccounts = values['accounts'];
  if (rawAccounts is! List ||
      rawAccounts.isEmpty ||
      rawAccounts.length > financialCashFlowAccountsMax) {
    throw const FormatException('cash flow accounts are invalid.');
  }
  final accounts = List<FinancialCashFlowAccount>.unmodifiable(
    rawAccounts.map((item) => _parseCashFlowAccount(item, currency, days)),
  );
  final accountIds = accounts.map((account) => account.accountId).toSet();
  if (accountIds.length != accounts.length) {
    throw const FormatException('duplicate cash flow account.');
  }
  for (final day in days) {
    // A day is anchored only when every account of the group is.
    if (day.anchored !=
        accounts.every((account) => account.anchoredOn(day.date))) {
      throw const FormatException('anchored flag contradicts the accounts.');
    }
  }

  final rawEvents = values['events'];
  if (rawEvents is! List || rawEvents.length > financialCashFlowEventsMax) {
    throw const FormatException('cash flow events are invalid.');
  }
  final events = List<FinancialCashFlowEvent>.unmodifiable(
    rawEvents.map((item) => _parseCashFlowEvent(item, currency)),
  );
  var previous = from;
  for (final event in events) {
    if (!accountIds.contains(event.accountId) ||
        event.date.compareTo(from) < 0 ||
        event.date.compareTo(through) > 0 ||
        event.date.compareTo(previous) < 0) {
      throw const FormatException('cash flow event is out of place.');
    }
    previous = event.date;
  }

  final rawIssues = values['issues'];
  if (rawIssues is! List || rawIssues.length > 16) {
    throw const FormatException('cash flow issues are invalid.');
  }
  final issues = List<FinancialCashFlowIssue>.unmodifiable(
    rawIssues.map((item) => _parseCashFlowIssue(item, accountIds)),
  );
  final status = FinancialCashFlowProjectionStatus.parse(
    values['projectionStatus'],
  );
  final hasIncomplete = issues.any(
    (issue) => issue.severity == FinancialCashFlowIssueSeverity.incomplete,
  );
  if (status == FinancialCashFlowProjectionStatus.complete && hasIncomplete) {
    // A complete projection with an incomplete issue would hide the risk.
    throw const FormatException('projectionStatus contradicts its issues.');
  }
  return FinancialCashFlowGroup(
    currency: currency,
    projectionStatus: status,
    issues: issues,
    startingBalance: money(values['startingBalance']),
    balanceAtReference: money(values['balanceAtReference']),
    closingBalance: money(values['closingBalance']),
    totals: _parseCashFlowTotals(values['totals'], currency),
    risk: _cashFlowGroupRisk(values['risk'], currency, [
      for (final day in days)
        if (day.anchored && day.projected) day,
    ]),
    historicalRisk: _cashFlowGroupRisk(values['historicalRisk'], currency, [
      for (final day in days)
        if (day.anchored && !day.projected) day,
    ]),
    accounts: accounts,
    days: days,
    events: events,
  );
}

FinancialMoneyWire _cashFlowMoney(Object? raw, String currency) {
  final money = _parseMoney(raw);
  if (money.currency != currency) {
    throw const FormatException('cash flow money mixes currencies.');
  }
  return money;
}

int _cashFlowCount(Object? value, String fieldName) {
  if (value is! int || value < 0) {
    throw FormatException('$fieldName is invalid.');
  }
  return value;
}

bool _cashFlowFlag(Object? value, String fieldName) {
  if (value is! bool) throw FormatException('$fieldName is invalid.');
  return value;
}

String? _cashFlowOptionalDate(Object? value, String fieldName) =>
    value == null ? null : _date(value, fieldName);

String? _cashFlowOptionalId(Object? value, String fieldName) =>
    value == null ? null : _financialResourceId(value, fieldName);

/// A risk must cover exactly the [dates] it claims to evaluate: absent when
/// there are none, present otherwise, with every reported date among them.
/// This rejects a deficit that already happened presented as a future risk,
/// and a pre-anchor day used as evidence.
FinancialCashFlowRisk? _parseCashFlowRisk(
  Object? raw,
  String currency,
  List<String> dates,
) {
  if (dates.isEmpty) {
    if (raw != null) {
      throw const FormatException('risk without evaluable days.');
    }
    return null;
  }
  if (raw == null) throw const FormatException('risk is missing.');
  final values = _strictMap(raw, allowedKeys: _cashFlowRiskKeys, label: 'risk');
  final minimumDate = _date(values['minimumBalanceDate'], 'minimumBalanceDate');
  final firstNegative = _cashFlowOptionalDate(
    values['firstNegativeDate'],
    'firstNegativeDate',
  );
  final negativeDays = _cashFlowCount(values['negativeDays'], 'negativeDays');
  final evaluatedDays = _cashFlowCount(
    values['evaluatedDays'],
    'evaluatedDays',
  );
  final evaluated = dates.toSet();
  if (evaluatedDays != dates.length ||
      negativeDays > evaluatedDays ||
      !evaluated.contains(minimumDate) ||
      (firstNegative != null && !evaluated.contains(firstNegative))) {
    throw const FormatException('risk does not match the evaluated days.');
  }
  if ((firstNegative == null) != (negativeDays == 0)) {
    throw const FormatException('risk is inconsistent.');
  }
  return FinancialCashFlowRisk(
    minimumBalance: _cashFlowMoney(values['minimumBalance'], currency),
    minimumBalanceDate: minimumDate,
    firstNegativeDate: firstNegative,
    negativeDays: negativeDays,
    evaluatedDays: evaluatedDays,
  );
}

/// The group risk is also checked against the server's own day flags: its
/// first deficit is the first negative evaluated day and its count matches.
FinancialCashFlowRisk? _cashFlowGroupRisk(
  Object? raw,
  String currency,
  List<FinancialCashFlowDay> days,
) {
  final risk = _parseCashFlowRisk(raw, currency, [
    for (final day in days) day.date,
  ]);
  if (risk == null) return null;
  final negative = [
    for (final day in days)
      if (day.negative) day.date,
  ];
  if (risk.negativeDays != negative.length ||
      risk.firstNegativeDate != (negative.isEmpty ? null : negative.first)) {
    throw const FormatException('risk contradicts the days.');
  }
  return risk;
}

FinancialCashFlowIssue _parseCashFlowIssue(
  Object? raw,
  Set<String> accountIds,
) {
  final values = _strictMap(
    raw,
    allowedKeys: _cashFlowIssueKeys,
    label: 'cash flow issue',
  );
  final rawAccounts = values['accountIds'];
  if (rawAccounts is! List ||
      rawAccounts.length > financialCashFlowAccountsMax) {
    throw const FormatException('issue accountIds is invalid.');
  }
  final ids = List<String>.unmodifiable(
    rawAccounts.map((item) => _financialResourceId(item, 'accountIds')),
  );
  if (ids.any((id) => !accountIds.contains(id))) {
    throw const FormatException('issue refers to an unknown account.');
  }
  final count = _cashFlowCount(values['count'], 'count');
  if (count < 1) throw const FormatException('count is invalid.');
  return FinancialCashFlowIssue(
    code: FinancialCashFlowIssueCode.parse(values['code']),
    severity: FinancialCashFlowIssueSeverity.parse(values['severity']),
    count: count,
    accountIds: ids,
  );
}

FinancialCashFlowTotals _parseCashFlowTotals(Object? raw, String currency) {
  final values = _strictMap(
    raw,
    allowedKeys: _cashFlowTotalsKeys,
    label: 'cash flow totals',
  );
  FinancialMoneyWire money(String key) => _cashFlowMoney(values[key], currency);
  return FinancialCashFlowTotals(
    realizedIncome: money('realizedIncome'),
    realizedExpense: money('realizedExpense'),
    neutralIn: money('neutralIn'),
    neutralOut: money('neutralOut'),
    realizedNet: money('realizedNet'),
    expectedIncome: money('expectedIncome'),
    expectedExpense: money('expectedExpense'),
    expectedNet: money('expectedNet'),
    overdueCount: _cashFlowCount(values['overdueCount'], 'overdueCount'),
    overdueNet: money('overdueNet'),
    recurrenceRealizedCount: _cashFlowCount(
      values['recurrenceRealizedCount'],
      'recurrenceRealizedCount',
    ),
    recurrenceRealizedExpected: money('recurrenceRealizedExpected'),
    recurrenceRealizedActual: money('recurrenceRealizedActual'),
    realizedCount: _cashFlowCount(values['realizedCount'], 'realizedCount'),
    expectedCount: _cashFlowCount(values['expectedCount'], 'expectedCount'),
  );
}

FinancialCashFlowAccount _parseCashFlowAccount(
  Object? raw,
  String currency,
  List<FinancialCashFlowDay> days,
) {
  final values = _strictMap(
    raw,
    allowedKeys: _cashFlowAccountKeys,
    label: 'cash flow account',
  );
  final hasOpening = _cashFlowFlag(
    values['hasOpeningBalance'],
    'hasOpeningBalance',
  );
  final openingDate = _cashFlowOptionalDate(
    values['openingBalanceDate'],
    'openingBalanceDate',
  );
  if (hasOpening != (openingDate != null)) {
    throw const FormatException('opening balance flag is inconsistent.');
  }
  FinancialMoneyWire money(String key) => _cashFlowMoney(values[key], currency);
  // The account is evaluated only from its own opening balance date on.
  List<String> anchored({required bool projected}) => [
    for (final day in days)
      if (day.projected == projected &&
          openingDate != null &&
          openingDate.compareTo(day.date) <= 0)
        day.date,
  ];
  return FinancialCashFlowAccount(
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    name: _boundedText(values['name'], 'name', maxLength: 96),
    accountType: FinancialAccountType.parse(values['accountType']),
    visibilityScope: FinancialVisibilityScope.parse(values['visibilityScope']),
    status: FinancialAccountStatus.parse(values['status']),
    hasOpeningBalance: hasOpening,
    openingBalanceDate: openingDate,
    startingBalance: money('startingBalance'),
    balanceAtReference: money('balanceAtReference'),
    realizedNet: money('realizedNet'),
    expectedNet: money('expectedNet'),
    closingBalance: money('closingBalance'),
    risk: _parseCashFlowRisk(
      values['risk'],
      currency,
      anchored(projected: true),
    ),
    historicalRisk: _parseCashFlowRisk(
      values['historicalRisk'],
      currency,
      anchored(projected: false),
    ),
  );
}

FinancialCashFlowDay _parseCashFlowDay(Object? raw, String currency) {
  final values = _strictMap(
    raw,
    allowedKeys: _cashFlowDayKeys,
    label: 'cash flow day',
  );
  FinancialMoneyWire money(String key) => _cashFlowMoney(values[key], currency);
  final closing = money('closing');
  final negative = _cashFlowFlag(values['negative'], 'negative');
  if (negative != closing.isNegative) {
    throw const FormatException('negative flag contradicts the closing.');
  }
  return FinancialCashFlowDay(
    date: _date(values['date'], 'date'),
    opening: money('opening'),
    realizedIncome: money('realizedIncome'),
    realizedExpense: money('realizedExpense'),
    expectedIncome: money('expectedIncome'),
    expectedExpense: money('expectedExpense'),
    neutralNet: money('neutralNet'),
    closing: closing,
    projected: _cashFlowFlag(values['projected'], 'projected'),
    anchored: _cashFlowFlag(values['anchored'], 'anchored'),
    negative: negative,
  );
}

FinancialCashFlowEvent _parseCashFlowEvent(Object? raw, String currency) {
  final values = _strictMap(
    raw,
    allowedKeys: _cashFlowEventKeys,
    label: 'cash flow event',
  );
  final kind = FinancialCashFlowEventKind.parse(values['kind']);
  final effect = FinancialResultEffect.parse(values['resultEffect']);
  final amount = _nonZeroCashFlowMoney(values['amount'], currency);
  final movementId = _cashFlowOptionalId(values['movementId'], 'movementId');
  final rawRole = values['movementRole'];
  final role = rawRole == null ? null : FinancialMovementRole.parse(rawRole);
  final recurrenceId = _cashFlowOptionalId(
    values['recurrenceId'],
    'recurrenceId',
  );
  final occurrenceId = _cashFlowOptionalId(
    values['occurrenceId'],
    'occurrenceId',
  );
  final rawVersion = values['ruleVersion'];
  if (rawVersion != null && (rawVersion is! int || rawVersion < 1)) {
    throw const FormatException('ruleVersion is invalid.');
  }
  final scheduledDate = _cashFlowOptionalDate(
    values['scheduledDate'],
    'scheduledDate',
  );
  final periodStart = _cashFlowOptionalDate(
    values['periodStart'],
    'periodStart',
  );
  final overdue = _cashFlowFlag(values['overdue'], 'overdue');
  final rawExpected = values['expectedAmount'];
  final expectedAmount = rawExpected == null
      ? null
      : _nonZeroCashFlowMoney(rawExpected, currency);
  final date = _date(values['date'], 'date');

  if (kind == FinancialCashFlowEventKind.realized) {
    if (movementId == null || role == null || overdue) {
      throw const FormatException('realized event is inconsistent.');
    }
  } else {
    // An expectation never carries a Movement and always names its recurrence.
    if (movementId != null ||
        role != null ||
        values['reversalOfId'] != null ||
        values['transferId'] != null ||
        recurrenceId == null ||
        rawVersion == null ||
        scheduledDate == null ||
        periodStart == null ||
        expectedAmount == null ||
        effect == FinancialResultEffect.neutral) {
      throw const FormatException('expected event is inconsistent.');
    }
    if ((kind == FinancialCashFlowEventKind.expectedOccurrence) !=
        (occurrenceId != null)) {
      throw const FormatException('expected event origin is inconsistent.');
    }
    if (overdue != (scheduledDate.compareTo(date) < 0)) {
      throw const FormatException('overdue flag is inconsistent.');
    }
  }
  return FinancialCashFlowEvent(
    date: date,
    kind: kind,
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    amount: amount,
    resultEffect: effect,
    description: _optionalBoundedText(
      values['description'],
      'description',
      maxLength: 256,
    ),
    movementId: movementId,
    movementRole: role,
    reversalOfId: _cashFlowOptionalId(values['reversalOfId'], 'reversalOfId'),
    transferId: _cashFlowOptionalId(values['transferId'], 'transferId'),
    occurrenceId: occurrenceId,
    recurrenceId: recurrenceId,
    ruleVersion: rawVersion as int?,
    periodStart: periodStart,
    scheduledDate: scheduledDate,
    overdue: overdue,
    expectedAmount: expectedAmount,
    balanceAfter: _cashFlowMoney(values['balanceAfter'], currency),
    accountBalanceAfter: _cashFlowMoney(
      values['accountBalanceAfter'],
      currency,
    ),
  );
}

FinancialMoneyWire _nonZeroCashFlowMoney(Object? raw, String currency) {
  final money = _cashFlowMoney(raw, currency);
  if (money.isZero) throw const FormatException('event amount is zero.');
  return money;
}
