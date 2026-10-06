import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_controller.dart';

import 'fake_auth_transport.dart';
import 'fake_finance_backend.dart';

String budgetTestId(int index) =>
    'c3000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

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

/// `realized / planned * 100`, half-up at two places, as the server does it.
String _percent(BigInt planned, BigInt realized) {
  final negative = realized < BigInt.zero;
  final numerator = realized.abs() * BigInt.from(10000);
  var hundredths = numerator ~/ planned;
  final remainder = numerator.remainder(planned);
  if (remainder * BigInt.two >= planned) hundredths += BigInt.one;
  final text = hundredths.toString().padLeft(3, '0');
  final value =
      '${text.substring(0, text.length - 2)}.${text.substring(text.length - 2)}';
  return negative && hundredths != BigInt.zero ? '-$value' : value;
}

class FakeBudgetLine {
  FakeBudgetLine(this.categoryId, this.effect, this.planned);

  final String categoryId;
  final String effect;
  String planned;

  String get key => '$categoryId|$effect';
}

class FakeBudget {
  FakeBudget({
    required this.index,
    required this.period,
    required this.lines,
    this.scope = 'HOUSEHOLD',
    this.owner = financeTestOwnerId,
    this.name = 'Orçamento',
    this.currency = 'BRL',
    this.basis = 'CASH',
    this.version = 1,
  });

  final int index;
  final String period;
  String scope;
  String owner;
  String name;
  String currency;
  String basis;
  int version;
  List<FakeBudgetLine> lines;

  String get id => budgetTestId(index);
}

/// In-memory budget API (the server's side of the contract) for controller and
/// widget tests. Every request goes through [FakeAuthTransport], so tests count
/// exactly what was called. It plays the server: it owns the plan, the CAS
/// version, the realized amounts and the coverage (all set by the test as the
/// "ledger"), and derives remaining/status/percent itself, never the client.
class FakeBudgetBackend {
  FakeBudgetBackend({
    List<FakeBudget>? budgets,
    List<String>? categories,
    this.operatorId = financeTestOwnerId,
  }) : budgets = budgets ?? [],
       categories = categories ?? [] {
    transport = FakeAuthTransport(_handle);
  }

  List<FakeBudget> budgets;
  List<String> categories;
  final String operatorId;

  /// Realized amount per `budgetId` then `categoryId|effect` (positive text).
  final Map<String, Map<String, String>> realized = {};

  /// Coverage per `budgetId` (counts and decimal text).
  final Map<
    String,
    ({int expense, String expenseAmount, int income, String incomeAmount})
  >
  coverage = {};

  late final FakeAuthTransport transport;

  // --- failures / gates ---
  int? categoriesStatus;
  int? listStatus;
  bool listThrows = false;
  String? listBodyOverride;
  Completer<void>? listGate;
  int? failNextListsStatus;
  int failNextLists = 0;
  int? summaryStatus;
  bool summaryThrows = false;
  String? summaryBodyOverride;
  Completer<void>? summaryGate;
  int? postStatus;
  bool postThrows = false;

  /// Commit the write, then answer 503 (an ambiguous outcome).
  bool postCommitsThenFails = false;
  String? postBodyOverride;
  Completer<void>? postGate;
  int? putStatus;
  bool putThrows = false;
  bool putCommitsThenFails = false;
  String? putBodyOverride;
  Completer<void>? putGate;

  /// Runs inside every write, before it is decided (a concurrent writer).
  void Function()? beforePut;

  final List<Map<String, dynamic>> postBodies = [];
  final List<Map<String, dynamic>> putBodies = [];
  final Map<String, String> _idempotency = {};

  List<AuthTransportCall> get calls => transport.calls;

  int count(AuthHttpMethod method, String pathPrefix) => calls
      .where(
        (call) => call.method == method && call.uri.path.startsWith(pathPrefix),
      )
      .length;

  int get posts => count(AuthHttpMethod.post, '/api/v1/finance/budgets');
  int get puts => count(AuthHttpMethod.put, '/api/v1/finance/budgets');
  int get listReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            call.uri.path == '/api/v1/finance/budgets',
      )
      .length;
  int get summaryReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            call.uri.path.endsWith('/summary'),
      )
      .length;

  /// Every request that is not categories, the month list or one summary read.
  int get perLineRequests => calls.where((call) {
    final path = call.uri.path;
    return !(path == '/api/v1/finance/categories' ||
        path == '/api/v1/finance/budgets' ||
        path.endsWith('/summary') ||
        call.method != AuthHttpMethod.get);
  }).length;

  FakeBudget? byId(String id) {
    for (final budget in budgets) {
      if (budget.id == id) return budget;
    }
    return null;
  }

  // --- JSON ---

  String _money(String amount, String currency) =>
      '{"amount":"$amount","currency":"$currency"}';

  String budgetJson(FakeBudget budget) {
    final lines = budget.lines
        .map(
          (line) =>
              '{"categoryId":"${line.categoryId}","resultEffect":"${line.effect}",'
              '"planned":${_money(line.planned, budget.currency)}}',
        )
        .join(',');
    final year = int.parse(budget.period.substring(0, 4));
    final month = int.parse(budget.period.substring(5, 7));
    final end = month == 12
        ? '${(year + 1).toString().padLeft(4, '0')}-01-01'
        : '${budget.period.substring(0, 5)}${(month + 1).toString().padLeft(2, '0')}-01';
    return '{"id":"${budget.id}","ownerOperatorId":"${budget.owner}",'
        '"visibilityScope":"${budget.scope}","name":"${budget.name}",'
        '"currency":"${budget.currency}","periodKind":"MONTHLY",'
        '"periodStart":"${budget.period}-01","periodEnd":"$end",'
        '"dateBasis":"${budget.basis}","version":${budget.version},'
        '"createdAt":"2026-09-01T12:00:00Z","updatedAt":"2026-09-01T12:00:00Z",'
        '"canEdit":${budget.owner == operatorId},"lines":[$lines]}';
  }

  String summaryJson(FakeBudget budget) {
    final amounts = realized[budget.id] ?? const <String, String>{};
    final lines = budget.lines
        .map((line) {
          final planned = _scaled(line.planned);
          final done = _scaled(amounts[line.key] ?? '0');
          final status = done < planned
              ? 'UNDER'
              : done == planned
              ? 'AT'
              : 'OVER';
          return '{"categoryId":"${line.categoryId}","resultEffect":"${line.effect}",'
              '"planned":${_money(line.planned, budget.currency)},'
              '"realized":${_money(_canonical(done), budget.currency)},'
              '"remaining":${_money(_canonical(planned - done), budget.currency)},'
              '"status":"$status","progressPercent":"${_percent(planned, done)}"}';
        })
        .join(',');
    final cover = coverage[budget.id];
    return '{"budget":${budgetJson(budget)},"lines":[$lines],"coverage":'
        '{"unclassifiedExpenseCount":${cover?.expense ?? 0},'
        '"unclassifiedExpenseAmount":${_money(cover?.expenseAmount ?? '0', budget.currency)},'
        '"unclassifiedIncomeCount":${cover?.income ?? 0},'
        '"unclassifiedIncomeAmount":${_money(cover?.incomeAmount ?? '0', budget.currency)}}}';
  }

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
      if (path == '/api/v1/finance/categories') {
        final status = categoriesStatus;
        if (status != null) {
          return AuthHttpResponse(statusCode: status, body: '{}');
        }
        return AuthHttpResponse(
          statusCode: 200,
          body: '{"categories":[${categories.join(',')}]}',
        );
      }
      if (path == '/api/v1/finance/budgets') return _list(uri);
      final summary = RegExp(
        r'^/api/v1/finance/budgets/([^/]+)/summary$',
      ).firstMatch(path);
      if (summary != null) return _summary(summary.group(1)!);
      final one = RegExp(r'^/api/v1/finance/budgets/([^/]+)$').firstMatch(path);
      if (one != null) {
        final budget = byId(one.group(1)!);
        return budget == null
            ? const AuthHttpResponse(statusCode: 404, body: '{}')
            : AuthHttpResponse(statusCode: 200, body: budgetJson(budget));
      }
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (method == AuthHttpMethod.post && path == '/api/v1/finance/budgets') {
      return _post(jsonDecode(body!) as Map<String, dynamic>);
    }
    final put = RegExp(r'^/api/v1/finance/budgets/([^/]+)$').firstMatch(path);
    if (method == AuthHttpMethod.put && put != null) {
      return _put(put.group(1)!, jsonDecode(body!) as Map<String, dynamic>);
    }
    return const AuthHttpResponse(statusCode: 405, body: '{}');
  }

  Future<AuthHttpResponse> _list(Uri uri) async {
    final gate = listGate;
    if (gate != null) await gate.future;
    if (listThrows) throw const FormatException('simulated transport');
    if (failNextLists > 0) {
      failNextLists -= 1;
      return AuthHttpResponse(
        statusCode: failNextListsStatus ?? 503,
        body: '{}',
      );
    }
    final status = listStatus;
    if (status != null) {
      return AuthHttpResponse(statusCode: status, body: '{}');
    }
    final override = listBodyOverride;
    if (override != null) {
      return AuthHttpResponse(statusCode: 200, body: override);
    }
    final period = uri.queryParameters['period'];
    final items = budgets.where((budget) => budget.period == period);
    return AuthHttpResponse(
      statusCode: 200,
      body: '{"items":[${items.map(budgetJson).join(',')}]}',
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
    final budget = byId(id);
    return budget == null
        ? const AuthHttpResponse(statusCode: 404, body: '{}')
        : AuthHttpResponse(statusCode: 200, body: summaryJson(budget));
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
        body: budgetJson(byId(parts.last)!),
      );
    }
    final clash = budgets.any(
      (budget) =>
          budget.period == body['period'] &&
          budget.scope == body['visibilityScope'] &&
          budget.currency == body['currency'] &&
          budget.basis == body['dateBasis'],
    );
    if (clash) return const AuthHttpResponse(statusCode: 409, body: '{}');
    final created = FakeBudget(
      index: 900 + budgets.length,
      period: body['period'] as String,
      scope: body['visibilityScope'] as String,
      owner: operatorId,
      name: body['name'] as String,
      currency: body['currency'] as String,
      basis: body['dateBasis'] as String,
      lines: [
        for (final line in body['lines'] as List<dynamic>)
          FakeBudgetLine(
            (line as Map<String, dynamic>)['categoryId'] as String,
            line['resultEffect'] as String,
            _canonical(_scaled(line['plannedAmount'] as String)),
          ),
      ],
    );
    budgets.add(created);
    _idempotency[key] = '$material|${created.id}';
    if (postCommitsThenFails) {
      return const AuthHttpResponse(statusCode: 503, body: '{}');
    }
    final override = postBodyOverride;
    return AuthHttpResponse(
      statusCode: 201,
      body: override ?? budgetJson(created),
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
    final budget = byId(id);
    if (budget == null) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (budget.owner != operatorId) {
      return const AuthHttpResponse(statusCode: 403, body: '{}');
    }
    if (budget.version != body['expectedVersion']) {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    budget
      ..version += 1
      ..name = body['name'] as String
      ..lines = [
        for (final line in body['lines'] as List<dynamic>)
          FakeBudgetLine(
            (line as Map<String, dynamic>)['categoryId'] as String,
            line['resultEffect'] as String,
            _canonical(_scaled(line['plannedAmount'] as String)),
          ),
      ];
    if (putCommitsThenFails) {
      return const AuthHttpResponse(statusCode: 503, body: '{}');
    }
    return AuthHttpResponse(
      statusCode: 200,
      body: putBodyOverride ?? budgetJson(budget),
    );
  }
}

List<Override> budgetTestOverrides(
  FakeBudgetBackend backend, {
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
  financialBudgetClockProvider.overrideWithValue(
    () => now ?? DateTime(2026, 10, 15),
  ),
];

ProviderContainer budgetTestContainer(
  FakeBudgetBackend backend, {
  String operatorId = financeTestOwnerId,
  DateTime? now,
}) => ProviderContainer(
  overrides: budgetTestOverrides(backend, operatorId: operatorId, now: now),
);
