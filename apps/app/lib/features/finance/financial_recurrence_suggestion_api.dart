part of 'financial_core_api.dart';

// Assisted recurrence suggestions (#256, ADR-0028). A suggestion is *derived* by the
// server from realized, visible Movements: it is not a Movement, not an occurrence
// and not a recurrence, and it never changes a balance. The only effects are an
// explicit dismissal (personal) and an explicit acceptance that creates one
// canonical recurrence. This file validates wire shapes and builds requests; it
// detects nothing, computes no calendar rule and no amount. Money is decimal text,
// never double.

const _suggestionKeys = <String>{
  'fingerprint',
  'accountId',
  'description',
  'normalizedDescription',
  'currency',
  'evidence',
  'movementIds',
  'observedDates',
  'observedAmounts',
  'suggestedDayOfMonth',
  'suggestedExpectedAmount',
  'amountBehavior',
  'minAmount',
  'maxAmount',
  'lastAmount',
  'reasonCodes',
  'canAccept',
};
const _suggestionEvidenceKeys = <String>{
  'movementId',
  'effectiveDate',
  'amount',
};
const _suggestionsKeys = <String>{'windowFrom', 'windowThrough', 'items'};
const _suggestionDecisionKeys = <String>{
  'fingerprint',
  'accountId',
  'decision',
  'recurrenceId',
  'decidedAt',
  'created',
};
const _suggestionAcceptKeys = <String>{'recurrence', 'decision'};

/// Server caps: a list is never silently cut short (the server fails instead).
const financialRecurrenceSuggestionListMax = 100;
const financialRecurrenceSuggestionEvidenceMin = 3;
const financialRecurrenceSuggestionEvidenceMax = 12;

final _suggestionFingerprintPattern = RegExp(r'^[0-9a-f]{64}$');

/// Closed, enumerated explanations. There is no numeric confidence.
enum FinancialSuggestionReason {
  exactDescription('EXACT_DESCRIPTION'),
  consecutiveMonths('CONSECUTIVE_MONTHS'),
  onePerMonth('ONE_PER_MONTH'),
  dayWindow('DAY_WINDOW'),
  amountFixed('AMOUNT_FIXED'),
  amountVariable('AMOUNT_VARIABLE');

  const FinancialSuggestionReason(this.wireValue);
  final String wireValue;

  static FinancialSuggestionReason parse(Object? value) =>
      _enumByWire(values, value, 'reasonCode', (item) => item.wireValue);
}

enum FinancialSuggestionAmountBehavior {
  fixed('FIXED'),
  variable('VARIABLE');

  const FinancialSuggestionAmountBehavior(this.wireValue);
  final String wireValue;

  static FinancialSuggestionAmountBehavior parse(Object? value) =>
      _enumByWire(values, value, 'amountBehavior', (item) => item.wireValue);
}

enum FinancialSuggestionDecisionKind {
  accepted('ACCEPTED'),
  dismissed('DISMISSED');

  const FinancialSuggestionDecisionKind(this.wireValue);
  final String wireValue;

  static FinancialSuggestionDecisionKind parse(Object? value) =>
      _enumByWire(values, value, 'decision', (item) => item.wireValue);
}

/// One Movement that supports a suggestion.
class FinancialSuggestionEvidence {
  const FinancialSuggestionEvidence({
    required this.movementId,
    required this.effectiveDate,
    required this.amount,
  });

  final String movementId;
  final String effectiveDate;
  final FinancialMoneyWire amount;
}

class FinancialRecurrenceSuggestion {
  const FinancialRecurrenceSuggestion({
    required this.fingerprint,
    required this.accountId,
    required this.description,
    required this.normalizedDescription,
    required this.currency,
    required this.evidence,
    required this.suggestedDayOfMonth,
    required this.suggestedExpectedAmount,
    required this.amountBehavior,
    required this.minAmount,
    required this.maxAmount,
    required this.lastAmount,
    required this.reasonCodes,
    required this.canAccept,
  });

  /// Server-derived identity of *what* is suggested. Not a resource id and not
  /// proof of access: the server re-runs the detector before acting on it.
  final String fingerprint;
  final String accountId;
  final String description;
  final String normalizedDescription;
  final String currency;
  final List<FinancialSuggestionEvidence> evidence;
  final int suggestedDayOfMonth;
  final FinancialMoneyWire suggestedExpectedAmount;
  final FinancialSuggestionAmountBehavior amountBehavior;
  final FinancialMoneyWire minAmount;
  final FinancialMoneyWire maxAmount;
  final FinancialMoneyWire lastAmount;
  final List<FinancialSuggestionReason> reasonCodes;

  /// Decided by the server: only the owner of the account may accept.
  final bool canAccept;

  bool get isVariable =>
      amountBehavior == FinancialSuggestionAmountBehavior.variable;

  /// The last observed date (`YYYY-MM-DD`).
  String get lastObservedDate => evidence.last.effectiveDate;
}

class FinancialRecurrenceSuggestionList {
  const FinancialRecurrenceSuggestionList({
    required this.windowFrom,
    required this.windowThrough,
    required this.items,
  });

  final String windowFrom;
  final String windowThrough;
  final List<FinancialRecurrenceSuggestion> items;
}

class FinancialSuggestionDecision {
  const FinancialSuggestionDecision({
    required this.fingerprint,
    required this.accountId,
    required this.kind,
    required this.recurrenceId,
    required this.decidedAt,
    required this.created,
  });

  final String fingerprint;
  final String accountId;
  final FinancialSuggestionDecisionKind kind;
  final String? recurrenceId;
  final DateTime decidedAt;

  /// False when the server replayed an earlier identical decision.
  final bool created;
}

class FinancialSuggestionAcceptResult {
  const FinancialSuggestionAcceptResult({
    required this.recurrence,
    required this.decision,
  });

  final FinancialRecurrence recurrence;
  final FinancialSuggestionDecision decision;
}

/// The reviewed fields of an acceptance. Account, effect and currency are fixed by
/// the suggestion: [accountId] and [currency] only let the client cross-check the
/// answer and are never sent.
class FinancialRecurrenceSuggestionAcceptInput {
  FinancialRecurrenceSuggestionAcceptInput({
    required String fingerprint,
    required String accountId,
    required String currency,
    required String description,
    required String expectedAmount,
    required String startDate,
    required int dayOfMonth,
    String? endDate,
    String? idempotencyKey,
  }) : fingerprint = _suggestionFingerprint(fingerprint),
       accountId = _financialResourceId(accountId, 'accountId'),
       currency = _currency(currency, 'currency'),
       description = _boundedText(
         description.trim(),
         'description',
         maxLength: financialRecurrenceDescriptionMaxLength,
       ),
       expectedAmount = _positiveDecimalAmount(
         expectedAmount,
         'expectedAmount',
       ),
       startDate = _date(startDate, 'startDate'),
       dayOfMonth = _dayOfMonth(dayOfMonth),
       endDate = endDate == null ? null : _date(endDate, 'endDate'),
       idempotencyKey = idempotencyKey == null
           ? _newUuidV4()
           : _idempotencyKey(idempotencyKey) {
    if (this.expectedAmount.startsWith('-')) {
      throw const FormatException('expectedAmount must be positive.');
    }
    final end = this.endDate;
    if (end != null && end.compareTo(this.startDate) < 0) {
      throw const FormatException('endDate must not precede startDate.');
    }
  }

  final String fingerprint;
  final String accountId;
  final String currency;
  final String description;
  final String expectedAmount;
  final String startDate;
  final int dayOfMonth;
  final String? endDate;
  final String idempotencyKey;

  /// The same request under another idempotency key (an explicit, identical retry
  /// of an attempt whose outcome is unknown reuses the original key).
  FinancialRecurrenceSuggestionAcceptInput withIdempotencyKey(String key) =>
      FinancialRecurrenceSuggestionAcceptInput(
        fingerprint: fingerprint,
        accountId: accountId,
        currency: currency,
        description: description,
        expectedAmount: expectedAmount,
        startDate: startDate,
        dayOfMonth: dayOfMonth,
        endDate: endDate,
        idempotencyKey: key,
      );

  /// The logical attempt: same material, same key on an explicit retry.
  String get attemptKey => [
    fingerprint,
    description,
    _canonicalDecimal(expectedAmount),
    startDate,
    dayOfMonth.toString(),
    endDate ?? '',
  ].join('\u001f');

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'description': description,
    'expectedAmount': expectedAmount,
    'startDate': startDate,
    'dayOfMonth': dayOfMonth,
    'endDate': endDate,
  };
}

extension FinancialRecurrenceSuggestionApiCalls on FinancialCoreApi {
  /// The operator's current suggestions (derived on the server; a read never
  /// writes anything).
  Future<FinancialRecurrenceSuggestionList> listRecurrenceSuggestions() async {
    final response = await client.get('finance/recurrence-suggestions');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _suggestionsKeys,
      label: 'recurrence suggestions response',
    );
    final raw = root['items'];
    if (raw is! List || raw.length > financialRecurrenceSuggestionListMax) {
      throw const FormatException('items is invalid.');
    }
    final items = List<FinancialRecurrenceSuggestion>.unmodifiable(
      raw.map(_parseSuggestion),
    );
    if (items.map((item) => item.fingerprint).toSet().length != items.length) {
      throw const FormatException('duplicate suggestion.');
    }
    final from = _date(root['windowFrom'], 'windowFrom');
    final through = _date(root['windowThrough'], 'windowThrough');
    if (through.compareTo(from) < 0) {
      throw const FormatException('suggestion window is invalid.');
    }
    return FinancialRecurrenceSuggestionList(
      windowFrom: from,
      windowThrough: through,
      items: items,
    );
  }

  /// A personal, explicit dismissal. Hides the suggestion only for this operator.
  Future<FinancialSuggestionDecision> dismissRecurrenceSuggestion(
    String fingerprint,
  ) async {
    final id = _suggestionFingerprint(fingerprint);
    final response = await client.post(
      'finance/recurrence-suggestions/$id/dismiss',
    );
    final decision = _parseSuggestionDecision(
      _strictJsonObject(
        response.body,
        allowedKeys: _suggestionDecisionKeys,
        label: 'suggestion decision response',
      ),
    );
    if (decision.fingerprint != id ||
        decision.kind != FinancialSuggestionDecisionKind.dismissed ||
        decision.recurrenceId != null) {
      throw const FormatException('suggestion decision mismatch.');
    }
    return decision;
  }

  /// Creates one canonical recurrence from a suggestion (no Movement, no
  /// occurrence). The answer is cross-checked against the reviewed request.
  Future<FinancialSuggestionAcceptResult> acceptRecurrenceSuggestion(
    FinancialRecurrenceSuggestionAcceptInput input,
  ) async {
    final response = await client.post(
      'finance/recurrence-suggestions/${input.fingerprint}/accept',
      jsonBody: input.toJson(),
    );
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _suggestionAcceptKeys,
      label: 'suggestion accept response',
    );
    final recurrence = _parseRecurrence(root['recurrence']);
    final decision = _parseSuggestionDecision(
      _strictMap(
        root['decision'],
        allowedKeys: _suggestionDecisionKeys,
        label: 'suggestion decision',
      ),
    );
    if (recurrence.accountId != input.accountId ||
        recurrence.description != input.description ||
        recurrence.resultEffect != FinancialResultEffect.expense ||
        recurrence.expected.currency != input.currency ||
        _canonicalDecimal(recurrence.expected.amount) !=
            _canonicalDecimal(input.expectedAmount) ||
        recurrence.startDate != input.startDate ||
        recurrence.dayOfMonth != input.dayOfMonth ||
        recurrence.endDate != input.endDate ||
        recurrence.status != FinancialRecurrenceStatus.active ||
        recurrence.version != 1 ||
        decision.fingerprint != input.fingerprint ||
        decision.accountId != input.accountId ||
        decision.kind != FinancialSuggestionDecisionKind.accepted ||
        decision.recurrenceId != recurrence.id) {
      throw const FormatException('suggestion accept response mismatch.');
    }
    return FinancialSuggestionAcceptResult(
      recurrence: recurrence,
      decision: decision,
    );
  }
}

String _suggestionFingerprint(Object? value) {
  if (value is! String || !_suggestionFingerprintPattern.hasMatch(value)) {
    throw const FormatException('fingerprint is invalid.');
  }
  return value;
}

FinancialSuggestionDecision _parseSuggestionDecision(
  Map<String, Object?> values,
) {
  final created = values['created'];
  if (created is! bool) throw const FormatException('created is invalid.');
  final kind = FinancialSuggestionDecisionKind.parse(values['decision']);
  final rawRecurrence = values['recurrenceId'];
  final accepted = kind == FinancialSuggestionDecisionKind.accepted;
  if (accepted != (rawRecurrence != null)) {
    throw const FormatException('recurrenceId is invalid.');
  }
  return FinancialSuggestionDecision(
    fingerprint: _suggestionFingerprint(values['fingerprint']),
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    kind: kind,
    recurrenceId: rawRecurrence == null
        ? null
        : _financialResourceId(rawRecurrence, 'recurrenceId'),
    decidedAt: _timestamp(values['decidedAt'], 'decidedAt'),
    created: created,
  );
}

FinancialRecurrenceSuggestion _parseSuggestion(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _suggestionKeys,
    label: 'recurrence suggestion',
  );
  final currency = _currency(values['currency'], 'currency');
  final rawEvidence = values['evidence'];
  final rawIds = values['movementIds'];
  final rawDates = values['observedDates'];
  final rawAmounts = values['observedAmounts'];
  if (rawEvidence is! List ||
      rawIds is! List ||
      rawDates is! List ||
      rawAmounts is! List ||
      rawEvidence.length < financialRecurrenceSuggestionEvidenceMin ||
      rawEvidence.length > financialRecurrenceSuggestionEvidenceMax ||
      rawIds.length != rawEvidence.length ||
      rawDates.length != rawEvidence.length ||
      rawAmounts.length != rawEvidence.length) {
    throw const FormatException('suggestion evidence is invalid.');
  }
  final evidence = <FinancialSuggestionEvidence>[];
  for (var index = 0; index < rawEvidence.length; index += 1) {
    final entry = _strictMap(
      rawEvidence[index],
      allowedKeys: _suggestionEvidenceKeys,
      label: 'suggestion evidence',
    );
    final item = FinancialSuggestionEvidence(
      movementId: _financialResourceId(entry['movementId'], 'movementId'),
      effectiveDate: _date(entry['effectiveDate'], 'effectiveDate'),
      amount: _parseMoney(entry['amount']),
    );
    if (item.amount.currency != currency ||
        item.amount.isNegative ||
        item.amount.isZero) {
      throw const FormatException('suggestion evidence amount is invalid.');
    }
    // The flat lists mirror the evidence exactly: one source of truth.
    if (rawIds[index] != item.movementId ||
        rawDates[index] != item.effectiveDate) {
      throw const FormatException('suggestion evidence is inconsistent.');
    }
    final flat = _parseMoney(rawAmounts[index]);
    if (flat.currency != currency ||
        _canonicalDecimal(flat.amount) !=
            _canonicalDecimal(item.amount.amount)) {
      throw const FormatException('suggestion evidence is inconsistent.');
    }
    if (index > 0 &&
        item.effectiveDate.compareTo(evidence.last.effectiveDate) <= 0) {
      throw const FormatException('suggestion evidence is not ordered.');
    }
    evidence.add(item);
  }
  if (evidence.map((item) => item.movementId).toSet().length !=
      evidence.length) {
    throw const FormatException('duplicate evidence.');
  }
  final day = values['suggestedDayOfMonth'];
  if (day is! int || day < 1 || day > 31) {
    throw const FormatException('suggestedDayOfMonth is invalid.');
  }
  final canAccept = values['canAccept'];
  if (canAccept is! bool) throw const FormatException('canAccept is invalid.');
  final suggested = _parseMoney(values['suggestedExpectedAmount']);
  final minAmount = _parseMoney(values['minAmount']);
  final maxAmount = _parseMoney(values['maxAmount']);
  final lastAmount = _parseMoney(values['lastAmount']);
  for (final money in [suggested, minAmount, maxAmount, lastAmount]) {
    if (money.currency != currency || money.isNegative || money.isZero) {
      throw const FormatException('suggestion amount is invalid.');
    }
  }
  final canonical = evidence
      .map((item) => _canonicalDecimal(item.amount.amount))
      .toList();
  final behavior = FinancialSuggestionAmountBehavior.parse(
    values['amountBehavior'],
  );
  final fixed = canonical.every((amount) => amount == canonical.first);
  if ((behavior == FinancialSuggestionAmountBehavior.fixed) != fixed ||
      _canonicalDecimal(lastAmount.amount) != canonical.last ||
      _canonicalDecimal(suggested.amount) != canonical.last ||
      !canonical.contains(_canonicalDecimal(minAmount.amount)) ||
      !canonical.contains(_canonicalDecimal(maxAmount.amount))) {
    throw const FormatException('suggestion amounts are inconsistent.');
  }
  final rawReasons = values['reasonCodes'];
  if (rawReasons is! List || rawReasons.isEmpty || rawReasons.length > 8) {
    throw const FormatException('reasonCodes is invalid.');
  }
  final reasons = List<FinancialSuggestionReason>.unmodifiable(
    rawReasons.map(FinancialSuggestionReason.parse),
  );
  if (reasons.toSet().length != reasons.length ||
      reasons.contains(FinancialSuggestionReason.amountFixed) !=
          (behavior == FinancialSuggestionAmountBehavior.fixed)) {
    throw const FormatException('reasonCodes is inconsistent.');
  }
  return FinancialRecurrenceSuggestion(
    fingerprint: _suggestionFingerprint(values['fingerprint']),
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    description: _boundedText(
      values['description'],
      'description',
      maxLength: financialRecurrenceDescriptionMaxLength,
    ),
    normalizedDescription: _boundedText(
      values['normalizedDescription'],
      'normalizedDescription',
      maxLength: financialRecurrenceDescriptionMaxLength * 3,
    ),
    currency: currency,
    evidence: List<FinancialSuggestionEvidence>.unmodifiable(evidence),
    suggestedDayOfMonth: day,
    suggestedExpectedAmount: suggested,
    amountBehavior: behavior,
    minAmount: minAmount,
    maxAmount: maxAmount,
    lastAmount: lastAmount,
    reasonCodes: reasons,
    canAccept: canAccept,
  );
}
