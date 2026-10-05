import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_finance_backend.dart';

final _category = financeTestCategoryId(1);
final _rule = financeTestRuleId(1);
final _movementA = financeTestMovementId(1);
final _movementB = financeTestMovementId(2);
final _setA = financeTestAllocationSetId(1);

FinancialCoreApi _api(FakeAuthTransport transport) => FinancialCoreApi(
  AuthenticatedApiClient(
    transport: transport,
    tokenVault: SessionTokenVault()..store(financeTestToken),
    apiBaseUri: Uri.parse('http://localhost/api/v1/'),
    timeout: const Duration(seconds: 2),
    onUnauthorized: () {},
  ),
);

FakeAuthTransport _ok(String body, {int status = 200}) =>
    FakeAuthTransport.response(statusCode: status, body: body);

FinancialCategorizationRuleCreateInput _input({
  String pattern = '  Padaria  ',
  String? key,
  String? accountId,
  FinancialResultEffect? effect,
  int priority = 10,
  FinancialCategorizationMatcher matcher =
      FinancialCategorizationMatcher.contains,
}) => FinancialCategorizationRuleCreateInput(
  matcher: matcher,
  pattern: pattern,
  targetCategoryId: _category,
  priority: priority,
  accountId: accountId,
  resultEffect: effect,
  idempotencyKey: key,
);

String _previewJson({
  int matched = 1,
  int ambiguous = 0,
  int noMatch = 0,
  int ineligible = 0,
  int already = 0,
  int? total,
  String items = '',
  bool truncated = false,
}) =>
    '{"accountId":"$financeTestAccountId",'
    '"totalMovements":${total ?? matched + ambiguous + noMatch + ineligible + already},'
    '"counts":{"matched":$matched,"noMatch":$noMatch,"ambiguous":$ambiguous,'
    '"ineligible":$ineligible,"alreadyClassified":$already},'
    '"items":[$items],"itemsTruncated":$truncated}';

String _matchedItem(String movement) =>
    '{"movementId":"$movement","status":"MATCHED","ruleId":"$_rule",'
    '"targetCategoryId":"$_category"}';

String _applyJson({
  required List<String> results,
  required Map<String, int> counts,
  int? requested,
}) =>
    '{"accountId":"$financeTestAccountId","requested":${requested ?? results.length},'
    '"counts":{"classified":${counts['classified'] ?? 0},'
    '"alreadyClassified":${counts['alreadyClassified'] ?? 0},'
    '"ambiguous":${counts['ambiguous'] ?? 0},"noMatch":${counts['noMatch'] ?? 0},'
    '"ineligible":${counts['ineligible'] ?? 0},"conflict":${counts['conflict'] ?? 0},'
    '"failed":${counts['failed'] ?? 0}},"results":[${results.join(',')}]}';

String _classified(String movement, String set, {String? rule}) =>
    '{"movementId":"$movement","status":"CLASSIFIED","ruleId":"${rule ?? _rule}",'
    '"allocationSetId":"$set"}';

String _status(String movement, String status) =>
    '{"movementId":"$movement","status":"$status","ruleId":null,'
    '"allocationSetId":null}';

void main() {
  group('rule input', () {
    test('trims, bounds and serializes exactly the v1 fields', () {
      final input = _input(
        key: financeTestRuleId(9),
        accountId: financeTestAccountId,
        effect: FinancialResultEffect.expense,
      );
      expect(input.toJson(), {
        'idempotencyKey': financeTestRuleId(9),
        'descriptionMatcher': 'CONTAINS',
        'descriptionPattern': 'Padaria',
        'targetCategoryId': _category,
        'priority': 10,
        'accountId': financeTestAccountId,
        'resultEffect': 'EXPENSE',
      });
      expect(
        _input().toJson().keys,
        isNot(contains('accountId')),
        reason: 'optional filters are omitted, not sent as null',
      );
    });

    test('rejects empty, control, oversized, priority and NEUTRAL inputs', () {
      for (final bad in ['', '   ', 'a\nb', 'x' * 257]) {
        expect(() => _input(pattern: bad), throwsFormatException);
      }
      expect(() => _input(priority: 0), throwsFormatException);
      expect(() => _input(priority: 1001), throwsFormatException);
      expect(
        () => _input(effect: FinancialResultEffect.neutral),
        throwsFormatException,
      );
      expect(() => _input(accountId: 'not-an-id'), throwsFormatException);
      expect(() => _input(key: 'x'), throwsFormatException);
    });

    test('attempt identity changes with every material field, not the key', () {
      final base = _input(key: financeTestRuleId(1)).attemptIdentity;
      expect(_input(key: financeTestRuleId(2)).attemptIdentity, base);
      for (final other in [
        _input(pattern: 'Mercado'),
        _input(priority: 11),
        _input(matcher: FinancialCategorizationMatcher.exact),
        _input(accountId: financeTestAccountId),
        _input(effect: FinancialResultEffect.income),
      ]) {
        expect(other.attemptIdentity, isNot(base));
      }
    });
  });

  group('rules', () {
    test('lists strictly and rejects shape drift', () async {
      final rule = fakeRuleJson(id: _rule, pattern: 'Padaria Pão');
      final transport = _ok('{"rules":[$rule]}');
      final rules = await _api(transport).listCategorizationRules();
      expect(
        transport.calls.single.uri.path,
        '/api/v1/finance/categorization-rules',
      );
      expect(rules.single.pattern, 'Padaria Pão');
      expect(rules.single.isActive, isTrue);
      expect(rules.single.matcher, FinancialCategorizationMatcher.contains);

      for (final bad in [
        '{"rules":[${rule.replaceFirst('"priority":10', '"priority":10,"extra":1')}]}',
        '{"rules":[${rule.replaceFirst('"priority":10', '"priority":"10"')}]}',
        '{"rules":[${rule.replaceFirst('"priority":10', '"priority":0')}]}',
        '{"rules":[${rule.replaceFirst('"descriptionMatcher":"CONTAINS"', '"descriptionMatcher":"REGEX"')}]}',
        '{"rules":[${rule.replaceFirst('"resultEffect":null', '"resultEffect":"NEUTRAL"')}]}',
        '{"rules":[${rule.replaceFirst('"disabledAt":null', '"disabledAt":"2026-09-22T12:00:00Z"')}]}',
        '{"rules":[$rule,$rule]}',
        '{"rules":[${rule.replaceFirst('"status":"ACTIVE"', '"status":"DISABLED"')}]}',
      ]) {
        await expectLater(
          _api(_ok(bad)).listCategorizationRules(),
          throwsA(isA<FormatException>()),
          reason: bad,
        );
      }
    });

    test(
      'create must be echoed exactly, active, and never invents semantics',
      () async {
        final input = _input(key: financeTestRuleId(9));
        final good = fakeRuleJson(
          id: _rule,
          pattern: 'Padaria',
          categoryId: _category,
        );
        final transport = _ok(good, status: 201);
        final rule = await _api(transport).createCategorizationRule(input);
        expect(rule.ruleId, _rule);
        expect(transport.calls.single.method, AuthHttpMethod.post);
        final sent =
            jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
        expect(sent['idempotencyKey'], financeTestRuleId(9));

        for (final bad in [
          good.replaceFirst('"priority":10', '"priority":11'),
          good.replaceFirst(
            '"descriptionPattern":"Padaria"',
            '"descriptionPattern":"Outra"',
          ),
          good.replaceFirst(
            '"descriptionMatcher":"CONTAINS"',
            '"descriptionMatcher":"EXACT"',
          ),
          good.replaceFirst(
            '"targetCategoryId":"$_category"',
            '"targetCategoryId":"${financeTestCategoryId(2)}"',
          ),
          good.replaceFirst(
            '"accountId":null',
            '"accountId":"$financeTestAccountId"',
          ),
          fakeRuleJson(id: _rule, categoryId: _category, status: 'DISABLED'),
        ]) {
          await expectLater(
            _api(_ok(bad, status: 201)).createCategorizationRule(input),
            throwsA(isA<FormatException>()),
            reason: bad,
          );
        }
      },
    );

    test(
      'disable posts an empty body to the rule id and requires DISABLED',
      () async {
        final disabled = fakeRuleJson(id: _rule, status: 'DISABLED');
        final transport = _ok(disabled);
        final rule = await _api(transport).disableCategorizationRule(_rule);
        expect(rule.isActive, isFalse);
        expect(
          transport.calls.single.uri.path,
          '/api/v1/finance/categorization-rules/$_rule/disable',
        );
        await expectLater(
          _api(_ok(fakeRuleJson(id: _rule))).disableCategorizationRule(_rule),
          throwsA(isA<FormatException>()),
        );
        await expectLater(
          _api(
            _ok(fakeRuleJson(id: financeTestRuleId(2), status: 'DISABLED')),
          ).disableCategorizationRule(_rule),
          throwsA(isA<FormatException>()),
        );
      },
    );
  });

  group('preview', () {
    test(
      'parses counts and candidates; applicable items are only MATCHED',
      () async {
        final body = _previewJson(
          matched: 1,
          ambiguous: 1,
          noMatch: 2,
          ineligible: 1,
          already: 3,
          items:
              '${_matchedItem(_movementA)},'
              '{"movementId":"$_movementB","status":"AMBIGUOUS","ruleId":null,"targetCategoryId":null}',
        );
        final transport = _ok(body);
        final preview = await _api(
          transport,
        ).previewCategorizationRules(financeTestAccountId);
        expect(transport.calls.single.method, AuthHttpMethod.post);
        expect(
          transport.calls.single.uri.path,
          '/api/v1/finance/accounts/$financeTestAccountId/categorization-rules/preview',
        );
        expect(preview.counts.matched, 1);
        expect(preview.counts.ambiguous, 1);
        expect(preview.counts.total, 8);
        expect(preview.applicableItems.map((item) => item.movementId), [
          _movementA,
        ]);
        expect(preview.applicableItems.single.ruleId, _rule);
      },
    );

    test('rejects inconsistent previews', () async {
      for (final bad in [
        _previewJson(matched: 1, total: 5, items: _matchedItem(_movementA)),
        _previewJson(matched: 1, items: ''),
        _previewJson(matched: 0, items: _matchedItem(_movementA)),
        _previewJson(
          matched: 2,
          items: '${_matchedItem(_movementA)},${_matchedItem(_movementA)}',
        ),
        _previewJson(
          matched: 1,
          items:
              '{"movementId":"$_movementA","status":"MATCHED","ruleId":null,"targetCategoryId":null}',
        ),
        _previewJson(
          ambiguous: 1,
          matched: 0,
          items:
              '{"movementId":"$_movementA","status":"AMBIGUOUS","ruleId":"$_rule","targetCategoryId":"$_category"}',
        ),
        _previewJson(matched: 1, items: _matchedItem(_movementA)).replaceFirst(
          '"itemsTruncated":false',
          '"itemsTruncated":false,"providerItem":"x"',
        ),
        _previewJson(
          matched: 1,
          items: _matchedItem(_movementA),
        ).replaceFirst(financeTestAccountId, financeTestMovementId(7)),
      ]) {
        await expectLater(
          _api(_ok(bad)).previewCategorizationRules(financeTestAccountId),
          throwsA(isA<FormatException>()),
          reason: bad,
        );
      }
    });

    test(
      'a truncated preview may list fewer candidates than counted',
      () async {
        final preview = await _api(
          _ok(
            _previewJson(
              matched: 500,
              items: _matchedItem(_movementA),
              truncated: true,
            ),
          ),
        ).previewCategorizationRules(financeTestAccountId);
        expect(preview.itemsTruncated, isTrue);
        expect(preview.counts.matched, 500);
        expect(preview.applicableItems, hasLength(1));
      },
    );
  });

  group('apply', () {
    final pairs = [
      FinancialCategorizationApplyItem(movementId: _movementA, ruleId: _rule),
      FinancialCategorizationApplyItem(movementId: _movementB, ruleId: _rule),
    ];

    test(
      'sends the confirmed pairs once and parses the canonical outcome',
      () async {
        final body = _applyJson(
          results: [
            _classified(_movementA, _setA),
            _status(_movementB, 'ALREADY_CLASSIFIED'),
          ],
          counts: {'classified': 1, 'alreadyClassified': 1},
        );
        final transport = _ok(body);
        final outcome = await _api(
          transport,
        ).applyCategorizationRules(financeTestAccountId, pairs);
        expect(transport.calls, hasLength(1));
        final sent =
            jsonDecode(transport.calls.single.body!) as Map<String, dynamic>;
        expect(sent, {
          'items': [
            {'movementId': _movementA, 'ruleId': _rule},
            {'movementId': _movementB, 'ruleId': _rule},
          ],
        });
        expect(outcome.counts.classified, 1);
        expect(
          outcome.isFullSuccess,
          isFalse,
          reason: 'partial is not success',
        );
        expect(outcome.results.first.allocationSetId, _setA);
      },
    );

    test('only everything classified is a full success', () async {
      final outcome = await _api(
        _ok(
          _applyJson(
            results: [
              _classified(_movementA, _setA),
              _classified(_movementB, financeTestAllocationSetId(2)),
            ],
            counts: {'classified': 2},
          ),
        ),
      ).applyCategorizationRules(financeTestAccountId, pairs);
      expect(outcome.isFullSuccess, isTrue);
    });

    test(
      'rejects responses that do not match the request or themselves',
      () async {
        final ok = [
          _classified(_movementA, _setA),
          _status(_movementB, 'NO_MATCH'),
        ];
        for (final bad in [
          // order/identity mismatch
          _applyJson(
            results: [
              _status(_movementB, 'NO_MATCH'),
              _classified(_movementA, _setA),
            ],
            counts: {'classified': 1, 'noMatch': 1},
          ),
          // counts disagree with results
          _applyJson(results: ok, counts: {'classified': 2}),
          // requested disagrees
          _applyJson(
            results: ok,
            counts: {'classified': 1, 'noMatch': 1},
            requested: 3,
          ),
          // classified without allocation set
          _applyJson(
            results: [
              _status(_movementA, 'CLASSIFIED'),
              _status(_movementB, 'NO_MATCH'),
            ],
            counts: {'classified': 1, 'noMatch': 1},
          ),
          // applied a different rule than the one confirmed
          _applyJson(
            results: [
              _classified(_movementA, _setA, rule: financeTestRuleId(5)),
              _status(_movementB, 'NO_MATCH'),
            ],
            counts: {'classified': 1, 'noMatch': 1},
          ),
          // unknown status
          _applyJson(
            results: [
              _status(_movementA, 'APPLIED'),
              _status(_movementB, 'NO_MATCH'),
            ],
            counts: {'noMatch': 2},
          ),
        ]) {
          await expectLater(
            _api(
              _ok(bad),
            ).applyCategorizationRules(financeTestAccountId, pairs),
            throwsA(isA<FormatException>()),
            reason: bad,
          );
        }
      },
    );

    test('refuses to send empty, oversized or duplicated requests', () async {
      final transport = _ok('{}');
      final api = _api(transport);
      await expectLater(
        api.applyCategorizationRules(financeTestAccountId, const []),
        throwsA(isA<FormatException>()),
      );
      await expectLater(
        api.applyCategorizationRules(financeTestAccountId, [
          pairs.first,
          pairs.first,
        ]),
        throwsA(isA<FormatException>()),
      );
      await expectLater(
        api.applyCategorizationRules(financeTestAccountId, [
          for (var i = 0; i <= financialCategorizationMaxApplyItems; i += 1)
            FinancialCategorizationApplyItem(
              movementId: financeTestMovementId(1000 + i),
              ruleId: _rule,
            ),
        ]),
        throwsA(isA<FormatException>()),
      );
      expect(transport.calls, isEmpty);
    });
  });

  group('origins', () {
    test('one bulk GET, keyed by allocation set, strict and unique', () async {
      final origin = fakeOriginJson(
        movementId: _movementA,
        setId: _setA,
        ruleId: _rule,
      );
      final transport = _ok(
        '{"accountId":"$financeTestAccountId","origins":[$origin]}',
      );
      final origins = await _api(
        transport,
      ).listRuleOrigins(financeTestAccountId);
      expect(transport.calls, hasLength(1));
      expect(
        transport.calls.single.uri.path,
        '/api/v1/finance/accounts/$financeTestAccountId/categorization-rules/origins',
      );
      expect(origins.single.allocationSetId, _setA);

      for (final bad in [
        '{"accountId":"$financeTestAccountId","origins":[$origin,$origin]}',
        '{"accountId":"${financeTestMovementId(9)}","origins":[$origin]}',
        '{"accountId":"$financeTestAccountId","origins":[${origin.replaceFirst('"ruleId"', '"extra":1,"ruleId"')}]}',
      ]) {
        await expectLater(
          _api(_ok(bad)).listRuleOrigins(financeTestAccountId),
          throwsA(isA<FormatException>()),
          reason: bad,
        );
      }
    });
  });
}
