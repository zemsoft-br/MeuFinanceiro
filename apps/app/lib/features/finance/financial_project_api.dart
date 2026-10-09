part of 'financial_core_api.dart';

// Financial projects #262 / ADR-0030. Analytic association only: never new
// Movements, transfers, account balances or category budget realizations.
// The backend decides realized amounts, CAS, scope and edit permissions.

const _projectKeys = <String>{
  'id',
  'ownerOperatorId',
  'visibilityScope',
  'title',
  'description',
  'currency',
  'planned',
  'targetDate',
  'version',
  'createdAt',
  'updatedAt',
  'canEdit',
};
const _projectSummaryKeys = <String>{
  'project',
  'realized',
  'remaining',
  'excess',
  'progressPercent',
  'progressStatus',
  'expenseCount',
  'expenses',
};
const _projectExpenseKeys = <String>{
  'movementId',
  'description',
  'effectiveDate',
  'originalAmount',
  'realized',
  'reversed',
};
const _projectLinkKeys = <String>{
  'id',
  'movementId',
  'projectId',
  'supersedesId',
  'revision',
  'actorOperatorId',
  'createdAt',
};
const financialProjectsMax = 1000;
const financialProjectExpensesMax = 1000;
const financialProjectRevisionsMax = 100;
final _projectProgressPattern = RegExp(r'^[0-9]{1,18}\.[0-9]{2}$');

enum FinancialProjectProgressStatus {
  under('UNDER'),
  at('AT'),
  over('OVER');

  const FinancialProjectProgressStatus(this.wireValue);
  final String wireValue;

  static FinancialProjectProgressStatus parse(Object? raw) =>
      _enumByWire(values, raw, 'progressStatus', (item) => item.wireValue);
}

class FinancialProject {
  const FinancialProject({
    required this.id,
    required this.ownerOperatorId,
    required this.visibilityScope,
    required this.title,
    required this.description,
    required this.currency,
    required this.planned,
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
  final FinancialMoneyWire planned;
  final String? targetDate;
  final int version;
  final DateTime createdAt;
  final DateTime updatedAt;
  final bool canEdit;
}

class FinancialProjectExpense {
  const FinancialProjectExpense({
    required this.movementId,
    required this.description,
    required this.effectiveDate,
    required this.originalAmount,
    required this.realized,
    required this.reversed,
  });
  final String movementId;
  final String? description;
  final String effectiveDate;
  final FinancialMoneyWire originalAmount;
  final FinancialMoneyWire realized;
  final bool reversed;
}

class FinancialProjectSummary {
  const FinancialProjectSummary({
    required this.project,
    required this.realized,
    required this.remaining,
    required this.excess,
    required this.progressPercent,
    required this.progressStatus,
    required this.expenseCount,
    required this.expenses,
  });
  final FinancialProject project;
  final FinancialMoneyWire realized;
  final FinancialMoneyWire remaining;
  final FinancialMoneyWire excess;
  final String progressPercent;
  final FinancialProjectProgressStatus progressStatus;
  final int expenseCount;
  final List<FinancialProjectExpense> expenses;
}

class FinancialProjectLink {
  const FinancialProjectLink({
    required this.id,
    required this.movementId,
    required this.projectId,
    required this.supersedesId,
    required this.revision,
    required this.actorOperatorId,
    required this.createdAt,
  });

  final String id;
  final String movementId;
  final String? projectId;
  final String? supersedesId;
  final int revision;
  final String actorOperatorId;
  final DateTime createdAt;
}

String? _projectDescription(String? raw) {
  if (raw == null || raw.trim().isEmpty) return null;
  return _boundedText(raw.trim(), 'description', maxLength: 280);
}

String? _projectDate(String? raw) =>
    raw == null || raw.isEmpty ? null : _date(raw, 'targetDate');

class FinancialProjectCreateInput {
  FinancialProjectCreateInput({
    required String title,
    String? description,
    required this.visibilityScope,
    required String currency,
    required String plannedAmount,
    String? targetDate,
    String? idempotencyKey,
  }) : title = _boundedText(title.trim(), 'title', maxLength: 96),
       description = _projectDescription(description),
       currency = _currency(currency, 'currency'),
       plannedAmount = _positiveDecimalAmount(plannedAmount, 'plannedAmount'),
       targetDate = _projectDate(targetDate),
       idempotencyKey = _idempotencyKey(idempotencyKey ?? _newUuidV4()) {
    if (visibilityScope == FinancialVisibilityScope.shared) {
      throw const FormatException('project scope is not supported.');
    }
  }

  final String title;
  final String? description;
  final FinancialVisibilityScope visibilityScope;
  final String currency;
  final String plannedAmount;
  final String? targetDate;
  final String idempotencyKey;

  /// An explicit identical retry retains the original key.
  FinancialProjectCreateInput withIdempotencyKey(String key) =>
      FinancialProjectCreateInput(
        title: title,
        description: description,
        visibilityScope: visibilityScope,
        currency: currency,
        plannedAmount: plannedAmount,
        targetDate: targetDate,
        idempotencyKey: key,
      );

  String get attemptKey => [
    title,
    description ?? '',
    visibilityScope.wireValue,
    currency,
    _canonicalDecimal(plannedAmount),
    targetDate ?? '',
  ].join('\u001f');

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'title': title,
    'description': description,
    'visibilityScope': visibilityScope.wireValue,
    'currency': currency,
    'plannedAmount': plannedAmount,
    'targetDate': targetDate,
  };
}

class FinancialProjectReplaceInput {
  FinancialProjectReplaceInput({
    required this.expectedVersion,
    required String title,
    String? description,
    required String currency,
    required String plannedAmount,
    String? targetDate,
  }) : title = _boundedText(title.trim(), 'title', maxLength: 96),
       description = _projectDescription(description),
       currency = _currency(currency, 'currency'),
       plannedAmount = _positiveDecimalAmount(plannedAmount, 'plannedAmount'),
       targetDate = _projectDate(targetDate) {
    if (expectedVersion < 1) {
      throw const FormatException('project expectedVersion is invalid.');
    }
  }

  final int expectedVersion;
  final String title;
  final String? description;
  final String currency;
  final String plannedAmount;
  final String? targetDate;

  Map<String, Object?> toJson() => {
    'expectedVersion': expectedVersion,
    'title': title,
    'description': description,
    'currency': currency,
    'plannedAmount': plannedAmount,
    'targetDate': targetDate,
  };
}

class FinancialProjectLinkInput {
  FinancialProjectLinkInput({
    String? projectId,
    String? expectedPredecessorId,
    String? idempotencyKey,
  }) : projectId = projectId == null
           ? null
           : _financialResourceId(projectId, 'projectId'),
       expectedPredecessorId = expectedPredecessorId == null
           ? null
           : _financialResourceId(
               expectedPredecessorId,
               'expectedPredecessorId',
             ),
       idempotencyKey = _idempotencyKey(idempotencyKey ?? _newUuidV4()) {
    if (projectId == null && expectedPredecessorId == null) {
      throw const FormatException('nothing to unlink.');
    }
  }

  final String? projectId;
  final String? expectedPredecessorId;
  final String idempotencyKey;

  FinancialProjectLinkInput withIdempotencyKey(String key) =>
      FinancialProjectLinkInput(
        projectId: projectId,
        expectedPredecessorId: expectedPredecessorId,
        idempotencyKey: key,
      );

  String get attemptKey =>
      [projectId ?? '', expectedPredecessorId ?? ''].join('\u001f');

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'projectId': projectId,
    'expectedPredecessorId': expectedPredecessorId,
  };
}

extension FinancialProjectApiCalls on FinancialCoreApi {
  Future<List<FinancialProject>> listProjects() async {
    final response = await client.get('finance/projects');
    final data = _strictJsonObject(
      response.body,
      allowedKeys: const {'items'},
      label: 'projects response',
    );
    final raw = data['items'];
    if (raw is! List || raw.length > financialProjectsMax) {
      throw const FormatException('projects is invalid.');
    }
    final items = List<FinancialProject>.unmodifiable(raw.map(_parseProject));
    if (items.map((p) => p.id).toSet().length != items.length) {
      throw const FormatException('duplicate project.');
    }
    return items;
  }

  Future<FinancialProject> getProject(String projectId) async {
    final id = _financialResourceId(projectId, 'projectId');
    final response = await client.get('finance/projects/$id');
    final result = _parseProject(
      _decodeJsonObject(response.body, 'project response'),
    );
    if (result.id != id) throw const FormatException('project id mismatch.');
    return result;
  }

  Future<FinancialProject> createProject(
    FinancialProjectCreateInput input,
  ) async {
    final response = await client.post(
      'finance/projects',
      jsonBody: input.toJson(),
    );
    final project = _parseProject(
      _decodeJsonObject(response.body, 'project response'),
    );
    if (project.visibilityScope != input.visibilityScope ||
        project.title != input.title ||
        project.description != input.description ||
        project.currency != input.currency ||
        project.targetDate != input.targetDate ||
        !project.canEdit ||
        _canonicalDecimal(project.planned.amount) !=
            _canonicalDecimal(input.plannedAmount)) {
      throw const FormatException('project create response mismatch.');
    }
    return project;
  }

  Future<FinancialProject> replaceProject(
    String projectId,
    FinancialProjectReplaceInput input,
  ) async {
    final id = _financialResourceId(projectId, 'projectId');
    final response = await client.put(
      'finance/projects/$id',
      jsonBody: input.toJson(),
    );
    final project = _parseProject(
      _decodeJsonObject(response.body, 'project response'),
    );
    if (project.id != id ||
        project.version != input.expectedVersion + 1 ||
        project.title != input.title ||
        project.description != input.description ||
        project.currency != input.currency ||
        project.targetDate != input.targetDate ||
        _canonicalDecimal(project.planned.amount) !=
            _canonicalDecimal(input.plannedAmount)) {
      throw const FormatException('project edit response mismatch.');
    }
    return project;
  }

  Future<FinancialProjectSummary> getProjectSummary(String projectId) async {
    final id = _financialResourceId(projectId, 'projectId');
    final response = await client.get('finance/projects/$id/summary');
    final result = _parseProjectSummary(
      _decodeJsonObject(response.body, 'project summary'),
    );
    if (result.project.id != id) {
      throw const FormatException('project summary id mismatch.');
    }
    return result;
  }

  Future<FinancialProjectLink?> getProjectLink(String movementId) async {
    final id = _financialResourceId(movementId, 'movementId');
    final response = await client.get('finance/movements/$id/project-link');
    final data = _strictJsonObject(
      response.body,
      allowedKeys: const {'link'},
      label: 'project link envelope',
    );
    final raw = data['link'];
    if (raw == null) return null;
    final link = _parseProjectLink(raw);
    if (link.movementId != id) {
      throw const FormatException('project link movement mismatch.');
    }
    return link;
  }

  Future<List<FinancialProjectLink>> getProjectLinkHistory(
    String movementId,
  ) async {
    final id = _financialResourceId(movementId, 'movementId');
    final response = await client.get(
      'finance/movements/$id/project-link/revisions',
    );
    final data = _strictJsonObject(
      response.body,
      allowedKeys: const {'items'},
      label: 'project link history',
    );
    final raw = data['items'];
    if (raw is! List || raw.length > financialProjectRevisionsMax) {
      throw const FormatException('project link history is invalid.');
    }
    final items = List<FinancialProjectLink>.unmodifiable(
      raw.map(_parseProjectLink),
    );
    for (var i = 0; i < items.length; i++) {
      if (items[i].movementId != id ||
          items[i].revision != i + 1 ||
          (i == 0 && items[i].supersedesId != null) ||
          (i > 0 && items[i].supersedesId != items[i - 1].id)) {
        throw const FormatException('project link revision chain is invalid.');
      }
    }
    return items;
  }

  /// One write. The controller must canonical-refetch after every outcome,
  /// including transport ambiguity and invalid 2xx. Never retry automatically.
  Future<FinancialProjectLink> reviseProjectLink(
    String movementId,
    FinancialProjectLinkInput input,
  ) async {
    final id = _financialResourceId(movementId, 'movementId');
    final response = await client.post(
      'finance/movements/$id/project-link',
      jsonBody: input.toJson(),
    );
    final link = _parseProjectLink(
      _decodeJsonObject(response.body, 'project link response'),
    );
    if (link.movementId != id ||
        link.projectId != input.projectId ||
        link.supersedesId != input.expectedPredecessorId) {
      throw const FormatException('project link response mismatch.');
    }
    return link;
  }
}

FinancialProject _parseProject(Object? raw) {
  final v = _strictMap(raw, allowedKeys: _projectKeys, label: 'project');
  final scope = FinancialVisibilityScope.parse(v['visibilityScope']);
  if (scope == FinancialVisibilityScope.shared) {
    throw const FormatException('project scope is invalid.');
  }
  final version = v['version'];
  final editable = v['canEdit'];
  if (version is! int || version < 1 || editable is! bool) {
    throw const FormatException('project version/access is invalid.');
  }
  final currency = _currency(v['currency'], 'currency');
  final planned = _parseMoney(v['planned']);
  if (planned.currency != currency || planned.isNegative || planned.isZero) {
    throw const FormatException('project planned amount is invalid.');
  }
  return FinancialProject(
    id: _financialResourceId(v['id'], 'id'),
    ownerOperatorId: _uuid(v['ownerOperatorId'], 'ownerOperatorId'),
    visibilityScope: scope,
    title: _boundedText(v['title'], 'title', maxLength: 96),
    description: _optionalBoundedText(
      v['description'],
      'description',
      maxLength: 280,
    ),
    currency: currency,
    planned: planned,
    targetDate: v['targetDate'] == null
        ? null
        : _date(v['targetDate'], 'targetDate'),
    version: version,
    createdAt: _timestamp(v['createdAt'], 'createdAt'),
    updatedAt: _timestamp(v['updatedAt'], 'updatedAt'),
    canEdit: editable,
  );
}

FinancialMoneyWire _projectMoney(Object? raw, String currency) {
  final value = _parseMoney(raw);
  if (value.currency != currency || value.isNegative) {
    throw const FormatException('project money is invalid.');
  }
  return value;
}

FinancialProjectSummary _parseProjectSummary(Object? raw) {
  final v = _strictMap(
    raw,
    allowedKeys: _projectSummaryKeys,
    label: 'project summary',
  );
  final project = _parseProject(v['project']);
  final count = v['expenseCount'];
  final rawExpenses = v['expenses'];
  final progress = v['progressPercent'];
  if (count is! int ||
      count < 0 ||
      rawExpenses is! List ||
      rawExpenses.length > financialProjectExpensesMax ||
      count != rawExpenses.length ||
      progress is! String ||
      !_projectProgressPattern.hasMatch(progress)) {
    throw const FormatException('project summary is invalid.');
  }
  final expenses = List<FinancialProjectExpense>.unmodifiable(
    rawExpenses.map((rawExpense) {
      final e = _strictMap(
        rawExpense,
        allowedKeys: _projectExpenseKeys,
        label: 'project expense',
      );
      if (e['reversed'] is! bool) {
        throw const FormatException('project reversed is invalid.');
      }
      return FinancialProjectExpense(
        movementId: _financialResourceId(e['movementId'], 'movementId'),
        description: _optionalBoundedText(
          e['description'],
          'description',
          maxLength: 256,
        ),
        effectiveDate: _date(e['effectiveDate'], 'effectiveDate'),
        originalAmount: _projectMoney(e['originalAmount'], project.currency),
        realized: _projectMoney(e['realized'], project.currency),
        reversed: e['reversed'] as bool,
      );
    }),
  );
  if (expenses.map((e) => e.movementId).toSet().length != expenses.length) {
    throw const FormatException('project expense is duplicated.');
  }
  return FinancialProjectSummary(
    project: project,
    realized: _projectMoney(v['realized'], project.currency),
    remaining: _projectMoney(v['remaining'], project.currency),
    excess: _projectMoney(v['excess'], project.currency),
    progressPercent: progress,
    progressStatus: FinancialProjectProgressStatus.parse(v['progressStatus']),
    expenseCount: count,
    expenses: expenses,
  );
}

FinancialProjectLink _parseProjectLink(Object? raw) {
  final v = _strictMap(
    raw,
    allowedKeys: _projectLinkKeys,
    label: 'project link',
  );
  final revision = v['revision'];
  if (revision is! int ||
      revision < 1 ||
      revision > financialProjectRevisionsMax) {
    throw const FormatException('project link revision is invalid.');
  }
  final predecessor = v['supersedesId'] == null
      ? null
      : _financialResourceId(v['supersedesId'], 'supersedesId');
  final project = v['projectId'] == null
      ? null
      : _financialResourceId(v['projectId'], 'projectId');
  if ((revision == 1 && (predecessor != null || project == null)) ||
      (revision > 1 && predecessor == null)) {
    throw const FormatException('project link chain is invalid.');
  }
  return FinancialProjectLink(
    id: _financialResourceId(v['id'], 'id'),
    movementId: _financialResourceId(v['movementId'], 'movementId'),
    projectId: project,
    supersedesId: predecessor,
    revision: revision,
    actorOperatorId: _uuid(v['actorOperatorId'], 'actorOperatorId'),
    createdAt: _timestamp(v['createdAt'], 'createdAt'),
  );
}
