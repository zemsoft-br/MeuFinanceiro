import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_pending_controller.dart';

import '../../support/fake_finance_backend.dart';
import '../../support/fake_pending_backend.dart';

final _mercado = financeTestCategoryId(1);
final _lazer = financeTestCategoryId(2);
final _rule = financeTestRuleId(1);

FakePendingBackend _backend({List<FakePendingItem>? items, int? pageSize}) =>
    FakePendingBackend(
      items:
          items ??
          [
            FakePendingItem(
              index: 1,
              description: 'Padaria',
              status: 'MATCHED',
              ruleId: _rule,
              categoryId: _mercado,
            ),
            FakePendingItem(
              index: 2,
              description: 'Cinema',
              date: '2026-09-09',
            ),
            FakePendingItem(
              index: 3,
              description: 'Mercado',
              date: '2026-09-08',
              status: 'AMBIGUOUS',
            ),
          ],
      pageSize: pageSize,
      categories: [
        fakeCategoryJson(id: _mercado, name: 'Mercado'),
        fakeCategoryJson(id: _lazer, name: 'Lazer'),
        fakeCategoryJson(
          id: financeTestCategoryId(3),
          name: 'Do outro',
          scope: 'PERSONAL',
          owner: financeTestOtherOperatorId,
        ),
        fakeCategoryJson(
          id: financeTestCategoryId(4),
          name: 'Antiga',
          status: 'DISABLED',
        ),
      ],
    );

ProviderContainer _container(FakePendingBackend backend) {
  final container = pendingTestContainer(backend);
  addTearDown(container.dispose);
  container.listen(
    financialPendingControllerProvider,
    (previous, next) {},
    fireImmediately: true,
  );
  return container;
}

FinancialPendingController _controller(ProviderContainer container) =>
    container.read(financialPendingControllerProvider.notifier);

FinancialPendingState _state(ProviderContainer container) =>
    container.read(financialPendingControllerProvider);

Future<ProviderContainer> _loaded(FakePendingBackend backend) async {
  final container = _container(backend);
  await _controller(container).load();
  return container;
}

List<String> _ids(ProviderContainer container) =>
    _state(container).items.map((item) => item.movementId).toList();

void main() {
  group('loading and fixed cost', () {
    test('one page, categories and accounts; no request per row', () async {
      for (final size in [0, 1, 25]) {
        final backend = _backend(
          items: [
            for (var i = 1; i <= size; i += 1)
              FakePendingItem(
                index: i,
                date: '2026-09-${(10 + i % 10).toString()}',
              ),
          ],
        );
        final container = await _loaded(backend);
        expect(_state(container).isLoaded, isTrue);
        expect(_state(container).items, hasLength(size));
        expect(backend.calls, hasLength(3), reason: 'size=$size');
        expect(backend.perRowRequests, 0);
        expect(backend.pendingReads.single.uri.queryParameters, {
          'limit': '50',
        });
      }
    });

    test('items arrive in server order with their derived state', () async {
      final container = await _loaded(_backend());
      final items = _state(container).items;
      expect(items.map((item) => item.ruleStatus), [
        FinancialPendingRuleStatus.matched,
        FinancialPendingRuleStatus.noMatch,
        FinancialPendingRuleStatus.ambiguous,
      ]);
      expect(items.first.matchedRuleId, _rule);
      expect(items.first.suggestedCategoryId, _mercado);
      expect(items[1].matchedRuleId, isNull);
      expect(_state(container).nextCursor, isNull);
    });

    test(
      'a failed first read ends in an error phase, never fake data',
      () async {
        final backend = _backend()..pendingReadStatus = 503;
        final container = _container(backend);
        await _controller(container).load();
        expect(
          _state(container).phase,
          FinancialLoadPhase.temporarilyUnavailable,
        );
        expect(_state(container).items, isEmpty);

        backend
          ..pendingReadStatus = null
          ..pendingBodyOverride = '{"items":[],"nextCursor":null,"extra":1}';
        await _controller(container).refresh();
        expect(_state(container).phase, FinancialLoadPhase.invalidResponse);
      },
    );

    test('401 and 403 block access instead of retrying', () async {
      for (final (status, phase) in [
        (401, FinancialLoadPhase.authenticationRequired),
        (403, FinancialLoadPhase.forbidden),
      ]) {
        final backend = _backend()..pendingReadStatus = status;
        final container = _container(backend);
        await _controller(container).load();
        expect(_state(container).phase, phase);
        expect(backend.pendingReads, hasLength(1));
      }
    });

    test('a failed refresh keeps the list and says so', () async {
      final backend = _backend();
      final container = await _loaded(backend);
      backend.pendingReadStatus = 503;
      await _controller(container).refresh();
      final state = _state(container);
      expect(state.isLoaded, isTrue);
      expect(state.items, hasLength(3));
      expect(
        state.refreshFailure,
        FinancialRefreshFailure.temporarilyUnavailable,
      );
    });
  });

  group('keyset pagination', () {
    FakePendingBackend many() => _backend(
      pageSize: 2,
      items: [
        for (var i = 1; i <= 5; i += 1)
          FakePendingItem(
            index: i,
            date: '2026-09-${10 + i}',
            description: 'm$i',
          ),
      ],
    );

    test('pages append without duplicating or skipping', () async {
      final backend = many();
      final container = await _loaded(backend);
      expect(_ids(container), hasLength(2));
      expect(_state(container).hasMore, isTrue);

      while (_state(container).hasMore) {
        await _controller(container).loadMore();
      }
      final ids = _ids(container);
      expect(ids, hasLength(5));
      expect(ids.toSet(), hasLength(5));
      expect(ids, [for (var i = 5; i >= 1; i -= 1) pendingTestMovementId(i)]);
      expect(backend.pendingReads, hasLength(3));
      expect(backend.perRowRequests, 0);
      // The cursor of each read is the opaque value of the previous one.
      expect(backend.pendingReads[1].uri.queryParameters['cursor'], isNotNull);
    });

    test(
      'a row the server repeats on a later page is never listed twice',
      () async {
        final backend = many();
        final container = await _loaded(backend);
        final repeated = backend.items.firstWhere(
          (item) => item.id == _ids(container).first,
        );
        final fresh = FakePendingItem(index: 77, date: '2026-09-01');
        backend.pendingBodyOverride = jsonEncode({
          'items': [
            jsonDecode(repeated.json(financeTestOwnerId)),
            jsonDecode(fresh.json(financeTestOwnerId)),
          ],
          'nextCursor': null,
        });
        await _controller(container).loadMore();
        final ids = _ids(container);
        expect(ids.toSet(), hasLength(ids.length));
        expect(ids, hasLength(3));
        expect(ids.last, fresh.id);
      },
    );

    test('a failed next page keeps the items and retry is explicit', () async {
      final backend = many();
      final container = await _loaded(backend);
      backend
        ..failNextPendingReads = 1
        ..failNextPendingReadsStatus = 503;
      await _controller(container).loadMore();
      var state = _state(container);
      expect(state.items, hasLength(2));
      expect(
        state.loadMoreFailure,
        FinancialRefreshFailure.temporarilyUnavailable,
      );
      expect(state.hasMore, isTrue);
      expect(backend.pendingReads, hasLength(2), reason: 'no automatic retry');

      await _controller(container).loadMore();
      state = _state(container);
      expect(state.items, hasLength(4));
      expect(state.loadMoreFailure, FinancialRefreshFailure.none);
    });

    test('an invalid next page is rejected whole', () async {
      final backend = many();
      final container = await _loaded(backend);
      backend.pendingBodyOverride =
          '{"items":[{"movementId":"x"}],"nextCursor":null}';
      await _controller(container).loadMore();
      final state = _state(container);
      expect(state.items, hasLength(2));
      expect(state.loadMoreFailure, FinancialRefreshFailure.invalidResponse);
    });

    test('loadMore is a no-op without a cursor and never overlaps', () async {
      final backend = _backend();
      final container = await _loaded(backend);
      await _controller(container).loadMore();
      expect(backend.pendingReads, hasLength(1));

      final paged = many();
      final other = await _loaded(paged);
      paged.pendingGate = Completer<void>();
      final first = _controller(other).loadMore();
      await _controller(other).loadMore();
      paged.pendingGate!.complete();
      await first;
      expect(paged.pendingReads, hasLength(2));
    });
  });

  group('overlap', () {
    test('a write cannot start while a next page is loading', () async {
      final backend = _backend(
        pageSize: 1,
        items: [
          FakePendingItem(index: 1, date: '2026-09-12'),
          FakePendingItem(index: 2, date: '2026-09-11'),
        ],
      );
      final container = await _loaded(backend);
      backend.pendingGate = Completer<void>();
      final more = _controller(container).loadMore();
      await Future<void>.delayed(Duration.zero);
      expect(_state(container).isBusy, isTrue);
      final refused = await _controller(
        container,
      ).classify(pendingTestMovementId(1), _lazer);
      expect(refused.outcome, FinancialPendingActionOutcome.notAllowed);
      backend.pendingGate!.complete();
      await more;
      expect(backend.allocationPosts, 0);
      expect(_ids(container), hasLength(2));
    });
  });

  group('filters', () {
    test('filters go to the server and drop the old cursor', () async {
      final backend = _backend(
        pageSize: 1,
        items: [
          FakePendingItem(
            index: 1,
            date: '2026-09-12',
            effect: 'INCOME',
            amount: '10.00',
          ),
          FakePendingItem(index: 2, date: '2026-09-11'),
          FakePendingItem(
            index: 3,
            date: '2026-09-10',
            accountId: pendingTestAccountB,
          ),
        ],
      );
      final container = await _loaded(backend);
      await _controller(container).loadMore();
      expect(_state(container).items, hasLength(2));

      await _controller(container).setFilters(
        const FinancialPendingFilters(
          accountId: pendingTestAccountB,
          resultEffect: FinancialResultEffect.expense,
          ruleStatus: FinancialPendingRuleStatus.noMatch,
        ),
      );
      final query = backend.pendingReads.last.uri.queryParameters;
      expect(query['cursor'], isNull);
      expect(query['accountId'], pendingTestAccountB);
      expect(query['resultEffect'], 'EXPENSE');
      expect(query['ruleStatus'], 'NO_MATCH');
      expect(_ids(container), [pendingTestMovementId(3)]);

      await _controller(container).setFilters(FinancialPendingFilters.none);
      expect(_state(container).filters.isActive, isFalse);
      expect(backend.pendingReads.last.uri.queryParameters, {'limit': '50'});
    });

    test('an empty page with a cursor is not the end', () async {
      final backend = _backend()
        ..pendingBodyOverride = '{"items":[],"nextCursor":"after_abc"}';
      final container = _container(backend);
      await _controller(container).load();
      expect(_state(container).items, isEmpty);
      expect(_state(container).hasMore, isTrue);
    });

    test('a response that ignores the filter is rejected', () async {
      final backend = _backend();
      final container = await _loaded(backend);
      backend.pendingBodyOverride = jsonEncode({
        'items': [
          jsonDecode(
            FakePendingItem(
              index: 1,
              status: 'NO_MATCH',
            ).json(financeTestOwnerId),
          ),
        ],
        'nextCursor': null,
      });
      await _controller(container).setFilters(
        const FinancialPendingFilters(
          ruleStatus: FinancialPendingRuleStatus.matched,
        ),
      );
      expect(
        _state(container).refreshFailure,
        FinancialRefreshFailure.invalidResponse,
      );
      expect(
        _state(container).items,
        hasLength(3),
        reason: 'previous list kept',
      );
    });
  });

  group('apply a suggestion (explicit, one POST, canonical refresh)', () {
    test(
      'success: one POST, then the list is read again; no optimistic removal',
      () async {
        final backend = _backend();
        final container = await _loaded(backend);
        final movement = pendingTestMovementId(1);

        backend.pendingGate = Completer<void>();
        final future = _controller(container).applySuggestion(movement);
        await Future<void>.delayed(Duration.zero);
        await Future<void>.delayed(Duration.zero);
        // The write is done, the canonical read is still pending: the item stays.
        expect(backend.applyPosts, 1);
        expect(_ids(container), contains(movement));
        expect(_state(container).mutationMovementId, movement);

        backend.pendingGate!.complete();
        final result = await future;
        expect(result.outcome, FinancialPendingActionOutcome.ruleApplied);
        expect(result.reconciled, isTrue);
        expect(_ids(container), isNot(contains(movement)));
        expect(_state(container).mutationInFlight, isFalse);
        expect(backend.applyBodies.single, {
          'items': [
            {'movementId': movement, 'ruleId': _rule},
          ],
        });
        expect(backend.applyPosts, 1);
        expect(backend.pendingReads, hasLength(2));
      },
    );

    for (final (status, outcome) in [
      ('ALREADY_CLASSIFIED', FinancialPendingActionOutcome.alreadyClassified),
      ('AMBIGUOUS', FinancialPendingActionOutcome.stateChanged),
      ('NO_MATCH', FinancialPendingActionOutcome.stateChanged),
      ('INELIGIBLE', FinancialPendingActionOutcome.stateChanged),
      ('CONFLICT', FinancialPendingActionOutcome.stateChanged),
      ('FAILED', FinancialPendingActionOutcome.failed),
    ]) {
      test(
        'backend result $status is reported as it is and the item stays',
        () async {
          final backend = _backend()..applyResultStatus = status;
          final container = await _loaded(backend);
          final movement = pendingTestMovementId(1);
          final result = await _controller(container).applySuggestion(movement);
          expect(result.outcome, outcome);
          // Nothing was written, so the canonical read still lists it.
          expect(_ids(container), contains(movement));
          expect(backend.applyPosts, 1);
        },
      );
    }

    test(
      'the rule changed before the apply: the canonical state wins',
      () async {
        final backend = _backend();
        backend.onApply = (_) {
          // Another operator disabled the rule: now the item has no suggestion.
          final item = backend.items.firstWhere(
            (candidate) => candidate.id == pendingTestMovementId(1),
          );
          item
            ..status = 'NO_MATCH'
            ..ruleId = null
            ..categoryId = null;
        };
        backend.applyResultStatus = 'CONFLICT';
        final container = await _loaded(backend);
        final result = await _controller(
          container,
        ).applySuggestion(pendingTestMovementId(1));
        expect(result.outcome, FinancialPendingActionOutcome.stateChanged);
        final item = _state(container).itemOf(pendingTestMovementId(1))!;
        expect(item.ruleStatus, FinancialPendingRuleStatus.noMatch);
        expect(item.hasSuggestion, isFalse);
        expect(backend.applyPosts, 1);
      },
    );

    test(
      'classified elsewhere first: no recreation, the item is gone',
      () async {
        final backend = _backend()..applyResultStatus = 'ALREADY_CLASSIFIED';
        backend.onApply = (item) => backend.items = backend.items
            .where((candidate) => candidate.id != item['movementId'])
            .toList();
        final container = await _loaded(backend);
        final result = await _controller(
          container,
        ).applySuggestion(pendingTestMovementId(1));
        expect(result.outcome, FinancialPendingActionOutcome.alreadyClassified);
        expect(_ids(container), isNot(contains(pendingTestMovementId(1))));
      },
    );

    for (final (label, arrange, outcome)
        in <
          (
            String,
            void Function(FakePendingBackend),
            FinancialPendingActionOutcome,
          )
        >[
          (
            '409',
            (b) => b.applyStatus = 409,
            FinancialPendingActionOutcome.stateChanged,
          ),
          (
            '404',
            (b) => b.applyStatus = 404,
            FinancialPendingActionOutcome.rejected,
          ),
          (
            '422',
            (b) => b.applyStatus = 422,
            FinancialPendingActionOutcome.rejected,
          ),
          (
            '503',
            (b) => b.applyStatus = 503,
            FinancialPendingActionOutcome.unknownOutcome,
          ),
          (
            'transport failure',
            (b) => b.applyThrows = true,
            FinancialPendingActionOutcome.unknownOutcome,
          ),
          (
            'invalid 2xx',
            (b) => b.applyBodyOverride = '{"nonsense":true}',
            FinancialPendingActionOutcome.unknownOutcome,
          ),
        ]) {
      test(
        '$label: exactly one POST, one canonical read, never a retry',
        () async {
          final backend = _backend();
          arrange(backend);
          final container = await _loaded(backend);
          final result = await _controller(
            container,
          ).applySuggestion(pendingTestMovementId(1));
          expect(result.outcome, outcome);
          expect(result.reconciled, isTrue);
          expect(backend.applyPosts, 1);
          expect(backend.pendingReads, hasLength(2));
          expect(_ids(container), contains(pendingTestMovementId(1)));
        },
      );
    }

    test(
      'an apply whose response claims another rule is unknown, not success',
      () async {
        final backend = _backend()
          ..applyBodyOverride =
              '{"accountId":"$pendingTestAccountA","requested":1,'
              '"counts":{"classified":1,"alreadyClassified":0,"ambiguous":0,'
              '"noMatch":0,"ineligible":0,"conflict":0,"failed":0},'
              '"results":[{"movementId":"${pendingTestMovementId(1)}",'
              '"status":"CLASSIFIED","ruleId":"${financeTestRuleId(9)}",'
              '"allocationSetId":"e5000000-0000-4000-8000-000000000901"}]}';
        final container = await _loaded(backend);
        final result = await _controller(
          container,
        ).applySuggestion(pendingTestMovementId(1));
        expect(result.outcome, FinancialPendingActionOutcome.unknownOutcome);
        expect(backend.applyPosts, 1);
      },
    );

    test('a failed canonical read leaves the item, marks the list stale and '
        'blocks further writes until refreshed', () async {
      final backend = _backend();
      final container = await _loaded(backend);
      backend
        ..failNextPendingReads = 1
        ..failNextPendingReadsStatus = 503;
      final result = await _controller(
        container,
      ).applySuggestion(pendingTestMovementId(1));
      expect(result.outcome, FinancialPendingActionOutcome.ruleApplied);
      expect(result.reconciled, isFalse);
      expect(_state(container).trusted, isFalse);
      expect(_ids(container), contains(pendingTestMovementId(1)));

      // A write that is otherwise allowed (owned item, eligible category) is
      // refused only because the list can no longer be trusted.
      final blockedClassify = await _controller(
        container,
      ).classify(pendingTestMovementId(2), _lazer);
      expect(blockedClassify.outcome, FinancialPendingActionOutcome.notAllowed);
      final blocked = await _controller(
        container,
      ).applySuggestion(pendingTestMovementId(1));
      expect(blocked.outcome, FinancialPendingActionOutcome.notAllowed);
      expect(backend.applyPosts, 1);
      expect(backend.allocationPosts, 0);

      await _controller(container).refresh();
      expect(_state(container).trusted, isTrue);
      expect(_ids(container), isNot(contains(pendingTestMovementId(1))));
    });

    test(
      'an AMBIGUOUS or unsuggested item is never applied automatically',
      () async {
        final backend = _backend();
        final container = await _loaded(backend);
        for (final index in [2, 3]) {
          final result = await _controller(
            container,
          ).applySuggestion(pendingTestMovementId(index));
          expect(result.outcome, FinancialPendingActionOutcome.notAllowed);
        }
        expect(backend.applyPosts, 0);
      },
    );

    test('a read-only item offers no write and sends nothing', () async {
      final backend = _backend(
        items: [
          FakePendingItem(
            index: 1,
            accountId: pendingTestAccountB,
            status: 'MATCHED',
            ruleId: _rule,
            categoryId: _mercado,
            canClassify: false,
          ),
        ],
      );
      final container = await _loaded(backend);
      expect(
        (await _controller(
          container,
        ).applySuggestion(pendingTestMovementId(1))).outcome,
        FinancialPendingActionOutcome.notAllowed,
      );
      expect(
        (await _controller(
          container,
        ).classify(pendingTestMovementId(1), _mercado)).outcome,
        FinancialPendingActionOutcome.notAllowed,
      );
      expect(backend.applyPosts + backend.allocationPosts, 0);
    });

    test(
      'an archived account is read-only even when the server lists the item',
      () async {
        final backend = _backend()..accountAStatus = 'ARCHIVED';
        final container = await _loaded(backend);
        expect(
          (await _controller(
            container,
          ).applySuggestion(pendingTestMovementId(1))).outcome,
          FinancialPendingActionOutcome.notAllowed,
        );
        expect(backend.applyPosts, 0);
      },
    );

    test('a second action while one is in flight is refused', () async {
      final backend = _backend()..applyGate = Completer<void>();
      final container = await _loaded(backend);
      final first = _controller(
        container,
      ).applySuggestion(pendingTestMovementId(1));
      await Future<void>.delayed(Duration.zero);
      final second = await _controller(
        container,
      ).classify(pendingTestMovementId(2), _lazer);
      expect(second.outcome, FinancialPendingActionOutcome.notAllowed);
      backend.applyGate!.complete();
      await first;
      expect(backend.applyPosts, 1);
      expect(backend.allocationPosts, 0);
    });
  });

  group('manual classification (the #245 endpoint, single category)', () {
    test(
      'writes one share with the exact Movement money, then re-reads',
      () async {
        final backend = _backend();
        final container = await _loaded(backend);
        final movement = pendingTestMovementId(2);
        final result = await _controller(container).classify(movement, _lazer);
        expect(
          result.outcome,
          FinancialPendingActionOutcome.manuallyClassified,
        );
        expect(backend.allocationMovementIds, [movement]);
        final body = backend.allocationBodies.single;
        expect(body['allocations'], [
          {'categoryId': _lazer, 'amount': '-10.00', 'currency': 'BRL'},
        ]);
        expect(_ids(container), isNot(contains(movement)));
        expect(backend.pendingReads, hasLength(2));
      },
    );

    test(
      'an AMBIGUOUS item is resolved by choosing the category manually',
      () async {
        final backend = _backend();
        final container = await _loaded(backend);
        final result = await _controller(
          container,
        ).classify(pendingTestMovementId(3), _mercado);
        expect(
          result.outcome,
          FinancialPendingActionOutcome.manuallyClassified,
        );
        expect(backend.applyPosts, 0);
      },
    );

    test('only categories the account may use are accepted', () async {
      final backend = _backend();
      final container = await _loaded(backend);
      for (final category in [
        financeTestCategoryId(3), // another owner's PERSONAL
        financeTestCategoryId(4), // DISABLED
        financeTestCategoryId(99), // unknown
      ]) {
        final result = await _controller(
          container,
        ).classify(pendingTestMovementId(2), category);
        expect(result.outcome, FinancialPendingActionOutcome.notAllowed);
      }
      expect(backend.allocationPosts, 0);
    });

    test('409 (classified meanwhile): reconciled, never retried', () async {
      final backend = _backend()..allocationStatus = 409;
      final container = await _loaded(backend);
      final result = await _controller(
        container,
      ).classify(pendingTestMovementId(2), _lazer);
      expect(result.outcome, FinancialPendingActionOutcome.stateChanged);
      expect(backend.allocationPosts, 1);
      expect(backend.pendingReads, hasLength(2));
    });

    test('404 and 422 are rejections, never retried', () async {
      for (final status in [404, 422]) {
        final backend = _backend()..allocationStatus = status;
        final container = await _loaded(backend);
        final result = await _controller(
          container,
        ).classify(pendingTestMovementId(2), _lazer);
        expect(result.outcome, FinancialPendingActionOutcome.rejected);
        expect(backend.allocationPosts, 1);
      }
    });

    test(
      'unknown outcome: one POST, one read, and the key survives an explicit '
      'identical retry',
      () async {
        final backend = _backend()..allocationThrows = true;
        final container = await _loaded(backend);
        final movement = pendingTestMovementId(2);
        final first = await _controller(container).classify(movement, _lazer);
        expect(first.outcome, FinancialPendingActionOutcome.unknownOutcome);
        expect(backend.allocationPosts, 1);
        expect(_ids(container), contains(movement));

        backend.allocationThrows = false;
        final second = await _controller(container).classify(movement, _lazer);
        expect(
          second.outcome,
          FinancialPendingActionOutcome.manuallyClassified,
        );
        expect(backend.allocationPosts, 2);
        expect(
          backend.allocationBodies[0]['idempotencyKey'],
          backend.allocationBodies[1]['idempotencyKey'],
        );
      },
    );

    test(
      'a different category is a different attempt with a fresh key',
      () async {
        final backend = _backend()..allocationThrows = true;
        final container = await _loaded(backend);
        final movement = pendingTestMovementId(2);
        await _controller(container).classify(movement, _lazer);
        await _controller(container).classify(movement, _mercado);
        expect(
          backend.allocationBodies[0]['idempotencyKey'],
          isNot(backend.allocationBodies[1]['idempotencyKey']),
        );
      },
    );

    test(
      'classified by someone else during the attempt: the item just leaves',
      () async {
        final backend = _backend()..allocationStatus = 409;
        backend.onAllocation = (id) => backend.items = backend.items
            .where((candidate) => candidate.id != id)
            .toList();
        final container = await _loaded(backend);
        await _controller(container).classify(pendingTestMovementId(2), _lazer);
        expect(_ids(container), isNot(contains(pendingTestMovementId(2))));
      },
    );
  });

  group('contract of the response', () {
    Future<Object?> parse(String body) async {
      final backend = _backend()..pendingBodyOverride = body;
      final container = _container(backend);
      await _controller(container).load();
      return _state(container).phase;
    }

    String item({
      String status = 'NO_MATCH',
      String? rule,
      String? category,
      String effect = 'EXPENSE',
      String amount = '-10.00',
      String extra = '',
    }) =>
        '{"movementId":"${pendingTestMovementId(1)}","accountId":"$pendingTestAccountA",'
        '"money":{"amount":"$amount","currency":"BRL"},"resultEffect":"$effect",'
        '"effectiveDate":"2026-09-10","competenceDate":"2026-09-10",'
        '"description":"Padaria","accountVisibilityScope":"HOUSEHOLD",'
        '"accountOwnerOperatorId":"$financeTestOwnerId","canClassify":true,'
        '"ruleStatus":"$status","matchedRuleId":${rule == null ? 'null' : '"$rule"'},'
        '"suggestedCategoryId":${category == null ? 'null' : '"$category"'}$extra}';

    test('accepts a well-formed page', () async {
      expect(
        await parse('{"items":[${item()}],"nextCursor":null}'),
        FinancialLoadPhase.loaded,
      );
    });

    for (final (label, body) in <(String, String)>[
      ('matched without a rule', '{"items":[__M__],"nextCursor":null}'),
      ('unexpected top-level key', '{"items":[],"nextCursor":null,"total":3}'),
      ('missing nextCursor', '{"items":[]}'),
      ('bad cursor characters', '{"items":[],"nextCursor":"a b"}'),
      ('cursor too long', '{"items":[],"nextCursor":"${'a' * 257}"}'),
      ('items not a list', '{"items":{},"nextCursor":null}'),
    ]) {
      test('rejects $label', () async {
        final broken = body.replaceAll('__M__', item(status: 'MATCHED'));
        expect(await parse(broken), FinancialLoadPhase.invalidResponse);
      });
    }

    test('rejects a NO_MATCH item that carries a rule or category', () async {
      expect(
        await parse('{"items":[${item(rule: _rule)}],"nextCursor":null}'),
        FinancialLoadPhase.invalidResponse,
      );
      expect(
        await parse(
          '{"items":[${item(category: _mercado)}],"nextCursor":null}',
        ),
        FinancialLoadPhase.invalidResponse,
      );
    });

    test(
      'rejects NEUTRAL, wrong sign, unknown fields, duplicate rows, order',
      () async {
        expect(
          await parse(
            '{"items":[${item(effect: 'NEUTRAL')}],"nextCursor":null}',
          ),
          FinancialLoadPhase.invalidResponse,
        );
        expect(
          await parse('{"items":[${item(amount: '10.00')}],"nextCursor":null}'),
          FinancialLoadPhase.invalidResponse,
        );
        expect(
          await parse(
            '{"items":[${item(extra: ',"categoryId":"x"')}],"nextCursor":null}',
          ),
          FinancialLoadPhase.invalidResponse,
        );
        expect(
          await parse('{"items":[${item()},${item()}],"nextCursor":null}'),
          FinancialLoadPhase.invalidResponse,
        );
        final older = FakePendingItem(
          index: 2,
          date: '2026-09-01',
        ).json(financeTestOwnerId);
        final newer = FakePendingItem(
          index: 3,
          date: '2026-09-20',
        ).json(financeTestOwnerId);
        expect(
          await parse('{"items":[$older,$newer],"nextCursor":null}'),
          FinancialLoadPhase.invalidResponse,
        );
      },
    );

    test('a page above the requested limit is invalid', () async {
      final many = [
        for (var i = 1; i <= 51; i += 1)
          FakePendingItem(index: i).json(financeTestOwnerId),
      ];
      expect(
        await parse('{"items":[${many.join(',')}],"nextCursor":null}'),
        FinancialLoadPhase.invalidResponse,
      );
    });
  });
}
