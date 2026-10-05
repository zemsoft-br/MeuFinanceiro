import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';

import 'fake_auth_transport.dart';
import 'fake_finance_backend.dart';

const pendingTestAccountA = '40000000-0000-4000-8000-0000000000a1';
const pendingTestAccountB = '40000000-0000-4000-8000-0000000000b2';

String pendingTestMovementId(int index) =>
    '61000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

/// One Movement in the fake canonical "pending" state.
class FakePendingItem {
  FakePendingItem({
    required this.index,
    this.accountId = pendingTestAccountA,
    this.amount = '-10.00',
    this.effect = 'EXPENSE',
    this.description = 'Padaria',
    this.date = '2026-09-10',
    this.status = 'NO_MATCH',
    this.ruleId,
    this.categoryId,
    this.canClassify = true,
  });

  final int index;
  String accountId;
  String amount;
  String effect;
  String description;
  String date;
  String status;
  String? ruleId;
  String? categoryId;
  bool canClassify;

  String get id => pendingTestMovementId(index);

  String json(String ownerId) =>
      '{"movementId":"$id","accountId":"$accountId",'
      '"money":{"amount":"$amount","currency":"BRL"},"resultEffect":"$effect",'
      '"effectiveDate":"$date","competenceDate":"$date",'
      '"description":"$description","accountVisibilityScope":"HOUSEHOLD",'
      '"accountOwnerOperatorId":"$ownerId","canClassify":$canClassify,'
      '"ruleStatus":"$status",'
      '"matchedRuleId":${ruleId == null ? 'null' : '"$ruleId"'},'
      '"suggestedCategoryId":${categoryId == null ? 'null' : '"$categoryId"'}}';
}

/// In-memory pending-inbox API (and the two canonical writes it reuses) for
/// controller and widget tests. Every request goes through [FakeAuthTransport],
/// so tests count exactly what was called. The server's behaviour is mimicked:
/// keyset pages in `date DESC, id DESC` order, filters applied server-side, and
/// a classified Movement leaves the pending state.
class FakePendingBackend {
  FakePendingBackend({
    List<FakePendingItem>? items,
    List<String>? categories,
    this.pageSize,
  }) : items = items ?? [],
       categories = categories ?? [] {
    transport = FakeAuthTransport(_handle);
  }

  /// The canonical pending state. Sorted on every read.
  List<FakePendingItem> items;
  List<String> categories;

  /// Caps a page below the requested limit (to force pagination in tests).
  int? pageSize;

  /// Accounts: A is owned by the signed-in operator, B by someone else.
  String accountAStatus = 'ACTIVE';

  late final FakeAuthTransport transport;

  // --- read failures / gates ---
  int? pendingReadStatus;
  bool pendingReadThrows = false;
  String? pendingBodyOverride;
  Completer<void>? pendingGate;
  int? categoryReadStatus;
  int? accountsReadStatus;

  /// When set, the next `n` pending reads fail with this status (then recover).
  int? failNextPendingReadsStatus;
  int failNextPendingReads = 0;

  // --- apply (rule) POST ---
  final List<Map<String, dynamic>> applyBodies = [];
  int? applyStatus;
  bool applyThrows = false;

  /// Result status for the single requested Movement. `CLASSIFIED` (default)
  /// removes the item from the pending state; every other status leaves the
  /// canonical state alone unless [onApply] changes it.
  String applyResultStatus = 'CLASSIFIED';
  String? applyBodyOverride;
  void Function(Map<String, dynamic> item)? onApply;
  Completer<void>? applyGate;

  // --- manual classification POST ---
  final List<Map<String, dynamic>> allocationBodies = [];
  final List<String> allocationMovementIds = [];
  int? allocationStatus;
  bool allocationThrows = false;
  void Function(String movementId)? onAllocation;
  Completer<void>? allocationGate;

  List<AuthTransportCall> get calls => transport.calls;

  List<AuthTransportCall> get pendingReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            call.uri.path == '/api/v1/finance/pending-movements',
      )
      .toList();

  int count(AuthHttpMethod method, String path) => calls
      .where((call) => call.method == method && call.uri.path == path)
      .length;

  int get applyPosts => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.post &&
            call.uri.path.endsWith('/categorization-rules/apply'),
      )
      .length;

  int get allocationPosts => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.post &&
            call.uri.path.endsWith('/allocation'),
      )
      .length;

  /// Every request that is not the page read, categories or accounts.
  int get perRowRequests => calls.where((call) {
    final path = call.uri.path;
    return !(path == '/api/v1/finance/pending-movements' ||
        path == '/api/v1/finance/categories' ||
        path == '/api/v1/finance/accounts' ||
        call.method == AuthHttpMethod.post);
  }).length;

  String _accountJson(String id, String owner, String name, String status) =>
      '{"accountId":"$id","ownerOperatorId":"$owner",'
      '"visibilityScope":"HOUSEHOLD","accountType":"CHECKING",'
      '"customTypeName":null,"name":"$name","currency":"BRL",'
      '"status":"$status","createdAt":"2026-09-01T12:00:00Z",'
      '"updatedAt":"2026-09-01T12:00:00Z",'
      '"archivedAt":${status == 'ARCHIVED' ? '"2026-09-02T12:00:00Z"' : 'null'}}';

  String get _accountsJson =>
      '{"accounts":['
      '${_accountJson(pendingTestAccountA, financeTestOwnerId, 'Conta Corrente', accountAStatus)},'
      '${_accountJson(pendingTestAccountB, financeTestOtherOperatorId, 'Conta do Membro', 'ACTIVE')}'
      ']}';

  List<FakePendingItem> get _sorted => [...items]
    ..sort((a, b) {
      final byDate = b.date.compareTo(a.date);
      return byDate != 0 ? byDate : b.id.compareTo(a.id);
    });

  Future<AuthHttpResponse> _handle(
    Uri uri,
    AuthHttpMethod method,
    Duration timeout,
    Map<String, String> headers,
    String? body,
  ) async {
    final path = uri.path;
    if (method == AuthHttpMethod.get) {
      if (path == '/api/v1/finance/pending-movements') {
        return _getPending(uri);
      }
      if (path == '/api/v1/finance/categories') {
        final status = categoryReadStatus;
        if (status != null) {
          return AuthHttpResponse(statusCode: status, body: '{}');
        }
        return AuthHttpResponse(
          statusCode: 200,
          body: '{"categories":[${categories.join(',')}]}',
        );
      }
      if (path == '/api/v1/finance/accounts') {
        final status = accountsReadStatus;
        if (status != null) {
          return AuthHttpResponse(statusCode: status, body: '{}');
        }
        return AuthHttpResponse(statusCode: 200, body: _accountsJson);
      }
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (method != AuthHttpMethod.post) {
      return const AuthHttpResponse(statusCode: 405, body: '{}');
    }
    final apply = RegExp(
      r'^/api/v1/finance/accounts/([^/]+)/categorization-rules/apply$',
    ).firstMatch(path);
    if (apply != null) {
      return _postApply(jsonDecode(body!) as Map<String, dynamic>);
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
    return const AuthHttpResponse(statusCode: 405, body: '{}');
  }

  Future<AuthHttpResponse> _getPending(Uri uri) async {
    final gate = pendingGate;
    if (gate != null) await gate.future;
    if (pendingReadThrows) throw const FormatException('simulated transport');
    if (failNextPendingReads > 0) {
      failNextPendingReads -= 1;
      return AuthHttpResponse(
        statusCode: failNextPendingReadsStatus ?? 503,
        body: '{}',
      );
    }
    final status = pendingReadStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final override = pendingBodyOverride;
    if (override != null) {
      return AuthHttpResponse(statusCode: 200, body: override);
    }
    final query = uri.queryParameters;
    final limit = int.parse(query['limit'] ?? '50');
    final cursor = query['cursor'];
    var rows = _sorted.where((item) {
      if (query['accountId'] != null && item.accountId != query['accountId']) {
        return false;
      }
      if (query['resultEffect'] != null &&
          item.effect != query['resultEffect']) {
        return false;
      }
      if (query['ruleStatus'] != null && item.status != query['ruleStatus']) {
        return false;
      }
      return true;
    }).toList();
    if (cursor != null) {
      // Keyset: the cursor is the id of the last item already returned.
      final after = cursor.replaceFirst('after_', '');
      final position = _sorted.indexWhere((item) => item.id == after);
      final later = position < 0
          ? _sorted
          : _sorted.skip(position + 1).toList();
      rows = rows.where(later.contains).toList();
    }
    final take = pageSize == null
        ? limit
        : (pageSize! < limit ? pageSize! : limit);
    final page = rows.take(take).toList();
    final more = rows.length > take;
    final nextCursor = more && page.isNotEmpty
        ? '"after_${page.last.id}"'
        : 'null';
    return AuthHttpResponse(
      statusCode: 200,
      body:
          '{"items":[${page.map((item) => item.json(item.accountId == pendingTestAccountA ? financeTestOwnerId : financeTestOtherOperatorId)).join(',')}],'
          '"nextCursor":$nextCursor}',
    );
  }

  Future<AuthHttpResponse> _postApply(Map<String, dynamic> body) async {
    applyBodies.add(body);
    final requested = (body['items'] as List<dynamic>)
        .cast<Map<String, dynamic>>();
    final item = requested.single;
    onApply?.call(item);
    final gate = applyGate;
    if (gate != null) await gate.future;
    if (applyThrows) throw const FormatException('simulated transport');
    final status = applyStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    final override = applyBodyOverride;
    if (override != null) {
      return AuthHttpResponse(statusCode: 200, body: override);
    }
    final movementId = item['movementId'] as String;
    final ruleId = item['ruleId'] as String;
    final result = applyResultStatus;
    if (result == 'CLASSIFIED') {
      items = items.where((candidate) => candidate.id != movementId).toList();
    }
    final classified = result == 'CLASSIFIED';
    final counts = {
      'classified': 0,
      'alreadyClassified': 0,
      'ambiguous': 0,
      'noMatch': 0,
      'ineligible': 0,
      'conflict': 0,
      'failed': 0,
    };
    const key = {
      'CLASSIFIED': 'classified',
      'ALREADY_CLASSIFIED': 'alreadyClassified',
      'AMBIGUOUS': 'ambiguous',
      'NO_MATCH': 'noMatch',
      'INELIGIBLE': 'ineligible',
      'CONFLICT': 'conflict',
      'FAILED': 'failed',
    };
    counts[key[result]!] = 1;
    return AuthHttpResponse(
      statusCode: 200,
      body:
          '{"accountId":"$pendingTestAccountA","requested":1,'
          '"counts":${jsonEncode(counts)},'
          '"results":[{"movementId":"$movementId","status":"$result",'
          '"ruleId":${classified ? '"$ruleId"' : 'null'},'
          '"allocationSetId":${classified ? '"e5000000-0000-4000-8000-000000000901"' : 'null'}}]}',
    );
  }

  Future<AuthHttpResponse> _postAllocation(
    String movementId,
    Map<String, dynamic> body,
  ) async {
    allocationBodies.add(body);
    allocationMovementIds.add(movementId);
    onAllocation?.call(movementId);
    final gate = allocationGate;
    if (gate != null) await gate.future;
    if (allocationThrows) throw const FormatException('simulated transport');
    final status = allocationStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final item = items.where((candidate) => candidate.id == movementId);
    if (item.isEmpty) {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    final shares = (body['allocations'] as List<dynamic>)
        .cast<Map<String, dynamic>>();
    items = items.where((candidate) => candidate.id != movementId).toList();
    return AuthHttpResponse(
      statusCode: 201,
      body: fakeAllocationJson(
        setId: financeTestAllocationSetId(700 + allocationBodies.length),
        movementId: movementId,
        shares: [
          for (final share in shares)
            (share['categoryId'] as String, share['amount'] as String),
        ],
      ),
    );
  }
}

List<Override> pendingTestOverrides(
  FakePendingBackend backend, {
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

ProviderContainer pendingTestContainer(
  FakePendingBackend backend, {
  String operatorId = financeTestOwnerId,
}) => ProviderContainer(
  overrides: pendingTestOverrides(backend, operatorId: operatorId),
);
