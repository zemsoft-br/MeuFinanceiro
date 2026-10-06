import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_allocation_math.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

final financialCoreApiProvider = Provider<FinancialCoreApi>(
  (ref) => FinancialCoreApi(ref.watch(authenticatedApiClientProvider)),
);

enum FinancialLoadPhase {
  idle,
  loading,
  loaded,
  empty,
  refreshing,
  authenticationRequired,
  forbidden,
  primaryResidenceRequired,
  notFound,
  conflict,
  temporarilyUnavailable,
  invalidResponse,
}

enum FinancialRefreshFailure { none, temporarilyUnavailable, invalidResponse }

class FinancialAccountsState {
  const FinancialAccountsState._({
    required this.phase,
    this.accounts = const [],
    this.refreshFailure = FinancialRefreshFailure.none,
  });

  const FinancialAccountsState.idle() : this._(phase: FinancialLoadPhase.idle);
  const FinancialAccountsState.phase(FinancialLoadPhase phase)
    : this._(phase: phase);

  FinancialAccountsState.loaded(
    List<FinancialAccount> accounts, {
    bool refreshing = false,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
  }) : this._(
         phase: refreshing
             ? FinancialLoadPhase.refreshing
             : FinancialLoadPhase.loaded,
         accounts: List<FinancialAccount>.unmodifiable(accounts),
         refreshFailure: refreshFailure,
       );

  final FinancialLoadPhase phase;
  final List<FinancialAccount> accounts;
  final FinancialRefreshFailure refreshFailure;

  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing;
}

final financialAccountsControllerProvider =
    NotifierProvider.autoDispose<
      FinancialAccountsController,
      FinancialAccountsState
    >(FinancialAccountsController.new);

class FinancialAccountsController extends Notifier<FinancialAccountsState> {
  int _generation = 0;
  bool _inFlight = false;

  @override
  FinancialAccountsState build() {
    ref.onDispose(() {
      _generation += 1;
      _inFlight = false;
    });
    return const FinancialAccountsState.idle();
  }

  Future<void> load() => _load(refresh: false);
  Future<void> refresh() => _load(refresh: true);

  Future<FinancialAccount> createAccount(
    FinancialAccountCreateInput input,
  ) async {
    final account = await ref
        .read(financialCoreApiProvider)
        .createAccount(input);
    if (state.phase == FinancialLoadPhase.loaded ||
        state.phase == FinancialLoadPhase.refreshing) {
      state = FinancialAccountsState.loaded([
        ...state.accounts.where((item) => item.accountId != account.accountId),
        account,
      ]);
    }
    return account;
  }

  Future<void> _load({required bool refresh}) async {
    if (_inFlight || state.isBusy) return;
    final previous = state.accounts;
    final preserve = refresh && previous.isNotEmpty;
    final generation = ++_generation;
    _inFlight = true;
    state = preserve
        ? FinancialAccountsState.loaded(previous, refreshing: true)
        : const FinancialAccountsState.phase(FinancialLoadPhase.loading);
    try {
      final accounts = await ref.read(financialCoreApiProvider).listAccounts();
      if (!_isCurrent(generation)) return;
      state = accounts.isEmpty
          ? const FinancialAccountsState.phase(FinancialLoadPhase.empty)
          : FinancialAccountsState.loaded(accounts);
    } catch (error) {
      if (!_isCurrent(generation)) return;
      final phase = financialPhaseForFailure(error);
      if (preserve &&
          (phase == FinancialLoadPhase.temporarilyUnavailable ||
              phase == FinancialLoadPhase.invalidResponse)) {
        state = FinancialAccountsState.loaded(
          previous,
          refreshFailure: phase == FinancialLoadPhase.invalidResponse
              ? FinancialRefreshFailure.invalidResponse
              : FinancialRefreshFailure.temporarilyUnavailable,
        );
      } else {
        state = FinancialAccountsState.phase(phase);
      }
    } finally {
      if (generation == _generation) _inFlight = false;
    }
  }

  bool _isCurrent(int generation) => generation == _generation && _inFlight;
}

class FinancialAccountDetailState {
  const FinancialAccountDetailState._({
    required this.phase,
    this.account,
    this.openingBalance,
    this.balance,
    this.statement,
    this.accounts = const [],
    this.transfers = const [],
    this.categories = const [],
    this.categoryIndex = FinancialCategoryIndex.empty,
    this.currentAllocations = const {},
    this.ruleOriginsBySetId = const {},
    this.refreshFailure = FinancialRefreshFailure.none,
    this.openingBalanceMutationInFlight = false,
    this.operationMutationInFlight = false,
    this.classificationMutationInFlight = false,
    this.classificationTrusted = true,
    this.categoryCreationUnknown = false,
  });

  const FinancialAccountDetailState.idle()
    : this._(phase: FinancialLoadPhase.idle);
  const FinancialAccountDetailState.phase(FinancialLoadPhase phase)
    : this._(phase: phase);

  FinancialAccountDetailState.loaded({
    required FinancialAccount account,
    required FinancialOpeningBalance? openingBalance,
    required FinancialBalanceSnapshot balance,
    required FinancialStatement statement,
    required List<FinancialAccount> accounts,
    List<FinancialTransfer> transfers = const [],
    List<FinancialCategory> categories = const [],
    FinancialCategoryIndex? categoryIndex,
    Map<String, FinancialMovementAllocation> currentAllocations = const {},
    Map<String, FinancialRuleOrigin> ruleOriginsBySetId = const {},
    bool refreshing = false,
    bool openingBalanceMutationInFlight = false,
    bool operationMutationInFlight = false,
    bool classificationMutationInFlight = false,
    bool classificationTrusted = true,
    bool categoryCreationUnknown = false,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
  }) : this._(
         phase: refreshing
             ? FinancialLoadPhase.refreshing
             : FinancialLoadPhase.loaded,
         account: account,
         openingBalance: openingBalance,
         balance: balance,
         statement: statement,
         accounts: List<FinancialAccount>.unmodifiable(accounts),
         transfers: List<FinancialTransfer>.unmodifiable(transfers),
         categories: List<FinancialCategory>.unmodifiable(categories),
         categoryIndex:
             categoryIndex ?? FinancialCategoryIndex.build(categories),
         currentAllocations:
             Map<String, FinancialMovementAllocation>.unmodifiable(
               currentAllocations,
             ),
         ruleOriginsBySetId: Map<String, FinancialRuleOrigin>.unmodifiable(
           ruleOriginsBySetId,
         ),
         refreshFailure: refreshFailure,
         openingBalanceMutationInFlight: openingBalanceMutationInFlight,
         operationMutationInFlight: operationMutationInFlight,
         classificationMutationInFlight: classificationMutationInFlight,
         classificationTrusted: classificationTrusted,
         categoryCreationUnknown: categoryCreationUnknown,
       );

  final FinancialLoadPhase phase;
  final FinancialAccount? account;
  final FinancialOpeningBalance? openingBalance;
  final FinancialBalanceSnapshot? balance;
  final FinancialStatement? statement;
  final List<FinancialAccount> accounts;
  final List<FinancialTransfer> transfers;

  /// Every category the server returned, DISABLED included, so historical
  /// classifications keep resolving their names.
  final List<FinancialCategory> categories;
  final FinancialCategoryIndex categoryIndex;

  /// Current classification by `movementId`, joined in memory with the
  /// statement. Fed by one bulk read, never one request per Movement.
  final Map<String, FinancialMovementAllocation> currentAllocations;

  /// Rule provenance by `allocationSetId`, from one bulk read. Evidence only:
  /// a classification counts as "applied by a rule" solely when its *current*
  /// allocation set has an origin here; it never decides what is current.
  final Map<String, FinancialRuleOrigin> ruleOriginsBySetId;
  final FinancialRefreshFailure refreshFailure;
  final bool openingBalanceMutationInFlight;
  final bool operationMutationInFlight;
  final bool classificationMutationInFlight;

  /// False after a classification write was refused (409/404) and the
  /// reconciliation read also failed: the visible classifications may be stale.
  /// Fail closed: no classification is offered or sent until a full refresh (or
  /// a successful reconciliation) restores the persisted truth.
  final bool classificationTrusted;

  /// True after a category POST ended with an unknown outcome and the
  /// reconciling `GET categories` also failed. The POST is not idempotent, so
  /// creating another category is blocked until categories are read again.
  final bool categoryCreationUnknown;

  List<FinancialMovement> get movements => List<FinancialMovement>.unmodifiable(
    statement?.entries.map((entry) => entry.movement) ?? const [],
  );

  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing ||
      openingBalanceMutationInFlight ||
      operationMutationInFlight ||
      classificationMutationInFlight;

  /// Rebuilds a loaded state from this one. Flags and the refresh failure are
  /// reset unless passed explicitly; data is kept unless replaced.
  FinancialAccountDetailState copyLoaded({
    bool refreshing = false,
    bool openingBalanceMutationInFlight = false,
    bool operationMutationInFlight = false,
    bool classificationMutationInFlight = false,
    bool? classificationTrusted,
    bool? categoryCreationUnknown,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
    List<FinancialCategory>? categories,
    FinancialCategoryIndex? categoryIndex,
    Map<String, FinancialMovementAllocation>? currentAllocations,
    Map<String, FinancialRuleOrigin>? ruleOriginsBySetId,
  }) {
    return FinancialAccountDetailState.loaded(
      account: account!,
      openingBalance: openingBalance,
      balance: balance!,
      statement: statement!,
      accounts: accounts,
      transfers: transfers,
      categories: categories ?? this.categories,
      categoryIndex: categories == null
          ? (categoryIndex ?? this.categoryIndex)
          : categoryIndex,
      currentAllocations: currentAllocations ?? this.currentAllocations,
      ruleOriginsBySetId: ruleOriginsBySetId ?? this.ruleOriginsBySetId,
      refreshing: refreshing,
      openingBalanceMutationInFlight: openingBalanceMutationInFlight,
      operationMutationInFlight: operationMutationInFlight,
      classificationMutationInFlight: classificationMutationInFlight,
      classificationTrusted:
          classificationTrusted ?? this.classificationTrusted,
      categoryCreationUnknown:
          categoryCreationUnknown ?? this.categoryCreationUnknown,
      refreshFailure: refreshFailure,
    );
  }
}

/// Typed result for classification and category mutations, so the UI can tell
/// a confirmed write from a rejected, reconciled or unavailable one.
enum FinancialMutationOutcome {
  /// Backend confirmed (2xx) and the confirmed response was incorporated.
  success,

  /// Refused locally before any request (owner, eligibility, audience, busy).
  notAllowed,

  /// 404/422: the backend rejected the request; canonical state is untouched.
  rejected,

  /// 409: the visible state was stale. Persisted truth was refetched and
  /// replaced the local view; the write was NOT retried.
  conflictReconciled,

  /// 5xx/transport: outcome unknown. The visible state was not changed.
  temporarilyUnavailable,

  /// The response could not be validated; nothing was incorporated.
  invalidResponse,

  /// 401/403/residence: the session or access is gone; the screen phase says so.
  accessBlocked,

  /// A non-idempotent write ended with an unknown outcome. It was NOT retried;
  /// the persisted state was read again and replaced the local view. The
  /// original request is neither confirmed nor denied.
  unknownOutcomeReconciled,
}

class FinancialCategoryCreateResult {
  const FinancialCategoryCreateResult(
    this.outcome, [
    this.category,
    this.matches = const [],
  ]);

  final FinancialMutationOutcome outcome;

  /// The backend-confirmed category (only for [FinancialMutationOutcome.success]).
  final FinancialCategory? category;

  /// After an unknown outcome: categories that appeared since the request and
  /// look compatible (same name, scope and parent, owned by the operator).
  /// Never chosen automatically; the user decides.
  final List<FinancialCategory> matches;
}

final financialAccountDetailControllerProvider = NotifierProvider.autoDispose
    .family<
      FinancialAccountDetailController,
      FinancialAccountDetailState,
      String
    >((accountId) => FinancialAccountDetailController(accountId));

class FinancialAccountDetailController
    extends Notifier<FinancialAccountDetailState> {
  FinancialAccountDetailController(this.accountId);

  final String accountId;
  int _generation = 0;
  bool _inFlight = false;
  bool _disposed = false;

  /// Idempotency keys of classification attempts whose outcome is unknown
  /// (timeout/5xx). An identical retry reuses the key so a write that did
  /// commit is replayed instead of duplicated. Cleared on any definitive answer.
  final Map<String, String> _pendingClassificationKeys = {};

  /// Same contract for revisions, kept apart so a key minted for a first
  /// classification can never be reused by a revision (and vice versa).
  final Map<String, String> _pendingRevisionKeys = {};

  @override
  FinancialAccountDetailState build() {
    ref.onDispose(() {
      _disposed = true;
      _generation += 1;
      _inFlight = false;
    });
    return const FinancialAccountDetailState.idle();
  }

  Future<void> load() => _load(refresh: false);
  Future<void> refresh() => _load(refresh: true);

  Future<bool> createOpeningBalance(
    FinancialOpeningBalanceCreateInput input,
  ) async {
    final account = state.account;
    final balance = state.balance;
    final statement = state.statement;
    if (account == null ||
        balance == null ||
        statement == null ||
        state.openingBalanceMutationInFlight) {
      return false;
    }
    final previous = state;
    state = previous.copyLoaded(
      openingBalanceMutationInFlight: true,
      refreshFailure: previous.refreshFailure,
    );
    try {
      final opening = await ref
          .read(financialCoreApiProvider)
          .createOpeningBalance(accountId, input);
      if (opening.money.currency != account.currency) {
        throw const FormatException('opening balance currency mismatch.');
      }
      await _load(refresh: true, force: true);
      return true;
    } on AuthenticatedApiException catch (error) {
      if (error.statusCode == 409) {
        await _load(refresh: true, force: true);
        return false;
      }
      _restoreAfterMutationFailure(previous, error);
      return false;
    } on FormatException {
      _restoreInvalidResponse(previous);
      return false;
    }
  }

  Future<bool> createManualEntry(
    FinancialManualEntryKind kind,
    FinancialManualEntryCreateInput input,
  ) => _runOperation((api) async {
    await api.createManualEntry(accountId, kind, input);
  });

  Future<bool> createTransfer(FinancialTransferCreateInput input) =>
      _runOperation((api) async {
        await api.createTransfer(input);
      });

  Future<bool> reverseMovement(
    String movementId,
    FinancialMovementReversalInput input,
  ) => _runOperation((api) async {
    await api.reverseMovement(movementId, input);
  });

  Future<bool> reverseTransfer(
    String transferId,
    FinancialTransferReversalInput input,
  ) => _runOperation((api) async {
    await api.reverseTransfer(transferId, input);
  });

  /// First, simple (100% in one category) classification of a Movement.
  ///
  /// The share is built from the Movement already held in state, never from
  /// UI-provided money. Nothing visible changes before the backend confirms;
  /// a 409 refetches the persisted truth and is never retried.
  Future<FinancialMutationOutcome> classifyMovement({
    required String movementId,
    required String categoryId,
  }) async {
    final movement = _movementOf(state, movementId);
    if (movement == null) return FinancialMutationOutcome.notAllowed;
    final List<FinancialAllocationShareInput> shares;
    try {
      shares = FinancialMovementAllocationCreateInput.single(
        categoryId: categoryId,
        movementMoney: movement.money,
      ).allocations;
    } on FormatException {
      return FinancialMutationOutcome.notAllowed;
    }
    return classifyMovementShares(movementId: movementId, shares: shares);
  }

  /// First classification of a Movement with 1..50 shares. Same guarantees as
  /// [classifyMovement]; the shares must close the Movement money exactly.
  Future<FinancialMutationOutcome> classifyMovementShares({
    required String movementId,
    required List<FinancialAllocationShareInput> shares,
  }) async {
    final previous = state;
    final account = previous.account;
    final movement = _movementOf(previous, movementId);
    final operatorId = ref
        .read(operatorSessionControllerProvider)
        .principal
        ?.operatorId;
    if (account == null ||
        movement == null ||
        !_canWriteClassification(previous) ||
        !canClassifyFinancialMovementSimply(
          account: account,
          movement: movement,
          currentAllocation: previous.currentAllocations[movementId],
          operatorId: operatorId,
        ) ||
        !_sharesAreSendable(previous, account, movement, shares)) {
      return FinancialMutationOutcome.notAllowed;
    }

    // One logical attempt: same Movement and the same shares (any order).
    // Anything else is a different request and never reuses a key.
    final attemptKey = financialAllocationAttemptIdentity(
      kind: 'classify',
      movementId: movementId,
      shares: shares,
    );
    final FinancialMovementAllocationCreateInput input;
    try {
      input = FinancialMovementAllocationCreateInput(
        allocations: shares,
        idempotencyKey: _pendingClassificationKeys[attemptKey],
      );
    } on FormatException {
      return FinancialMutationOutcome.notAllowed;
    }
    _pendingClassificationKeys[attemptKey] = input.idempotencyKey;

    return _writeAllocation(
      previous: previous,
      keys: _pendingClassificationKeys,
      attemptKey: attemptKey,
      send: (api) => api.createMovementAllocation(movementId, input),
      // Any current allocation means the write (or someone's) is persisted.
      keyConsumed: (reconciled) =>
          reconciled.currentAllocations.containsKey(movementId),
    );
  }

  /// Appends a revision of the current classification.
  ///
  /// [supersedesId] is the `allocationSetId` the editor was opened on and must
  /// still be the current one: a revision against a known historical set is
  /// refused here without any request. Append-only: the server never updates
  /// or deletes the current set.
  ///
  /// * 201: the confirmed response becomes the current allocation (no ledger
  ///   reload; classification does not touch balance or statement).
  /// * 409 (stale predecessor): never retried, the edit is never re-applied on
  ///   top of the newer set. Persisted truth replaces the view and the user
  ///   must review again from the new predecessor.
  /// * timeout/5xx/transport/invalid 2xx: one reconciliation, no retry. The
  ///   attempt key is kept only while the predecessor is still current.
  Future<FinancialMutationOutcome> reviseMovementClassification({
    required String movementId,
    required String supersedesId,
    required List<FinancialAllocationShareInput> shares,
  }) async {
    final previous = state;
    final account = previous.account;
    final movement = _movementOf(previous, movementId);
    final current = previous.currentAllocations[movementId];
    final operatorId = ref
        .read(operatorSessionControllerProvider)
        .principal
        ?.operatorId;
    if (account == null ||
        movement == null ||
        current == null ||
        !_canWriteClassification(previous) ||
        !canReviseFinancialMovementClassification(
          account: account,
          movement: movement,
          currentAllocation: current,
          operatorId: operatorId,
        )) {
      return FinancialMutationOutcome.notAllowed;
    }
    if (current.allocationSetId != supersedesId) {
      // The editor was opened on a set that is no longer current. The local
      // view is already the newer truth: send nothing, ask for a new review.
      return FinancialMutationOutcome.conflictReconciled;
    }
    if (!_sharesAreSendable(previous, account, movement, shares) ||
        financialSharesMatchAllocation(current, shares)) {
      return FinancialMutationOutcome.notAllowed;
    }

    final attemptKey = financialAllocationAttemptIdentity(
      kind: 'revise',
      movementId: movementId,
      supersedesId: supersedesId,
      shares: shares,
    );
    final FinancialMovementAllocationRevisionInput input;
    try {
      input = FinancialMovementAllocationRevisionInput(
        supersedesId: supersedesId,
        allocations: shares,
        idempotencyKey: _pendingRevisionKeys[attemptKey],
      );
    } on FormatException {
      return FinancialMutationOutcome.notAllowed;
    }
    _pendingRevisionKeys[attemptKey] = input.idempotencyKey;

    return _writeAllocation(
      previous: previous,
      keys: _pendingRevisionKeys,
      attemptKey: attemptKey,
      send: (api) => api.reviseMovementAllocation(movementId, input),
      // The key stays usable only while the predecessor is still current.
      keyConsumed: (reconciled) =>
          reconciled.currentAllocations[movementId]?.allocationSetId !=
          supersedesId,
    );
  }

  FinancialMovement? _movementOf(
    FinancialAccountDetailState from,
    String movementId,
  ) {
    for (final item in from.movements) {
      if (item.movementId == movementId) return item;
    }
    return null;
  }

  bool _canWriteClassification(FinancialAccountDetailState from) =>
      from.account != null &&
      from.balance != null &&
      from.statement != null &&
      !from.isBusy &&
      from.classificationTrusted;

  /// Local, ergonomic refusal of requests the backend would reject anyway:
  /// every category known and eligible for the account, and the shares close
  /// the Movement money exactly (sign, currency, count, uniqueness, sum).
  bool _sharesAreSendable(
    FinancialAccountDetailState from,
    FinancialAccount account,
    FinancialMovement movement,
    List<FinancialAllocationShareInput> shares,
  ) {
    for (final share in shares) {
      final category = from.categoryIndex.byId(share.categoryId);
      if (category == null ||
          !isFinancialCategoryEligibleForAccount(
            category: category,
            account: account,
          )) {
        return false;
      }
    }
    return financialAllocationClosureIssues(
      movementMoney: movement.money,
      shares: shares,
    ).isEmpty;
  }

  /// Sends one allocation write and maps every answer to a typed outcome.
  /// Shared by the first classification and by revisions; neither ever retries.
  Future<FinancialMutationOutcome> _writeAllocation({
    required FinancialAccountDetailState previous,
    required Map<String, String> keys,
    required String attemptKey,
    required Future<FinancialMovementAllocation> Function(FinancialCoreApi api)
    send,
    required bool Function(FinancialAccountDetailState reconciled) keyConsumed,
  }) async {
    final account = previous.account!;
    state = previous.copyLoaded(
      classificationMutationInFlight: true,
      refreshFailure: previous.refreshFailure,
    );
    try {
      final created = await send(ref.read(financialCoreApiProvider));
      if (_disposed) return FinancialMutationOutcome.success;
      if (created.currency != account.currency ||
          created.allocations.any(
            (share) => state.categoryIndex.byId(share.categoryId) == null,
          )) {
        throw const FormatException('financial allocation response mismatch.');
      }
      keys.remove(attemptKey);
      state = state.copyLoaded(
        refreshFailure: previous.refreshFailure,
        currentAllocations: {
          ...state.currentAllocations,
          created.movementId: created,
        },
      );
      return FinancialMutationOutcome.success;
    } on AuthenticatedApiException catch (error) {
      if (_disposed) return FinancialMutationOutcome.temporarilyUnavailable;
      if (error.statusCode == 409) {
        keys.remove(attemptKey);
        return await _reconcileClassification(previous) ??
            FinancialMutationOutcome.conflictReconciled;
      }
      if (error.statusCode == 404) {
        // A sanitized 404 may hide a canonical change (category disabled or
        // gone from the audience): read the truth once, never retry the POST.
        keys.remove(attemptKey);
        final failure = await _reconcileClassification(previous);
        return failure == FinancialMutationOutcome.accessBlocked
            ? failure!
            : FinancialMutationOutcome.rejected;
      }
      if (error.statusCode == 422) {
        keys.remove(attemptKey);
        state = previous.copyLoaded(refreshFailure: previous.refreshFailure);
        return FinancialMutationOutcome.rejected;
      }
      final phase = financialPhaseForFailure(error);
      if (phase == FinancialLoadPhase.authenticationRequired ||
          phase == FinancialLoadPhase.forbidden ||
          phase == FinancialLoadPhase.primaryResidenceRequired) {
        return _failMutation(previous, error);
      }
      // Timeout/transport/5xx: the write may or may not have committed.
      return _reconcileAfterUnknownWrite(
        previous,
        keys,
        attemptKey,
        keyConsumed,
      );
    } on FormatException {
      if (_disposed) return FinancialMutationOutcome.invalidResponse;
      // A 2xx that cannot be validated is just as ambiguous.
      return _reconcileAfterUnknownWrite(
        previous,
        keys,
        attemptKey,
        keyConsumed,
      );
    }
  }

  /// Creates a category and, only after the backend confirms, adds the
  /// returned canonical category to the local state (no full reload).
  Future<FinancialCategoryCreateResult> createCategory(
    FinancialCategoryCreateInput input,
  ) async {
    final previous = state;
    final account = previous.account;
    if (account == null ||
        previous.balance == null ||
        previous.statement == null ||
        previous.isBusy ||
        previous.categoryCreationUnknown ||
        !previous.classificationTrusted) {
      return const FinancialCategoryCreateResult(
        FinancialMutationOutcome.notAllowed,
      );
    }
    final operatorId = ref
        .read(operatorSessionControllerProvider)
        .principal
        ?.operatorId;
    final parentId = input.parentId;
    final parent = parentId == null
        ? null
        : previous.categoryIndex.byId(parentId);
    if (!financialCategoryCreationScopes(
          account,
        ).contains(input.visibilityScope) ||
        operatorId == null ||
        (parentId != null &&
            (parent == null ||
                !eligibleFinancialCategoryParents(
                  index: previous.categoryIndex,
                  scope: input.visibilityScope,
                  operatorId: operatorId,
                ).any((item) => item.categoryId == parentId)))) {
      return const FinancialCategoryCreateResult(
        FinancialMutationOutcome.notAllowed,
      );
    }

    state = previous.copyLoaded(
      classificationMutationInFlight: true,
      refreshFailure: previous.refreshFailure,
    );
    try {
      final created = await ref
          .read(financialCoreApiProvider)
          .createCategory(input);
      if (_disposed) {
        return FinancialCategoryCreateResult(
          FinancialMutationOutcome.success,
          created,
        );
      }
      final categories = [
        ...state.categories.where(
          (item) => item.categoryId != created.categoryId,
        ),
        created,
      ];
      final index = FinancialCategoryIndex.build(categories);
      state = state.copyLoaded(
        refreshFailure: previous.refreshFailure,
        categories: categories,
        categoryIndex: index,
      );
      return FinancialCategoryCreateResult(
        FinancialMutationOutcome.success,
        created,
      );
    } on AuthenticatedApiException catch (error) {
      if (_disposed) {
        return const FinancialCategoryCreateResult(
          FinancialMutationOutcome.temporarilyUnavailable,
        );
      }
      if (error.statusCode == 404 ||
          error.statusCode == 409 ||
          error.statusCode == 422) {
        state = previous.copyLoaded(refreshFailure: previous.refreshFailure);
        return const FinancialCategoryCreateResult(
          FinancialMutationOutcome.rejected,
        );
      }
      final phase = financialPhaseForFailure(error);
      if (phase == FinancialLoadPhase.authenticationRequired ||
          phase == FinancialLoadPhase.forbidden ||
          phase == FinancialLoadPhase.primaryResidenceRequired) {
        state = FinancialAccountDetailState.phase(phase);
        return const FinancialCategoryCreateResult(
          FinancialMutationOutcome.accessBlocked,
        );
      }
      // Timeout/transport/5xx after the send: the category may exist. The POST
      // is not idempotent, so it is never repeated; read the truth instead.
      return _reconcileCategoriesAfterUnknown(
        previous,
        input,
        operatorId,
        FinancialMutationOutcome.temporarilyUnavailable,
      );
    } on FormatException {
      if (_disposed) {
        return const FinancialCategoryCreateResult(
          FinancialMutationOutcome.invalidResponse,
        );
      }
      // A confirmed-looking but unusable response is just as ambiguous.
      return _reconcileCategoriesAfterUnknown(
        previous,
        input,
        operatorId,
        FinancialMutationOutcome.invalidResponse,
      );
    }
  }

  /// Reads categories again (the only way out of an unknown category outcome
  /// when the first reconciling read failed). Clears the block on success.
  Future<FinancialMutationOutcome> reconcileCategories() async {
    final previous = state;
    final account = previous.account;
    if (account == null ||
        previous.balance == null ||
        previous.statement == null ||
        previous.isBusy) {
      return FinancialMutationOutcome.notAllowed;
    }
    state = previous.copyLoaded(
      classificationMutationInFlight: true,
      refreshFailure: previous.refreshFailure,
    );
    try {
      final categories = await ref
          .read(financialCoreApiProvider)
          .listCategories();
      final index = FinancialCategoryIndex.build(categories);
      _resolveAllocations(
        account: account,
        index: index,
        allocations: previous.currentAllocations.values.toList(),
      );
      if (_disposed) return FinancialMutationOutcome.success;
      state = previous.copyLoaded(
        refreshFailure: previous.refreshFailure,
        categories: categories,
        categoryIndex: index,
        categoryCreationUnknown: false,
      );
      return FinancialMutationOutcome.success;
    } on AuthenticatedApiException catch (error) {
      if (_disposed) return FinancialMutationOutcome.temporarilyUnavailable;
      return _failMutation(previous, error);
    } on FormatException {
      if (_disposed) return FinancialMutationOutcome.invalidResponse;
      _restoreInvalidResponse(previous);
      return FinancialMutationOutcome.invalidResponse;
    }
  }

  /// After a category POST with unknown outcome: one `GET categories`, no
  /// second POST. On success the canonical list replaces the local one and
  /// compatible newcomers are reported, never auto-selected. On failure the
  /// state is marked unknown and creation stays blocked.
  Future<FinancialCategoryCreateResult> _reconcileCategoriesAfterUnknown(
    FinancialAccountDetailState previous,
    FinancialCategoryCreateInput input,
    String operatorId,
    FinancialMutationOutcome fallback,
  ) async {
    try {
      final categories = await ref
          .read(financialCoreApiProvider)
          .listCategories();
      final index = FinancialCategoryIndex.build(categories);
      _resolveAllocations(
        account: previous.account!,
        index: index,
        allocations: previous.currentAllocations.values.toList(),
      );
      if (_disposed) {
        return FinancialCategoryCreateResult(fallback);
      }
      final knownIds = previous.categories
          .map((item) => item.categoryId)
          .toSet();
      final matches = List<FinancialCategory>.unmodifiable(
        categories.where(
          (item) =>
              !knownIds.contains(item.categoryId) &&
              item.isActive &&
              item.name == input.name &&
              item.visibilityScope == input.visibilityScope &&
              item.parentId == input.parentId &&
              item.ownerOperatorId == operatorId,
        ),
      );
      state = previous.copyLoaded(
        refreshFailure: previous.refreshFailure,
        categories: categories,
        categoryIndex: index,
        categoryCreationUnknown: false,
      );
      return FinancialCategoryCreateResult(
        FinancialMutationOutcome.unknownOutcomeReconciled,
        null,
        matches,
      );
    } on AuthenticatedApiException catch (error) {
      if (_disposed) return FinancialCategoryCreateResult(fallback);
      final phase = financialPhaseForFailure(error);
      if (phase == FinancialLoadPhase.authenticationRequired ||
          phase == FinancialLoadPhase.forbidden ||
          phase == FinancialLoadPhase.primaryResidenceRequired) {
        state = FinancialAccountDetailState.phase(phase);
        return const FinancialCategoryCreateResult(
          FinancialMutationOutcome.accessBlocked,
        );
      }
      state = previous.copyLoaded(
        refreshFailure: previous.refreshFailure,
        categoryCreationUnknown: true,
      );
      return FinancialCategoryCreateResult(fallback);
    } on FormatException {
      if (_disposed) return FinancialCategoryCreateResult(fallback);
      state = previous.copyLoaded(
        refreshFailure: FinancialRefreshFailure.invalidResponse,
        categoryCreationUnknown: true,
      );
      return FinancialCategoryCreateResult(fallback);
    }
  }

  /// 409/404: replace the local view with the persisted truth (categories and
  /// the bulk current allocations) instead of trusting or retrying the write.
  ///
  /// Returns null when the truth was read and incorporated. Otherwise the
  /// failure outcome; the visible data is kept but marked untrusted, so no new
  /// classification is offered until a refresh restores trust.
  Future<FinancialMutationOutcome?> _reconcileClassification(
    FinancialAccountDetailState previous,
  ) async {
    try {
      final api = ref.read(financialCoreApiProvider);
      final categories = await api.listCategories();
      final allocations = await api.listCurrentMovementAllocations(accountId);
      final index = FinancialCategoryIndex.build(categories);
      final currentAllocations = _resolveAllocations(
        account: previous.account!,
        index: index,
        allocations: allocations,
      );
      if (_disposed) return null;
      state = previous.copyLoaded(
        refreshFailure: previous.refreshFailure,
        categories: categories,
        categoryIndex: index,
        currentAllocations: currentAllocations,
        classificationTrusted: true,
      );
      return null;
    } on AuthenticatedApiException catch (error) {
      if (_disposed) return FinancialMutationOutcome.temporarilyUnavailable;
      final phase = financialPhaseForFailure(error);
      if (phase == FinancialLoadPhase.authenticationRequired ||
          phase == FinancialLoadPhase.forbidden ||
          phase == FinancialLoadPhase.primaryResidenceRequired) {
        state = FinancialAccountDetailState.phase(phase);
        return FinancialMutationOutcome.accessBlocked;
      }
      state = previous.copyLoaded(
        refreshFailure: previous.refreshFailure,
        classificationTrusted: false,
      );
      return FinancialMutationOutcome.temporarilyUnavailable;
    } on FormatException {
      if (_disposed) return FinancialMutationOutcome.invalidResponse;
      state = previous.copyLoaded(
        refreshFailure: FinancialRefreshFailure.invalidResponse,
        classificationTrusted: false,
      );
      return FinancialMutationOutcome.invalidResponse;
    }
  }

  /// An allocation POST ended with an unknown outcome. Idempotency of the
  /// write (the pending key) and trust in the snapshot are separate things: the
  /// POST is never repeated automatically, and the snapshot is only trusted
  /// again after one canonical read of categories and current allocations.
  ///
  /// * read ok, the write (or a successor) is visible: the persisted truth
  ///   replaces the local map; the key is no longer needed and nothing is
  ///   resent. No causality is claimed.
  /// * read ok, nothing changed: trusted again, the key is kept so an explicit
  ///   retry of the SAME logical attempt replays instead of duplicating.
  /// * read failed: untrusted (see [_reconcileClassification]); the key is kept.
  Future<FinancialMutationOutcome> _reconcileAfterUnknownWrite(
    FinancialAccountDetailState previous,
    Map<String, String> keys,
    String attemptKey,
    bool Function(FinancialAccountDetailState reconciled) keyConsumed,
  ) async {
    final failure = await _reconcileClassification(previous);
    if (failure != null) return failure;
    if (_disposed) return FinancialMutationOutcome.unknownOutcomeReconciled;
    if (keyConsumed(state)) keys.remove(attemptKey);
    return FinancialMutationOutcome.unknownOutcomeReconciled;
  }

  FinancialMutationOutcome _failMutation(
    FinancialAccountDetailState previous,
    AuthenticatedApiException error,
  ) {
    final phase = financialPhaseForFailure(error);
    if (phase == FinancialLoadPhase.authenticationRequired ||
        phase == FinancialLoadPhase.forbidden ||
        phase == FinancialLoadPhase.primaryResidenceRequired) {
      state = FinancialAccountDetailState.phase(phase);
      return FinancialMutationOutcome.accessBlocked;
    }
    state = previous.copyLoaded(refreshFailure: previous.refreshFailure);
    return FinancialMutationOutcome.temporarilyUnavailable;
  }

  Future<bool> _runOperation(
    Future<void> Function(FinancialCoreApi api) operation,
  ) async {
    final account = state.account;
    final balance = state.balance;
    final statement = state.statement;
    if (account == null ||
        balance == null ||
        statement == null ||
        state.operationMutationInFlight) {
      return false;
    }
    final previous = state;
    state = previous.copyLoaded(
      operationMutationInFlight: true,
      refreshFailure: previous.refreshFailure,
    );
    try {
      await operation(ref.read(financialCoreApiProvider));
      await _load(refresh: true, force: true);
      return true;
    } on AuthenticatedApiException catch (error) {
      if (error.statusCode == 409 || error.statusCode == 422) {
        state = previous.copyLoaded();
        return false;
      }
      _restoreAfterMutationFailure(previous, error);
      return false;
    } on FormatException {
      _restoreInvalidResponse(previous);
      return false;
    }
  }

  void _restoreAfterMutationFailure(
    FinancialAccountDetailState previous,
    AuthenticatedApiException error,
  ) {
    final phase = financialPhaseForFailure(error);
    if (phase == FinancialLoadPhase.authenticationRequired ||
        phase == FinancialLoadPhase.forbidden ||
        phase == FinancialLoadPhase.primaryResidenceRequired) {
      state = FinancialAccountDetailState.phase(phase);
      return;
    }
    state = previous.copyLoaded(
      refreshFailure: FinancialRefreshFailure.temporarilyUnavailable,
    );
  }

  void _restoreInvalidResponse(FinancialAccountDetailState previous) {
    state = previous.copyLoaded(
      refreshFailure: FinancialRefreshFailure.invalidResponse,
    );
  }

  /// Indexes the bulk read by `movementId` and requires every referenced
  /// category to resolve (DISABLED included) in the same-currency account.
  Map<String, FinancialMovementAllocation> _resolveAllocations({
    required FinancialAccount account,
    required FinancialCategoryIndex index,
    required List<FinancialMovementAllocation> allocations,
  }) {
    final byMovement = <String, FinancialMovementAllocation>{};
    for (final allocation in allocations) {
      if (allocation.currency != account.currency ||
          allocation.allocations.any(
            (share) => index.byId(share.categoryId) == null,
          ) ||
          byMovement.containsKey(allocation.movementId)) {
        throw const FormatException('movement allocation is inconsistent.');
      }
      byMovement[allocation.movementId] = allocation;
    }
    return Map.unmodifiable(byMovement);
  }

  Future<void> _load({required bool refresh, bool force = false}) async {
    if (!force && (_inFlight || state.isBusy)) return;
    final previous = state;
    final preserve =
        refresh &&
        previous.account != null &&
        previous.balance != null &&
        previous.statement != null;
    final generation = ++_generation;
    _inFlight = true;
    state = preserve
        ? previous.copyLoaded(refreshing: true)
        : const FinancialAccountDetailState.phase(FinancialLoadPhase.loading);
    try {
      final api = ref.read(financialCoreApiProvider);
      final account = await api.getAccount(accountId);
      final openingBalance = await api.getOpeningBalance(accountId);
      final balance = await api.getBalance(accountId);
      final statement = await api.getStatement(accountId);
      final transfers = await api.listTransfers(accountId);
      final accounts = await api.listAccounts();
      // Fixed cost: one categories read, one bulk allocations read and one
      // bulk rule-origin read, independent of the number of statement rows.
      final categories = await api.listCategories();
      final allocations = await api.listCurrentMovementAllocations(accountId);
      final origins = await api.listRuleOrigins(accountId);

      if (openingBalance != null &&
          openingBalance.money.currency != account.currency) {
        throw const FormatException('opening balance currency mismatch.');
      }
      if (balance.accountId != account.accountId ||
          balance.currency != account.currency) {
        throw const FormatException('balance account mismatch.');
      }
      if (statement.accountId != account.accountId ||
          statement.currency != account.currency ||
          statement.entries.any(
            (entry) => entry.movement.money.currency != account.currency,
          )) {
        throw const FormatException('statement account mismatch.');
      }
      final statementMovementIds = statement.entries
          .map((entry) => entry.movement.movementId)
          .toSet();
      final standardTransferIds = transfers
          .where((item) => item.role == FinancialTransferRole.standard)
          .map((item) => item.transferId)
          .toSet();
      final localTransferMovementIds = <String>{};
      for (final transfer in transfers) {
        if (transfer.currency != account.currency ||
            (transfer.sourceAccountId != account.accountId &&
                transfer.destinationAccountId != account.accountId)) {
          throw const FormatException('transfer account mismatch.');
        }
        final localMovementId = transfer.sourceAccountId == account.accountId
            ? transfer.sourceMovementId
            : transfer.destinationMovementId;
        if (!statementMovementIds.contains(localMovementId) ||
            !localTransferMovementIds.add(localMovementId)) {
          throw const FormatException('transfer movement relation mismatch.');
        }
        if (transfer.role == FinancialTransferRole.reversal &&
            !standardTransferIds.contains(transfer.reversalOfId)) {
          throw const FormatException('transfer reversal relation mismatch.');
        }
      }
      final categoryIndex = FinancialCategoryIndex.build(categories);
      final currentAllocations = _resolveAllocations(
        account: account,
        index: categoryIndex,
        allocations: allocations,
      );
      if (!_isCurrent(generation)) return;
      state = FinancialAccountDetailState.loaded(
        account: account,
        openingBalance: openingBalance,
        balance: balance,
        statement: statement,
        accounts: accounts,
        transfers: transfers,
        categories: categories,
        categoryIndex: categoryIndex,
        currentAllocations: currentAllocations,
        ruleOriginsBySetId: {
          for (final origin in origins) origin.allocationSetId: origin,
        },
      );
    } catch (error) {
      if (!_isCurrent(generation)) return;
      final phase = financialPhaseForFailure(error);
      if (preserve &&
          (phase == FinancialLoadPhase.temporarilyUnavailable ||
              phase == FinancialLoadPhase.invalidResponse)) {
        state = previous.copyLoaded(
          refreshFailure: phase == FinancialLoadPhase.invalidResponse
              ? FinancialRefreshFailure.invalidResponse
              : FinancialRefreshFailure.temporarilyUnavailable,
        );
      } else {
        state = FinancialAccountDetailState.phase(phase);
      }
    } finally {
      if (generation == _generation) _inFlight = false;
    }
  }

  bool _isCurrent(int generation) => generation == _generation && _inFlight;
}

FinancialLoadPhase financialPhaseForFailure(Object error) {
  if (error is FormatException) return FinancialLoadPhase.invalidResponse;
  if (error is AuthenticatedApiException) {
    if (error.failure == AuthenticatedApiFailure.authenticationRequired ||
        error.statusCode == 401) {
      return FinancialLoadPhase.authenticationRequired;
    }
    if (error.failure == AuthenticatedApiFailure.forbidden ||
        error.statusCode == 403) {
      return FinancialLoadPhase.forbidden;
    }
    if (error.statusCode == 404) {
      return FinancialLoadPhase.notFound;
    }
    if (error.statusCode == 409) {
      return FinancialLoadPhase.primaryResidenceRequired;
    }
    if (error.failure == AuthenticatedApiFailure.temporarilyUnavailable ||
        error.failure == AuthenticatedApiFailure.transportFailure ||
        (error.statusCode != null && error.statusCode! >= 500)) {
      return FinancialLoadPhase.temporarilyUnavailable;
    }
  }
  return FinancialLoadPhase.temporarilyUnavailable;
}
