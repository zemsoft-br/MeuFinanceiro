import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_goal_controller.dart';

import 'fake_auth_transport.dart';
import 'fake_finance_backend.dart';

String goalTestId(int index) =>
    'c4000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

String goalTestEventId(int index) =>
    'c5000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

String goalTestAccountId(int index) =>
    'c6000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

BigInt _scaled(String amount) {
  final negative = amount.startsWith('-');
  final unsigned = negative ? amount.substring(1) : amount;
  final parts = unsigned.split('.');
  final fraction = (parts.length == 2 ? parts[1] : '').padRight(8, '0');
  final value = BigInt.parse('${parts.first}$fraction');
  return negative ? -value : value;
}

String _canonical(BigInt scaled) {
  final negative = scaled < BigInt.zero;
  final digits = scaled.abs().toString().padLeft(9, '0');
  final integer = digits.substring(0, digits.length - 8);
  var fraction = digits.substring(digits.length - 8);
  while (fraction.endsWith('0')) {
    fraction = fraction.substring(0, fraction.length - 1);
  }
  final body = fraction.isEmpty ? integer : '$integer.$fraction';
  return negative && scaled != BigInt.zero ? '-$body' : body;
}

/// `allocated / target * 100`, half-up at two places, as the server does it.
String _percent(BigInt target, BigInt allocated) {
  final numerator = allocated * BigInt.from(10000);
  var hundredths = numerator ~/ target;
  final remainder = numerator.remainder(target);
  if (remainder * BigInt.two >= target) hundredths += BigInt.one;
  final text = hundredths.toString().padLeft(3, '0');
  return '${text.substring(0, text.length - 2)}.${text.substring(text.length - 2)}';
}

class FakeGoal {
  FakeGoal({
    required this.index,
    this.scope = 'HOUSEHOLD',
    this.owner = financeTestOwnerId,
    this.title = 'Reserva',
    this.description,
    this.currency = 'BRL',
    this.target = '1000',
    this.targetDate,
    this.version = 1,
  });

  final int index;
  String scope;
  String owner;
  String title;
  String? description;
  String currency;
  String target;
  String? targetDate;
  int version;

  String get id => goalTestId(index);
}

class FakeGoalAccount {
  FakeGoalAccount({
    required this.index,
    this.name = 'Conta',
    this.scope = 'HOUSEHOLD',
    this.owner = financeTestOwnerId,
    this.currency = 'BRL',
    this.status = 'ACTIVE',
    this.balance = '1000',
  });

  final int index;
  String name;
  String scope;
  String owner;
  String currency;
  String status;

  /// The canonical balance, set by the test (the "ledger").
  String balance;

  String get id => goalTestAccountId(index);
}

class FakeGoalEvent {
  FakeGoalEvent({
    required this.index,
    required this.goalId,
    required this.accountId,
    required this.operation,
    required this.amount,
    this.actor = financeTestOwnerId,
  });

  final int index;
  final String goalId;
  final String accountId;
  final String operation;
  final String amount;
  final String actor;

  String get id => goalTestEventId(index);
}

/// In-memory goal API (the server's side of the contract) for controller and
/// widget tests. Every request goes through [FakeAuthTransport], so tests count
/// exactly what was called. It plays the server: it owns the goals, the CAS
/// version, the append-only events, the account balances (set by the test as the
/// "ledger"), the availability rule and every derived number.
class FakeGoalBackend {
  FakeGoalBackend({
    List<FakeGoal>? goals,
    List<FakeGoalAccount>? accounts,
    this.operatorId = financeTestOwnerId,
  }) : goals = goals ?? [],
       accounts = accounts ?? [] {
    transport = FakeAuthTransport(_handle);
  }

  List<FakeGoal> goals;
  List<FakeGoalAccount> accounts;
  final List<FakeGoalEvent> events = [];
  final String operatorId;

  late final FakeAuthTransport transport;

  // --- failures / gates ---
  int? accountsStatus;
  int? listStatus;
  bool listThrows = false;
  String? listBodyOverride;
  Completer<void>? listGate;
  int failNextLists = 0;
  int? summaryStatus;
  bool summaryThrows = false;
  String? summaryBodyOverride;
  Completer<void>? summaryGate;
  int? postStatus;
  bool postThrows = false;
  bool postCommitsThenFails = false;
  String? postBodyOverride;
  Completer<void>? postGate;
  int? putStatus;
  bool putThrows = false;
  bool putCommitsThenFails = false;
  String? putBodyOverride;
  Completer<void>? putGate;
  int? allocStatus;
  bool allocThrows = false;
  bool allocCommitsThenFails = false;
  String? allocBodyOverride;
  Completer<void>? allocGate;

  /// Runs inside every write, before it is decided (a concurrent writer).
  void Function()? beforePut;
  void Function()? beforeAllocate;

  final List<Map<String, dynamic>> postBodies = [];
  final List<Map<String, dynamic>> putBodies = [];
  final List<Map<String, dynamic>> allocationBodies = [];
  final Map<String, String> _idempotency = {};
  final Map<String, String> _allocationIdempotency = {};
  int _nextEvent = 1;

  List<AuthTransportCall> get calls => transport.calls;

  int count(AuthHttpMethod method, String pathPrefix) => calls
      .where(
        (call) => call.method == method && call.uri.path.startsWith(pathPrefix),
      )
      .length;

  int get creates => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.post &&
            call.uri.path == '/api/v1/finance/goals',
      )
      .length;
  int get puts => count(AuthHttpMethod.put, '/api/v1/finance/goals');
  int get allocationPosts => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.post &&
            call.uri.path.endsWith('/allocations'),
      )
      .length;
  int get listReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            call.uri.path == '/api/v1/finance/goals',
      )
      .length;
  int get accountReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            call.uri.path == '/api/v1/finance/accounts',
      )
      .length;
  int get summaryReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            call.uri.path.endsWith('/summary'),
      )
      .length;

  /// Every GET that is not the account list, the goal list or one summary.
  int get perItemRequests => calls.where((call) {
    final path = call.uri.path;
    return call.method == AuthHttpMethod.get &&
        !(path == '/api/v1/finance/accounts' ||
            path == '/api/v1/finance/goals' ||
            path.endsWith('/summary'));
  }).length;

  FakeGoal? byId(String id) {
    for (final goal in goals) {
      if (goal.id == id) return goal;
    }
    return null;
  }

  FakeGoalAccount? accountById(String id) {
    for (final account in accounts) {
      if (account.id == id) return account;
    }
    return null;
  }

  /// Seeds a past event directly (history that already existed).
  FakeGoalEvent seed(
    FakeGoal goal,
    FakeGoalAccount account,
    String operation,
    String amount,
  ) {
    final created = FakeGoalEvent(
      index: _nextEvent++,
      goalId: goal.id,
      accountId: account.id,
      operation: operation,
      amount: amount,
      actor: goal.owner,
    );
    events.add(created);
    return created;
  }

  BigInt _net(String goalId, String accountId) {
    var total = BigInt.zero;
    for (final event in events) {
      if (event.goalId == goalId && event.accountId == accountId) {
        final value = _scaled(event.amount);
        total += event.operation == 'ALLOCATE' ? value : -value;
      }
    }
    return total;
  }

  BigInt _accountTotal(String accountId) {
    var total = BigInt.zero;
    for (final event in events) {
      if (event.accountId == accountId) {
        final value = _scaled(event.amount);
        total += event.operation == 'ALLOCATE' ? value : -value;
      }
    }
    return total;
  }

  BigInt _allocated(FakeGoal goal) {
    var total = BigInt.zero;
    for (final event in events.where((event) => event.goalId == goal.id)) {
      final value = _scaled(event.amount);
      total += event.operation == 'ALLOCATE' ? value : -value;
    }
    return total;
  }

  // --- JSON ---

  String _money(String amount, String currency) =>
      '{"amount":"$amount","currency":"$currency"}';

  String goalJson(FakeGoal goal) =>
      '{"id":"${goal.id}","ownerOperatorId":"${goal.owner}",'
      '"visibilityScope":"${goal.scope}","title":${jsonEncode(goal.title)},'
      '"description":${goal.description == null ? 'null' : jsonEncode(goal.description)},'
      '"currency":"${goal.currency}","target":${_money(goal.target, goal.currency)},'
      '"targetDate":${goal.targetDate == null ? 'null' : '"${goal.targetDate}"'},'
      '"version":${goal.version},'
      '"createdAt":"2026-10-01T12:00:00Z","updatedAt":"2026-10-01T12:00:00Z",'
      '"canEdit":${goal.owner == operatorId}}';

  String listItemJson(FakeGoal goal) {
    final target = _scaled(goal.target);
    final allocated = _allocated(goal);
    final remaining = target > allocated ? target - allocated : BigInt.zero;
    return '{"goal":${goalJson(goal)},'
        '"allocated":${_money(_canonical(allocated), goal.currency)},'
        '"remainingTarget":${_money(_canonical(remaining), goal.currency)},'
        '"progressPercent":"${_percent(target, allocated)}",'
        '"progressStatus":"${_status(target, allocated)}"}';
  }

  String _status(BigInt target, BigInt allocated) => allocated <= BigInt.zero
      ? 'NOT_STARTED'
      : allocated < target
      ? 'IN_PROGRESS'
      : allocated == target
      ? 'REACHED'
      : 'EXCEEDED';

  String eventJson(FakeGoalEvent event, String currency) =>
      '{"id":"${event.id}","goalId":"${event.goalId}",'
      '"accountId":"${event.accountId}","operation":"${event.operation}",'
      '"amount":${_money(event.amount, currency)},'
      '"actorOperatorId":"${event.actor}",'
      '"createdAt":"2026-10-02T12:00:00Z"}';

  String summaryJson(FakeGoal goal) {
    final target = _scaled(goal.target);
    final allocated = _allocated(goal);
    final remaining = target > allocated ? target - allocated : BigInt.zero;
    final surplus = allocated > target ? allocated - target : BigInt.zero;
    final goalEvents = events
        .where((event) => event.goalId == goal.id)
        .toList();
    final accountIds = {
      for (final event in goalEvents) event.accountId,
    }.toList()..sort();
    var anyInsufficient = false;
    final accountJson = accountIds
        .map((accountId) {
          final account = accountById(accountId)!;
          final total = _accountTotal(accountId);
          final balance = _scaled(account.balance);
          final insufficient = total > balance;
          anyInsufficient = anyInsufficient || insufficient;
          return '{"accountId":"$accountId","accountStatus":"${account.status}",'
              '"allocated":${_money(_canonical(_net(goal.id, accountId)), goal.currency)},'
              '"accountBalance":${_money(account.balance, goal.currency)},'
              '"accountAllocatedTotal":${_money(_canonical(total), goal.currency)},'
              '"backingStatus":"${insufficient ? 'INSUFFICIENT' : 'COVERED'}",'
              '"shortfall":${_money(_canonical(insufficient ? total - balance : BigInt.zero), goal.currency)}}';
        })
        .join(',');
    return '{"goal":${goalJson(goal)},"target":${_money(goal.target, goal.currency)},'
        '"allocated":${_money(_canonical(allocated), goal.currency)},'
        '"remainingTarget":${_money(_canonical(remaining), goal.currency)},'
        '"surplus":${_money(_canonical(surplus), goal.currency)},'
        '"progressPercent":"${_percent(target, allocated)}",'
        '"progressStatus":"${_status(target, allocated)}",'
        '"hasInsufficientBacking":$anyInsufficient,'
        '"accounts":[$accountJson],'
        '"events":[${goalEvents.map((event) => eventJson(event, goal.currency)).join(',')}]}';
  }

  String accountJson(FakeGoalAccount account) =>
      '{"accountId":"${account.id}","ownerOperatorId":"${account.owner}",'
      '"visibilityScope":"${account.scope}","accountType":"CHECKING",'
      '"customTypeName":null,"name":${jsonEncode(account.name)},'
      '"currency":"${account.currency}","status":"${account.status}",'
      '"createdAt":"2026-09-01T12:00:00Z","updatedAt":"2026-09-01T12:00:00Z",'
      '"archivedAt":${account.status == 'ARCHIVED' ? '"2026-09-02T12:00:00Z"' : 'null'}}';

  // --- routing ---

  Future<AuthHttpResponse> _handle(
    Uri uri,
    AuthHttpMethod method,
    Duration timeout,
    Map<String, String> headers,
    String? body,
  ) async {
    final path = uri.path;
    if (method == AuthHttpMethod.get) {
      if (path == '/api/v1/finance/accounts') {
        final status = accountsStatus;
        if (status != null) {
          return AuthHttpResponse(statusCode: status, body: '{}');
        }
        return AuthHttpResponse(
          statusCode: 200,
          body: '{"accounts":[${accounts.map(accountJson).join(',')}]}',
        );
      }
      if (path == '/api/v1/finance/goals') return _list();
      final summary = RegExp(
        r'^/api/v1/finance/goals/([^/]+)/summary$',
      ).firstMatch(path);
      if (summary != null) return _summary(summary.group(1)!);
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (method == AuthHttpMethod.post && path == '/api/v1/finance/goals') {
      return _post(jsonDecode(body!) as Map<String, dynamic>);
    }
    final alloc = RegExp(
      r'^/api/v1/finance/goals/([^/]+)/allocations$',
    ).firstMatch(path);
    if (method == AuthHttpMethod.post && alloc != null) {
      return _allocate(
        alloc.group(1)!,
        jsonDecode(body!) as Map<String, dynamic>,
      );
    }
    final put = RegExp(r'^/api/v1/finance/goals/([^/]+)$').firstMatch(path);
    if (method == AuthHttpMethod.put && put != null) {
      return _put(put.group(1)!, jsonDecode(body!) as Map<String, dynamic>);
    }
    return const AuthHttpResponse(statusCode: 405, body: '{}');
  }

  Future<AuthHttpResponse> _list() async {
    final gate = listGate;
    if (gate != null) await gate.future;
    if (listThrows) throw const FormatException('simulated transport');
    if (failNextLists > 0) {
      failNextLists -= 1;
      return const AuthHttpResponse(statusCode: 503, body: '{}');
    }
    final status = listStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final override = listBodyOverride;
    if (override != null) {
      return AuthHttpResponse(statusCode: 200, body: override);
    }
    return AuthHttpResponse(
      statusCode: 200,
      body: '{"items":[${goals.map(listItemJson).join(',')}]}',
    );
  }

  Future<AuthHttpResponse> _summary(String id) async {
    final gate = summaryGate;
    if (gate != null) await gate.future;
    if (summaryThrows) throw const FormatException('simulated transport');
    final status = summaryStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final override = summaryBodyOverride;
    if (override != null) {
      return AuthHttpResponse(statusCode: 200, body: override);
    }
    final goal = byId(id);
    return goal == null
        ? const AuthHttpResponse(statusCode: 404, body: '{}')
        : AuthHttpResponse(statusCode: 200, body: summaryJson(goal));
  }

  Future<AuthHttpResponse> _post(Map<String, dynamic> body) async {
    postBodies.add(body);
    final gate = postGate;
    if (gate != null) await gate.future;
    if (postThrows) throw const FormatException('simulated transport');
    final status = postStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final key = body['idempotencyKey'] as String;
    final material = jsonEncode({...body}..remove('idempotencyKey'));
    final known = _idempotency[key];
    if (known != null) {
      final parts = known.split('|');
      if (parts.first != material) {
        return const AuthHttpResponse(statusCode: 409, body: '{}');
      }
      return AuthHttpResponse(
        statusCode: 201,
        body: goalJson(byId(parts.last)!),
      );
    }
    final created = FakeGoal(
      index: 900 + goals.length,
      scope: body['visibilityScope'] as String,
      owner: operatorId,
      title: body['title'] as String,
      description: body['description'] as String?,
      currency: body['currency'] as String,
      target: _canonical(_scaled(body['targetAmount'] as String)),
      targetDate: body['targetDate'] as String?,
    );
    goals.add(created);
    _idempotency[key] = '$material|${created.id}';
    if (postCommitsThenFails) {
      return const AuthHttpResponse(statusCode: 503, body: '{}');
    }
    return AuthHttpResponse(
      statusCode: 201,
      body: postBodyOverride ?? goalJson(created),
    );
  }

  Future<AuthHttpResponse> _put(String id, Map<String, dynamic> body) async {
    putBodies.add(body);
    final gate = putGate;
    if (gate != null) await gate.future;
    beforePut?.call();
    if (putThrows) throw const FormatException('simulated transport');
    final status = putStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final goal = byId(id);
    if (goal == null) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (goal.owner != operatorId) {
      return const AuthHttpResponse(statusCode: 403, body: '{}');
    }
    if (goal.version != body['expectedVersion']) {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    goal
      ..version += 1
      ..title = body['title'] as String
      ..description = body['description'] as String?
      ..target = _canonical(_scaled(body['targetAmount'] as String))
      ..targetDate = body['targetDate'] as String?;
    if (putCommitsThenFails) {
      return const AuthHttpResponse(statusCode: 503, body: '{}');
    }
    return AuthHttpResponse(
      statusCode: 200,
      body: putBodyOverride ?? goalJson(goal),
    );
  }

  Future<AuthHttpResponse> _allocate(
    String goalId,
    Map<String, dynamic> body,
  ) async {
    allocationBodies.add(body);
    final gate = allocGate;
    if (gate != null) await gate.future;
    beforeAllocate?.call();
    if (allocThrows) throw const FormatException('simulated transport');
    final status = allocStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final goal = byId(goalId);
    if (goal == null) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (goal.owner != operatorId) {
      return const AuthHttpResponse(statusCode: 403, body: '{}');
    }
    final key = body['idempotencyKey'] as String;
    final material = jsonEncode({...body}..remove('idempotencyKey'));
    final known = _allocationIdempotency[key];
    if (known != null) {
      final parts = known.split('|');
      if (parts.first != material) {
        return const AuthHttpResponse(statusCode: 409, body: '{}');
      }
      final event = events.firstWhere(
        (candidate) => candidate.id == parts.last,
      );
      return AuthHttpResponse(
        statusCode: 201,
        body: eventJson(event, goal.currency),
      );
    }
    final account = accountById(body['accountId'] as String);
    final operation = body['operation'] as String;
    final eligible =
        account != null &&
        account.owner == goal.owner &&
        account.scope == goal.scope &&
        account.currency == goal.currency &&
        (operation == 'RELEASE' || account.status == 'ACTIVE');
    if (!eligible) return const AuthHttpResponse(statusCode: 404, body: '{}');
    final amount = _scaled(body['amount'] as String);
    if (operation == 'ALLOCATE') {
      final available = _scaled(account.balance) - _accountTotal(account.id);
      if (amount > available) {
        return const AuthHttpResponse(statusCode: 409, body: '{}');
      }
    } else if (amount > _net(goal.id, account.id)) {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    final event = FakeGoalEvent(
      index: _nextEvent++,
      goalId: goal.id,
      accountId: account.id,
      operation: operation,
      amount: _canonical(amount),
      actor: operatorId,
    );
    events.add(event);
    _allocationIdempotency[key] = '$material|${event.id}';
    if (allocCommitsThenFails) {
      return const AuthHttpResponse(statusCode: 503, body: '{}');
    }
    return AuthHttpResponse(
      statusCode: 201,
      body: allocBodyOverride ?? eventJson(event, goal.currency),
    );
  }
}

List<Override> goalTestOverrides(
  FakeGoalBackend backend, {
  String operatorId = financeTestOwnerId,
  DateTime? now,
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
  financialGoalClockProvider.overrideWithValue(
    () => now ?? DateTime(2026, 10, 7),
  ),
];

ProviderContainer goalTestContainer(
  FakeGoalBackend backend, {
  String operatorId = financeTestOwnerId,
  DateTime? now,
}) => ProviderContainer(
  overrides: goalTestOverrides(backend, operatorId: operatorId, now: now),
);
