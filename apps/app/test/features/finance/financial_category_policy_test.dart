import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

const _owner = '30000000-0000-4000-8000-000000000003';
const _other = '31000000-0000-4000-8000-000000000031';
String _id(int n) => 'a1000000-0000-4000-8000-${n.toString().padLeft(12, '0')}';

FinancialAccount _account(
  FinancialVisibilityScope scope, {
  FinancialAccountStatus status = FinancialAccountStatus.active,
}) => FinancialAccount(
  accountId: '40000000-0000-4000-8000-000000000004',
  ownerOperatorId: _owner,
  visibilityScope: scope,
  accountType: FinancialAccountType.checking,
  customTypeName: null,
  name: 'Conta',
  currency: 'BRL',
  status: status,
  createdAt: DateTime.utc(2026),
  updatedAt: DateTime.utc(2026),
  archivedAt: status == FinancialAccountStatus.archived
      ? DateTime.utc(2026, 2)
      : null,
);

FinancialCategory _category(
  int n, {
  FinancialVisibilityScope scope = FinancialVisibilityScope.household,
  String owner = _owner,
  String? parentId,
  FinancialCategoryStatus status = FinancialCategoryStatus.active,
  String? name,
}) => FinancialCategory(
  categoryId: _id(n),
  ownerOperatorId: owner,
  visibilityScope: scope,
  parentId: parentId,
  name: name ?? 'Cat $n',
  status: status,
  createdAt: DateTime.utc(2026),
  updatedAt: DateTime.utc(2026),
  disabledAt: status == FinancialCategoryStatus.disabled
      ? DateTime.utc(2026, 2)
      : null,
);

FinancialMovement _movement({
  String effect = 'EXPENSE',
  FinancialMovementRole role = FinancialMovementRole.standard,
}) {
  final resultEffect = FinancialResultEffect.parse(effect);
  final reversal = role == FinancialMovementRole.reversal;
  return FinancialMovement(
    movementId: '60000000-0000-4000-8000-000000000001',
    accountId: '40000000-0000-4000-8000-000000000004',
    money: FinancialMoneyWire(amount: '-10', currency: 'BRL'),
    resultEffect: resultEffect,
    role: role,
    effectiveDate: '2026-09-10',
    competenceDate: '2026-09-10',
    description: reversal ? null : 'x',
    reversalOfId: reversal ? '60000000-0000-4000-8000-000000000002' : null,
    reversalReason: reversal ? 'erro' : null,
    createdAt: DateTime.utc(2026, 9, 10),
  );
}

FinancialMovementAllocation _allocation(List<int> categories) =>
    FinancialMovementAllocation(
      allocationSetId: 'e5000000-0000-4000-8000-000000000001',
      movementId: '60000000-0000-4000-8000-000000000001',
      revision: 1,
      supersedesId: null,
      allocations: [
        for (final n in categories)
          FinancialAllocationShare(
            categoryId: _id(n),
            money: FinancialMoneyWire(amount: '-1', currency: 'BRL'),
          ),
      ],
      createdAt: DateTime.utc(2026, 9, 20),
    );

void main() {
  group('audience matrix mirrors ADR-0022', () {
    bool eligible(
      FinancialVisibilityScope accountScope,
      FinancialCategory category,
    ) => isFinancialCategoryEligibleForAccount(
      category: category,
      account: _account(accountScope),
    );

    test('PERSONAL account', () {
      const scope = FinancialVisibilityScope.personal;
      expect(
        eligible(scope, _category(1, scope: FinancialVisibilityScope.personal)),
        isTrue,
        reason: 'PERSONAL of the same owner',
      );
      expect(
        eligible(
          scope,
          _category(1, scope: FinancialVisibilityScope.personal, owner: _other),
        ),
        isFalse,
        reason: 'PERSONAL of another owner',
      );
      expect(eligible(scope, _category(1)), isTrue, reason: 'HOUSEHOLD');
      expect(
        eligible(scope, _category(1, status: FinancialCategoryStatus.disabled)),
        isFalse,
        reason: 'DISABLED',
      );
    });

    test('SHARED account', () {
      const scope = FinancialVisibilityScope.shared;
      expect(
        eligible(scope, _category(1, scope: FinancialVisibilityScope.personal)),
        isFalse,
      );
      expect(eligible(scope, _category(1)), isTrue);
    });

    test('HOUSEHOLD account', () {
      const scope = FinancialVisibilityScope.household;
      expect(
        eligible(scope, _category(1, scope: FinancialVisibilityScope.personal)),
        isFalse,
      );
      expect(eligible(scope, _category(1)), isTrue);
      expect(
        eligible(scope, _category(1, status: FinancialCategoryStatus.disabled)),
        isFalse,
      );
    });

    test('a SHARED category is never eligible anywhere', () {
      final shared = _category(1, scope: FinancialVisibilityScope.shared);
      for (final scope in FinancialVisibilityScope.values) {
        expect(eligible(scope, shared), isFalse);
      }
    });
  });

  group('picker list', () {
    test('contains only ACTIVE eligible categories, hierarchy-sorted', () {
      final index = FinancialCategoryIndex.build([
        _category(1, name: 'Moradia'),
        _category(2, name: 'Energia', parentId: _id(1)),
        _category(3, name: 'Alimentação'),
        _category(4, name: 'Antiga', status: FinancialCategoryStatus.disabled),
        _category(5, name: 'Minha', scope: FinancialVisibilityScope.personal),
        _category(
          6,
          name: 'Do outro',
          scope: FinancialVisibilityScope.personal,
          owner: _other,
        ),
      ]);

      final personal = eligibleFinancialCategories(
        index: index,
        account: _account(FinancialVisibilityScope.personal),
      );
      expect(personal.map((item) => index.pathLabel(item.categoryId)), [
        'Alimentação',
        'Minha',
        'Moradia',
        'Moradia > Energia',
      ]);

      final household = eligibleFinancialCategories(
        index: index,
        account: _account(FinancialVisibilityScope.household),
      );
      expect(household.map((item) => item.name), [
        'Alimentação',
        'Moradia',
        'Energia',
      ]);
    });
  });

  group('category creation context', () {
    test('scopes offered per account scope', () {
      expect(
        financialCategoryCreationScopes(
          _account(FinancialVisibilityScope.personal),
        ),
        [FinancialVisibilityScope.personal, FinancialVisibilityScope.household],
      );
      for (final scope in [
        FinancialVisibilityScope.shared,
        FinancialVisibilityScope.household,
      ]) {
        expect(financialCategoryCreationScopes(_account(scope)), [
          FinancialVisibilityScope.household,
        ]);
      }
      for (final scope in FinancialVisibilityScope.values) {
        expect(
          financialCategoryCreationScopes(_account(scope)),
          isNot(contains(FinancialVisibilityScope.shared)),
        );
      }
    });

    test('parents are active, same scope and owned by the operator', () {
      final index = FinancialCategoryIndex.build([
        _category(1, name: 'Casa'),
        _category(2, name: 'Alheia', owner: _other),
        _category(3, name: 'Velha', status: FinancialCategoryStatus.disabled),
        _category(4, name: 'Minha', scope: FinancialVisibilityScope.personal),
      ]);

      expect(
        eligibleFinancialCategoryParents(
          index: index,
          scope: FinancialVisibilityScope.household,
          operatorId: _owner,
        ).map((item) => item.name),
        ['Casa'],
      );
      expect(
        eligibleFinancialCategoryParents(
          index: index,
          scope: FinancialVisibilityScope.personal,
          operatorId: _owner,
        ).map((item) => item.name),
        ['Minha'],
      );
    });
  });

  group('classification eligibility', () {
    bool can({
      FinancialAccount? account,
      FinancialMovement? movement,
      FinancialMovementAllocation? allocation,
      String? operatorId = _owner,
    }) => canClassifyFinancialMovementSimply(
      account: account ?? _account(FinancialVisibilityScope.personal),
      movement: movement ?? _movement(),
      currentAllocation: allocation,
      operatorId: operatorId,
    );

    test('only STANDARD income/expense, unclassified, active, owner', () {
      expect(can(), isTrue);
      expect(can(movement: _movement(effect: 'INCOME')), isTrue);
      expect(can(movement: _movement(effect: 'NEUTRAL')), isFalse);
      expect(
        can(movement: _movement(role: FinancialMovementRole.reversal)),
        isFalse,
      );
      expect(can(allocation: _allocation([1])), isFalse);
      expect(can(operatorId: _other), isFalse);
      expect(can(operatorId: null), isFalse);
      expect(
        can(
          account: _account(
            FinancialVisibilityScope.personal,
            status: FinancialAccountStatus.archived,
          ),
        ),
        isFalse,
      );
    });
  });

  group('labels', () {
    final index = FinancialCategoryIndex.build([
      _category(1, name: 'Moradia'),
      _category(2, name: 'Energia', parentId: _id(1)),
      _category(3, name: 'Antiga', status: FinancialCategoryStatus.disabled),
    ]);

    String label(FinancialMovement movement, FinancialMovementAllocation? a) =>
        financialMovementClassificationLabel(
          movement: movement,
          allocation: a,
          index: index,
        );

    test('Sem categoria, single, hierarchy, disabled and N categorias', () {
      expect(label(_movement(), null), 'Sem categoria');
      expect(label(_movement(), _allocation([1])), 'Moradia');
      expect(label(_movement(), _allocation([2])), 'Moradia > Energia');
      expect(label(_movement(), _allocation([3])), 'Antiga');
      expect(label(_movement(), _allocation([1, 2, 3])), '3 categorias');
    });

    test('non-classifiable movements are not a pending task', () {
      expect(label(_movement(effect: 'NEUTRAL'), null), 'Não se aplica');
      expect(
        label(_movement(role: FinancialMovementRole.reversal), null),
        'Não se aplica',
      );
    });

    test('an unknown category is an inconsistency, never a silent name', () {
      expect(
        () => label(_movement(), _allocation([42])),
        throwsFormatException,
      );
    });
  });

  group('index', () {
    FinancialCategory node(int n, int? parent) => _category(
      n,
      name: 'N$n',
      parentId: parent == null ? null : _id(parent),
    );
    List<FinancialCategory> chain(int depth) => [
      for (var i = 1; i <= depth; i++) node(i, i == 1 ? null : i - 1),
    ];

    test('has no depth limit: long acyclic chains stay valid', () {
      for (final depth in [8, 9, 20, 2000]) {
        final index = FinancialCategoryIndex.build(chain(depth));
        final label = index.pathLabel(_id(depth))!;
        expect(label.split(' > '), hasLength(depth), reason: 'depth $depth');
        expect(label, startsWith('N1 > N2'));
        expect(label, endsWith('N$depth'));
      }
    });

    test('a long chain is valid regardless of the order it arrives in', () {
      final shuffled = chain(30).reversed.toList()..shuffle();
      final index = FinancialCategoryIndex.build(shuffled);
      expect(index.pathLabel(_id(30))!.split(' > '), hasLength(30));
    });

    test('siblings and shared parents are not cycles', () {
      final index = FinancialCategoryIndex.build([
        node(1, null),
        node(2, 1),
        node(3, 1),
        node(4, 2),
        node(5, 3),
      ]);
      expect(index.pathLabel(_id(4)), 'N1 > N2 > N4');
      expect(index.pathLabel(_id(5)), 'N1 > N3 > N5');
    });

    test('rejects duplicates, unknown parents, cycles and self reference', () {
      expect(
        () => FinancialCategoryIndex.build([_category(1), _category(1)]),
        throwsFormatException,
      );
      expect(
        () => FinancialCategoryIndex.build([_category(1, parentId: _id(9))]),
        throwsFormatException,
      );
      expect(
        () => FinancialCategoryIndex.build([
          _category(1, parentId: _id(2)),
          _category(2, parentId: _id(1)),
        ]),
        throwsFormatException,
      );
      expect(
        () => FinancialCategoryIndex.build([_category(1, parentId: _id(1))]),
        throwsFormatException,
      );
    });

    test('a cycle hidden behind a long valid chain is still rejected', () {
      expect(
        () => FinancialCategoryIndex.build([
          node(1, null),
          node(2, 1),
          node(3, 2),
          // 4 -> 5 -> 6 -> 4 hangs off the valid chain.
          node(4, 6),
          node(5, 4),
          node(6, 5),
          node(7, 3),
        ]),
        throwsFormatException,
      );
    });

    test('a missing ancestor deep in a chain is rejected', () {
      final broken = chain(15).where((c) => c.categoryId != _id(7)).toList();
      expect(() => FinancialCategoryIndex.build(broken), throwsFormatException);
    });
  });
}
