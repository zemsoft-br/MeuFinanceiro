part of 'financial_core_api.dart';

// Deterministic categorization rules (#247). A rule proposes the first
// classification of an unclassified STANDARD income/expense Movement; the
// backend owns matching, priority, eligibility and every write. This file only
// validates wire shapes and builds requests: it never matches, ranks or decides.

const _ruleKeys = <String>{
  'ruleId',
  'createdByOperatorId',
  'accountId',
  'resultEffect',
  'descriptionMatcher',
  'descriptionPattern',
  'targetCategoryId',
  'priority',
  'status',
  'createdAt',
  'disabledAt',
};
const _rulesKeys = <String>{'rules'};
const _previewKeys = <String>{
  'accountId',
  'totalMovements',
  'counts',
  'items',
  'itemsTruncated',
};
const _previewCountKeys = <String>{
  'matched',
  'noMatch',
  'ambiguous',
  'ineligible',
  'alreadyClassified',
};
const _previewItemKeys = <String>{
  'movementId',
  'status',
  'ruleId',
  'targetCategoryId',
};
const _applyKeys = <String>{'accountId', 'requested', 'counts', 'results'};
const _applyCountKeys = <String>{
  'classified',
  'alreadyClassified',
  'ambiguous',
  'noMatch',
  'ineligible',
  'conflict',
  'failed',
};
const _applyResultKeys = <String>{
  'movementId',
  'status',
  'ruleId',
  'allocationSetId',
};
const _originsKeys = <String>{'accountId', 'origins'};
const _originKeys = <String>{
  'movementId',
  'allocationSetId',
  'ruleId',
  'createdAt',
};

/// Server-side caps (also enforced by the backend): the client never sends more.
const financialCategorizationMaxApplyItems = 200;
const financialCategorizationPatternMaxLength = 256;
const financialCategorizationPriorityMin = 1;
const financialCategorizationPriorityMax = 1000;
const _maxRules = 1000;
const _maxOrigins = 10000;

enum FinancialCategorizationMatcher {
  exact('EXACT'),
  contains('CONTAINS');

  const FinancialCategorizationMatcher(this.wireValue);
  final String wireValue;

  static FinancialCategorizationMatcher parse(Object? value) => _enumByWire(
    values,
    value,
    'descriptionMatcher',
    (item) => item.wireValue,
  );
}

enum FinancialCategorizationRuleStatus {
  active('ACTIVE'),
  disabled('DISABLED');

  const FinancialCategorizationRuleStatus(this.wireValue);
  final String wireValue;

  static FinancialCategorizationRuleStatus parse(Object? value) =>
      _enumByWire(values, value, 'status', (item) => item.wireValue);
}

/// Per-Movement result of a preview. Never a promise: apply re-evaluates.
enum FinancialCategorizationPreviewStatus {
  matched('MATCHED'),
  ambiguous('AMBIGUOUS');

  const FinancialCategorizationPreviewStatus(this.wireValue);
  final String wireValue;

  static FinancialCategorizationPreviewStatus parse(Object? value) =>
      _enumByWire(values, value, 'status', (item) => item.wireValue);
}

enum FinancialCategorizationApplyStatus {
  classified('CLASSIFIED'),
  alreadyClassified('ALREADY_CLASSIFIED'),
  ambiguous('AMBIGUOUS'),
  noMatch('NO_MATCH'),
  ineligible('INELIGIBLE'),
  conflict('CONFLICT'),
  failed('FAILED');

  const FinancialCategorizationApplyStatus(this.wireValue);
  final String wireValue;

  static FinancialCategorizationApplyStatus parse(Object? value) =>
      _enumByWire(values, value, 'status', (item) => item.wireValue);
}

class FinancialCategorizationRule {
  const FinancialCategorizationRule({
    required this.ruleId,
    required this.createdByOperatorId,
    required this.accountId,
    required this.resultEffect,
    required this.matcher,
    required this.pattern,
    required this.targetCategoryId,
    required this.priority,
    required this.status,
    required this.createdAt,
    required this.disabledAt,
  });

  final String ruleId;
  final String createdByOperatorId;
  final String? accountId;
  final FinancialResultEffect? resultEffect;
  final FinancialCategorizationMatcher matcher;

  /// The text the user typed (case and accents preserved). Matching is defined
  /// and executed by the backend, never here.
  final String pattern;
  final String targetCategoryId;
  final int priority;
  final FinancialCategorizationRuleStatus status;
  final DateTime createdAt;
  final DateTime? disabledAt;

  bool get isActive => status == FinancialCategorizationRuleStatus.active;
}

/// Creation intent. Rules are immutable: there is no edit input, only
/// "disable + create a new rule".
class FinancialCategorizationRuleCreateInput {
  FinancialCategorizationRuleCreateInput({
    required this.matcher,
    required String pattern,
    required String targetCategoryId,
    required this.priority,
    String? accountId,
    this.resultEffect,
    String? idempotencyKey,
  }) : pattern = _categorizationPattern(pattern),
       targetCategoryId = _financialResourceId(
         targetCategoryId,
         'targetCategoryId',
       ),
       accountId = accountId == null
           ? null
           : _financialResourceId(accountId, 'accountId'),
       idempotencyKey = _idempotencyKey(idempotencyKey ?? _newUuidV4()) {
    if (priority < financialCategorizationPriorityMin ||
        priority > financialCategorizationPriorityMax) {
      throw const FormatException('priority is invalid.');
    }
    if (resultEffect == FinancialResultEffect.neutral) {
      throw const FormatException('resultEffect is invalid.');
    }
  }

  final FinancialCategorizationMatcher matcher;
  final String pattern;
  final String targetCategoryId;
  final int priority;
  final String? accountId;
  final FinancialResultEffect? resultEffect;
  final String idempotencyKey;

  /// Identity of one logical creation attempt: the same material may reuse a
  /// pending key (server-side replay); anything else is a different request.
  String get attemptIdentity => [
    matcher.wireValue,
    pattern,
    targetCategoryId,
    '$priority',
    accountId ?? '-',
    resultEffect?.wireValue ?? '-',
  ].join('\u001f');

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'descriptionMatcher': matcher.wireValue,
    'descriptionPattern': pattern,
    'targetCategoryId': targetCategoryId,
    'priority': priority,
    if (accountId != null) 'accountId': accountId,
    if (resultEffect != null) 'resultEffect': resultEffect!.wireValue,
  };
}

class FinancialCategorizationPreviewCounts {
  const FinancialCategorizationPreviewCounts({
    required this.matched,
    required this.noMatch,
    required this.ambiguous,
    required this.ineligible,
    required this.alreadyClassified,
  });

  final int matched;
  final int noMatch;
  final int ambiguous;
  final int ineligible;
  final int alreadyClassified;

  int get total =>
      matched + noMatch + ambiguous + ineligible + alreadyClassified;
}

class FinancialCategorizationPreviewItem {
  const FinancialCategorizationPreviewItem({
    required this.movementId,
    required this.status,
    required this.ruleId,
    required this.targetCategoryId,
  });

  final String movementId;
  final FinancialCategorizationPreviewStatus status;
  final String? ruleId;
  final String? targetCategoryId;
}

class FinancialCategorizationPreview {
  const FinancialCategorizationPreview({
    required this.accountId,
    required this.totalMovements,
    required this.counts,
    required this.items,
    required this.itemsTruncated,
  });

  final String accountId;
  final int totalMovements;
  final FinancialCategorizationPreviewCounts counts;
  final List<FinancialCategorizationPreviewItem> items;

  /// More candidates exist than the preview lists: apply what is shown, then
  /// preview again.
  final bool itemsTruncated;

  /// Exactly the pairs a confirmation may send, in preview order.
  List<FinancialCategorizationApplyItem> get applicableItems =>
      List.unmodifiable([
        for (final item in items)
          if (item.status == FinancialCategorizationPreviewStatus.matched &&
              item.ruleId != null)
            FinancialCategorizationApplyItem(
              movementId: item.movementId,
              ruleId: item.ruleId!,
            ),
      ]);
}

/// One Movement/rule pair the operator confirmed after a preview.
class FinancialCategorizationApplyItem {
  FinancialCategorizationApplyItem({
    required String movementId,
    required String ruleId,
  }) : movementId = _financialResourceId(movementId, 'movementId'),
       ruleId = _financialResourceId(ruleId, 'ruleId');

  final String movementId;
  final String ruleId;

  Map<String, Object?> toJson() => {'movementId': movementId, 'ruleId': ruleId};
}

class FinancialCategorizationApplyCounts {
  const FinancialCategorizationApplyCounts({
    required this.classified,
    required this.alreadyClassified,
    required this.ambiguous,
    required this.noMatch,
    required this.ineligible,
    required this.conflict,
    required this.failed,
  });

  final int classified;
  final int alreadyClassified;
  final int ambiguous;
  final int noMatch;
  final int ineligible;
  final int conflict;
  final int failed;

  int get total =>
      classified +
      alreadyClassified +
      ambiguous +
      noMatch +
      ineligible +
      conflict +
      failed;
}

class FinancialCategorizationApplyResult {
  const FinancialCategorizationApplyResult({
    required this.movementId,
    required this.status,
    required this.ruleId,
    required this.allocationSetId,
  });

  final String movementId;
  final FinancialCategorizationApplyStatus status;
  final String? ruleId;
  final String? allocationSetId;
}

class FinancialCategorizationApplyOutcome {
  const FinancialCategorizationApplyOutcome({
    required this.accountId,
    required this.requested,
    required this.counts,
    required this.results,
  });

  final String accountId;
  final int requested;
  final FinancialCategorizationApplyCounts counts;
  final List<FinancialCategorizationApplyResult> results;

  /// Only "everything requested was classified" is a full success. Anything
  /// else (already classified, ambiguous, conflict, failure...) is partial and
  /// must be presented as such.
  bool get isFullSuccess => counts.classified == requested && requested > 0;
}

/// Evidence that the *current* classification of a Movement was applied by a
/// rule. Never decides which classification is current.
class FinancialRuleOrigin {
  const FinancialRuleOrigin({
    required this.movementId,
    required this.allocationSetId,
    required this.ruleId,
    required this.createdAt,
  });

  final String movementId;
  final String allocationSetId;
  final String ruleId;
  final DateTime createdAt;
}

extension FinancialCategorizationApiCalls on FinancialCoreApi {
  Future<List<FinancialCategorizationRule>> listCategorizationRules() async {
    final response = await client.get('finance/categorization-rules');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _rulesKeys,
      label: 'categorization rules response',
    );
    final raw = root['rules'];
    if (raw is! List || raw.length > _maxRules) {
      throw const FormatException('rules is invalid.');
    }
    final rules = List<FinancialCategorizationRule>.unmodifiable(
      raw.map(_parseCategorizationRule),
    );
    if (rules.map((item) => item.ruleId).toSet().length != rules.length) {
      throw const FormatException('duplicate rule identity.');
    }
    return rules;
  }

  Future<FinancialCategorizationRule> createCategorizationRule(
    FinancialCategorizationRuleCreateInput input,
  ) async {
    final response = await client.post(
      'finance/categorization-rules',
      jsonBody: input.toJson(),
    );
    final rule = _parseCategorizationRule(
      _decodeJsonObject(response.body, 'categorization rule response'),
    );
    if (!rule.isActive ||
        rule.matcher != input.matcher ||
        rule.pattern != input.pattern ||
        rule.targetCategoryId != input.targetCategoryId ||
        rule.priority != input.priority ||
        rule.accountId != input.accountId ||
        rule.resultEffect != input.resultEffect) {
      throw const FormatException('categorization rule response mismatch.');
    }
    return rule;
  }

  Future<FinancialCategorizationRule> disableCategorizationRule(
    String ruleId,
  ) async {
    final id = _financialResourceId(ruleId, 'ruleId');
    final response = await client.post(
      'finance/categorization-rules/$id/disable',
      jsonBody: const {},
    );
    final rule = _parseCategorizationRule(
      _decodeJsonObject(response.body, 'categorization rule response'),
    );
    if (rule.ruleId != id || rule.isActive) {
      throw const FormatException('categorization rule response mismatch.');
    }
    return rule;
  }

  /// Read-only: evaluates every Movement of the account, writes nothing.
  Future<FinancialCategorizationPreview> previewCategorizationRules(
    String accountId,
  ) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.post(
      'finance/accounts/$id/categorization-rules/preview',
      jsonBody: const {},
    );
    final preview = _parseCategorizationPreview(
      _decodeJsonObject(response.body, 'categorization preview response'),
    );
    if (preview.accountId != id) {
      throw const FormatException('categorization preview account mismatch.');
    }
    return preview;
  }

  /// One explicit POST of the confirmed pairs. The response is the only source
  /// of truth for what happened; nothing is assumed beforehand.
  Future<FinancialCategorizationApplyOutcome> applyCategorizationRules(
    String accountId,
    List<FinancialCategorizationApplyItem> items,
  ) async {
    final id = _financialResourceId(accountId, 'accountId');
    if (items.isEmpty || items.length > financialCategorizationMaxApplyItems) {
      throw const FormatException('apply items are invalid.');
    }
    if (items.map((item) => item.movementId).toSet().length != items.length) {
      throw const FormatException('apply items must name each Movement once.');
    }
    final response = await client.post(
      'finance/accounts/$id/categorization-rules/apply',
      jsonBody: {'items': items.map((item) => item.toJson()).toList()},
    );
    final outcome = _parseCategorizationApply(
      _decodeJsonObject(response.body, 'categorization apply response'),
    );
    if (outcome.accountId != id ||
        outcome.requested != items.length ||
        outcome.results.length != items.length) {
      throw const FormatException('categorization apply response mismatch.');
    }
    for (var index = 0; index < items.length; index += 1) {
      final result = outcome.results[index];
      if (result.movementId != items[index].movementId) {
        throw const FormatException('categorization apply order mismatch.');
      }
      if (result.status == FinancialCategorizationApplyStatus.classified &&
          result.ruleId != items[index].ruleId) {
        throw const FormatException('categorization applied another rule.');
      }
    }
    return outcome;
  }

  /// One bulk read of the rule provenance of the *current* classifications.
  Future<List<FinancialRuleOrigin>> listRuleOrigins(String accountId) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.get(
      'finance/accounts/$id/categorization-rules/origins',
    );
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _originsKeys,
      label: 'categorization rule origins response',
    );
    if (_financialResourceId(root['accountId'], 'accountId') != id) {
      throw const FormatException('rule origins account mismatch.');
    }
    final raw = root['origins'];
    if (raw is! List || raw.length > _maxOrigins) {
      throw const FormatException('origins is invalid.');
    }
    final origins = List<FinancialRuleOrigin>.unmodifiable(
      raw.map(_parseRuleOrigin),
    );
    if (origins.map((item) => item.allocationSetId).toSet().length !=
            origins.length ||
        origins.map((item) => item.movementId).toSet().length !=
            origins.length) {
      throw const FormatException('duplicate rule origin.');
    }
    return origins;
  }
}

String _categorizationPattern(String value) {
  final trimmed = value.trim();
  if (trimmed.isEmpty ||
      trimmed.runes.length > financialCategorizationPatternMaxLength ||
      trimmed.codeUnits.any((unit) => unit < 32 || unit == 127)) {
    throw const FormatException('description pattern is invalid.');
  }
  return trimmed;
}

/// The pattern as persisted by the backend. Its trimming follows the server's
/// Unicode whitespace definition, which can differ from Dart's `trim()` on rare
/// code points, so only emptiness, size and control characters are enforced here.
String _serverPattern(Object? value) {
  if (value is! String ||
      value.isEmpty ||
      value.runes.length > financialCategorizationPatternMaxLength ||
      value.codeUnits.any((unit) => unit < 32 || unit == 127)) {
    throw const FormatException('descriptionPattern is invalid.');
  }
  return value;
}

FinancialCategorizationRule _parseCategorizationRule(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _ruleKeys, label: 'rule');
  final status = FinancialCategorizationRuleStatus.parse(values['status']);
  final createdAt = _timestamp(values['createdAt'], 'createdAt');
  final disabledAt = _optionalTimestamp(values['disabledAt'], 'disabledAt');
  if ((status == FinancialCategorizationRuleStatus.active) !=
      (disabledAt == null)) {
    throw const FormatException('rule disable state is invalid.');
  }
  if (disabledAt != null && disabledAt.isBefore(createdAt)) {
    throw const FormatException('rule timestamps are invalid.');
  }
  final effect = values['resultEffect'] == null
      ? null
      : FinancialResultEffect.parse(values['resultEffect']);
  if (effect == FinancialResultEffect.neutral) {
    throw const FormatException('rule resultEffect is invalid.');
  }
  final priority = values['priority'];
  if (priority is! int ||
      priority < financialCategorizationPriorityMin ||
      priority > financialCategorizationPriorityMax) {
    throw const FormatException('priority is invalid.');
  }
  final pattern = _serverPattern(values['descriptionPattern']);
  return FinancialCategorizationRule(
    ruleId: _financialResourceId(values['ruleId'], 'ruleId'),
    createdByOperatorId: _uuid(
      values['createdByOperatorId'],
      'createdByOperatorId',
    ),
    accountId: values['accountId'] == null
        ? null
        : _financialResourceId(values['accountId'], 'accountId'),
    resultEffect: effect,
    matcher: FinancialCategorizationMatcher.parse(values['descriptionMatcher']),
    pattern: pattern,
    targetCategoryId: _financialResourceId(
      values['targetCategoryId'],
      'targetCategoryId',
    ),
    priority: priority,
    status: status,
    createdAt: createdAt,
    disabledAt: disabledAt,
  );
}

int _count(Object? value, String fieldName) {
  if (value is! int || value < 0 || value > 1000000) {
    throw FormatException('$fieldName is invalid.');
  }
  return value;
}

FinancialCategorizationPreview _parseCategorizationPreview(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _previewKeys, label: 'preview');
  final countValues = _strictMap(
    values['counts'],
    allowedKeys: _previewCountKeys,
    label: 'preview counts',
  );
  final counts = FinancialCategorizationPreviewCounts(
    matched: _count(countValues['matched'], 'matched'),
    noMatch: _count(countValues['noMatch'], 'noMatch'),
    ambiguous: _count(countValues['ambiguous'], 'ambiguous'),
    ineligible: _count(countValues['ineligible'], 'ineligible'),
    alreadyClassified: _count(
      countValues['alreadyClassified'],
      'alreadyClassified',
    ),
  );
  final totalMovements = _count(values['totalMovements'], 'totalMovements');
  if (counts.total != totalMovements) {
    throw const FormatException('preview counts do not add up.');
  }
  final rawItems = values['items'];
  final truncated = values['itemsTruncated'];
  if (rawItems is! List ||
      rawItems.length > financialCategorizationMaxApplyItems ||
      truncated is! bool) {
    throw const FormatException('preview items are invalid.');
  }
  final items = List<FinancialCategorizationPreviewItem>.unmodifiable(
    rawItems.map((item) {
      final entry = _strictMap(
        item,
        allowedKeys: _previewItemKeys,
        label: 'preview item',
      );
      final status = FinancialCategorizationPreviewStatus.parse(
        entry['status'],
      );
      final matched = status == FinancialCategorizationPreviewStatus.matched;
      final ruleId = entry['ruleId'] == null
          ? null
          : _financialResourceId(entry['ruleId'], 'ruleId');
      final target = entry['targetCategoryId'] == null
          ? null
          : _financialResourceId(entry['targetCategoryId'], 'targetCategoryId');
      if (matched != (ruleId != null) || matched != (target != null)) {
        throw const FormatException('preview item shape is invalid.');
      }
      return FinancialCategorizationPreviewItem(
        movementId: _financialResourceId(entry['movementId'], 'movementId'),
        status: status,
        ruleId: ruleId,
        targetCategoryId: target,
      );
    }),
  );
  if (items.map((item) => item.movementId).toSet().length != items.length) {
    throw const FormatException('duplicate preview movement.');
  }
  final listedMatched = items
      .where(
        (item) => item.status == FinancialCategorizationPreviewStatus.matched,
      )
      .length;
  final listedAmbiguous = items.length - listedMatched;
  if (listedMatched > counts.matched ||
      listedAmbiguous > counts.ambiguous ||
      (!truncated &&
          (listedMatched != counts.matched ||
              listedAmbiguous != counts.ambiguous))) {
    throw const FormatException('preview items do not match the counts.');
  }
  return FinancialCategorizationPreview(
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    totalMovements: totalMovements,
    counts: counts,
    items: items,
    itemsTruncated: truncated,
  );
}

FinancialCategorizationApplyOutcome _parseCategorizationApply(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _applyKeys, label: 'apply');
  final countValues = _strictMap(
    values['counts'],
    allowedKeys: _applyCountKeys,
    label: 'apply counts',
  );
  final counts = FinancialCategorizationApplyCounts(
    classified: _count(countValues['classified'], 'classified'),
    alreadyClassified: _count(
      countValues['alreadyClassified'],
      'alreadyClassified',
    ),
    ambiguous: _count(countValues['ambiguous'], 'ambiguous'),
    noMatch: _count(countValues['noMatch'], 'noMatch'),
    ineligible: _count(countValues['ineligible'], 'ineligible'),
    conflict: _count(countValues['conflict'], 'conflict'),
    failed: _count(countValues['failed'], 'failed'),
  );
  final requested = _count(values['requested'], 'requested');
  final rawResults = values['results'];
  if (rawResults is! List ||
      rawResults.length > financialCategorizationMaxApplyItems) {
    throw const FormatException('apply results are invalid.');
  }
  final results = List<FinancialCategorizationApplyResult>.unmodifiable(
    rawResults.map((item) {
      final entry = _strictMap(
        item,
        allowedKeys: _applyResultKeys,
        label: 'apply result',
      );
      final status = FinancialCategorizationApplyStatus.parse(entry['status']);
      final allocationSetId = entry['allocationSetId'] == null
          ? null
          : _financialResourceId(entry['allocationSetId'], 'allocationSetId');
      if ((status == FinancialCategorizationApplyStatus.classified) !=
          (allocationSetId != null)) {
        throw const FormatException('apply result shape is invalid.');
      }
      return FinancialCategorizationApplyResult(
        movementId: _financialResourceId(entry['movementId'], 'movementId'),
        status: status,
        ruleId: entry['ruleId'] == null
            ? null
            : _financialResourceId(entry['ruleId'], 'ruleId'),
        allocationSetId: allocationSetId,
      );
    }),
  );
  if (results.map((item) => item.movementId).toSet().length != results.length) {
    throw const FormatException('duplicate apply movement.');
  }
  int tally(FinancialCategorizationApplyStatus status) =>
      results.where((item) => item.status == status).length;
  const status = FinancialCategorizationApplyStatus.values;
  final tallies = [for (final item in status) tally(item)];
  final reported = [
    counts.classified,
    counts.alreadyClassified,
    counts.ambiguous,
    counts.noMatch,
    counts.ineligible,
    counts.conflict,
    counts.failed,
  ];
  if (results.length != requested ||
      counts.total != requested ||
      tallies.toString() != reported.toString()) {
    throw const FormatException('apply counts do not match the results.');
  }
  return FinancialCategorizationApplyOutcome(
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    requested: requested,
    counts: counts,
    results: results,
  );
}

FinancialRuleOrigin _parseRuleOrigin(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _originKeys, label: 'origin');
  return FinancialRuleOrigin(
    movementId: _financialResourceId(values['movementId'], 'movementId'),
    allocationSetId: _financialResourceId(
      values['allocationSetId'],
      'allocationSetId',
    ),
    ruleId: _financialResourceId(values['ruleId'], 'ruleId'),
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
  );
}
