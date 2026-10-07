part of 'financial_core_api.dart';

// Manual monthly recurrences (#254). A recurrence is a *model* and an occurrence is
// one *instance* of it for a month: neither is a financial fact. Only registering
// an occurrence creates a Movement, and only the server does that (exactly one,
// atomically). This file validates wire shapes and builds requests; it computes no
// calendar rule, no balance and no realized amount. Money is decimal text, never
// double.

const _recurrenceKeys = <String>{
  'id',
  'accountId',
  'ownerOperatorId',
  'description',
  'resultEffect',
  'expected',
  'frequency',
  'startDate',
  'dayOfMonth',
  'endDate',
  'status',
  'version',
  'createdAt',
  'updatedAt',
  'canEdit',
};
const _recurrencesKeys = <String>{'items'};
const _occurrenceKeys = <String>{
  'id',
  'recurrenceId',
  'accountId',
  'ownerOperatorId',
  'periodStart',
  'scheduledDate',
  'ruleVersion',
  'resultEffect',
  'expected',
  'description',
  'status',
  'createdAt',
  'updatedAt',
  'canEdit',
  'realization',
};
const _occurrenceRealizationKeys = <String>{
  'movementId',
  'actual',
  'effectiveDate',
  'competenceDate',
  'realizedAt',
  'movementState',
};
const _occurrencesKeys = <String>{'items'};
const _occurrenceGenerationKeys = <String>{'createdCount', 'items'};

const financialRecurrenceDescriptionMaxLength = 256;

/// Server-side cap on the months of one generation call (and of one read window).
const financialRecurrenceWindowMaxMonths = 12;

enum FinancialRecurrenceStatus {
  active('ACTIVE'),
  paused('PAUSED');

  const FinancialRecurrenceStatus(this.wireValue);
  final String wireValue;

  static FinancialRecurrenceStatus parse(Object? value) =>
      _enumByWire(values, value, 'status', (item) => item.wireValue);
}

enum FinancialOccurrenceStatus {
  pending('PENDING'),
  realized('REALIZED'),
  skipped('SKIPPED'),
  superseded('SUPERSEDED');

  const FinancialOccurrenceStatus(this.wireValue);
  final String wireValue;

  static FinancialOccurrenceStatus parse(Object? value) =>
      _enumByWire(values, value, 'status', (item) => item.wireValue);
}

/// Derived state of the Movement an occurrence was registered as. A reversal of
/// the Movement never reopens the occurrence: it stays REALIZED.
enum FinancialOccurrenceMovementState {
  active('ACTIVE'),
  reversed('REVERSED');

  const FinancialOccurrenceMovementState(this.wireValue);
  final String wireValue;

  static FinancialOccurrenceMovementState parse(Object? value) =>
      _enumByWire(values, value, 'movementState', (item) => item.wireValue);
}

class FinancialRecurrence {
  const FinancialRecurrence({
    required this.id,
    required this.accountId,
    required this.ownerOperatorId,
    required this.description,
    required this.resultEffect,
    required this.expected,
    required this.startDate,
    required this.dayOfMonth,
    required this.endDate,
    required this.status,
    required this.version,
    required this.createdAt,
    required this.updatedAt,
    required this.canEdit,
  });

  final String id;
  final String accountId;
  final String ownerOperatorId;
  final String description;
  final FinancialResultEffect resultEffect;

  /// The plan. Never a realized amount.
  final FinancialMoneyWire expected;
  final String startDate;
  final int dayOfMonth;
  final String? endDate;
  final FinancialRecurrenceStatus status;

  /// CAS token: the only valid `expectedVersion` of the next edit.
  final int version;
  final DateTime createdAt;
  final DateTime updatedAt;

  /// Decided by the server: the operator owns this rule (the account owner).
  final bool canEdit;

  bool get isPaused => status == FinancialRecurrenceStatus.paused;
}

class FinancialOccurrenceRealization {
  const FinancialOccurrenceRealization({
    required this.movementId,
    required this.actual,
    required this.effectiveDate,
    required this.competenceDate,
    required this.realizedAt,
    required this.movementState,
  });

  final String movementId;

  /// The fact, read from the Movement. May differ from the expected amount.
  final FinancialMoneyWire actual;
  final String effectiveDate;
  final String competenceDate;
  final DateTime realizedAt;
  final FinancialOccurrenceMovementState movementState;
}

class FinancialRecurrenceOccurrence {
  const FinancialRecurrenceOccurrence({
    required this.id,
    required this.recurrenceId,
    required this.accountId,
    required this.ownerOperatorId,
    required this.periodStart,
    required this.scheduledDate,
    required this.ruleVersion,
    required this.resultEffect,
    required this.expected,
    required this.description,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
    required this.canEdit,
    required this.realization,
  });

  final String id;
  final String recurrenceId;
  final String accountId;
  final String ownerOperatorId;

  /// First day of the month (`YYYY-MM-DD`), server-decided.
  final String periodStart;

  /// The date the monthly calendar produced (server-decided).
  final String scheduledDate;
  final int ruleVersion;
  final FinancialResultEffect resultEffect;

  /// Snapshot of the plan this occurrence was generated from.
  final FinancialMoneyWire expected;
  final String description;
  final FinancialOccurrenceStatus status;
  final DateTime createdAt;
  final DateTime updatedAt;
  final bool canEdit;

  /// Only a REALIZED occurrence carries one.
  final FinancialOccurrenceRealization? realization;

  /// `YYYY-MM`.
  String get period => periodStart.substring(0, 7);
}

class FinancialRecurrenceEditResult {
  const FinancialRecurrenceEditResult({
    required this.recurrence,
    required this.supersededCount,
  });

  final FinancialRecurrence recurrence;

  /// Future PENDING occurrences the edit explicitly superseded.
  final int supersededCount;
}

class FinancialOccurrenceGeneration {
  const FinancialOccurrenceGeneration({
    required this.createdCount,
    required this.items,
  });

  final int createdCount;
  final List<FinancialRecurrenceOccurrence> items;
}

int _dayOfMonth(int value) {
  if (value < 1 || value > 31) {
    throw const FormatException('dayOfMonth is invalid.');
  }
  return value;
}

String _recurrencePeriod(String value) => _budgetPeriod(value);

class FinancialRecurrenceCreateInput {
  FinancialRecurrenceCreateInput({
    required String accountId,
    required String description,
    required this.resultEffect,
    required String expectedAmount,
    required String currency,
    required String startDate,
    required int dayOfMonth,
    String? endDate,
    String? idempotencyKey,
  }) : accountId = _financialResourceId(accountId, 'accountId'),
       description = _boundedText(
         description.trim(),
         'description',
         maxLength: financialRecurrenceDescriptionMaxLength,
       ),
       expectedAmount = _positiveDecimalAmount(
         expectedAmount,
         'expectedAmount',
       ),
       currency = _currency(currency, 'currency'),
       startDate = _date(startDate, 'startDate'),
       dayOfMonth = _dayOfMonth(dayOfMonth),
       endDate = endDate == null ? null : _date(endDate, 'endDate'),
       idempotencyKey = idempotencyKey == null
           ? _newUuidV4()
           : _idempotencyKey(idempotencyKey) {
    if (resultEffect == FinancialResultEffect.neutral) {
      throw const FormatException('resultEffect is invalid.');
    }
    if (this.expectedAmount.startsWith('-')) {
      throw const FormatException('expectedAmount must be positive.');
    }
    final end = this.endDate;
    if (end != null && end.compareTo(this.startDate) < 0) {
      throw const FormatException('endDate must not precede startDate.');
    }
  }

  final String accountId;
  final String description;
  final FinancialResultEffect resultEffect;
  final String expectedAmount;
  final String currency;
  final String startDate;
  final int dayOfMonth;
  final String? endDate;
  final String idempotencyKey;

  /// The same request under another idempotency key (an explicit, identical retry
  /// of an attempt whose outcome is unknown reuses the original key).
  FinancialRecurrenceCreateInput withIdempotencyKey(String key) =>
      FinancialRecurrenceCreateInput(
        accountId: accountId,
        description: description,
        resultEffect: resultEffect,
        expectedAmount: expectedAmount,
        currency: currency,
        startDate: startDate,
        dayOfMonth: dayOfMonth,
        endDate: endDate,
        idempotencyKey: key,
      );

  /// The logical attempt: same material, same key on an explicit retry.
  String get attemptKey => [
    accountId,
    description,
    resultEffect.wireValue,
    _canonicalDecimal(expectedAmount),
    currency,
    startDate,
    dayOfMonth.toString(),
    endDate ?? '',
  ].join('\u001f');

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'accountId': accountId,
    'description': description,
    'resultEffect': resultEffect.wireValue,
    'expectedAmount': expectedAmount,
    'currency': currency,
    'startDate': startDate,
    'dayOfMonth': dayOfMonth,
    'endDate': endDate,
  };
}

class FinancialRecurrenceReplaceInput {
  FinancialRecurrenceReplaceInput({
    required this.expectedVersion,
    required String description,
    required String expectedAmount,
    required int dayOfMonth,
    String? endDate,
  }) : description = _boundedText(
         description.trim(),
         'description',
         maxLength: financialRecurrenceDescriptionMaxLength,
       ),
       expectedAmount = _positiveDecimalAmount(
         expectedAmount,
         'expectedAmount',
       ),
       dayOfMonth = _dayOfMonth(dayOfMonth),
       endDate = endDate == null ? null : _date(endDate, 'endDate') {
    if (expectedVersion < 1) {
      throw const FormatException('expectedVersion is invalid.');
    }
    if (this.expectedAmount.startsWith('-')) {
      throw const FormatException('expectedAmount must be positive.');
    }
  }

  final int expectedVersion;
  final String description;
  final String expectedAmount;
  final int dayOfMonth;
  final String? endDate;

  Map<String, Object?> toJson() => {
    'expectedVersion': expectedVersion,
    'description': description,
    'expectedAmount': expectedAmount,
    'dayOfMonth': dayOfMonth,
    'endDate': endDate,
  };
}

/// The explicit user decision that turns one PENDING occurrence into a fact.
class FinancialRecurrenceRealizeInput {
  FinancialRecurrenceRealizeInput({
    required String actualAmount,
    required String currency,
    required String effectiveDate,
    required String competenceDate,
    String? idempotencyKey,
  }) : actualAmount = _positiveDecimalAmount(actualAmount, 'actualAmount'),
       currency = _currency(currency, 'currency'),
       effectiveDate = _date(effectiveDate, 'effectiveDate'),
       competenceDate = _date(competenceDate, 'competenceDate'),
       idempotencyKey = idempotencyKey == null
           ? _newUuidV4()
           : _idempotencyKey(idempotencyKey) {
    if (this.actualAmount.startsWith('-')) {
      throw const FormatException('actualAmount must be positive.');
    }
  }

  final String actualAmount;
  final String currency;
  final String effectiveDate;
  final String competenceDate;
  final String idempotencyKey;

  FinancialRecurrenceRealizeInput withIdempotencyKey(String key) =>
      FinancialRecurrenceRealizeInput(
        actualAmount: actualAmount,
        currency: currency,
        effectiveDate: effectiveDate,
        competenceDate: competenceDate,
        idempotencyKey: key,
      );

  /// The logical attempt on one occurrence: same material, same key on an
  /// explicit retry of an attempt whose outcome is unknown.
  String attemptKey(String occurrenceId) => [
    occurrenceId,
    _canonicalDecimal(actualAmount),
    currency,
    effectiveDate,
    competenceDate,
  ].join('\u001f');

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'actualAmount': actualAmount,
    'currency': currency,
    'effectiveDate': effectiveDate,
    'competenceDate': competenceDate,
  };
}

extension FinancialRecurrenceApiCalls on FinancialCoreApi {
  /// The recurrences visible to the operator (the account's audience).
  Future<List<FinancialRecurrence>> listRecurrences() async {
    final response = await client.get('finance/recurrences');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _recurrencesKeys,
      label: 'recurrences response',
    );
    final raw = root['items'];
    if (raw is! List || raw.length > 200) {
      throw const FormatException('items is invalid.');
    }
    final items = List<FinancialRecurrence>.unmodifiable(
      raw.map(_parseRecurrence),
    );
    if (items.map((item) => item.id).toSet().length != items.length) {
      throw const FormatException('duplicate recurrence.');
    }
    return items;
  }

  /// Creates a rule. The response is cross-checked against the request: anything
  /// that does not mirror it is an invalid (ambiguous) answer.
  Future<FinancialRecurrence> createRecurrence(
    FinancialRecurrenceCreateInput input,
  ) async {
    final response = await client.post(
      'finance/recurrences',
      jsonBody: input.toJson(),
    );
    final recurrence = _parseRecurrence(
      _decodeJsonObject(response.body, 'recurrence response'),
    );
    if (recurrence.accountId != input.accountId ||
        recurrence.description != input.description ||
        recurrence.resultEffect != input.resultEffect ||
        recurrence.expected.currency != input.currency ||
        _canonicalDecimal(recurrence.expected.amount) !=
            _canonicalDecimal(input.expectedAmount) ||
        recurrence.startDate != input.startDate ||
        recurrence.dayOfMonth != input.dayOfMonth ||
        recurrence.endDate != input.endDate ||
        recurrence.status != FinancialRecurrenceStatus.active ||
        recurrence.version != 1) {
      throw const FormatException('recurrence response mismatch.');
    }
    return recurrence;
  }

  /// One compare-and-swap edit under `expectedVersion`. A stale version is a
  /// `409` that wrote nothing; the caller must re-read and decide.
  Future<FinancialRecurrenceEditResult> replaceRecurrence(
    String recurrenceId,
    FinancialRecurrenceReplaceInput input,
  ) async {
    final id = _financialResourceId(recurrenceId, 'recurrenceId');
    final response = await client.put(
      'finance/recurrences/$id',
      jsonBody: input.toJson(),
    );
    final values = _decodeJsonObject(response.body, 'recurrence response');
    final recurrence = _parseRecurrence(
      Map<String, Object?>.of(values)..remove('supersededCount'),
    );
    final superseded = values['supersededCount'];
    if (superseded is! int || superseded < 0) {
      throw const FormatException('supersededCount is invalid.');
    }
    final changed = recurrence.version == input.expectedVersion + 1;
    if (recurrence.id != id ||
        (!changed && recurrence.version != input.expectedVersion) ||
        (!changed && superseded != 0) ||
        recurrence.description != input.description ||
        _canonicalDecimal(recurrence.expected.amount) !=
            _canonicalDecimal(input.expectedAmount) ||
        recurrence.dayOfMonth != input.dayOfMonth ||
        recurrence.endDate != input.endDate) {
      throw const FormatException('recurrence response mismatch.');
    }
    return FinancialRecurrenceEditResult(
      recurrence: recurrence,
      supersededCount: superseded,
    );
  }

  /// PAUSED stops new generation and keeps the history. Idempotent by state.
  Future<FinancialRecurrence> pauseRecurrence(String recurrenceId) =>
      _recurrenceTransition(
        recurrenceId,
        'pause',
        FinancialRecurrenceStatus.paused,
      );

  /// ACTIVE allows new generation again. It generates nothing by itself.
  Future<FinancialRecurrence> resumeRecurrence(String recurrenceId) =>
      _recurrenceTransition(
        recurrenceId,
        'resume',
        FinancialRecurrenceStatus.active,
      );

  Future<FinancialRecurrence> _recurrenceTransition(
    String recurrenceId,
    String action,
    FinancialRecurrenceStatus expected,
  ) async {
    final id = _financialResourceId(recurrenceId, 'recurrenceId');
    final response = await client.post('finance/recurrences/$id/$action');
    final recurrence = _parseRecurrence(
      _decodeJsonObject(response.body, 'recurrence response'),
    );
    if (recurrence.id != id || recurrence.status != expected) {
      throw const FormatException('recurrence response mismatch.');
    }
    return recurrence;
  }

  /// Explicitly materializes the due months of `[fromPeriod, throughPeriod]` as
  /// PENDING forecasts. Nothing here touches the ledger.
  Future<FinancialOccurrenceGeneration> generateOccurrences(
    String recurrenceId, {
    required String fromPeriod,
    required String throughPeriod,
  }) async {
    final id = _financialResourceId(recurrenceId, 'recurrenceId');
    final from = _recurrencePeriod(fromPeriod);
    final through = _recurrencePeriod(throughPeriod);
    final response = await client.post(
      'finance/recurrences/$id/occurrences/generate',
      jsonBody: {'fromPeriod': from, 'throughPeriod': through},
    );
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _occurrenceGenerationKeys,
      label: 'occurrence generation response',
    );
    final created = root['createdCount'];
    final items = _parseOccurrences(root['items']);
    if (created is! int || created < 0 || created > items.length) {
      throw const FormatException('createdCount is invalid.');
    }
    for (final item in items) {
      if (item.recurrenceId != id ||
          item.period.compareTo(from) < 0 ||
          item.period.compareTo(through) > 0) {
        throw const FormatException('occurrence violates the window.');
      }
    }
    return FinancialOccurrenceGeneration(createdCount: created, items: items);
  }

  /// The occurrences of a bounded month window. SUPERSEDED rows are history and
  /// never listed here.
  Future<List<FinancialRecurrenceOccurrence>> listOccurrences({
    required String fromPeriod,
    required String throughPeriod,
  }) async {
    final from = _recurrencePeriod(fromPeriod);
    final through = _recurrencePeriod(throughPeriod);
    final response = await client.get(
      'finance/recurrence-occurrences?fromPeriod=$from&throughPeriod=$through',
    );
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _occurrencesKeys,
      label: 'occurrences response',
    );
    final items = _parseOccurrences(root['items']);
    for (final item in items) {
      if (item.period.compareTo(from) < 0 ||
          item.period.compareTo(through) > 0 ||
          item.status == FinancialOccurrenceStatus.superseded) {
        throw const FormatException('occurrence violates the window.');
      }
    }
    return items;
  }

  /// PENDING -> SKIPPED. No Movement, no balance change. Idempotent.
  Future<FinancialRecurrenceOccurrence> skipOccurrence(
    String occurrenceId,
  ) async {
    final id = _financialResourceId(occurrenceId, 'occurrenceId');
    final response = await client.post(
      'finance/recurrence-occurrences/$id/skip',
    );
    final occurrence = _parseOccurrence(
      _decodeJsonObject(response.body, 'occurrence response'),
    );
    if (occurrence.id != id ||
        occurrence.status != FinancialOccurrenceStatus.skipped) {
      throw const FormatException('occurrence response mismatch.');
    }
    return occurrence;
  }

  /// Registers one PENDING occurrence: the server creates exactly one canonical
  /// Movement and links it atomically. The response is cross-checked against the
  /// request.
  Future<FinancialRecurrenceOccurrence> realizeOccurrence(
    String occurrenceId,
    FinancialRecurrenceRealizeInput input,
  ) async {
    final id = _financialResourceId(occurrenceId, 'occurrenceId');
    final response = await client.post(
      'finance/recurrence-occurrences/$id/realize',
      jsonBody: input.toJson(),
    );
    final occurrence = _parseOccurrence(
      _decodeJsonObject(response.body, 'occurrence response'),
    );
    final link = occurrence.realization;
    if (occurrence.id != id ||
        occurrence.status != FinancialOccurrenceStatus.realized ||
        link == null ||
        link.actual.currency != input.currency ||
        _canonicalDecimal(link.actual.amount) !=
            _canonicalDecimal(input.actualAmount) ||
        link.effectiveDate != input.effectiveDate ||
        link.competenceDate != input.competenceDate) {
      throw const FormatException('occurrence response mismatch.');
    }
    return occurrence;
  }
}

List<FinancialRecurrenceOccurrence> _parseOccurrences(Object? raw) {
  if (raw is! List || raw.length > 2400) {
    throw const FormatException('items is invalid.');
  }
  final items = List<FinancialRecurrenceOccurrence>.unmodifiable(
    raw.map(_parseOccurrence),
  );
  if (items.map((item) => item.id).toSet().length != items.length) {
    throw const FormatException('duplicate occurrence.');
  }
  return items;
}

FinancialRecurrence _parseRecurrence(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _recurrenceKeys,
    label: 'recurrence',
  );
  if (values['frequency'] != 'MONTHLY') {
    throw const FormatException('frequency is invalid.');
  }
  final effect = FinancialResultEffect.parse(values['resultEffect']);
  if (effect == FinancialResultEffect.neutral) {
    throw const FormatException('recurrence resultEffect is invalid.');
  }
  final expected = _parseMoney(values['expected']);
  if (expected.isNegative || expected.isZero) {
    throw const FormatException('recurrence expected is invalid.');
  }
  final version = values['version'];
  final canEdit = values['canEdit'];
  final day = values['dayOfMonth'];
  if (version is! int || version < 1) {
    throw const FormatException('version is invalid.');
  }
  if (canEdit is! bool) throw const FormatException('canEdit is invalid.');
  if (day is! int || day < 1 || day > 31) {
    throw const FormatException('dayOfMonth is invalid.');
  }
  final startDate = _date(values['startDate'], 'startDate');
  final rawEnd = values['endDate'];
  final endDate = rawEnd == null ? null : _date(rawEnd, 'endDate');
  if (endDate != null && endDate.compareTo(startDate) < 0) {
    throw const FormatException('recurrence period is invalid.');
  }
  return FinancialRecurrence(
    id: _financialResourceId(values['id'], 'id'),
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    ownerOperatorId: _uuid(values['ownerOperatorId'], 'ownerOperatorId'),
    description: _boundedText(
      values['description'],
      'description',
      maxLength: financialRecurrenceDescriptionMaxLength,
    ),
    resultEffect: effect,
    expected: expected,
    startDate: startDate,
    dayOfMonth: day,
    endDate: endDate,
    status: FinancialRecurrenceStatus.parse(values['status']),
    version: version,
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
    updatedAt: _timestamp(values['updatedAt'], 'updatedAt'),
    canEdit: canEdit,
  );
}

FinancialRecurrenceOccurrence _parseOccurrence(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _occurrenceKeys,
    label: 'recurrence occurrence',
  );
  final effect = FinancialResultEffect.parse(values['resultEffect']);
  if (effect == FinancialResultEffect.neutral) {
    throw const FormatException('occurrence resultEffect is invalid.');
  }
  final expected = _parseMoney(values['expected']);
  if (expected.isNegative || expected.isZero) {
    throw const FormatException('occurrence expected is invalid.');
  }
  final periodStart = _date(values['periodStart'], 'periodStart');
  final scheduledDate = _date(values['scheduledDate'], 'scheduledDate');
  if (!periodStart.endsWith('-01') ||
      scheduledDate.substring(0, 7) != periodStart.substring(0, 7)) {
    throw const FormatException('occurrence period is invalid.');
  }
  final ruleVersion = values['ruleVersion'];
  final canEdit = values['canEdit'];
  if (ruleVersion is! int || ruleVersion < 1) {
    throw const FormatException('ruleVersion is invalid.');
  }
  if (canEdit is! bool) throw const FormatException('canEdit is invalid.');
  final status = FinancialOccurrenceStatus.parse(values['status']);
  final realization = _parseOccurrenceRealization(
    values['realization'],
    expected.currency,
  );
  if ((status == FinancialOccurrenceStatus.realized) != (realization != null)) {
    // Only a REALIZED occurrence carries a link to a Movement.
    throw const FormatException('occurrence realization is invalid.');
  }
  return FinancialRecurrenceOccurrence(
    id: _financialResourceId(values['id'], 'id'),
    recurrenceId: _financialResourceId(values['recurrenceId'], 'recurrenceId'),
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    ownerOperatorId: _uuid(values['ownerOperatorId'], 'ownerOperatorId'),
    periodStart: periodStart,
    scheduledDate: scheduledDate,
    ruleVersion: ruleVersion,
    resultEffect: effect,
    expected: expected,
    description: _boundedText(
      values['description'],
      'description',
      maxLength: financialRecurrenceDescriptionMaxLength,
    ),
    status: status,
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
    updatedAt: _timestamp(values['updatedAt'], 'updatedAt'),
    canEdit: canEdit,
    realization: realization,
  );
}

FinancialOccurrenceRealization? _parseOccurrenceRealization(
  Object? raw,
  String currency,
) {
  if (raw == null) return null;
  final values = _strictMap(
    raw,
    allowedKeys: _occurrenceRealizationKeys,
    label: 'occurrence realization',
  );
  final actual = _parseMoney(values['actual']);
  if (actual.currency != currency || actual.isNegative || actual.isZero) {
    throw const FormatException('occurrence actual is invalid.');
  }
  return FinancialOccurrenceRealization(
    movementId: _financialResourceId(values['movementId'], 'movementId'),
    actual: actual,
    effectiveDate: _date(values['effectiveDate'], 'effectiveDate'),
    competenceDate: _date(values['competenceDate'], 'competenceDate'),
    realizedAt: _timestamp(values['realizedAt'], 'realizedAt'),
    movementState: FinancialOccurrenceMovementState.parse(
      values['movementState'],
    ),
  );
}
