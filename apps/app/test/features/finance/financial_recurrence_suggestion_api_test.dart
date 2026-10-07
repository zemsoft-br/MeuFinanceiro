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
final _fingerprint = suggestionTestFingerprint(1);

FinancialCoreApi _api(FakeAuthTransport transport) => FinancialCoreApi(
  AuthenticatedApiClient(
    transport: transport,
    tokenVault: SessionTokenVault()..store(financeTestToken),
    apiBaseUri: Uri.parse('http://localhost/api/v1/'),
    timeout: const Duration(seconds: 2),
    onUnauthorized: () {},
  ),
);

FakeRecurrenceBackend _backend({List<FakeSuggestionEvidence>? evidence}) {
  final backend = FakeRecurrenceBackend();
  backend.suggestions.add(
    FakeSuggestion(index: 1, accountId: _account, evidence: evidence),
  );
  return backend;
}

FinancialRecurrenceSuggestionAcceptInput _accept({
  String amount = '41.90',
  String description = 'Streaming',
  String? endDate,
  String? key,
  String? fingerprint,
}) => FinancialRecurrenceSuggestionAcceptInput(
  fingerprint: fingerprint ?? _fingerprint,
  accountId: _account,
  currency: 'BRL',
  description: description,
  expectedAmount: amount,
  startDate: '2026-11-01',
  dayOfMonth: 10,
  endDate: endDate,
  idempotencyKey: key,
);

String _list(Map<String, Object?> Function(Map<String, Object?>) mutate) {
  final backend = _backend();
  final original =
      jsonDecode(backend.suggestionJson(backend.suggestions.single))
          as Map<String, Object?>;
  final changed = mutate(Map<String, Object?>.of(original));
  return jsonEncode({
    'windowFrom': '2025-11-01',
    'windowThrough': '2026-10-06',
    'items': [changed],
  });
}

Future<void> _expectInvalid(
  Map<String, Object?> Function(Map<String, Object?>) mutate,
) async {
  final backend = _backend()..suggestionsBodyOverride = _list(mutate);
  await expectLater(
    _api(backend.transport).listRecurrenceSuggestions(),
    throwsA(isA<FormatException>()),
  );
}

void main() {
  group('listing', () {
    test('is a plain GET (never a write) and parses the evidence', () async {
      final backend = _backend();
      final result = await _api(backend.transport).listRecurrenceSuggestions();
      final call = backend.calls.single;
      expect(call.method, AuthHttpMethod.get);
      expect(call.uri.path, '/api/v1/finance/recurrence-suggestions');
      expect(call.uri.queryParameters, isEmpty);
      expect(call.body, isNull);
      expect(result.windowFrom, '2025-11-01');
      final item = result.items.single;
      expect(item.fingerprint, _fingerprint);
      expect(item.description, 'Streaming');
      expect(item.evidence, hasLength(3));
      expect(item.evidence.first.effectiveDate, '2026-08-10');
      expect(item.suggestedDayOfMonth, 10);
      expect(item.suggestedExpectedAmount.amount, '39.9');
      expect(item.amountBehavior, FinancialSuggestionAmountBehavior.fixed);
      expect(item.isVariable, isFalse);
      expect(item.canAccept, isTrue);
      expect(item.lastObservedDate, '2026-10-10');
      expect(item.reasonCodes, contains(FinancialSuggestionReason.amountFixed));
    });

    test(
      'a variable pattern keeps min, max and last as decimal text',
      () async {
        final backend = _backend(
          evidence: const [
            FakeSuggestionEvidence('2026-08-10', '100.00'),
            FakeSuggestionEvidence('2026-09-10', '120.50'),
            FakeSuggestionEvidence('2026-10-10', '110.25'),
          ],
        );
        final item = (await _api(
          backend.transport,
        ).listRecurrenceSuggestions()).items.single;
        expect(item.isVariable, isTrue);
        expect(item.minAmount.amount, '100');
        expect(item.maxAmount.amount, '120.5');
        expect(item.lastAmount.amount, '110.25');
        expect(item.suggestedExpectedAmount.amount, '110.25');
        expect(
          item.reasonCodes,
          contains(FinancialSuggestionReason.amountVariable),
        );
      },
    );

    test('an empty list is valid', () async {
      final backend = FakeRecurrenceBackend();
      expect(
        (await _api(backend.transport).listRecurrenceSuggestions()).items,
        isEmpty,
      );
    });

    test('invalid or inconsistent shapes are never rendered', () async {
      await _expectInvalid((m) => {...m, 'extra': 1});
      await _expectInvalid((m) => {...m, 'fingerprint': 'ABC'});
      await _expectInvalid((m) => {...m, 'fingerprint': 'g' * 64});
      await _expectInvalid((m) => {...m, 'canAccept': 'yes'});
      await _expectInvalid((m) => {...m, 'suggestedDayOfMonth': 32});
      await _expectInvalid((m) => {...m, 'currency': 'brl'});
      await _expectInvalid((m) => {...m, 'amountBehavior': 'VARIABLE'});
      await _expectInvalid(
        (m) => {
          ...m,
          'reasonCodes': ['NOPE'],
        },
      );
      await _expectInvalid((m) => {...m, 'reasonCodes': []});
      await _expectInvalid(
        (m) => {
          ...m,
          'reasonCodes': ['EXACT_DESCRIPTION', 'EXACT_DESCRIPTION'],
        },
      );
      await _expectInvalid(
        (m) => {
          ...m,
          'reasonCodes': ['EXACT_DESCRIPTION', 'AMOUNT_VARIABLE'],
        },
      );
      await _expectInvalid(
        (m) => {...m, 'evidence': (m['evidence']! as List).take(2).toList()},
      );
      await _expectInvalid(
        (m) => {
          ...m,
          'movementIds': (m['movementIds']! as List).reversed.toList(),
        },
      );
      await _expectInvalid(
        (m) => {
          ...m,
          'observedDates': (m['observedDates']! as List).reversed.toList(),
        },
      );
      // A wrong behavior with perfectly matching reason codes is still invalid.
      await _expectInvalid(
        (m) => {
          ...m,
          'amountBehavior': 'VARIABLE',
          'reasonCodes': [
            'EXACT_DESCRIPTION',
            'CONSECUTIVE_MONTHS',
            'ONE_PER_MONTH',
            'DAY_WINDOW',
            'AMOUNT_VARIABLE',
          ],
        },
      );
      // Evidence that is not in chronological order is invalid even when every
      // mirrored list is reversed consistently.
      await _expectInvalid(
        (m) => {
          ...m,
          'evidence': (m['evidence']! as List).reversed.toList(),
          'movementIds': (m['movementIds']! as List).reversed.toList(),
          'observedDates': (m['observedDates']! as List).reversed.toList(),
          'observedAmounts': (m['observedAmounts']! as List).reversed.toList(),
        },
      );
      await _expectInvalid(
        (m) => {
          ...m,
          'suggestedExpectedAmount': {'amount': '1', 'currency': 'BRL'},
        },
      );
      await _expectInvalid(
        (m) => {
          ...m,
          'minAmount': {'amount': '1', 'currency': 'BRL'},
        },
      );
      await _expectInvalid(
        (m) => {
          ...m,
          'lastAmount': {'amount': '0', 'currency': 'BRL'},
        },
      );
    });

    test('duplicate suggestions and an oversized list are rejected', () async {
      final backend = _backend();
      final one = backend.suggestionJson(backend.suggestions.single);
      backend.suggestionsBodyOverride =
          '{"windowFrom":"2025-11-01","windowThrough":"2026-10-06",'
          '"items":[$one,$one]}';
      await expectLater(
        _api(backend.transport).listRecurrenceSuggestions(),
        throwsA(isA<FormatException>()),
      );
      backend.suggestionsBodyOverride =
          '{"windowFrom":"2026-10-06","windowThrough":"2025-11-01","items":[]}';
      await expectLater(
        _api(backend.transport).listRecurrenceSuggestions(),
        throwsA(isA<FormatException>()),
      );
    });
  });

  group('dismiss', () {
    test('posts to the fingerprint route with no body', () async {
      final backend = _backend();
      final decision = await _api(
        backend.transport,
      ).dismissRecurrenceSuggestion(_fingerprint);
      final call = backend.calls.single;
      expect(call.method, AuthHttpMethod.post);
      expect(
        call.uri.path,
        '/api/v1/finance/recurrence-suggestions/$_fingerprint/dismiss',
      );
      expect(call.body == null || call.body!.isEmpty, isTrue);
      expect(decision.kind, FinancialSuggestionDecisionKind.dismissed);
      expect(decision.recurrenceId, isNull);
      expect(decision.created, isTrue);
    });

    test('a malformed fingerprint is refused before any request', () async {
      final backend = _backend();
      await expectLater(
        _api(backend.transport).dismissRecurrenceSuggestion('abc'),
        throwsA(isA<FormatException>()),
      );
      expect(backend.calls, isEmpty);
    });

    test(
      'an answer that is not a dismissal of that fingerprint is invalid',
      () async {
        final backend = _backend()
          ..writeBodyOverride =
              '{"fingerprint":"${suggestionTestFingerprint(2)}",'
              '"accountId":"$_account","decision":"DISMISSED",'
              '"recurrenceId":null,"decidedAt":"2026-10-06T12:00:00Z",'
              '"created":true}';
        await expectLater(
          _api(backend.transport).dismissRecurrenceSuggestion(_fingerprint),
          throwsA(isA<FormatException>()),
        );
      },
    );
  });

  group('accept', () {
    test(
      'sends only the reviewed fields: no account, effect or currency',
      () async {
        final backend = _backend();
        final result = await _api(
          backend.transport,
        ).acceptRecurrenceSuggestion(_accept(endDate: '2027-12-31'));
        final call = backend.calls.single;
        expect(call.method, AuthHttpMethod.post);
        expect(
          call.uri.path,
          '/api/v1/finance/recurrence-suggestions/$_fingerprint/accept',
        );
        final body = jsonDecode(call.body!) as Map<String, dynamic>;
        expect(body.keys.toSet(), {
          'idempotencyKey',
          'description',
          'expectedAmount',
          'startDate',
          'dayOfMonth',
          'endDate',
        });
        expect(body['expectedAmount'], '41.90');
        expect(result.recurrence.accountId, _account);
        expect(result.recurrence.resultEffect, FinancialResultEffect.expense);
        expect(result.recurrence.version, 1);
        expect(result.decision.kind, FinancialSuggestionDecisionKind.accepted);
        expect(result.decision.recurrenceId, result.recurrence.id);
      },
    );

    test('the idempotency key is a stable UUID v4 per input', () {
      final input = _accept();
      expect(
        RegExp(
          r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ).hasMatch(input.idempotencyKey),
        isTrue,
      );
      final retry = input.withIdempotencyKey(
        'f0000000-0000-4000-8000-000000000001',
      );
      expect(retry.idempotencyKey, 'f0000000-0000-4000-8000-000000000001');
      expect(retry.attemptKey, input.attemptKey);
      expect(_accept(amount: '1').attemptKey, isNot(input.attemptKey));
    });

    test('invalid inputs are refused before any request', () async {
      final backend = _backend();
      for (final build in <FinancialRecurrenceSuggestionAcceptInput Function()>[
        () => _accept(amount: '0'),
        () => _accept(amount: '-5'),
        () => _accept(amount: '1e3'),
        () => _accept(description: '   '),
        () => _accept(endDate: '2026-10-31'),
        () => _accept(fingerprint: 'zz'),
        () => _accept(key: 'not-a-uuid'),
      ]) {
        expect(build, throwsA(isA<FormatException>()));
      }
      expect(backend.calls, isEmpty);
    });

    test('an answer that does not mirror the review is invalid', () async {
      Future<void> check(String Function(String ruleJson) mutate) async {
        final backend = _backend();
        final probe = FakeRule(
          index: 77,
          accountId: _account,
          description: 'Streaming',
          expected: '41.9',
          startDate: '2026-11-01',
        );
        final rule = backend.ruleJson(probe);
        backend.writeBodyOverride =
            '{"recurrence":${mutate(rule)},"decision":'
            '{"fingerprint":"$_fingerprint","accountId":"$_account",'
            '"decision":"ACCEPTED","recurrenceId":"${probe.id}",'
            '"decidedAt":"2026-10-06T12:00:00Z","created":true}}';
        await expectLater(
          _api(backend.transport).acceptRecurrenceSuggestion(_accept()),
          throwsA(isA<FormatException>()),
        );
      }

      await check(
        (r) => r.replaceFirst(
          '"description":"Streaming"',
          '"description":"Outra"',
        ),
      );
      await check(
        (r) => r.replaceFirst(
          '"expected":{"amount":"41.9"',
          '"expected":{"amount":"42"',
        ),
      );
      await check(
        (r) => r.replaceFirst(
          '"resultEffect":"EXPENSE"',
          '"resultEffect":"INCOME"',
        ),
      );
      await check((r) => r.replaceFirst('"dayOfMonth":10', '"dayOfMonth":11'));
      await check(
        (r) => r.replaceFirst(
          '"accountId":"$_account"',
          '"accountId":"${recurrenceTestAccountId(2)}"',
        ),
      );
      await check((r) => r.replaceFirst('"version":1', '"version":2'));
      await check(
        (r) => r.replaceFirst('"status":"ACTIVE"', '"status":"PAUSED"'),
      );
    });

    test('a decision that is not the matching acceptance is invalid', () async {
      final backend = _backend();
      final probe = FakeRule(
        index: 77,
        accountId: _account,
        expected: '41.9',
        startDate: '2026-11-01',
      );
      backend.writeBodyOverride =
          '{"recurrence":${backend.ruleJson(probe)},"decision":'
          '{"fingerprint":"$_fingerprint","accountId":"$_account",'
          '"decision":"DISMISSED","recurrenceId":null,'
          '"decidedAt":"2026-10-06T12:00:00Z","created":true}}';
      await expectLater(
        _api(backend.transport).acceptRecurrenceSuggestion(_accept()),
        throwsA(isA<FormatException>()),
      );
    });
  });
}
