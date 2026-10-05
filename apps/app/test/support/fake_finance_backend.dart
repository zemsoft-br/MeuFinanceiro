import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';

import 'fake_auth_transport.dart';

const financeTestToken = 'FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF';
const financeTestAccountId = '40000000-0000-4000-8000-000000000004';
const financeTestOwnerId = '30000000-0000-4000-8000-000000000003';
const financeTestOtherOperatorId = '31000000-0000-4000-8000-000000000031';
const financeTestInstallationId = '10000000-0000-4000-8000-000000000001';

String financeTestMovementId(int index) =>
    '60000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

String financeTestCategoryId(int index) =>
    'a1000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

String financeTestAllocationSetId(int index) =>
    'e5000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

class FakeMovementSpec {
  const FakeMovementSpec({
    required this.id,
    this.amount = '-75.25',
    this.effect = 'EXPENSE',
    this.role = 'STANDARD',
    this.description = 'Mercado',
  });

  final String id;
  final String amount;
  final String effect;
  final String role;
  final String? description;
}

String fakeCategoryJson({
  required String id,
  required String name,
  String scope = 'HOUSEHOLD',
  String owner = financeTestOwnerId,
  String? parentId,
  String status = 'ACTIVE',
}) =>
    '{"categoryId":"$id","ownerOperatorId":"$owner","visibilityScope":"$scope",'
    '"parentId":${parentId == null ? 'null' : '"$parentId"'},"name":"$name",'
    '"status":"$status","createdAt":"2026-09-01T12:00:00Z",'
    '"updatedAt":"2026-09-01T12:00:00Z",'
    '"disabledAt":${status == 'DISABLED' ? '"2026-09-02T12:00:00Z"' : 'null'}}';

String financeTestRuleId(int index) =>
    'b2000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

String fakeRuleJson({
  required String id,
  String pattern = 'padaria',
  String matcher = 'CONTAINS',
  String categoryId = 'a1000000-0000-4000-8000-000000000001',
  int priority = 10,
  String status = 'ACTIVE',
  String? accountId,
  String? effect,
  String createdBy = financeTestOwnerId,
}) =>
    '{"ruleId":"$id","createdByOperatorId":"$createdBy",'
    '"accountId":${accountId == null ? 'null' : '"$accountId"'},'
    '"resultEffect":${effect == null ? 'null' : '"$effect"'},'
    '"descriptionMatcher":"$matcher","descriptionPattern":"$pattern",'
    '"targetCategoryId":"$categoryId","priority":$priority,"status":"$status",'
    '"createdAt":"2026-09-21T12:00:00Z",'
    '"disabledAt":${status == 'DISABLED' ? '"2026-09-22T12:00:00Z"' : 'null'}}';

String fakeOriginJson({
  required String movementId,
  required String setId,
  required String ruleId,
}) =>
    '{"movementId":"$movementId","allocationSetId":"$setId",'
    '"ruleId":"$ruleId","createdAt":"2026-09-21T13:00:00Z"}';

String fakeAllocationJson({
  required String setId,
  required String movementId,
  required List<(String, String)> shares,
  int revision = 1,
  String? supersedesId,
}) =>
    '{"allocationSetId":"$setId","movementId":"$movementId","revision":$revision,'
    '"supersedesId":${supersedesId == null ? 'null' : '"$supersedesId"'},'
    '"allocations":[${shares.map((share) => '{"categoryId":"${share.$1}","money":{"amount":"${share.$2}","currency":"BRL"}}').join(',')}],'
    '"createdAt":"2026-09-20T05:30:00Z"}';

/// In-memory finance API for controller and widget tests. Every request goes
/// through [FakeAuthTransport], so tests can count exactly what was called.
class FakeFinanceBackend {
  FakeFinanceBackend({
    this.accountScope = 'PERSONAL',
    this.accountOwnerId = financeTestOwnerId,
    this.accountStatus = 'ACTIVE',
    List<FakeMovementSpec>? movements,
    List<String>? categories,
    Map<String, String>? allocations,
  }) : movements =
           movements ?? [FakeMovementSpec(id: financeTestMovementId(1))],
       categories = categories ?? [],
       allocations = allocations ?? {} {
    transport = FakeAuthTransport(_handle);
  }

  String accountScope;
  String accountOwnerId;
  String accountStatus;
  List<FakeMovementSpec> movements;
  List<String> categories;

  /// Current allocation JSON keyed by movement id.
  Map<String, String> allocations;

  late final FakeAuthTransport transport;

  /// Idempotency keys received by `POST .../allocation`, in order.
  final List<String> postedKeys = [];
  final List<Map<String, dynamic>> postedBodies = [];

  /// Forces a status for the next/all allocation POSTs (null = normal 201).
  int? allocationPostStatus;

  /// Makes the allocation POST blow up at transport level (timeout-like) after
  /// [onAllocationPost] ran: the request reached the server, the client sees
  /// a failure.
  bool allocationPostThrows = false;

  /// Replaces the 201 body of the allocation POST.
  String Function(String movementId, Map<String, dynamic> body)?
  allocationPostBody;

  /// Runs when the allocation POST arrives, before the backend decides.
  void Function(String movementId)? onAllocationPost;

  /// Holds the allocation POST open until completed.
  Completer<void>? allocationPostGate;

  /// Idempotency keys / bodies received by `POST .../allocation/revisions`.
  final List<String> revisionKeys = [];
  final List<Map<String, dynamic>> revisionBodies = [];
  final List<String> revisionMovementIds = [];

  /// Forces a status for revision POSTs (null = normal 201).
  int? revisionPostStatus;

  /// The revision POST reaches the server, then fails at transport level.
  bool revisionPostThrows = false;

  /// Replaces the 201 body of the revision POST.
  String Function(String movementId, Map<String, dynamic> body)?
  revisionPostBody;

  /// Runs when the revision POST arrives, before the backend decides. Lets a
  /// test commit another writer's revision (or this one) server-side.
  void Function(String movementId, Map<String, dynamic> body)? onRevisionPost;

  /// Holds the revision POST open until completed.
  Completer<void>? revisionPostGate;

  /// Responses already produced per idempotency key (server-side replay).
  final Map<String, String> _revisionReplays = {};

  /// Holds the next bulk allocations GET open (snapshot taken before waiting).
  Completer<void>? nextBulkGate;

  /// Forces a status for category POSTs (null = normal 201).
  int? categoryPostStatus;

  /// Makes the category POST blow up at transport level (timeout-like) after
  /// [onCategoryPost] ran, i.e. the request reached the server.
  bool categoryPostThrows = false;

  /// Runs when the category POST arrives, before the backend decides. Lets a
  /// test commit the category server-side while the client sees a failure.
  void Function(Map<String, dynamic> body)? onCategoryPost;

  /// Forces a status for `GET categories` / the bulk allocations read.
  int? categoryReadStatus;
  int? bulkReadStatus;

  // --- categorization rules (#247) -----------------------------------------

  /// Rule JSON, in list order.
  List<String> rules = [];

  /// Current rule provenance JSON keyed by allocation set id.
  Map<String, String> origins = {};
  int? rulesReadStatus;
  int? originsReadStatus;

  /// Bodies of rule POSTs, in order.
  final List<Map<String, dynamic>> ruleBodies = [];
  int? rulePostStatus;
  bool rulePostThrows = false;
  void Function(Map<String, dynamic> body)? onRulePost;
  final List<String> disabledRuleIds = [];
  int? ruleDisableStatus;
  bool ruleDisableThrows = false;

  /// Preview answer. Null = derive one from `movements`, `allocations`, `rules`.
  String? previewBody;
  int? previewStatus;
  bool previewThrows = false;

  /// Apply POST bodies, in order (one entry per request).
  final List<Map<String, dynamic>> applyBodies = [];
  int? applyStatus;
  bool applyThrows = false;

  /// Replaces the default apply behaviour. Receives the requested items and
  /// returns the response body (HTTP 200).
  String Function(List<Map<String, dynamic>> items)? applyResponder;

  /// Runs when the apply POST arrives, before the backend decides (lets a test
  /// persist a competing manual classification).
  void Function(List<Map<String, dynamic>> items)? onApplyPost;
  Completer<void>? applyGate;
  int _createdRules = 0;
  int _ruleSets = 0;
  String Function(Map<String, dynamic> body)? categoryPostBody;
  int _createdCategories = 0;
  int _createdSets = 0;

  List<AuthTransportCall> get calls => transport.calls;

  String get _accountPath => '/api/v1/finance/accounts/$financeTestAccountId';

  int count(AuthHttpMethod method, String path) => calls
      .where((call) => call.method == method && call.uri.path == path)
      .length;

  int get categoryReads =>
      count(AuthHttpMethod.get, '/api/v1/finance/categories');
  int get bulkReads =>
      count(AuthHttpMethod.get, '$_accountPath/movement-allocations');
  int get categoryPosts =>
      count(AuthHttpMethod.post, '/api/v1/finance/categories');
  int get statementReads =>
      count(AuthHttpMethod.get, '$_accountPath/statement');
  int get allocationPosts => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.post &&
            call.uri.path.endsWith('/allocation'),
      )
      .length;
  int get revisionPosts => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.post &&
            call.uri.path.endsWith('/allocation/revisions'),
      )
      .length;
  int get ruleReads =>
      count(AuthHttpMethod.get, '/api/v1/finance/categorization-rules');
  int get originReads =>
      count(AuthHttpMethod.get, '$_accountPath/categorization-rules/origins');
  int get rulePosts =>
      count(AuthHttpMethod.post, '/api/v1/finance/categorization-rules');
  int get previewPosts =>
      count(AuthHttpMethod.post, '$_accountPath/categorization-rules/preview');
  int get applyPosts =>
      count(AuthHttpMethod.post, '$_accountPath/categorization-rules/apply');
  int get singleAllocationReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            RegExp(
              r'/finance/movements/[^/]+/allocation$',
            ).hasMatch(call.uri.path),
      )
      .length;

  String get accountJson =>
      '{"accountId":"$financeTestAccountId","ownerOperatorId":"$accountOwnerId",'
      '"visibilityScope":"$accountScope","accountType":"CHECKING",'
      '"customTypeName":null,"name":"Conta Corrente","currency":"BRL",'
      '"status":"$accountStatus","createdAt":"2026-09-01T12:00:00Z",'
      '"updatedAt":"2026-09-01T12:00:00Z",'
      '"archivedAt":${accountStatus == 'ARCHIVED' ? '"2026-09-02T12:00:00Z"' : 'null'}}';

  String _movementJson(FakeMovementSpec spec) {
    final reversal = spec.role == 'REVERSAL';
    return '{"movementId":"${spec.id}","accountId":"$financeTestAccountId",'
        '"money":{"amount":"${spec.amount}","currency":"BRL"},'
        '"resultEffect":"${spec.effect}","role":"${spec.role}",'
        '"effectiveDate":"2026-09-10","competenceDate":"2026-09-10",'
        '"description":${spec.description == null ? 'null' : '"${spec.description}"'},'
        '"reversalOfId":${reversal ? '"${financeTestMovementId(9999)}"' : 'null'},'
        '"reversalReason":${reversal ? '"Erro"' : 'null'},'
        '"createdAt":"2026-09-10T12:00:00Z"}';
  }

  String get _bulkJson =>
      '{"accountId":"$financeTestAccountId","movementAllocations":'
      '[${allocations.values.join(',')}]}';

  Future<AuthHttpResponse> _handle(
    Uri uri,
    AuthHttpMethod method,
    Duration timeout,
    Map<String, String> headers,
    String? body,
  ) async {
    final path = uri.path;
    AuthHttpResponse ok(String json, [int status = 200]) =>
        AuthHttpResponse(statusCode: status, body: json);

    if (method == AuthHttpMethod.post) {
      final revision = RegExp(
        r'^/api/v1/finance/movements/([^/]+)/allocation/revisions$',
      ).firstMatch(path);
      if (revision != null) {
        return _postRevision(
          revision.group(1)!,
          jsonDecode(body!) as Map<String, dynamic>,
        );
      }
      final allocation = RegExp(
        r'^/api/v1/finance/movements/([^/]+)/allocation$',
      ).firstMatch(path);
      if (allocation != null) {
        return _postAllocation(
          allocation.group(1)!,
          jsonDecode(body!) as Map<String, dynamic>,
        );
      }
      if (path == '/api/v1/finance/categories') {
        return _postCategory(jsonDecode(body!) as Map<String, dynamic>);
      }
      if (path == '/api/v1/finance/categorization-rules') {
        return _postRule(jsonDecode(body!) as Map<String, dynamic>);
      }
      final disable = RegExp(
        r'^/api/v1/finance/categorization-rules/([^/]+)/disable$',
      ).firstMatch(path);
      if (disable != null) return _postDisable(disable.group(1)!);
      if (path == '$_accountPath/categorization-rules/preview') {
        return _postPreview();
      }
      if (path == '$_accountPath/categorization-rules/apply') {
        return _postApply(jsonDecode(body!) as Map<String, dynamic>);
      }
      final entry = RegExp(
        r'^/api/v1/finance/accounts/[^/]+/(income|expense)$',
      ).firstMatch(path);
      if (entry != null) {
        final payload = jsonDecode(body!) as Map<String, dynamic>;
        final kind = entry.group(1)!;
        final spec = FakeMovementSpec(
          id: financeTestMovementId(900 + movements.length),
          amount: kind == 'expense'
              ? '-${payload['amount']}'
              : payload['amount'] as String,
          effect: kind.toUpperCase(),
          description: payload['description'] as String,
        );
        movements = [...movements, spec];
        return ok(_movementJson(spec), 201);
      }
      return const AuthHttpResponse(statusCode: 405, body: '{}');
    }
    if (method != AuthHttpMethod.get) {
      return const AuthHttpResponse(statusCode: 405, body: '{}');
    }
    if (path == _accountPath) return ok(accountJson);
    if (path == '$_accountPath/opening-balance') {
      return ok('{"openingBalance":null}');
    }
    if (path == '$_accountPath/balance') {
      return ok(
        '{"accountId":"$financeTestAccountId","currency":"BRL",'
        '"openingBalance":null,"movementNet":{"amount":"0","currency":"BRL"},'
        '"currentBalance":{"amount":"0","currency":"BRL"},'
        '"movementCount":${movements.length},'
        '"calculatedAt":"2026-09-20T12:00:00Z"}',
      );
    }
    if (path == '$_accountPath/statement') {
      final entries = movements
          .map(
            (spec) =>
                '{"movement":${_movementJson(spec)},'
                '"balanceAfter":{"amount":"0","currency":"BRL"}}',
          )
          .join(',');
      return ok(
        '{"accountId":"$financeTestAccountId","currency":"BRL",'
        '"openingBalance":null,"entries":[$entries],'
        '"closingBalance":{"amount":"0","currency":"BRL"},'
        '"calculatedAt":"2026-09-20T12:00:00Z"}',
      );
    }
    if (path == '$_accountPath/transfers') return ok('{"transfers":[]}');
    if (path == '/api/v1/finance/accounts') {
      return ok('{"accounts":[$accountJson]}');
    }
    if (path == '/api/v1/finance/categories') {
      final failure = categoryReadStatus;
      if (failure != null) {
        return AuthHttpResponse(statusCode: failure, body: '{}');
      }
      return ok('{"categories":[${categories.join(',')}]}');
    }
    if (path == '/api/v1/finance/categorization-rules') {
      final failure = rulesReadStatus;
      if (failure != null) {
        return AuthHttpResponse(statusCode: failure, body: '{}');
      }
      return ok('{"rules":[${rules.join(',')}]}');
    }
    if (path == '$_accountPath/categorization-rules/origins') {
      final failure = originsReadStatus;
      if (failure != null) {
        return AuthHttpResponse(statusCode: failure, body: '{}');
      }
      return ok(
        '{"accountId":"$financeTestAccountId",'
        '"origins":[${origins.values.join(',')}]}',
      );
    }
    if (path == '$_accountPath/movement-allocations') {
      final failure = bulkReadStatus;
      if (failure != null) {
        return AuthHttpResponse(statusCode: failure, body: '{}');
      }
      final snapshot = _bulkJson;
      final gate = nextBulkGate;
      nextBulkGate = null;
      if (gate != null) await gate.future;
      return ok(snapshot);
    }
    return const AuthHttpResponse(statusCode: 404, body: '{}');
  }

  Future<AuthHttpResponse> _postAllocation(
    String movementId,
    Map<String, dynamic> body,
  ) async {
    postedKeys.add(body['idempotencyKey'] as String);
    postedBodies.add(body);
    onAllocationPost?.call(movementId);
    final gate = allocationPostGate;
    if (gate != null) await gate.future;
    if (allocationPostThrows) {
      throw const FormatException('simulated transport failure');
    }
    final status = allocationPostStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final override = allocationPostBody;
    if (override != null) {
      return AuthHttpResponse(
        statusCode: 201,
        body: override(movementId, body),
      );
    }
    _createdSets += 1;
    final shares = (body['allocations'] as List<dynamic>)
        .cast<Map<String, dynamic>>()
        .map(
          (share) => (share['categoryId'] as String, share['amount'] as String),
        )
        .toList();
    final json = fakeAllocationJson(
      setId: financeTestAllocationSetId(100 + _createdSets),
      movementId: movementId,
      shares: shares,
    );
    allocations[movementId] = json;
    return AuthHttpResponse(statusCode: 201, body: json);
  }

  /// Mimics the server: replays a known idempotency key, answers 409 when the
  /// predecessor is not the current set, otherwise appends revision N+1.
  Future<AuthHttpResponse> _postRevision(
    String movementId,
    Map<String, dynamic> body,
  ) async {
    final key = body['idempotencyKey'] as String;
    revisionKeys.add(key);
    revisionBodies.add(body);
    revisionMovementIds.add(movementId);
    onRevisionPost?.call(movementId, body);
    final gate = revisionPostGate;
    if (gate != null) await gate.future;
    if (revisionPostThrows) {
      throw const FormatException('simulated transport failure');
    }
    final status = revisionPostStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final override = revisionPostBody;
    if (override != null) {
      return AuthHttpResponse(
        statusCode: 201,
        body: override(movementId, body),
      );
    }
    final replay = _revisionReplays[key];
    if (replay != null) return AuthHttpResponse(statusCode: 201, body: replay);
    final currentJson = allocations[movementId];
    if (currentJson == null) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    final current = jsonDecode(currentJson) as Map<String, dynamic>;
    if (current['allocationSetId'] != body['supersedesId']) {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    _createdSets += 1;
    final shares = (body['allocations'] as List<dynamic>)
        .cast<Map<String, dynamic>>()
        .map(
          (share) => (share['categoryId'] as String, share['amount'] as String),
        )
        .toList();
    final json = fakeAllocationJson(
      setId: financeTestAllocationSetId(200 + _createdSets),
      movementId: movementId,
      shares: shares,
      revision: (current['revision'] as int) + 1,
      supersedesId: body['supersedesId'] as String,
    );
    allocations[movementId] = json;
    _revisionReplays[key] = json;
    return AuthHttpResponse(statusCode: 201, body: json);
  }

  Future<AuthHttpResponse> _postRule(Map<String, dynamic> body) async {
    ruleBodies.add(body);
    onRulePost?.call(body);
    if (rulePostThrows) throw const FormatException('simulated transport');
    final status = rulePostStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    _createdRules += 1;
    final json = fakeRuleJson(
      id: financeTestRuleId(100 + _createdRules),
      pattern: body['descriptionPattern'] as String,
      matcher: body['descriptionMatcher'] as String,
      categoryId: body['targetCategoryId'] as String,
      priority: body['priority'] as int,
      accountId: body['accountId'] as String?,
      effect: body['resultEffect'] as String?,
    );
    rules = [json, ...rules];
    return AuthHttpResponse(statusCode: 201, body: json);
  }

  Future<AuthHttpResponse> _postDisable(String ruleId) async {
    disabledRuleIds.add(ruleId);
    if (ruleDisableThrows) throw const FormatException('simulated transport');
    final status = ruleDisableStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    for (var index = 0; index < rules.length; index += 1) {
      final rule = jsonDecode(rules[index]) as Map<String, dynamic>;
      if (rule['ruleId'] != ruleId) continue;
      final disabled = fakeRuleJson(
        id: ruleId,
        pattern: rule['descriptionPattern'] as String,
        matcher: rule['descriptionMatcher'] as String,
        categoryId: rule['targetCategoryId'] as String,
        priority: rule['priority'] as int,
        status: 'DISABLED',
        accountId: rule['accountId'] as String?,
        effect: rule['resultEffect'] as String?,
        createdBy: rule['createdByOperatorId'] as String,
      );
      rules = [...rules]..[index] = disabled;
      return AuthHttpResponse(statusCode: 200, body: disabled);
    }
    return const AuthHttpResponse(statusCode: 404, body: '{}');
  }

  Future<AuthHttpResponse> _postPreview() async {
    if (previewThrows) throw const FormatException('simulated transport');
    final status = previewStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    final override = previewBody;
    if (override != null) {
      return AuthHttpResponse(statusCode: 200, body: override);
    }
    final first = rules.isEmpty
        ? null
        : jsonDecode(rules.first) as Map<String, dynamic>;
    var matched = 0;
    var noMatch = 0;
    var ineligible = 0;
    var already = 0;
    final items = <String>[];
    for (final spec in movements) {
      String status;
      if (spec.role != 'STANDARD' || spec.effect == 'NEUTRAL') {
        status = 'INELIGIBLE';
        ineligible += 1;
      } else if (allocations.containsKey(spec.id)) {
        status = 'ALREADY_CLASSIFIED';
        already += 1;
      } else if (first != null) {
        status = 'MATCHED';
        matched += 1;
      } else {
        status = 'NO_MATCH';
        noMatch += 1;
      }
      final matchedItem = status == 'MATCHED';
      items.add(
        '{"movementId":"${spec.id}","status":"$status",'
        '"ruleId":${matchedItem ? '"${first!['ruleId']}"' : 'null'},'
        '"targetCategoryId":${matchedItem ? '"${first!['targetCategoryId']}"' : 'null'}}',
      );
    }
    return AuthHttpResponse(
      statusCode: 200,
      body:
          '{"accountId":"$financeTestAccountId",'
          '"totalMovements":${movements.length},"counts":{"matched":$matched,'
          '"noMatch":$noMatch,"ambiguous":0,"ineligible":$ineligible,'
          '"alreadyClassified":$already},"items":[${items.join(',')}],'
          '"applicableTruncated":${matched > 200}}',
    );
  }

  Future<AuthHttpResponse> _postApply(Map<String, dynamic> body) async {
    applyBodies.add(body);
    final items = (body['items'] as List<dynamic>).cast<Map<String, dynamic>>();
    onApplyPost?.call(items);
    final gate = applyGate;
    if (gate != null) await gate.future;
    if (applyThrows) throw const FormatException('simulated transport');
    final status = applyStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    final responder = applyResponder;
    if (responder != null) {
      return AuthHttpResponse(statusCode: 200, body: responder(items));
    }
    final results = <String>[];
    var classified = 0;
    var already = 0;
    for (final item in items) {
      final movementId = item['movementId'] as String;
      final ruleId = item['ruleId'] as String;
      if (allocations.containsKey(movementId)) {
        already += 1;
        results.add(
          '{"movementId":"$movementId","status":"ALREADY_CLASSIFIED",'
          '"ruleId":null,"allocationSetId":null}',
        );
        continue;
      }
      _ruleSets += 1;
      final setId = financeTestAllocationSetId(300 + _ruleSets);
      final spec = movements.firstWhere(
        (candidate) => candidate.id == movementId,
      );
      final rule = rules
          .map((raw) => jsonDecode(raw) as Map<String, dynamic>)
          .firstWhere((candidate) => candidate['ruleId'] == ruleId);
      allocations[movementId] = fakeAllocationJson(
        setId: setId,
        movementId: movementId,
        shares: [(rule['targetCategoryId'] as String, spec.amount)],
      );
      origins[setId] = fakeOriginJson(
        movementId: movementId,
        setId: setId,
        ruleId: ruleId,
      );
      classified += 1;
      results.add(
        '{"movementId":"$movementId","status":"CLASSIFIED",'
        '"ruleId":"$ruleId","allocationSetId":"$setId"}',
      );
    }
    return AuthHttpResponse(
      statusCode: 200,
      body:
          '{"accountId":"$financeTestAccountId","requested":${items.length},'
          '"counts":{"classified":$classified,"alreadyClassified":$already,'
          '"ambiguous":0,"noMatch":0,"ineligible":0,"conflict":0,"failed":0},'
          '"results":[${results.join(',')}]}',
    );
  }

  Future<AuthHttpResponse> _postCategory(Map<String, dynamic> body) async {
    onCategoryPost?.call(body);
    if (categoryPostThrows) {
      throw const FormatException('simulated transport failure');
    }
    final status = categoryPostStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final override = categoryPostBody;
    if (override != null) {
      return AuthHttpResponse(statusCode: 201, body: override(body));
    }
    _createdCategories += 1;
    final json = fakeCategoryJson(
      id: financeTestCategoryId(500 + _createdCategories),
      name: body['name'] as String,
      scope: body['visibilityScope'] as String,
      parentId: body['parentId'] as String?,
    );
    categories.add(json);
    return AuthHttpResponse(statusCode: 201, body: json);
  }
}

/// Session fixed to an authenticated operator, as the real login would leave it.
class FixedOperatorSession extends OperatorSessionController {
  FixedOperatorSession(this.operatorId);

  final String operatorId;

  @override
  OperatorSessionState build() => OperatorSessionState.authenticated(
    OperatorPrincipal(
      operatorId: operatorId,
      installationId: financeTestInstallationId,
      primaryResidenceId: null,
      login: 'admin',
      role: 'installation_admin',
      expiresAt: DateTime.utc(2030),
    ),
  );
}

List<Override> financeTestOverrides(
  FakeFinanceBackend backend, {
  String operatorId = financeTestOwnerId,
}) => [
  authTransportProvider.overrideWithValue(backend.transport),
  authApiBaseUriProvider.overrideWithValue(
    Uri.parse('http://localhost/api/v1/'),
  ),
  authRequestTimeoutProvider.overrideWithValue(const Duration(seconds: 2)),
  sessionTokenVaultProvider.overrideWithValue(
    SessionTokenVault()..store(financeTestToken),
  ),
  operatorSessionControllerProvider.overrideWith(
    () => FixedOperatorSession(operatorId),
  ),
];

ProviderContainer financeTestContainer(
  FakeFinanceBackend backend, {
  String operatorId = financeTestOwnerId,
}) => ProviderContainer(
  overrides: financeTestOverrides(backend, operatorId: operatorId),
);
