import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart' show Override;
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_controller.dart';

import 'fake_auth_transport.dart';
import 'fake_finance_backend.dart';

String recurrenceTestId(int index) =>
    'd4000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

String occurrenceTestId(int index) =>
    'd5000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

String suggestionTestMovementId(int suggestion, int evidence) =>
    'd7000000-0000-4000-8000-${(suggestion * 100 + evidence).toString().padLeft(12, '0')}';

String recurrenceTestAccountId(int index) =>
    'd3000000-0000-4000-8000-${index.toString().padLeft(12, '0')}';

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

String _canonicalText(String amount) => _canonical(_scaled(amount));

/// The monthly calendar the *server* applies. The client never does.
String _scheduledDate(String period, int day) {
  final year = int.parse(period.substring(0, 4));
  final month = int.parse(period.substring(5, 7));
  final last = DateTime.utc(year, month + 1, 0).day;
  final clamped = day > last ? last : day;
  return '$period-${clamped.toString().padLeft(2, '0')}';
}

String _nextPeriod(String period) {
  final year = int.parse(period.substring(0, 4));
  final month = int.parse(period.substring(5, 7));
  final index = year * 12 + month;
  final shiftedYear = index ~/ 12;
  final shiftedMonth = index % 12 + 1;
  return '${shiftedYear.toString().padLeft(4, '0')}-${shiftedMonth.toString().padLeft(2, '0')}';
}

class FakeAccount {
  FakeAccount({
    required this.id,
    this.owner = financeTestOwnerId,
    this.name = 'Conta Corrente',
    this.currency = 'BRL',
    this.status = 'ACTIVE',
    this.scope = 'HOUSEHOLD',
  });

  final String id;
  String owner;
  String name;
  String currency;
  String status;
  String scope;
}

class FakeRule {
  FakeRule({
    required this.index,
    required this.accountId,
    this.owner = financeTestOwnerId,
    this.description = 'Internet',
    this.effect = 'EXPENSE',
    this.expected = '120',
    this.currency = 'BRL',
    this.startDate = '2026-01-10',
    this.dayOfMonth = 10,
    this.endDate,
    this.status = 'ACTIVE',
    this.version = 1,
  });

  final int index;
  String accountId;
  String owner;
  String description;
  String effect;
  String expected;
  String currency;
  String startDate;
  int dayOfMonth;
  String? endDate;
  String status;
  int version;

  String get id => recurrenceTestId(index);
}

class FakeOccurrence {
  FakeOccurrence({
    required this.index,
    required this.rule,
    required this.period,
    this.status = 'PENDING',
  }) : scheduledDate = _scheduledDate(period, rule.dayOfMonth),
       ruleVersion = rule.version,
       expected = rule.expected,
       description = rule.description;

  final int index;
  final FakeRule rule;
  final String period;
  final String scheduledDate;
  final int ruleVersion;
  final String expected;
  final String description;
  String status;

  String? movementId;
  String? actual;
  String? effectiveDate;
  String? competenceDate;
  bool reversed = false;
  String? realizeKey;
  String? realizeMaterial;

  String get id => occurrenceTestId(index);
}

String suggestionTestFingerprint(int index) =>
    index.toRadixString(16).padLeft(64, '0');

class FakeSuggestionEvidence {
  const FakeSuggestionEvidence(this.date, this.amount);

  final String date;
  final String amount;
}

/// One monthly pattern the fake *server* derived. The client never detects one.
class FakeSuggestion {
  FakeSuggestion({
    required this.index,
    required this.accountId,
    this.owner = financeTestOwnerId,
    this.description = 'Streaming',
    this.currency = 'BRL',
    this.day = 10,
    List<FakeSuggestionEvidence>? evidence,
  }) : evidence =
           evidence ??
           const [
             FakeSuggestionEvidence('2026-08-10', '39.9'),
             FakeSuggestionEvidence('2026-09-10', '39.9'),
             FakeSuggestionEvidence('2026-10-10', '39.9'),
           ];

  final int index;
  String accountId;
  String owner;
  String description;
  String currency;
  int day;
  List<FakeSuggestionEvidence> evidence;

  /// OPEN | DISMISSED | ACCEPTED. Only OPEN is listed.
  String status = 'OPEN';
  String? acceptKey;
  String? acceptMaterial;
  String? ruleId;

  String get fingerprint => suggestionTestFingerprint(index);

  bool get variable =>
      evidence.map((e) => _canonicalText(e.amount)).toSet().length > 1;
}

class FakeLedgerEntry {
  FakeLedgerEntry(this.movementId, this.accountId, this.amount);

  final String movementId;
  final String accountId;
  final String amount;
}

/// In-memory recurrence API (the server's side of the contract) for controller and
/// widget tests. Every request goes through [FakeAuthTransport], so tests count
/// exactly what was called. It plays the server: it owns the rules, the CAS
/// version, the monthly calendar, the generation, the registration and the
/// ledger, and the client never decides any of that.
class FakeRecurrenceBackend {
  FakeRecurrenceBackend({
    List<FakeAccount>? accounts,
    List<FakeRule>? rules,
    this.operatorId = financeTestOwnerId,
    this.today = '2026-10-06',
  }) : accounts = accounts ?? [FakeAccount(id: recurrenceTestAccountId(1))],
       rules = rules ?? [] {
    transport = FakeAuthTransport(_handle);
  }

  List<FakeAccount> accounts;
  List<FakeRule> rules;
  final List<FakeOccurrence> occurrences = [];
  final List<FakeLedgerEntry> ledger = [];
  final List<FakeSuggestion> suggestions = [];
  final String operatorId;

  /// The server's own "today" (the clock lives on the server).
  final String today;
  int _nextOccurrence = 1000;
  int _nextRule = 900;
  int _nextMovement = 5000;
  final Map<String, String> _createKeys = {};
  final Map<String, String> _realizeKeys = {};
  final Map<String, String> _acceptKeys = {};

  // --- failures / gates ---
  int? accountsStatus;
  int? listStatus;
  bool listThrows = false;
  String? listBodyOverride;
  Completer<void>? listGate;
  int? suggestionsStatus;
  bool suggestionsThrows = false;
  String? suggestionsBodyOverride;
  int? occurrencesStatus;
  bool occurrencesThrows = false;
  String? occurrencesBodyOverride;
  int? writeStatus;
  bool writeThrows = false;
  Completer<void>? writeGate;

  /// Commit the write, then answer 503 (an ambiguous outcome).
  bool writeCommitsThenFails = false;
  String? writeBodyOverride;

  /// Runs inside every write before it is decided (a concurrent writer).
  void Function()? beforeWrite;

  final List<Map<String, dynamic>> writeBodies = [];

  List<AuthTransportCall> get calls => transport.calls;
  late final FakeAuthTransport transport;

  int writes(AuthHttpMethod method, [String? contains]) => calls
      .where(
        (call) =>
            call.method == method &&
            (contains == null || call.uri.path.contains(contains)),
      )
      .length;

  int get realizeCalls =>
      calls.where((call) => call.uri.path.endsWith('/realize')).length;
  int get generateCalls =>
      calls.where((call) => call.uri.path.endsWith('/generate')).length;
  int get skipCalls =>
      calls.where((call) => call.uri.path.endsWith('/skip')).length;
  int get listReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            call.uri.path == '/api/v1/finance/recurrences',
      )
      .length;
  int get suggestionReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            call.uri.path == '/api/v1/finance/recurrence-suggestions',
      )
      .length;
  int get acceptCalls => calls
      .where(
        (call) =>
            call.uri.path.startsWith(
              '/api/v1/finance/recurrence-suggestions/',
            ) &&
            call.uri.path.endsWith('/accept'),
      )
      .length;
  int get dismissCalls => calls
      .where(
        (call) =>
            call.uri.path.startsWith(
              '/api/v1/finance/recurrence-suggestions/',
            ) &&
            call.uri.path.endsWith('/dismiss'),
      )
      .length;
  int get occurrenceReads => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.get &&
            call.uri.path == '/api/v1/finance/recurrence-occurrences',
      )
      .length;

  /// Every write request (POST/PUT) the client sent.
  int get totalWrites => calls
      .where(
        (call) =>
            call.method == AuthHttpMethod.post ||
            call.method == AuthHttpMethod.put,
      )
      .length;

  FakeRule? ruleById(String id) {
    for (final rule in rules) {
      if (rule.id == id) return rule;
    }
    return null;
  }

  FakeOccurrence? occurrenceById(String id) {
    for (final occurrence in occurrences) {
      if (occurrence.id == id) return occurrence;
    }
    return null;
  }

  FakeSuggestion? suggestionByFingerprint(String fingerprint) {
    for (final suggestion in suggestions) {
      if (suggestion.fingerprint == fingerprint) return suggestion;
    }
    return null;
  }

  FakeAccount? accountById(String id) {
    for (final account in accounts) {
      if (account.id == id) return account;
    }
    return null;
  }

  /// The ledger's balance of an account (opening 1000 + Movements). Only a
  /// registration moves it; a forecast, a skip or a rule never does.
  String balanceOf(String accountId) {
    var total = _scaled('1000');
    for (final entry in ledger.where((e) => e.accountId == accountId)) {
      total += _scaled(entry.amount);
    }
    return _canonical(total);
  }

  /// Plays an external reversal of the Movement behind an occurrence.
  void reverseMovementOf(String occurrenceId) {
    final occurrence = occurrenceById(occurrenceId)!;
    occurrence.reversed = true;
    ledger.add(
      FakeLedgerEntry(
        'reversal-${occurrence.movementId}',
        occurrence.rule.accountId,
        _canonical(-_scaled(ledger.last.amount)),
      ),
    );
  }

  FakeOccurrence addOccurrence(FakeRule rule, String period) {
    final occurrence = FakeOccurrence(
      index: _nextOccurrence++,
      rule: rule,
      period: period,
    );
    occurrences.add(occurrence);
    return occurrence;
  }

  // --- JSON ---

  String _money(String amount, String currency) =>
      '{"amount":"$amount","currency":"$currency"}';

  String accountJson(FakeAccount account) =>
      '{"accountId":"${account.id}","ownerOperatorId":"${account.owner}",'
      '"visibilityScope":"${account.scope}","accountType":"CHECKING",'
      '"customTypeName":null,"name":"${account.name}","currency":"${account.currency}",'
      '"status":"${account.status}","createdAt":"2026-09-01T12:00:00Z",'
      '"updatedAt":"2026-09-01T12:00:00Z",'
      '"archivedAt":${account.status == 'ARCHIVED' ? '"2026-09-02T12:00:00Z"' : 'null'}}';

  String _ruleFields(FakeRule rule) =>
      '"id":"${rule.id}","accountId":"${rule.accountId}",'
      '"ownerOperatorId":"${rule.owner}","description":"${rule.description}",'
      '"resultEffect":"${rule.effect}","expected":${_money(rule.expected, rule.currency)},'
      '"frequency":"MONTHLY","startDate":"${rule.startDate}",'
      '"dayOfMonth":${rule.dayOfMonth},'
      '"endDate":${rule.endDate == null ? 'null' : '"${rule.endDate}"'},'
      '"status":"${rule.status}","version":${rule.version},'
      '"createdAt":"2026-09-01T12:00:00Z","updatedAt":"2026-09-01T12:00:00Z",'
      '"canEdit":${rule.owner == operatorId}';

  String ruleJson(FakeRule rule) => '{${_ruleFields(rule)}}';

  String occurrenceJson(FakeOccurrence occurrence) {
    final rule = occurrence.rule;
    final realization = occurrence.status == 'REALIZED'
        ? '{"movementId":"${occurrence.movementId}",'
              '"actual":${_money(occurrence.actual!, rule.currency)},'
              '"effectiveDate":"${occurrence.effectiveDate}",'
              '"competenceDate":"${occurrence.competenceDate}",'
              '"realizedAt":"2026-10-06T12:00:00Z",'
              '"movementState":"${occurrence.reversed ? 'REVERSED' : 'ACTIVE'}"}'
        : 'null';
    return '{"id":"${occurrence.id}","recurrenceId":"${rule.id}",'
        '"accountId":"${rule.accountId}","ownerOperatorId":"${rule.owner}",'
        '"periodStart":"${occurrence.period}-01",'
        '"scheduledDate":"${occurrence.scheduledDate}",'
        '"ruleVersion":${occurrence.ruleVersion},"resultEffect":"${rule.effect}",'
        '"expected":${_money(occurrence.expected, rule.currency)},'
        '"description":"${occurrence.description}","status":"${occurrence.status}",'
        '"createdAt":"2026-10-01T12:00:00Z","updatedAt":"2026-10-01T12:00:00Z",'
        '"canEdit":${rule.owner == operatorId},"realization":$realization}';
  }

  String suggestionJson(FakeSuggestion item) {
    final amounts = item.evidence.map((e) => _scaled(e.amount)).toList();
    var minimum = amounts.first;
    var maximum = amounts.first;
    for (final value in amounts) {
      if (value < minimum) minimum = value;
      if (value > maximum) maximum = value;
    }
    final last = item.evidence.last.amount;
    final evidence = [
      for (var i = 0; i < item.evidence.length; i += 1)
        '{"movementId":"${suggestionTestMovementId(item.index, i)}",'
            '"effectiveDate":"${item.evidence[i].date}",'
            '"amount":${_money(_canonicalText(item.evidence[i].amount), item.currency)}}',
    ];
    final reasons = [
      '"EXACT_DESCRIPTION"',
      '"CONSECUTIVE_MONTHS"',
      '"ONE_PER_MONTH"',
      '"DAY_WINDOW"',
      item.variable ? '"AMOUNT_VARIABLE"' : '"AMOUNT_FIXED"',
    ];
    return '{"fingerprint":"${item.fingerprint}","accountId":"${item.accountId}",'
        '"description":"${item.description}",'
        '"normalizedDescription":"${item.description.toLowerCase()}",'
        '"currency":"${item.currency}","evidence":[${evidence.join(',')}],'
        '"movementIds":[${[for (var i = 0; i < item.evidence.length; i += 1) '"${suggestionTestMovementId(item.index, i)}"'].join(',')}],'
        '"observedDates":[${item.evidence.map((e) => '"${e.date}"').join(',')}],'
        '"observedAmounts":[${item.evidence.map((e) => _money(_canonicalText(e.amount), item.currency)).join(',')}],'
        '"suggestedDayOfMonth":${item.day},'
        '"suggestedExpectedAmount":${_money(_canonicalText(last), item.currency)},'
        '"amountBehavior":"${item.variable ? 'VARIABLE' : 'FIXED'}",'
        '"minAmount":${_money(_canonical(minimum), item.currency)},'
        '"maxAmount":${_money(_canonical(maximum), item.currency)},'
        '"lastAmount":${_money(_canonicalText(last), item.currency)},'
        '"reasonCodes":[${reasons.join(',')}],'
        '"canAccept":${item.owner == operatorId}}';
  }

  String decisionJson(
    FakeSuggestion item, {
    required bool accepted,
    required bool created,
  }) =>
      '{"fingerprint":"${item.fingerprint}","accountId":"${item.accountId}",'
      '"decision":"${accepted ? 'ACCEPTED' : 'DISMISSED'}",'
      '"recurrenceId":${accepted ? '"${item.ruleId}"' : 'null'},'
      '"decidedAt":"2026-10-06T12:00:00Z","created":$created}';

  // --- routing ---

  static const _base = '/api/v1/finance';

  Future<AuthHttpResponse> _handle(
    Uri uri,
    AuthHttpMethod method,
    Duration timeout,
    Map<String, String> headers,
    String? body,
  ) async {
    final path = uri.path;
    if (method == AuthHttpMethod.get) {
      if (path == '$_base/accounts') return _accounts();
      if (path == '$_base/recurrences') return _list();
      if (path == '$_base/recurrence-occurrences') return _occurrences(uri);
      if (path == '$_base/recurrence-suggestions') return _suggestions();
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    final decoded = body == null
        ? <String, dynamic>{}
        : jsonDecode(body) as Map<String, dynamic>;
    if (method == AuthHttpMethod.post && path == '$_base/recurrences') {
      return _write(() => _create(decoded), decoded);
    }
    final suggestion = RegExp(
      r'^/api/v1/finance/recurrence-suggestions/([^/]+)/(dismiss|accept)$',
    ).firstMatch(path);
    if (method == AuthHttpMethod.post && suggestion != null) {
      final fingerprint = suggestion.group(1)!;
      return suggestion.group(2) == 'dismiss'
          ? _write(() => _dismissSuggestion(fingerprint), decoded)
          : _write(() => _acceptSuggestion(fingerprint, decoded), decoded);
    }
    final put = RegExp(
      r'^/api/v1/finance/recurrences/([^/]+)$',
    ).firstMatch(path);
    if (method == AuthHttpMethod.put && put != null) {
      return _write(() => _replace(put.group(1)!, decoded), decoded);
    }
    final action = RegExp(
      r'^/api/v1/finance/recurrences/([^/]+)/(pause|resume)$',
    ).firstMatch(path);
    if (method == AuthHttpMethod.post && action != null) {
      return _write(
        () => _setStatus(action.group(1)!, action.group(2)!),
        decoded,
      );
    }
    final generate = RegExp(
      r'^/api/v1/finance/recurrences/([^/]+)/occurrences/generate$',
    ).firstMatch(path);
    if (method == AuthHttpMethod.post && generate != null) {
      return _write(() => _generate(generate.group(1)!, decoded), decoded);
    }
    final skip = RegExp(
      r'^/api/v1/finance/recurrence-occurrences/([^/]+)/skip$',
    ).firstMatch(path);
    if (method == AuthHttpMethod.post && skip != null) {
      return _write(() => _skip(skip.group(1)!), decoded);
    }
    final realize = RegExp(
      r'^/api/v1/finance/recurrence-occurrences/([^/]+)/realize$',
    ).firstMatch(path);
    if (method == AuthHttpMethod.post && realize != null) {
      return _write(() => _realize(realize.group(1)!, decoded), decoded);
    }
    return const AuthHttpResponse(statusCode: 405, body: '{}');
  }

  Future<AuthHttpResponse> _accounts() async {
    final status = accountsStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    return AuthHttpResponse(
      statusCode: 200,
      body: '{"accounts":[${accounts.map(accountJson).join(',')}]}',
    );
  }

  Future<AuthHttpResponse> _list() async {
    final gate = listGate;
    if (gate != null) await gate.future;
    if (listThrows) throw const FormatException('simulated transport');
    final status = listStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    final override = listBodyOverride;
    if (override != null) {
      return AuthHttpResponse(statusCode: 200, body: override);
    }
    return AuthHttpResponse(
      statusCode: 200,
      body: '{"items":[${rules.map(ruleJson).join(',')}]}',
    );
  }

  Future<AuthHttpResponse> _suggestions() async {
    if (suggestionsThrows) throw const FormatException('simulated transport');
    final status = suggestionsStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    final override = suggestionsBodyOverride;
    if (override != null) {
      return AuthHttpResponse(statusCode: 200, body: override);
    }
    final open = suggestions.where((item) => item.status == 'OPEN');
    return AuthHttpResponse(
      statusCode: 200,
      body:
          '{"windowFrom":"2025-11-01","windowThrough":"$today",'
          '"items":[${open.map(suggestionJson).join(',')}]}',
    );
  }

  AuthHttpResponse _dismissSuggestion(String fingerprint) {
    final item = suggestionByFingerprint(fingerprint);
    if (item == null || item.status == 'ACCEPTED') {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    final created = item.status == 'OPEN';
    item.status = 'DISMISSED';
    return AuthHttpResponse(
      statusCode: 200,
      body: decisionJson(item, accepted: false, created: created),
    );
  }

  AuthHttpResponse _acceptSuggestion(
    String fingerprint,
    Map<String, dynamic> body,
  ) {
    final item = suggestionByFingerprint(fingerprint);
    final key = body['idempotencyKey'] as String;
    final material = jsonEncode({...body}..remove('idempotencyKey'));
    if (item != null && item.acceptKey == key) {
      if (item.acceptMaterial != material) {
        return const AuthHttpResponse(statusCode: 409, body: '{}');
      }
      return AuthHttpResponse(
        statusCode: 201,
        body:
            '{"recurrence":${ruleJson(ruleById(item.ruleId!)!)},'
            '"decision":${decisionJson(item, accepted: true, created: false)}}',
      );
    }
    if (item == null || item.status != 'OPEN') {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    if (item.owner != operatorId) {
      return const AuthHttpResponse(statusCode: 403, body: '{}');
    }
    final rule = FakeRule(
      index: _nextRule++,
      accountId: item.accountId,
      owner: operatorId,
      description: body['description'] as String,
      effect: 'EXPENSE',
      expected: _canonicalText(body['expectedAmount'] as String),
      currency: item.currency,
      startDate: body['startDate'] as String,
      dayOfMonth: body['dayOfMonth'] as int,
      endDate: body['endDate'] as String?,
    );
    rules.add(rule);
    item
      ..status = 'ACCEPTED'
      ..acceptKey = key
      ..acceptMaterial = material
      ..ruleId = rule.id;
    _acceptKeys[key] = rule.id;
    return AuthHttpResponse(
      statusCode: 201,
      body:
          '{"recurrence":${ruleJson(rule)},'
          '"decision":${decisionJson(item, accepted: true, created: true)}}',
    );
  }

  Future<AuthHttpResponse> _occurrences(Uri uri) async {
    if (occurrencesThrows) throw const FormatException('simulated transport');
    final status = occurrencesStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    final override = occurrencesBodyOverride;
    if (override != null) {
      return AuthHttpResponse(statusCode: 200, body: override);
    }
    final from = uri.queryParameters['fromPeriod']!;
    final through = uri.queryParameters['throughPeriod']!;
    final items = occurrences.where(
      (o) =>
          o.status != 'SUPERSEDED' &&
          o.period.compareTo(from) >= 0 &&
          o.period.compareTo(through) <= 0,
    );
    return AuthHttpResponse(
      statusCode: 200,
      body: '{"items":[${items.map(occurrenceJson).join(',')}]}',
    );
  }

  Future<AuthHttpResponse> _write(
    AuthHttpResponse Function() action,
    Map<String, dynamic> body,
  ) async {
    writeBodies.add(body);
    final gate = writeGate;
    if (gate != null) await gate.future;
    beforeWrite?.call();
    if (writeThrows) throw const FormatException('simulated transport');
    final status = writeStatus;
    if (status != null) return AuthHttpResponse(statusCode: status, body: '{}');
    final response = action();
    if (writeCommitsThenFails && response.statusCode < 300) {
      return const AuthHttpResponse(statusCode: 503, body: '{}');
    }
    final override = writeBodyOverride;
    if (override != null && response.statusCode < 300) {
      return AuthHttpResponse(statusCode: response.statusCode, body: override);
    }
    return response;
  }

  AuthHttpResponse _create(Map<String, dynamic> body) {
    final key = body['idempotencyKey'] as String;
    final material = jsonEncode({...body}..remove('idempotencyKey'));
    final known = _createKeys[key];
    if (known != null) {
      final parts = known.split('|');
      if (parts.first != material) {
        return const AuthHttpResponse(statusCode: 409, body: '{}');
      }
      return AuthHttpResponse(
        statusCode: 201,
        body: ruleJson(ruleById(parts.last)!),
      );
    }
    final account = accountById(body['accountId'] as String);
    if (account == null ||
        account.owner != operatorId ||
        account.status != 'ACTIVE' ||
        account.currency != body['currency']) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    final rule = FakeRule(
      index: _nextRule++,
      accountId: account.id,
      owner: operatorId,
      description: body['description'] as String,
      effect: body['resultEffect'] as String,
      expected: _canonicalText(body['expectedAmount'] as String),
      currency: body['currency'] as String,
      startDate: body['startDate'] as String,
      dayOfMonth: body['dayOfMonth'] as int,
      endDate: body['endDate'] as String?,
    );
    rules.add(rule);
    _createKeys[key] = '$material|${rule.id}';
    return AuthHttpResponse(statusCode: 201, body: ruleJson(rule));
  }

  AuthHttpResponse _replace(String id, Map<String, dynamic> body) {
    final rule = ruleById(id);
    if (rule == null) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (rule.owner != operatorId) {
      return const AuthHttpResponse(statusCode: 403, body: '{}');
    }
    if (rule.version != body['expectedVersion']) {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    final amount = _canonicalText(body['expectedAmount'] as String);
    final day = body['dayOfMonth'] as int;
    final end = body['endDate'] as String?;
    final description = body['description'] as String;
    final changed =
        rule.description != description ||
        rule.expected != amount ||
        rule.dayOfMonth != day ||
        rule.endDate != end;
    var superseded = 0;
    if (changed) {
      rule
        ..description = description
        ..expected = amount
        ..dayOfMonth = day
        ..endDate = end
        ..version += 1;
      for (final occurrence in occurrences.where(
        (o) =>
            o.rule == rule &&
            o.status == 'PENDING' &&
            o.scheduledDate.compareTo(today) >= 0,
      )) {
        final stale =
            occurrence.description != description ||
            occurrence.expected != amount ||
            occurrence.scheduledDate !=
                _scheduledDate(occurrence.period, day) ||
            (end != null && occurrence.scheduledDate.compareTo(end) > 0);
        if (stale) {
          occurrence.status = 'SUPERSEDED';
          superseded += 1;
        }
      }
    }
    return AuthHttpResponse(
      statusCode: 200,
      body: '{${_ruleFields(rule)},"supersededCount":$superseded}',
    );
  }

  AuthHttpResponse _setStatus(String id, String action) {
    final rule = ruleById(id);
    if (rule == null) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (rule.owner != operatorId) {
      return const AuthHttpResponse(statusCode: 403, body: '{}');
    }
    final target = action == 'pause' ? 'PAUSED' : 'ACTIVE';
    if (rule.status != target) {
      rule
        ..status = target
        ..version += 1;
    }
    return AuthHttpResponse(statusCode: 200, body: ruleJson(rule));
  }

  AuthHttpResponse _generate(String id, Map<String, dynamic> body) {
    final rule = ruleById(id);
    if (rule == null) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (rule.owner != operatorId) {
      return const AuthHttpResponse(statusCode: 403, body: '{}');
    }
    if (rule.status != 'ACTIVE') {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    final from = body['fromPeriod'] as String;
    final through = body['throughPeriod'] as String;
    var created = 0;
    var period = from;
    final window = <FakeOccurrence>[];
    while (period.compareTo(through) <= 0) {
      final scheduled = _scheduledDate(period, rule.dayOfMonth);
      final due =
          scheduled.compareTo(rule.startDate) >= 0 &&
          (rule.endDate == null || scheduled.compareTo(rule.endDate!) <= 0);
      if (due) {
        final live = occurrences
            .where(
              (o) =>
                  o.rule == rule &&
                  o.period == period &&
                  o.status != 'SUPERSEDED',
            )
            .firstOrNull;
        if (live == null) {
          window.add(addOccurrence(rule, period));
          created += 1;
        } else {
          window.add(live);
        }
      }
      period = _nextPeriod(period);
    }
    return AuthHttpResponse(
      statusCode: 200,
      body:
          '{"createdCount":$created,"items":[${window.map(occurrenceJson).join(',')}]}',
    );
  }

  AuthHttpResponse _skip(String id) {
    final occurrence = occurrenceById(id);
    if (occurrence == null) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    if (occurrence.rule.owner != operatorId) {
      return const AuthHttpResponse(statusCode: 403, body: '{}');
    }
    if (occurrence.status == 'PENDING') occurrence.status = 'SKIPPED';
    if (occurrence.status != 'SKIPPED') {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    return AuthHttpResponse(statusCode: 200, body: occurrenceJson(occurrence));
  }

  AuthHttpResponse _realize(String id, Map<String, dynamic> body) {
    final occurrence = occurrenceById(id);
    if (occurrence == null) {
      return const AuthHttpResponse(statusCode: 404, body: '{}');
    }
    final rule = occurrence.rule;
    if (rule.owner != operatorId) {
      return const AuthHttpResponse(statusCode: 403, body: '{}');
    }
    final key = body['idempotencyKey'] as String;
    final material = jsonEncode({
      'o': id,
      'a': _canonicalText(body['actualAmount'] as String),
      'c': body['currency'],
      'e': body['effectiveDate'],
      'k': body['competenceDate'],
    });
    if (occurrence.realizeKey == key) {
      if (occurrence.realizeMaterial != material) {
        return const AuthHttpResponse(statusCode: 409, body: '{}');
      }
      return AuthHttpResponse(
        statusCode: 200,
        body: occurrenceJson(occurrence),
      );
    }
    if (_realizeKeys.containsKey(key) || occurrence.status != 'PENDING') {
      return const AuthHttpResponse(statusCode: 409, body: '{}');
    }
    if (body['currency'] != rule.currency) {
      return const AuthHttpResponse(statusCode: 422, body: '{}');
    }
    final actual = _canonicalText(body['actualAmount'] as String);
    final movementId =
        'd6000000-0000-4000-8000-${(_nextMovement++).toString().padLeft(12, '0')}';
    final signed = rule.effect == 'EXPENSE' ? '-$actual' : actual;
    ledger.add(FakeLedgerEntry(movementId, rule.accountId, signed));
    occurrence
      ..status = 'REALIZED'
      ..movementId = movementId
      ..actual = actual
      ..effectiveDate = body['effectiveDate'] as String
      ..competenceDate = body['competenceDate'] as String
      ..realizeKey = key
      ..realizeMaterial = material;
    _realizeKeys[key] = id;
    return AuthHttpResponse(statusCode: 200, body: occurrenceJson(occurrence));
  }
}

List<Override> recurrenceTestOverrides(
  FakeRecurrenceBackend backend, {
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
  financialRecurrenceClockProvider.overrideWithValue(
    () => now ?? DateTime(2026, 10, 6),
  ),
];

ProviderContainer recurrenceTestContainer(
  FakeRecurrenceBackend backend, {
  String operatorId = financeTestOwnerId,
  DateTime? now,
}) => ProviderContainer(
  overrides: recurrenceTestOverrides(backend, operatorId: operatorId, now: now),
);
