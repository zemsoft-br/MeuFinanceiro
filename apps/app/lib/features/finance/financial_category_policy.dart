import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

/// Ergonomic mirror of the server contract (ADR-0022). The backend remains the
/// final authority on audience, ownership, status, currency, sign and closing
/// sum; this only keeps obviously invalid options out of the UI.

/// Immutable lookup of every category the server returned, DISABLED included,
/// so historical classifications keep resolving their names.
class FinancialCategoryIndex {
  const FinancialCategoryIndex._(this._byId);

  static const empty = FinancialCategoryIndex._(<String, FinancialCategory>{});

  /// Rejects structurally inconsistent responses: duplicate ids, unknown
  /// parents and cycles (including a category that is its own parent).
  ///
  /// There is deliberately no depth limit: the backend defines none, so any
  /// acyclic chain whose parents all exist is canonical. Termination does not
  /// depend on a guess either: every walk stops at a root, at an already
  /// verified node, or at a node repeated in the current walk, so the work is
  /// bounded by the number of categories received.
  factory FinancialCategoryIndex.build(Iterable<FinancialCategory> categories) {
    final byId = <String, FinancialCategory>{};
    for (final category in categories) {
      if (byId.containsKey(category.categoryId)) {
        throw const FormatException('duplicate category identity.');
      }
      byId[category.categoryId] = category;
    }
    final verified = <String>{};
    for (final start in byId.values) {
      if (verified.contains(start.categoryId)) continue;
      final walk = <String>{};
      FinancialCategory? cursor = start;
      while (cursor != null && !verified.contains(cursor.categoryId)) {
        if (!walk.add(cursor.categoryId)) {
          throw const FormatException('category hierarchy has a cycle.');
        }
        final parentId = cursor.parentId;
        if (parentId == null) break;
        cursor = byId[parentId];
        if (cursor == null) {
          throw const FormatException('category parent is unknown.');
        }
      }
      verified.addAll(walk);
    }
    return FinancialCategoryIndex._(Map.unmodifiable(byId));
  }

  final Map<String, FinancialCategory> _byId;

  Iterable<FinancialCategory> get all => _byId.values;

  FinancialCategory? byId(String categoryId) => _byId[categoryId];

  /// Flat breadcrumb such as "Moradia > Energia". The index is validated
  /// acyclic; the step bound (never more steps than categories) keeps this
  /// terminating even if that invariant were ever broken.
  String? pathLabel(String categoryId) {
    var cursor = _byId[categoryId];
    if (cursor == null) return null;
    final names = <String>[cursor.name];
    var steps = 0;
    while (cursor!.parentId != null) {
      if (++steps > _byId.length) return null;
      cursor = _byId[cursor.parentId];
      if (cursor == null) return null;
      names.add(cursor.name);
    }
    return names.reversed.join(' > ');
  }
}

/// ADR-0022 audience matrix, derived from the *account* of the Movement.
///
/// PERSONAL account : HOUSEHOLD, or PERSONAL of the account owner
/// SHARED account   : HOUSEHOLD only
/// HOUSEHOLD account: HOUSEHOLD only
/// Never DISABLED, never SHARED categories.
bool isFinancialCategoryEligibleForAccount({
  required FinancialCategory category,
  required FinancialAccount account,
}) {
  if (!category.isActive) return false;
  return switch (category.visibilityScope) {
    FinancialVisibilityScope.household => true,
    FinancialVisibilityScope.personal =>
      account.visibilityScope == FinancialVisibilityScope.personal &&
          category.ownerOperatorId == account.ownerOperatorId,
    FinancialVisibilityScope.shared => false,
  };
}

/// Active categories offered for a new classification, hierarchy-labelled and
/// sorted for stable selection.
List<FinancialCategory> eligibleFinancialCategories({
  required FinancialCategoryIndex index,
  required FinancialAccount account,
}) {
  final eligible = index.all
      .where(
        (category) => isFinancialCategoryEligibleForAccount(
          category: category,
          account: account,
        ),
      )
      .toList();
  eligible.sort((a, b) {
    final byPath = (index.pathLabel(a.categoryId) ?? a.name)
        .toLowerCase()
        .compareTo((index.pathLabel(b.categoryId) ?? b.name).toLowerCase());
    return byPath != 0 ? byPath : a.categoryId.compareTo(b.categoryId);
  });
  return List.unmodifiable(eligible);
}

/// Scopes a new category may be created with from the context of [account].
/// Backend assigns the operator as owner of PERSONAL categories.
List<FinancialVisibilityScope> financialCategoryCreationScopes(
  FinancialAccount account,
) => switch (account.visibilityScope) {
  FinancialVisibilityScope.personal => const [
    FinancialVisibilityScope.personal,
    FinancialVisibilityScope.household,
  ],
  FinancialVisibilityScope.shared || FinancialVisibilityScope.household =>
    const [FinancialVisibilityScope.household],
};

/// The server only accepts an ACTIVE parent owned by the creating operator in
/// the same scope as the new category.
List<FinancialCategory> eligibleFinancialCategoryParents({
  required FinancialCategoryIndex index,
  required FinancialVisibilityScope scope,
  required String operatorId,
}) {
  final parents = index.all
      .where(
        (category) =>
            category.isActive &&
            category.visibilityScope == scope &&
            category.ownerOperatorId == operatorId,
      )
      .toList();
  parents.sort(
    (a, b) => (index.pathLabel(a.categoryId) ?? a.name).toLowerCase().compareTo(
      (index.pathLabel(b.categoryId) ?? b.name).toLowerCase(),
    ),
  );
  return List.unmodifiable(parents);
}

/// Only STANDARD income/expense Movements are classifiable (ADR-0022).
bool isFinancialMovementClassifiableKind(FinancialMovement movement) =>
    movement.role == FinancialMovementRole.standard &&
    (movement.resultEffect == FinancialResultEffect.income ||
        movement.resultEffect == FinancialResultEffect.expense);

bool isFinancialAccountOwner({
  required FinancialAccount account,
  required String? operatorId,
}) => operatorId != null && operatorId == account.ownerOperatorId;

/// Whether the UI may offer the first (simple) classification. Read-only for
/// anyone but the account owner; the backend validates everything again.
bool canClassifyFinancialMovementSimply({
  required FinancialAccount account,
  required FinancialMovement movement,
  required FinancialMovementAllocation? currentAllocation,
  required String? operatorId,
}) =>
    account.status == FinancialAccountStatus.active &&
    isFinancialAccountOwner(account: account, operatorId: operatorId) &&
    isFinancialMovementClassifiableKind(movement) &&
    currentAllocation == null;

/// "Sem categoria", the category path, or "N categorias". Non-classifiable
/// kinds (NEUTRAL/REVERSAL) are "Não se aplica", never a pending task.
String financialMovementClassificationLabel({
  required FinancialMovement movement,
  required FinancialMovementAllocation? allocation,
  required FinancialCategoryIndex index,
}) {
  if (allocation == null) {
    return isFinancialMovementClassifiableKind(movement)
        ? 'Sem categoria'
        : 'Não se aplica';
  }
  if (allocation.allocations.length > 1) {
    return '${allocation.allocations.length} categorias';
  }
  final categoryId = allocation.allocations.single.categoryId;
  final label = index.pathLabel(categoryId);
  if (label == null) {
    throw const FormatException('allocation category is unknown.');
  }
  return label;
}
