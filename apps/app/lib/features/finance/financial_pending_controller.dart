import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

// Pending-classification inbox (#249).
//
// The inbox is derived by the backend; this controller only pages through it and
// triggers the existing canonical writes (manual classification of #245 and rule
// application of #247). Contract:
//  * nothing leaves the list before a canonical re-read says so (no optimistic
//    removal): after any write the first page is read again and replaces the
//    list;
//  * a write is sent once; an ambiguous outcome (transport/5xx/invalid 2xx) is
//    never retried automatically;
//  * a rule is only applied after an explicit confirmation, and an ambiguous
//    item never gets a rule chosen for it;
//  * the cost is fixed: one inbox page, categories and accounts per load, never
//    a request per row.

/// Filters of the inbox. All optional; they are part of every request.
class FinancialPendingFilters {
  const FinancialPendingFilters({
    this.accountId,
    this.resultEffect,
    this.ruleStatus,
  });

  static const none = FinancialPendingFilters();

  final String? accountId;
  final FinancialResultEffect? resultEffect;
  final FinancialPendingRuleStatus? ruleStatus;

  bool get isActive =>
      accountId != null || resultEffect != null || ruleStatus != null;

  FinancialPendingFilters copyWith({
    Object? accountId = _unset,
    Object? resultEffect = _unset,
    Object? ruleStatus = _unset,
  }) => FinancialPendingFilters(
    accountId: identical(accountId, _unset)
        ? this.accountId
        : accountId as String?,
    resultEffect: identical(resultEffect, _unset)
        ? this.resultEffect
        : resultEffect as FinancialResultEffect?,
    ruleStatus: identical(ruleStatus, _unset)
        ? this.ruleStatus
        : ruleStatus as FinancialPendingRuleStatus?,
  );

  @override
  bool operator ==(Object other) =>
      other is FinancialPendingFilters &&
      other.accountId == accountId &&
      other.resultEffect == resultEffect &&
      other.ruleStatus == ruleStatus;

  @override
  int get hashCode => Object.hash(accountId, resultEffect, ruleStatus);
}

const Object _unset = Object();

/// What an inbox action ended with. Never claims more than the backend said.
enum FinancialPendingActionOutcome {
  /// The suggested rule classified the Movement (confirmed by the backend).
  ruleApplied,

  /// The manual classification was persisted (confirmed by the backend).
  manuallyClassified,

  /// Someone (or another rule) classified it first; nothing was written here.
  alreadyClassified,

  /// The canonical state differs from what was shown (another rule wins, the
  /// rule or category changed, ambiguity appeared, a 409): nothing was written.
  stateChanged,

  /// 404/422: the backend refused the request; nothing was written.
  rejected,

  /// The backend reported a persistence failure for this Movement.
  failed,

  /// Transport/5xx/invalid response: the write may or may not have happened. It
  /// was NOT resent; the list was read again.
  unknownOutcome,

  /// Refused locally before any request (read-only, busy, stale, ineligible).
  notAllowed,

  /// 401/403/residence: the access is gone; the screen phase says so.
  accessBlocked,
}

class FinancialPendingActionResult {
  const FinancialPendingActionResult(this.outcome, {this.reconciled = true});

  final FinancialPendingActionOutcome outcome;

  /// False when the canonical re-read after the action also failed: the visible
  /// list may be stale and actions stay blocked until a refresh succeeds.
  final bool reconciled;
}

class FinancialPendingState {
  const FinancialPendingState._({
    required this.phase,
    this.items = const [],
    this.nextCursor,
    this.filters = FinancialPendingFilters.none,
    this.accounts = const [],
    this.categories = const [],
    this.categoryIndex = FinancialCategoryIndex.empty,
    this.loadingMore = false,
    this.loadMoreFailure = FinancialRefreshFailure.none,
    this.refreshFailure = FinancialRefreshFailure.none,
    this.mutationMovementId,
    this.trusted = true,
  });

  const FinancialPendingState.idle() : this._(phase: FinancialLoadPhase.idle);
  const FinancialPendingState.phase(
    FinancialLoadPhase phase, {
    FinancialPendingFilters filters = FinancialPendingFilters.none,
  }) : this._(phase: phase, filters: filters);

  FinancialPendingState.loaded({
    required List<FinancialPendingMovement> items,
    required String? nextCursor,
    required FinancialPendingFilters filters,
    required List<FinancialAccount> accounts,
    required List<FinancialCategory> categories,
    FinancialCategoryIndex? categoryIndex,
    bool refreshing = false,
    bool loadingMore = false,
    FinancialRefreshFailure loadMoreFailure = FinancialRefreshFailure.none,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
    String? mutationMovementId,
    bool trusted = true,
  }) : this._(
         phase: refreshing
             ? FinancialLoadPhase.refreshing
             : FinancialLoadPhase.loaded,
         items: List<FinancialPendingMovement>.unmodifiable(items),
         nextCursor: nextCursor,
         filters: filters,
         accounts: List<FinancialAccount>.unmodifiable(accounts),
         categories: List<FinancialCategory>.unmodifiable(categories),
         categoryIndex:
             categoryIndex ?? FinancialCategoryIndex.build(categories),
         loadingMore: loadingMore,
         loadMoreFailure: loadMoreFailure,
         refreshFailure: refreshFailure,
         mutationMovementId: mutationMovementId,
         trusted: trusted,
       );

  final FinancialLoadPhase phase;
  final List<FinancialPendingMovement> items;

  /// Set when more candidates may exist. With a rule-status filter the loaded
  /// list can be empty while this is set (the server scan budget ended).
  final String? nextCursor;
  final FinancialPendingFilters filters;
  final List<FinancialAccount> accounts;

  /// Every category the server returned, DISABLED included.
  final List<FinancialCategory> categories;
  final FinancialCategoryIndex categoryIndex;
  final bool loadingMore;
  final FinancialRefreshFailure loadMoreFailure;
  final FinancialRefreshFailure refreshFailure;

  /// The Movement whose write is in flight; every action is blocked meanwhile.
  final String? mutationMovementId;

  /// False when a canonical re-read after a write failed: the list may be stale.
  final bool trusted;

  bool get isLoaded =>
      phase == FinancialLoadPhase.loaded ||
      phase == FinancialLoadPhase.refreshing;

  bool get mutationInFlight => mutationMovementId != null;

  /// Busy also while a next page is loading, so a write can never overlap a
  /// page append and a late page can never clobber the in-flight flag.
  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing ||
      loadingMore ||
      mutationInFlight;

  bool get hasMore => nextCursor != null;

  FinancialAccount? accountOf(String accountId) {
    for (final account in accounts) {
      if (account.accountId == accountId) return account;
    }
    return null;
  }

  FinancialPendingMovement? itemOf(String movementId) {
    for (final item in items) {
      if (item.movementId == movementId) return item;
    }
    return null;
  }

  FinancialPendingState copyLoaded({
    List<FinancialPendingMovement>? items,
    Object? nextCursor = _unset,
    FinancialPendingFilters? filters,
    List<FinancialCategory>? categories,
    FinancialCategoryIndex? categoryIndex,
    bool refreshing = false,
    bool loadingMore = false,
    FinancialRefreshFailure loadMoreFailure = FinancialRefreshFailure.none,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
    Object? mutationMovementId = _unset,
    bool? trusted,
  }) => FinancialPendingState.loaded(
    items: items ?? this.items,
    nextCursor: identical(nextCursor, _unset)
        ? this.nextCursor
        : nextCursor as String?,
    filters: filters ?? this.filters,
    accounts: accounts,
    categories: categories ?? this.categories,
    categoryIndex: categories == null
        ? (categoryIndex ?? this.categoryIndex)
        : categoryIndex,
    refreshing: refreshing,
    loadingMore: loadingMore,
    loadMoreFailure: loadMoreFailure,
    refreshFailure: refreshFailure,
    mutationMovementId: identical(mutationMovementId, _unset)
        ? null
        : mutationMovementId as String?,
    trusted: trusted ?? this.trusted,
  );
}

final financialPendingControllerProvider =
    NotifierProvider.autoDispose<
      FinancialPendingController,
      FinancialPendingState
    >(FinancialPendingController.new);

class FinancialPendingController extends Notifier<FinancialPendingState> {
  int _generation = 0;
  bool _inFlight = false;
  bool _disposed = false;

  /// Idempotency keys of manual classification attempts whose outcome is
  /// unknown. Only an identical, user-initiated retry reuses one (the server
  /// replays it); anything else gets a fresh key. Never resent automatically.
  final Map<String, String> _pendingClassificationKeys = {};

  @override
  FinancialPendingState build() {
    ref.onDispose(() {
      _disposed = true;
      _generation += 1;
      _inFlight = false;
    });
    return const FinancialPendingState.idle();
  }

  Future<void> load() => _loadFirst(refresh: false);
  Future<void> refresh() => _loadFirst(refresh: true);

  /// Changes the filters and reads the first page again. The cursor of the
  /// previous filter set is dropped: the server binds a cursor to its filters.
  Future<void> setFilters(FinancialPendingFilters filters) async {
    final current = state;
    if (current.mutationInFlight || filters == current.filters) return;
    await _loadFirst(refresh: current.isLoaded, filters: filters, force: true);
  }

  /// Reads the next keyset page and appends only Movements not already listed.
  Future<void> loadMore() async {
    final previous = state;
    if (!previous.isLoaded ||
        previous.isBusy ||
        previous.loadingMore ||
        previous.nextCursor == null) {
      return;
    }
    final generation = _generation;
    state = previous.copyLoaded(
      loadingMore: true,
      refreshFailure: previous.refreshFailure,
    );
    try {
      final page = await ref
          .read(financialCoreApiProvider)
          .listPendingMovements(
            cursor: previous.nextCursor,
            accountId: previous.filters.accountId,
            resultEffect: previous.filters.resultEffect,
            ruleStatus: previous.filters.ruleStatus,
          );
      if (_disposed || generation != _generation) return;
      final known = previous.items.map((item) => item.movementId).toSet();
      // Writes cannot start while a page loads, but a stale page must still
      // never overwrite a state that moved on.
      if (state.mutationInFlight || !state.loadingMore) return;
      state = previous.copyLoaded(
        items: [
          ...previous.items,
          for (final item in page.items)
            if (!known.contains(item.movementId)) item,
        ],
        nextCursor: page.nextCursor,
      );
    } on AuthenticatedApiException catch (error) {
      if (_disposed || generation != _generation) return;
      final phase = financialPhaseForFailure(error);
      if (phase == FinancialLoadPhase.authenticationRequired ||
          phase == FinancialLoadPhase.forbidden ||
          phase == FinancialLoadPhase.primaryResidenceRequired) {
        state = FinancialPendingState.phase(phase, filters: previous.filters);
        return;
      }
      state = previous.copyLoaded(
        loadMoreFailure: FinancialRefreshFailure.temporarilyUnavailable,
      );
    } on FormatException {
      if (_disposed || generation != _generation) return;
      state = previous.copyLoaded(
        loadMoreFailure: FinancialRefreshFailure.invalidResponse,
      );
    }
  }

  /// Applies the suggested rule of one MATCHED item. The caller must have shown
  /// an explicit confirmation. One POST; the answer is the only truth and the
  /// list is always read again afterwards.
  Future<FinancialPendingActionResult> applySuggestion(
    String movementId,
  ) async {
    final previous = state;
    final item = previous.itemOf(movementId);
    if (item == null ||
        !_canWrite(previous, item) ||
        !item.hasSuggestion ||
        item.matchedRuleId == null) {
      return const FinancialPendingActionResult(
        FinancialPendingActionOutcome.notAllowed,
      );
    }
    final FinancialCategorizationApplyItem pair;
    try {
      pair = FinancialCategorizationApplyItem(
        movementId: item.movementId,
        ruleId: item.matchedRuleId!,
      );
    } on FormatException {
      return const FinancialPendingActionResult(
        FinancialPendingActionOutcome.notAllowed,
      );
    }
    state = previous.copyLoaded(
      mutationMovementId: movementId,
      refreshFailure: previous.refreshFailure,
    );
    final FinancialPendingActionOutcome outcome;
    try {
      final result = await ref
          .read(financialCoreApiProvider)
          .applyCategorizationRules(item.accountId, [pair]);
      outcome = switch (result.results.single.status) {
        FinancialCategorizationApplyStatus.classified =>
          FinancialPendingActionOutcome.ruleApplied,
        FinancialCategorizationApplyStatus.alreadyClassified =>
          FinancialPendingActionOutcome.alreadyClassified,
        FinancialCategorizationApplyStatus.failed =>
          FinancialPendingActionOutcome.failed,
        FinancialCategorizationApplyStatus.ambiguous ||
        FinancialCategorizationApplyStatus.noMatch ||
        FinancialCategorizationApplyStatus.ineligible ||
        FinancialCategorizationApplyStatus.conflict =>
          FinancialPendingActionOutcome.stateChanged,
      };
    } on AuthenticatedApiException catch (error) {
      return _afterFailedWrite(previous, error);
    } on FormatException {
      // A 2xx that cannot be validated: the write may have happened.
      return _reconcile(previous, FinancialPendingActionOutcome.unknownOutcome);
    }
    return _reconcile(previous, outcome);
  }

  /// First (simple) manual classification of one item in one category, through
  /// the same canonical endpoint and policy as the statement. Splitting between
  /// categories stays in the account screen.
  Future<FinancialPendingActionResult> classify(
    String movementId,
    String categoryId,
  ) async {
    final previous = state;
    final item = previous.itemOf(movementId);
    final account = item == null ? null : previous.accountOf(item.accountId);
    final category = previous.categoryIndex.byId(categoryId);
    if (item == null ||
        account == null ||
        category == null ||
        !_canWrite(previous, item) ||
        !isFinancialCategoryEligibleForAccount(
          category: category,
          account: account,
        )) {
      return const FinancialPendingActionResult(
        FinancialPendingActionOutcome.notAllowed,
      );
    }
    final attempt = '$movementId|$categoryId';
    final FinancialMovementAllocationCreateInput input;
    try {
      input = FinancialMovementAllocationCreateInput.single(
        categoryId: categoryId,
        movementMoney: item.money,
        idempotencyKey: _pendingClassificationKeys[attempt],
      );
    } on FormatException {
      return const FinancialPendingActionResult(
        FinancialPendingActionOutcome.notAllowed,
      );
    }
    _pendingClassificationKeys[attempt] = input.idempotencyKey;

    state = previous.copyLoaded(
      mutationMovementId: movementId,
      refreshFailure: previous.refreshFailure,
    );
    try {
      final created = await ref
          .read(financialCoreApiProvider)
          .createMovementAllocation(movementId, input);
      if (created.currency != item.money.currency) {
        throw const FormatException('financial allocation response mismatch.');
      }
      _pendingClassificationKeys.remove(attempt);
      return _reconcile(
        previous,
        FinancialPendingActionOutcome.manuallyClassified,
      );
    } on AuthenticatedApiException catch (error) {
      final status = error.statusCode;
      if (status == 409 || status == 404 || status == 422) {
        _pendingClassificationKeys.remove(attempt);
      }
      return _afterFailedWrite(previous, error);
    } on FormatException {
      return _reconcile(
        previous,
        FinancialPendingActionOutcome.unknownOutcome,
        keyAttempt: attempt,
      );
    }
  }

  bool _canWrite(FinancialPendingState state, FinancialPendingMovement item) {
    final operatorId = ref
        .read(operatorSessionControllerProvider)
        .principal
        ?.operatorId;
    final account = state.accountOf(item.accountId);
    return state.isLoaded &&
        state.trusted &&
        !state.isBusy &&
        item.canClassify &&
        account != null &&
        account.status == FinancialAccountStatus.active &&
        isFinancialAccountOwner(account: account, operatorId: operatorId);
  }

  Future<FinancialPendingActionResult> _afterFailedWrite(
    FinancialPendingState previous,
    AuthenticatedApiException error,
  ) async {
    if (_disposed) {
      return const FinancialPendingActionResult(
        FinancialPendingActionOutcome.unknownOutcome,
        reconciled: false,
      );
    }
    // 409/404/422 first, like the statement flow: a 409 is read as "state
    // changed" and the canonical re-read below reveals a lost residence.
    final status = error.statusCode;
    if (status == 409) {
      return _reconcile(previous, FinancialPendingActionOutcome.stateChanged);
    }
    if (status == 404 || status == 422) {
      return _reconcile(previous, FinancialPendingActionOutcome.rejected);
    }
    final phase = financialPhaseForFailure(error);
    if (phase == FinancialLoadPhase.authenticationRequired ||
        phase == FinancialLoadPhase.forbidden ||
        phase == FinancialLoadPhase.primaryResidenceRequired) {
      state = FinancialPendingState.phase(phase, filters: previous.filters);
      return const FinancialPendingActionResult(
        FinancialPendingActionOutcome.accessBlocked,
        reconciled: false,
      );
    }
    // Timeout/transport/5xx: unknown. Never resent; read the truth once.
    return _reconcile(previous, FinancialPendingActionOutcome.unknownOutcome);
  }

  /// One canonical read after any write answer: the first page and the
  /// categories replace the list. The write is never repeated.
  Future<FinancialPendingActionResult> _reconcile(
    FinancialPendingState previous,
    FinancialPendingActionOutcome outcome, {
    String? keyAttempt,
  }) async {
    if (_disposed) {
      return FinancialPendingActionResult(outcome, reconciled: false);
    }
    final generation = ++_generation;
    try {
      final api = ref.read(financialCoreApiProvider);
      final filters = previous.filters;
      final page = await api.listPendingMovements(
        accountId: filters.accountId,
        resultEffect: filters.resultEffect,
        ruleStatus: filters.ruleStatus,
      );
      final categories = await api.listCategories();
      final index = FinancialCategoryIndex.build(categories);
      if (_disposed || generation != _generation) {
        return FinancialPendingActionResult(outcome, reconciled: false);
      }
      if (keyAttempt != null &&
          !page.items.any(
            (item) => keyAttempt.startsWith('${item.movementId}|'),
          )) {
        // The Movement is no longer pending: the key has done its job.
        _pendingClassificationKeys.remove(keyAttempt);
      }
      state = FinancialPendingState.loaded(
        items: page.items,
        nextCursor: page.nextCursor,
        filters: filters,
        accounts: previous.accounts,
        categories: categories,
        categoryIndex: index,
        trusted: true,
      );
      return FinancialPendingActionResult(outcome);
    } on AuthenticatedApiException catch (error) {
      if (_disposed || generation != _generation) {
        return FinancialPendingActionResult(outcome, reconciled: false);
      }
      final phase = financialPhaseForFailure(error);
      if (phase == FinancialLoadPhase.authenticationRequired ||
          phase == FinancialLoadPhase.forbidden ||
          phase == FinancialLoadPhase.primaryResidenceRequired) {
        state = FinancialPendingState.phase(phase, filters: previous.filters);
        return const FinancialPendingActionResult(
          FinancialPendingActionOutcome.accessBlocked,
          reconciled: false,
        );
      }
      state = previous.copyLoaded(
        refreshFailure: FinancialRefreshFailure.temporarilyUnavailable,
        trusted: false,
      );
      return FinancialPendingActionResult(outcome, reconciled: false);
    } on FormatException {
      if (_disposed || generation != _generation) {
        return FinancialPendingActionResult(outcome, reconciled: false);
      }
      state = previous.copyLoaded(
        refreshFailure: FinancialRefreshFailure.invalidResponse,
        trusted: false,
      );
      return FinancialPendingActionResult(outcome, reconciled: false);
    }
  }

  Future<void> _loadFirst({
    required bool refresh,
    FinancialPendingFilters? filters,
    bool force = false,
  }) async {
    if (!force && (_inFlight || state.isBusy)) return;
    final previous = state;
    final effectiveFilters = filters ?? previous.filters;
    final preserve = refresh && previous.isLoaded;
    final generation = ++_generation;
    _inFlight = true;
    state = preserve
        ? previous.copyLoaded(refreshing: true, filters: effectiveFilters)
        : FinancialPendingState.phase(
            FinancialLoadPhase.loading,
            filters: effectiveFilters,
          );
    try {
      // Fixed cost: one inbox page, categories and accounts, whatever the size.
      final api = ref.read(financialCoreApiProvider);
      final page = await api.listPendingMovements(
        accountId: effectiveFilters.accountId,
        resultEffect: effectiveFilters.resultEffect,
        ruleStatus: effectiveFilters.ruleStatus,
      );
      final categories = await api.listCategories();
      final accounts = await api.listAccounts();
      final index = FinancialCategoryIndex.build(categories);
      if (generation != _generation || !_inFlight) return;
      state = FinancialPendingState.loaded(
        items: page.items,
        nextCursor: page.nextCursor,
        filters: effectiveFilters,
        accounts: accounts,
        categories: categories,
        categoryIndex: index,
      );
    } catch (error) {
      if (generation != _generation || !_inFlight) return;
      final phase = financialPhaseForFailure(error);
      if (preserve &&
          (phase == FinancialLoadPhase.temporarilyUnavailable ||
              phase == FinancialLoadPhase.invalidResponse)) {
        state = previous.copyLoaded(
          filters: previous.filters,
          trusted: previous.trusted,
          refreshFailure: phase == FinancialLoadPhase.invalidResponse
              ? FinancialRefreshFailure.invalidResponse
              : FinancialRefreshFailure.temporarilyUnavailable,
        );
      } else {
        state = FinancialPendingState.phase(phase, filters: effectiveFilters);
      }
    } finally {
      if (generation == _generation) _inFlight = false;
    }
  }
}
