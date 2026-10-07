import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_finance_backend.dart';
import '../../support/fake_recurrence_backend.dart';

final _account = recurrenceTestAccountId(1);

FinancialCoreApi _api(FakeAuthTransport transport) => FinancialCoreApi(
  AuthenticatedApiClient(
    transport: transport,
    tokenVault: SessionTokenVault()..store(financeTestToken),
    apiBaseUri: Uri.parse('http://localhost/api/v1/'),
    timeout: const Duration(seconds: 2),
    onUnauthorized: () {},
  ),
);

FakeRecurrenceBackend _backend() {
  final backend = FakeRecurrenceBackend();
  backend.rules.add(FakeRule(index: 1, accountId: _account));
  return backend;
}

FinancialRecurrenceCreateInput _create({
  String amount = '120',
  String? key,
  String? endDate,
}) => FinancialRecurrenceCreateInput(
  accountId: _account,
  description: 'Internet',
  resultEffect: FinancialResultEffect.expense,
  expectedAmount: amount,
  currency: 'BRL',
  startDate: '2026-01-10',
  dayOfMonth: 10,
  endDate: endDate,
  idempotencyKey: key,
);

FinancialRecurrenceRealizeInput _realize({String? key}) =>
    FinancialRecurrenceRealizeInput(
      actualAmount: '127.50',
      currency: 'BRL',
      effectiveDate: '2026-10-11',
      competenceDate: '2026-10-01',
      idempotencyKey: key,
    );

void main() {
  group('requests', () {
    test('listRecurrences is a plain GET and parses the rule', () async {
      final backend = _backend();
      final rules = await _api(backend.transport).listRecurrences();
      final call = backend.calls.single;
      expect(call.method, AuthHttpMethod.get);
      expect(call.uri.path, '/api/v1/finance/recurrences');
      expect(call.uri.queryParameters, isEmpty);
      final rule = rules.single;
      expect(rule.description, 'Internet');
      expect(rule.expected.amount, '120');
      expect(rule.dayOfMonth, 10);
      expect(rule.status, FinancialRecurrenceStatus.active);
      expect(rule.canEdit, isTrue);
      expect(rule.endDate, isNull);
    });

    test(
      'create posts the explicit contract with decimal text money',
      () async {
        final backend = FakeRecurrenceBackend();
        final created = await _api(
          backend.transport,
        ).createRecurrence(_create(amount: '120.50', endDate: '2026-12-31'));
        final call = backend.calls.single;
        expect(call.method, AuthHttpMethod.post);
        expect(call.uri.path, '/api/v1/finance/recurrences');
        final body = jsonDecode(call.body!) as Map<String, dynamic>;
        expect(body.keys.toSet(), {
          'idempotencyKey',
          'accountId',
          'description',
          'resultEffect',
          'expectedAmount',
          'currency',
          'startDate',
          'dayOfMonth',
          'endDate',
        });
        expect(body['expectedAmount'], '120.50');
        expect(body['dayOfMonth'], 10);
        expect(body['endDate'], '2026-12-31');
        expect(created.version, 1);
        expect(created.expected.amount, '120.5');
      },
    );

    test('a generated idempotency key is a UUID v4 and stable per input', () {
      final input = _create();
      expect(
        RegExp(
          r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ).hasMatch(input.idempotencyKey),
        isTrue,
      );
      expect(
        input.withIdempotencyKey(input.idempotencyKey).attemptKey,
        input.attemptKey,
      );
      expect(_create(amount: '121').attemptKey, isNot(input.attemptKey));
    });

    test('replace sends expectedVersion and the new mutable fields', () async {
      final backend = _backend();
      final result = await _api(backend.transport).replaceRecurrence(
        recurrenceTestId(1),
        FinancialRecurrenceReplaceInput(
          expectedVersion: 1,
          description: 'Internet fibra',
          expectedAmount: '135',
          dayOfMonth: 12,
        ),
      );
      final call = backend.calls.single;
      expect(call.method, AuthHttpMethod.put);
      final body = jsonDecode(call.body!) as Map<String, dynamic>;
      expect(body['expectedVersion'], 1);
      expect(body.containsKey('endDate'), isTrue);
      expect(body['endDate'], isNull);
      expect(result.recurrence.version, 2);
      expect(result.supersededCount, 0);
    });

    test('pause and resume are POSTs without a body', () async {
      final backend = _backend();
      final api = _api(backend.transport);
      final paused = await api.pauseRecurrence(recurrenceTestId(1));
      expect(paused.status, FinancialRecurrenceStatus.paused);
      final resumed = await api.resumeRecurrence(recurrenceTestId(1));
      expect(resumed.status, FinancialRecurrenceStatus.active);
      expect(backend.calls.map((call) => call.uri.path), [
        '/api/v1/finance/recurrences/${recurrenceTestId(1)}/pause',
        '/api/v1/finance/recurrences/${recurrenceTestId(1)}/resume',
      ]);
      expect(backend.calls.every((call) => call.body == null), isTrue);
    });

    test('generate sends exactly the explicit window', () async {
      final backend = _backend();
      final generation = await _api(backend.transport).generateOccurrences(
        recurrenceTestId(1),
        fromPeriod: '2026-10',
        throughPeriod: '2026-11',
      );
      final call = backend.calls.single;
      expect(call.uri.path, endsWith('/occurrences/generate'));
      expect(jsonDecode(call.body!), {
        'fromPeriod': '2026-10',
        'throughPeriod': '2026-11',
      });
      expect(generation.createdCount, 2);
      expect(generation.items, hasLength(2));
      expect(generation.items.first.status, FinancialOccurrenceStatus.pending);
      expect(generation.items.first.realization, isNull);
    });

    test('listOccurrences asks for one bounded window with GET', () async {
      final backend = _backend();
      backend.addOccurrence(backend.rules.single, '2026-10');
      final items = await _api(
        backend.transport,
      ).listOccurrences(fromPeriod: '2026-10', throughPeriod: '2026-10');
      final call = backend.calls.single;
      expect(call.method, AuthHttpMethod.get);
      expect(call.uri.queryParameters, {
        'fromPeriod': '2026-10',
        'throughPeriod': '2026-10',
      });
      expect(items.single.scheduledDate, '2026-10-10');
    });

    test('skip and realize post to the occurrence', () async {
      final backend = _backend();
      final first = backend.addOccurrence(backend.rules.single, '2026-10');
      final second = backend.addOccurrence(backend.rules.single, '2026-11');
      final api = _api(backend.transport);
      final skipped = await api.skipOccurrence(first.id);
      expect(skipped.status, FinancialOccurrenceStatus.skipped);
      final realized = await api.realizeOccurrence(second.id, _realize());
      expect(realized.status, FinancialOccurrenceStatus.realized);
      expect(realized.realization!.actual.amount, '127.5');
      expect(realized.realization!.effectiveDate, '2026-10-11');
      expect(
        realized.realization!.movementState,
        FinancialOccurrenceMovementState.active,
      );
      final body = jsonDecode(backend.calls.last.body!) as Map<String, dynamic>;
      expect(body.keys.toSet(), {
        'idempotencyKey',
        'actualAmount',
        'currency',
        'effectiveDate',
        'competenceDate',
      });
      expect(body['actualAmount'], '127.50');
    });
  });

  group('input validation (no request is sent)', () {
    test('rejects malformed rule input', () {
      for (final build in <FinancialRecurrenceCreateInput Function()>[
        () => FinancialRecurrenceCreateInput(
          accountId: _account,
          description: '   ',
          resultEffect: FinancialResultEffect.expense,
          expectedAmount: '1',
          currency: 'BRL',
          startDate: '2026-01-10',
          dayOfMonth: 10,
        ),
        () => FinancialRecurrenceCreateInput(
          accountId: _account,
          description: 'x',
          resultEffect: FinancialResultEffect.neutral,
          expectedAmount: '1',
          currency: 'BRL',
          startDate: '2026-01-10',
          dayOfMonth: 10,
        ),
        () => _create(amount: '0'),
        () => _create(amount: '-1'),
        () => _create(amount: '1,5'),
        () => _create(endDate: '2025-12-31'),
        () => FinancialRecurrenceCreateInput(
          accountId: _account,
          description: 'x',
          resultEffect: FinancialResultEffect.expense,
          expectedAmount: '1',
          currency: 'BRL',
          startDate: '2026-02-30',
          dayOfMonth: 10,
        ),
        () => FinancialRecurrenceCreateInput(
          accountId: _account,
          description: 'x',
          resultEffect: FinancialResultEffect.expense,
          expectedAmount: '1',
          currency: 'BRL',
          startDate: '2026-01-10',
          dayOfMonth: 32,
        ),
        () => FinancialRecurrenceCreateInput(
          accountId: _account,
          description: 'x',
          resultEffect: FinancialResultEffect.expense,
          expectedAmount: '1',
          currency: 'brl',
          startDate: '2026-01-10',
          dayOfMonth: 1,
        ),
      ]) {
        expect(build, throwsFormatException);
      }
    });

    test('rejects malformed realization input', () {
      for (final build in <FinancialRecurrenceRealizeInput Function()>[
        () => FinancialRecurrenceRealizeInput(
          actualAmount: '0',
          currency: 'BRL',
          effectiveDate: '2026-10-11',
          competenceDate: '2026-10-01',
        ),
        () => FinancialRecurrenceRealizeInput(
          actualAmount: '-3',
          currency: 'BRL',
          effectiveDate: '2026-10-11',
          competenceDate: '2026-10-01',
        ),
        () => FinancialRecurrenceRealizeInput(
          actualAmount: '1',
          currency: 'BRL',
          effectiveDate: '2026-10-1',
          competenceDate: '2026-10-01',
        ),
        () => FinancialRecurrenceRealizeInput(
          actualAmount: '1',
          currency: 'BRL',
          effectiveDate: '2026-10-11',
          competenceDate: '2026-13-01',
        ),
        () => FinancialRecurrenceRealizeInput(
          actualAmount: '1',
          currency: 'BRL',
          effectiveDate: '2026-10-11',
          competenceDate: '2026-10-01',
          idempotencyKey: 'not-a-uuid',
        ),
      ]) {
        expect(build, throwsFormatException);
      }
    });

    test('rejects malformed ids, periods and versions', () async {
      final backend = _backend();
      final api = _api(backend.transport);
      await expectLater(api.pauseRecurrence('nope'), throwsFormatException);
      await expectLater(api.skipOccurrence('nope'), throwsFormatException);
      await expectLater(
        api.generateOccurrences(
          recurrenceTestId(1),
          fromPeriod: '2026-13',
          throughPeriod: '2026-13',
        ),
        throwsFormatException,
      );
      await expectLater(
        api.listOccurrences(fromPeriod: '2026-1', throughPeriod: '2026-10'),
        throwsFormatException,
      );
      expect(
        () => FinancialRecurrenceReplaceInput(
          expectedVersion: 0,
          description: 'x',
          expectedAmount: '1',
          dayOfMonth: 1,
        ),
        throwsFormatException,
      );
      expect(backend.calls, isEmpty);
    });
  });

  group('responses are validated strictly', () {
    Future<Object?> list(String body) async {
      final backend = _backend()..listBodyOverride = body;
      try {
        return await _api(backend.transport).listRecurrences();
      } on FormatException catch (error) {
        return error;
      }
    }

    String rule(String Function(String) edit) =>
        '{"items":[${edit(_backend().ruleJson(FakeRule(index: 1, accountId: _account)))}]}';

    test('accepts the canonical shape and rejects every deviation', () async {
      expect(await list(rule((s) => s)), isA<List<FinancialRecurrence>>());
      for (final broken in <String Function(String)>[
        (s) => s.replaceFirst('"frequency":"MONTHLY"', '"frequency":"WEEKLY"'),
        (s) => s.replaceFirst(
          '"resultEffect":"EXPENSE"',
          '"resultEffect":"NEUTRAL"',
        ),
        (s) => s.replaceFirst('"dayOfMonth":10', '"dayOfMonth":0'),
        (s) => s.replaceFirst('"dayOfMonth":10', '"dayOfMonth":"10"'),
        (s) => s.replaceFirst('"version":1', '"version":0'),
        (s) => s.replaceFirst('"canEdit":true', '"canEdit":"yes"'),
        (s) => s.replaceFirst('"status":"ACTIVE"', '"status":"DELETED"'),
        (s) => s.replaceFirst('"amount":"120"', '"amount":"0"'),
        (s) => s.replaceFirst('"amount":"120"', '"amount":"-120"'),
        (s) => s.replaceFirst(
          '"startDate":"2026-01-10"',
          '"startDate":"2026-02-30"',
        ),
        (s) => s.replaceFirst('"endDate":null', '"endDate":"2025-12-31"'),
        (s) => s.replaceFirst('"canEdit"', '"extra":1,"canEdit"'),
        (s) => s.replaceFirst(
          '"id":"${recurrenceTestId(1)}"',
          '"id":"not-a-uuid"',
        ),
      ]) {
        expect(await list(rule(broken)), isA<FormatException>());
      }
      expect(await list('{"items":[],"x":1}'), isA<FormatException>());
      expect(await list('not json'), isA<FormatException>());
    });

    test('a duplicated rule is invalid', () async {
      final one = _backend().ruleJson(FakeRule(index: 1, accountId: _account));
      expect(await list('{"items":[$one,$one]}'), isA<FormatException>());
    });

    Future<Object?> occurrences(String body) async {
      final backend = _backend()..occurrencesBodyOverride = body;
      try {
        return await _api(
          backend.transport,
        ).listOccurrences(fromPeriod: '2026-10', throughPeriod: '2026-10');
      } on FormatException catch (error) {
        return error;
      }
    }

    String occurrence(
      String Function(String) edit, {
      String? status,
      bool realized = false,
    }) {
      final backend = _backend();
      final item = backend.addOccurrence(backend.rules.single, '2026-10');
      if (realized) {
        item
          ..status = 'REALIZED'
          ..movementId = 'd6000000-0000-4000-8000-000000000001'
          ..actual = '127.5'
          ..effectiveDate = '2026-10-11'
          ..competenceDate = '2026-10-01';
      }
      if (status != null) item.status = status;
      return '{"items":[${edit(backend.occurrenceJson(item))}]}';
    }

    test('occurrences: shape, window and the realization link', () async {
      expect(
        await occurrences(occurrence((s) => s)),
        isA<List<FinancialRecurrenceOccurrence>>(),
      );
      expect(
        await occurrences(occurrence((s) => s, realized: true)),
        isA<List<FinancialRecurrenceOccurrence>>(),
      );
      for (final broken in <String>[
        // wrong month for the window
        occurrence((s) => s.replaceAll('2026-10', '2026-11')),
        // superseded never listed
        occurrence((s) => s, status: 'SUPERSEDED'),
        // PENDING must not carry a realization
        occurrence(
          (s) => s.replaceFirst(
            '"realization":null',
            '"realization":{"movementId":"d6000000-0000-4000-8000-000000000001","actual":{"amount":"1","currency":"BRL"},"effectiveDate":"2026-10-11","competenceDate":"2026-10-01","realizedAt":"2026-10-06T12:00:00Z","movementState":"ACTIVE"}',
          ),
        ),
        // REALIZED must carry one
        occurrence(
          (s) => s.replaceFirst('"status":"PENDING"', '"status":"REALIZED"'),
        ),
        // scheduled date outside its month
        occurrence(
          (s) => s.replaceFirst(
            '"scheduledDate":"2026-10-10"',
            '"scheduledDate":"2026-11-10"',
          ),
        ),
        occurrence((s) => s.replaceFirst('"ruleVersion":1', '"ruleVersion":0')),
        occurrence(
          (s) => s.replaceFirst(
            '"periodStart":"2026-10-01"',
            '"periodStart":"2026-10-02"',
          ),
        ),
        occurrence((s) => s.replaceFirst('"canEdit"', '"x":1,"canEdit"')),
        // realized actual in another currency / negative
        occurrence(
          (s) => s.replaceFirst(
            '"actual":{"amount":"127.5","currency":"BRL"}',
            '"actual":{"amount":"127.5","currency":"USD"}',
          ),
          realized: true,
        ),
        occurrence(
          (s) => s.replaceFirst(
            '"actual":{"amount":"127.5"',
            '"actual":{"amount":"-127.5"',
          ),
          realized: true,
        ),
        occurrence(
          (s) => s.replaceFirst(
            '"movementState":"ACTIVE"',
            '"movementState":"GONE"',
          ),
          realized: true,
        ),
      ]) {
        expect(await occurrences(broken), isA<FormatException>());
      }
    });

    test('a mirror mismatch on the answer to a write is ambiguous', () async {
      final backend = FakeRecurrenceBackend();
      backend.writeBodyOverride = backend.ruleJson(
        FakeRule(index: 7, accountId: _account, expected: '999'),
      );
      await expectLater(
        _api(backend.transport).createRecurrence(_create()),
        throwsFormatException,
      );
    });

    test('registering with a mismatching answer is ambiguous', () async {
      final backend = _backend();
      final item = backend.addOccurrence(backend.rules.single, '2026-10');
      final other = backend.addOccurrence(backend.rules.single, '2026-11');
      backend.writeBodyOverride = backend.occurrenceJson(other);
      await expectLater(
        _api(backend.transport).realizeOccurrence(item.id, _realize()),
        throwsFormatException,
      );
    });

    test(
      'generation answers must stay inside the window and the rule',
      () async {
        final backend = _backend();
        final other = FakeRule(index: 2, accountId: _account);
        backend.rules.add(other);
        final stranger = backend.addOccurrence(other, '2026-10');
        backend.writeBodyOverride =
            '{"createdCount":1,"items":[${backend.occurrenceJson(stranger)}]}';
        await expectLater(
          _api(backend.transport).generateOccurrences(
            recurrenceTestId(1),
            fromPeriod: '2026-10',
            throughPeriod: '2026-10',
          ),
          throwsFormatException,
        );
      },
    );
  });

  test('wire money and secrets never leak through toString', () {
    expect(_create().expectedAmount, '120');
    expect(
      FinancialMoneyWire(amount: '1', currency: 'BRL').toString(),
      isNot(contains('1,')),
    );
  });
}
