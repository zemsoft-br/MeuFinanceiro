import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import '../../support/fake_auth_transport.dart';
import '../../support/fake_finance_backend.dart';
import '../../support/fake_goal_backend.dart';

FinancialCoreApi _api(FakeAuthTransport transport) => FinancialCoreApi(
  AuthenticatedApiClient(
    transport: transport,
    tokenVault: SessionTokenVault()..store(financeTestToken),
    apiBaseUri: Uri.parse('http://localhost/api/v1/'),
    timeout: const Duration(seconds: 2),
    onUnauthorized: () {},
  ),
);

FakeGoalBackend _backend() {
  final backend = FakeGoalBackend(
    goals: [FakeGoal(index: 1, target: '1000')],
    accounts: [
      FakeGoalAccount(index: 1, name: 'Conta casa', balance: '500'),
      FakeGoalAccount(index: 2, name: 'Outra', balance: '50'),
    ],
  );
  backend.seed(backend.goals.single, backend.accounts[0], 'ALLOCATE', '300');
  backend.seed(backend.goals.single, backend.accounts[0], 'RELEASE', '50');
  return backend;
}

void main() {
  group('requests', () {
    test('listGoals asks for exactly the goal list with GET', () async {
      final backend = _backend();
      final goals = await _api(backend.transport).listGoals();
      final call = backend.calls.single;
      expect(call.method, AuthHttpMethod.get);
      expect(call.uri.path, '/api/v1/finance/goals');
      expect(call.uri.query, isEmpty);
      expect(goals.single.allocated.amount, '250');
      expect(goals.single.remainingTarget.amount, '750');
      expect(goals.single.progressPercent, '25.00');
      expect(
        goals.single.progressStatus,
        FinancialGoalProgressStatus.inProgress,
      );
    });

    test(
      'the create body carries the key, strict fields and no owner',
      () async {
        final backend = _backend();
        final input = FinancialGoalCreateInput(
          title: '  Viagem  ',
          description: '  ',
          visibilityScope: FinancialVisibilityScope.household,
          currency: 'BRL',
          targetAmount: '2500.50',
          targetDate: '2027-06-01',
        );
        final goal = await _api(backend.transport).createGoal(input);
        expect(goal.title, 'Viagem');
        expect(goal.description, isNull);
        final body = backend.postBodies.single;
        expect(body.keys.toSet(), {
          'idempotencyKey',
          'title',
          'description',
          'visibilityScope',
          'currency',
          'targetAmount',
          'targetDate',
        });
        expect(body['targetAmount'], isA<String>());
        expect(body['title'], 'Viagem');
        expect(body['description'], isNull);
        expect(body['idempotencyKey'], input.idempotencyKey);
      },
    );

    test('the allocation body is explicit and amounts stay text', () async {
      final backend = _backend();
      final event = await _api(backend.transport).allocateGoal(
        backend.goals.single.id,
        FinancialGoalAllocationInput(
          operation: FinancialGoalOperation.allocate,
          accountId: backend.accounts[0].id,
          amount: '100.5',
          currency: 'BRL',
        ),
      );
      expect(event.operation, FinancialGoalOperation.allocate);
      expect(event.amount.amount, '100.5');
      final call = backend.calls.single;
      expect(call.method, AuthHttpMethod.post);
      expect(
        call.uri.path,
        '/api/v1/finance/goals/${backend.goals.single.id}/allocations',
      );
      final body = backend.allocationBodies.single;
      expect(body.keys.toSet(), {
        'idempotencyKey',
        'operation',
        'accountId',
        'amount',
        'currency',
      });
      expect(body['operation'], 'ALLOCATE');
      expect(body['amount'], isA<String>());
    });

    test('replace sends expectedVersion and is cross-checked', () async {
      final backend = _backend();
      final goal = await _api(backend.transport).replaceGoal(
        backend.goals.single.id,
        FinancialGoalReplaceInput(
          expectedVersion: 1,
          title: 'Novo',
          description: 'Texto',
          currency: 'BRL',
          targetAmount: '1200',
        ),
      );
      expect(goal.version, 2);
      expect(backend.putBodies.single['expectedVersion'], 1);
      expect(backend.putBodies.single.containsKey('visibilityScope'), isFalse);
    });

    test('there is no delete, patch or other verb', () async {
      final backend = _backend();
      final api = _api(backend.transport);
      await api.listGoals();
      await api.getGoalSummary(backend.goals.single.id);
      expect(backend.calls.map((call) => call.method).toSet(), {
        AuthHttpMethod.get,
      });
    });
  });

  group('inputs reject invalid material before any request', () {
    test('create', () {
      FinancialGoalCreateInput make({
        String title = 'Meta',
        String currency = 'BRL',
        String amount = '10',
        String? date,
        FinancialVisibilityScope scope = FinancialVisibilityScope.household,
      }) => FinancialGoalCreateInput(
        title: title,
        visibilityScope: scope,
        currency: currency,
        targetAmount: amount,
        targetDate: date,
      );
      expect(() => make(title: ''), throwsFormatException);
      expect(() => make(title: 'x' * 97), throwsFormatException);
      expect(() => make(currency: 'br'), throwsFormatException);
      expect(() => make(amount: '0'), throwsFormatException);
      expect(() => make(amount: '-1'), throwsFormatException);
      expect(() => make(amount: '1e3'), throwsFormatException);
      expect(() => make(amount: '1.123456789'), throwsFormatException);
      expect(() => make(date: '2027-02-30'), throwsFormatException);
      expect(() => make(date: '27-01-01'), throwsFormatException);
      expect(
        () => make(scope: FinancialVisibilityScope.shared),
        throwsFormatException,
      );
      expect(make(date: '').targetDate, isNull);
    });

    test('allocation and replace', () {
      expect(
        () => FinancialGoalAllocationInput(
          operation: FinancialGoalOperation.release,
          accountId: 'nope',
          amount: '1',
          currency: 'BRL',
        ),
        throwsFormatException,
      );
      expect(
        () => FinancialGoalAllocationInput(
          operation: FinancialGoalOperation.release,
          accountId: goalTestAccountId(1),
          amount: '0',
          currency: 'BRL',
        ),
        throwsFormatException,
      );
      expect(
        () => FinancialGoalReplaceInput(
          expectedVersion: 0,
          title: 'x',
          currency: 'BRL',
          targetAmount: '1',
        ),
        throwsFormatException,
      );
    });

    test('the attempt key follows the material, not the idempotency key', () {
      FinancialGoalAllocationInput make(String amount, {String? key}) =>
          FinancialGoalAllocationInput(
            operation: FinancialGoalOperation.allocate,
            accountId: goalTestAccountId(1),
            amount: amount,
            currency: 'BRL',
            idempotencyKey: key,
          );
      expect(make('10').attemptKey, make('10.0').attemptKey);
      expect(make('10').attemptKey, isNot(make('11').attemptKey));
      expect(make('10').idempotencyKey, isNot(make('10').idempotencyKey));
    });
  });

  group('responses are validated strictly', () {
    Future<void> expectInvalidList(String body) async {
      final backend = _backend()..listBodyOverride = body;
      await expectLater(
        _api(backend.transport).listGoals(),
        throwsFormatException,
      );
    }

    test('a list with an unknown key or a duplicate goal is rejected', () async {
      final backend = _backend();
      final item = backend.listItemJson(backend.goals.single);
      await expectInvalidList('{"items":[$item,$item]}');
      await expectInvalidList('{"items":[],"extra":1}');
      await expectInvalidList('{"items":[{}]}');
      await expectInvalidList(
        '{"items":[${item.replaceFirst('"progressPercent":"25.00"', '"progressPercent":"25"')}]}',
      );
      await expectInvalidList(
        '{"items":[${item.replaceFirst('"IN_PROGRESS"', '"WHATEVER"')}]}',
      );
    });

    test('a goal with a SHARED audience or another currency is rejected', () async {
      final backend = _backend();
      final item = backend.listItemJson(backend.goals.single);
      await expectInvalidList(
        '{"items":[${item.replaceFirst('"visibilityScope":"HOUSEHOLD"', '"visibilityScope":"SHARED"')}]}',
      );
      await expectInvalidList(
        '{"items":[${item.replaceFirst('"allocated":{"amount":"250","currency":"BRL"}', '"allocated":{"amount":"250","currency":"USD"}')}]}',
      );
      await expectInvalidList(
        '{"items":[${item.replaceFirst('"allocated":{"amount":"250"', '"allocated":{"amount":-1')}]}',
      );
    });

    test('a summary that contradicts itself is rejected', () async {
      final backend = _backend();
      final goal = backend.goals.single;
      Future<void> expectInvalid(String body) async {
        backend.summaryBodyOverride = body;
        await expectLater(
          _api(backend.transport).getGoalSummary(goal.id),
          throwsFormatException,
        );
      }

      final ok = backend.summaryJson(goal);
      expect(
        (await _api(backend.transport).getGoalSummary(goal.id)).accounts,
        hasLength(1),
      );
      await expectInvalid(
        ok.replaceFirst(
          '"hasInsufficientBacking":false',
          '"hasInsufficientBacking":true',
        ),
      );
      await expectInvalid(
        ok.replaceFirst(
          '"backingStatus":"COVERED"',
          '"backingStatus":"INSUFFICIENT"',
        ),
      );
      await expectInvalid(
        ok.replaceFirst(
          '"goalId":"${goal.id}"',
          '"goalId":"${goalTestId(77)}"',
        ),
      );
      await expectInvalid(
        ok.replaceFirst('"events":[', '"unknown":1,"events":['),
      );
      await expectInvalid(
        ok.replaceFirst(
          '"target":{"amount":"1000","currency":"BRL"},"allocated"',
          '"target":{"amount":"999","currency":"BRL"},"allocated"',
        ),
      );
    });

    test('mirrored responses are required for writes', () async {
      final backend = _backend();
      final goal = backend.goals.single;
      backend.allocBodyOverride = backend.eventJson(
        FakeGoalEvent(
          index: 90,
          goalId: goal.id,
          accountId: backend.accounts[0].id,
          operation: 'RELEASE',
          amount: '10',
        ),
        'BRL',
      );
      await expectLater(
        _api(backend.transport).allocateGoal(
          goal.id,
          FinancialGoalAllocationInput(
            operation: FinancialGoalOperation.allocate,
            accountId: backend.accounts[0].id,
            amount: '10',
            currency: 'BRL',
          ),
        ),
        throwsFormatException,
      );
      backend.postBodyOverride = backend.goalJson(
        FakeGoal(index: 50, title: 'Outra'),
      );
      await expectLater(
        _api(backend.transport).createGoal(
          FinancialGoalCreateInput(
            title: 'Esperada',
            visibilityScope: FinancialVisibilityScope.household,
            currency: 'BRL',
            targetAmount: '10',
          ),
        ),
        throwsFormatException,
      );
      backend.putBodyOverride = backend.goalJson(goal);
      await expectLater(
        _api(backend.transport).replaceGoal(
          goal.id,
          FinancialGoalReplaceInput(
            expectedVersion: 1,
            title: goal.title,
            currency: 'BRL',
            targetAmount: goal.target,
          ),
        ),
        throwsFormatException,
      );
    });

    test('the summary id must match the requested goal', () async {
      final backend = _backend();
      backend.summaryBodyOverride = backend.summaryJson(
        FakeGoal(index: 9, title: 'Outra'),
      );
      await expectLater(
        _api(backend.transport).getGoalSummary(backend.goals.single.id),
        throwsFormatException,
      );
    });
  });

  test('summary numbers come from the server untouched', () async {
    final backend = _backend();
    backend.accounts[0].balance = '100'; // below the 250 allocated
    final summary = await _api(
      backend.transport,
    ).getGoalSummary(backend.goals.single.id);

    expect(summary.allocated.amount, '250');
    expect(summary.remainingTarget.amount, '750');
    expect(summary.surplus.amount, '0');
    expect(summary.progressPercent, '25.00');
    expect(summary.hasInsufficientBacking, isTrue);
    final account = summary.accounts.single;
    expect(account.backingStatus, FinancialGoalBackingStatus.insufficient);
    expect(account.shortfall.amount, '150');
    expect(account.accountBalance.amount, '100');
    expect(summary.events.map((event) => event.operation), [
      FinancialGoalOperation.allocate,
      FinancialGoalOperation.release,
    ]);
  });
}
