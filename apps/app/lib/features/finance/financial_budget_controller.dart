import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

// Monthly category budgets (#252).
//
// A budget is planning, never a ledger. This controller only pages months, reads
// the plan and the server-derived summary, and sends the plan writes. Contract:
//  * the realized/remaining/status/percent come from the server on every read and
//    are never computed, cached or patched here;
//  * nothing is optimistic: after any write answer (success, 409, 403, 404, 422,
//    5xx, transport, invalid 2xx) the month is read again (one canonical
//    re-read) and replaces the state;
//  * a write is sent once. A stale `expectedVersion` (409) is never retried or
//    re-based: the user sees the current plan and edits again explicitly. An
//    ambiguous create keeps its idempotency key only for an explicit, identical
//    retry that the server replays;
//  * the cost per month is fixed: categories, the month's budgets and one summary,
//    never a request per line or per Movement.

/// What the last plan action ended with. Never claims more than the server said.
enum FinancialBudgetActionOutcome {
  /// The budget was created (confirmed by the backend).
  created,

  /// The plan was replaced (confirmed by the backend).
  updated,

  /// 409: the budget changed since it was read (stale version) or that month
  /// already has this plan. Nothing was written; the current plan was read.
  conflict,

  /// 404/422: the backend refused the request. Nothing was written.
  rejected,

  /// 403 with the access still valid: the budget is read-only for this operator.
  readOnly,

  /// Transport/5xx/invalid response: the write may or may not have happened. It
  /// was NOT resent; the month was read again.
  unknownOutcome,

  /// Refused locally before any request (busy, untrusted, read-only, invalid).
  notAllowed,

  /// 401/403/residence: the access is gone; the screen phase says so.
  accessBlocked,
}

class FinancialBudgetActionResult {
  const FinancialBudgetActionResult(
    this.outcome, {
    this.reconciled = true,
    this.budgetId,
  });

  final FinancialBudgetActionOutcome outcome;

  /// False when the canonical re-read after the action also failed: the visible
  /// plan may be stale and writes stay blocked until a refresh succeeds.
  final bool reconciled;

  /// The created/updated budget (confirmed), when there is one.
  final String? budgetId;
}

/// State of the summary of the selected budget.
enum FinancialBudgetSummaryPhase {
  none,
  loading,
  ready,
  temporarilyUnavailable,
  invalidResponse,
}

class FinancialBudgetsState {
  const FinancialBudgetsState._({
    required this.phase,
    required this.period,
    this.budgets = const [],
    this.selectedBudgetId,
    this.summary,
    this.summaryPhase = FinancialBudgetSummaryPhase.none,
    this.categories = const [],
    this.categoryIndex = FinancialCategoryIndex.empty,
    this.refreshFailure = FinancialRefreshFailure.none,
    this.mutationInFlight = false,
    this.trusted = true,
    this.conflictNotice = false,
  });

  const FinancialBudgetsState.idle(String period)
    : this._(phase: FinancialLoadPhase.idle, period: period);

  const FinancialBudgetsState.phase(FinancialLoadPhase phase, String period)
    : this._(phase: phase, period: period);

  FinancialBudgetsState.loaded({
    required String period,
    required List<FinancialBudget> budgets,
    required String? selectedBudgetId,
    required List<FinancialCategory> categories,
    FinancialCategoryIndex? categoryIndex,
    FinancialBudgetSummary? summary,
    FinancialBudgetSummaryPhase summaryPhase = FinancialBudgetSummaryPhase.none,
    bool refreshing = false,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
    bool mutationInFlight = false,
    bool trusted = true,
    bool conflictNotice = false,
  }) : this._(
         phase: refreshing
             ? FinancialLoadPhase.refreshing
             : budgets.isEmpty
             ? FinancialLoadPhase.empty
             : FinancialLoadPhase.loaded,
         period: period,
         budgets: List<FinancialBudget>.unmodifiable(budgets),
         selectedBudgetId: selectedBudgetId,
         summary: summary,
         summaryPhase: summaryPhase,
         categories: List<FinancialCategory>.unmodifiable(categories),
         categoryIndex:
             categoryIndex ?? FinancialCategoryIndex.build(categories),
         refreshFailure: refreshFailure,
         mutationInFlight: mutationInFlight,
         trusted: trusted,
         conflictNotice: conflictNotice,
       );

  final FinancialLoadPhase phase;

  /// The month being shown, `YYYY-MM`.
  final String period;
  final List<FinancialBudget> budgets;
  final String? selectedBudgetId;

  /// Server-derived summary of [selectedBudgetId]; null until it is read.
  final FinancialBudgetSummary? summary;
  final FinancialBudgetSummaryPhase summaryPhase;

  /// Every category the server returned, DISABLED included.
  final List<FinancialCategory> categories;
  final FinancialCategoryIndex categoryIndex;
  final FinancialRefreshFailure refreshFailure;
  final bool mutationInFlight;

  /// False when a canonical re-read after a write failed: the plan may be stale.
  final bool trusted;

  /// The last write lost a compare-and-swap (or hit an existing plan).
  final bool conflictNotice;

  bool get isLoaded =>
      phase == FinancialLoadPhase.loaded ||
      phase == FinancialLoadPhase.empty ||
      phase == FinancialLoadPhase.refreshing;

  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing ||
      summaryPhase == FinancialBudgetSummaryPhase.loading ||
      mutationInFlight;

  FinancialBudget? get selected {
    final id = selectedBudgetId;
    if (id == null) return null;
    for (final budget in budgets) {
      if (budget.id == id) return budget;
    }
    return null;
  }

  FinancialBudgetsState copyWith({
    List<FinancialBudget>? budgets,
    Object? selectedBudgetId = _unset,
    Object? summary = _unset,
    FinancialBudgetSummaryPhase? summaryPhase,
    List<FinancialCategory>? categories,
    FinancialCategoryIndex? categoryIndex,
    bool refreshing = false,
    FinancialRefreshFailure? refreshFailure,
    bool? mutationInFlight,
    bool? trusted,
    bool? conflictNotice,
  }) => FinancialBudgetsState.loaded(
    period: period,
    budgets: budgets ?? this.budgets,
    selectedBudgetId: identical(selectedBudgetId, _unset)
        ? this.selectedBudgetId
        : selectedBudgetId as String?,
    categories: categories ?? this.categories,
    categoryIndex: categories == null
        ? (categoryIndex ?? this.categoryIndex)
        : categoryIndex,
    summary: identical(summary, _unset)
        ? this.summary
        : summary as FinancialBudgetSummary?,
    summaryPhase: summaryPhase ?? this.summaryPhase,
    refreshing: refreshing,
    refreshFailure: refreshFailure ?? this.refreshFailure,
    mutationInFlight: mutationInFlight ?? this.mutationInFlight,
    trusted: trusted ?? this.trusted,
    conflictNotice: conflictNotice ?? this.conflictNotice,
  );
}

const Object _unset = Object();

/// Injectable clock so the initial month is deterministic in tests.
final financialBudgetClockProvider = Provider<DateTime Function()>(
  (ref) => DateTime.now,
);

final financialBudgetsControllerProvider =
    NotifierProvider.autoDispose<
      FinancialBudgetsController,
      FinancialBudgetsState
    >(FinancialBudgetsController.new);

class FinancialBudgetsController extends Notifier<FinancialBudgetsState> {
  int _generation = 0;
  bool _disposed = false;

  /// Idempotency keys of create attempts whose outcome is unknown. Only an
  /// identical, user-initiated retry reuses one (the server replays it).
  final Map<String, String> _createKeys = {};

  @override
  FinancialBudgetsState build() {
    ref.onDispose(() {
      _disposed = true;
      _generation += 1;
    });
    final now = ref.read(financialBudgetClockProvider)();
    return FinancialBudgetsState.idle(currentFinancialBudgetPeriod(now));
  }

  Future<void> load() => _loadMonth(state.period, refresh: false);

  Future<void> refresh() => _loadMonth(
    state.period,
    refresh: state.isLoaded,
    keepSelection: true,
    force: true,
  );

  /// Shows another month. Dropped: the previous month's selection and summary.
  Future<void> setPeriod(String period) async {
    if (state.mutationInFlight || period == state.period) return;
    await _loadMonth(period, refresh: state.isLoaded, force: true);
  }

  Future<void> nextMonth() =>
      setPeriod(shiftFinancialBudgetPeriod(state.period, 1));

  Future<void> previousMonth() =>
      setPeriod(shiftFinancialBudgetPeriod(state.period, -1));

  /// Selects another budget of the month and reads its summary.
  Future<void> select(String budgetId) async {
    final previous = state;
    if (!previous.isLoaded ||
        previous.mutationInFlight ||
        previous.phase == FinancialLoadPhase.refreshing ||
        previous.selectedBudgetId == budgetId ||
        !previous.budgets.any((budget) => budget.id == budgetId)) {
      return;
    }
    final generation = ++_generation;
    state = previous.copyWith(
      selectedBudgetId: budgetId,
      summary: null,
      summaryPhase: FinancialBudgetSummaryPhase.loading,
      conflictNotice: false,
    );
    await _readSummary(budgetId, generation);
  }

  /// Retries only the summary of the selected budget (the plan is fine).
  Future<void> reloadSummary() async {
    final previous = state;
    final id = previous.selectedBudgetId;
    if (!previous.isLoaded ||
        id == null ||
        previous.mutationInFlight ||
        previous.summaryPhase == FinancialBudgetSummaryPhase.loading) {
      return;
    }
    final generation = ++_generation;
    state = previous.copyWith(
      summary: null,
      summaryPhase: FinancialBudgetSummaryPhase.loading,
    );
    await _readSummary(id, generation);
  }

  void dismissConflictNotice() {
    if (state.isLoaded && state.conflictNotice) {
      state = state.copyWith(conflictNotice: false);
    }
  }

  /// Creates a budget for the shown month. One POST; the answer is the only
  /// truth and the month is always read again afterwards.
  Future<FinancialBudgetActionResult> createBudget(
    FinancialBudgetCreateInput input,
  ) async {
    final previous = state;
    if (!_canWrite(previous) || input.period != previous.period) {
      return const FinancialBudgetActionResult(
        FinancialBudgetActionOutcome.notAllowed,
      );
    }
    final attempt = input.attemptKey;
    final send = input.withIdempotencyKey(
      _createKeys[attempt] ?? input.idempotencyKey,
    );
    _createKeys[attempt] = send.idempotencyKey;
    state = previous.copyWith(mutationInFlight: true, conflictNotice: false);
    try {
      final created = await ref
          .read(financialCoreApiProvider)
          .createBudget(send);
      _createKeys.remove(attempt);
      return _reconcile(
        FinancialBudgetActionOutcome.created,
        select: created.id,
        budgetId: created.id,
      );
    } on AuthenticatedApiException catch (error) {
      final status = error.statusCode;
      if (status == 409 || status == 404 || status == 422) {
        _createKeys.remove(attempt);
      }
      return _afterFailedWrite(error);
    } on FormatException {
      // A 2xx that cannot be validated: the write may have happened. The key
      // stays for an explicit identical retry; nothing is resent here.
      return _reconcile(FinancialBudgetActionOutcome.unknownOutcome);
    }
  }

  /// Replaces name and lines of [budgetId] under CAS. One PUT, never retried.
  Future<FinancialBudgetActionResult> replaceBudget(
    String budgetId,
    FinancialBudgetReplaceInput input,
  ) async {
    final previous = state;
    final budget = previous.budgets
        .where((candidate) => candidate.id == budgetId)
        .firstOrNull;
    if (budget == null ||
        !_canWrite(previous) ||
        !budget.canEdit ||
        input.expectedVersion != budget.version ||
        input.currency != budget.currency) {
      return const FinancialBudgetActionResult(
        FinancialBudgetActionOutcome.notAllowed,
      );
    }
    state = previous.copyWith(mutationInFlight: true, conflictNotice: false);
    try {
      final updated = await ref
          .read(financialCoreApiProvider)
          .replaceBudget(budgetId, input);
      return _reconcile(
        FinancialBudgetActionOutcome.updated,
        select: updated.id,
        budgetId: updated.id,
      );
    } on AuthenticatedApiException catch (error) {
      return _afterFailedWrite(error);
    } on FormatException {
      return _reconcile(FinancialBudgetActionOutcome.unknownOutcome);
    }
  }

  bool _canWrite(FinancialBudgetsState state) =>
      state.isLoaded &&
      state.phase != FinancialLoadPhase.refreshing &&
      state.trusted &&
      !state.isBusy;

  Future<FinancialBudgetActionResult> _afterFailedWrite(
    AuthenticatedApiException error,
  ) async {
    if (_disposed) {
      return const FinancialBudgetActionResult(
        FinancialBudgetActionOutcome.unknownOutcome,
        reconciled: false,
      );
    }
    final status = error.statusCode;
    if (status == 409) {
      return _reconcile(FinancialBudgetActionOutcome.conflict, conflict: true);
    }
    if (status == 404 || status == 422) {
      return _reconcile(FinancialBudgetActionOutcome.rejected);
    }
    final phase = financialPhaseForFailure(error);
    if (phase == FinancialLoadPhase.authenticationRequired ||
        phase == FinancialLoadPhase.primaryResidenceRequired) {
      state = FinancialBudgetsState.phase(phase, state.period);
      return const FinancialBudgetActionResult(
        FinancialBudgetActionOutcome.accessBlocked,
        reconciled: false,
      );
    }
    if (phase == FinancialLoadPhase.forbidden) {
      // 403 is also "you may read it but not edit it": the canonical re-read
      // tells the two apart (a lost residence fails the read with 403 too).
      return _reconcile(FinancialBudgetActionOutcome.readOnly);
    }
    // Timeout/transport/5xx: unknown. Never resent; read the truth once.
    return _reconcile(FinancialBudgetActionOutcome.unknownOutcome);
  }

  /// One canonical read after any write answer. The write is never repeated.
  Future<FinancialBudgetActionResult> _reconcile(
    FinancialBudgetActionOutcome outcome, {
    String? select,
    String? budgetId,
    bool conflict = false,
  }) async {
    if (_disposed) {
      return FinancialBudgetActionResult(
        outcome,
        reconciled: false,
        budgetId: budgetId,
      );
    }
    final reconciled = await _loadMonth(
      state.period,
      refresh: true,
      keepSelection: true,
      select: select,
      force: true,
      afterWrite: true,
      conflict: conflict,
    );
    final blocked =
        state.phase == FinancialLoadPhase.authenticationRequired ||
        state.phase == FinancialLoadPhase.forbidden ||
        state.phase == FinancialLoadPhase.primaryResidenceRequired;
    return FinancialBudgetActionResult(
      blocked ? FinancialBudgetActionOutcome.accessBlocked : outcome,
      reconciled: reconciled,
      budgetId: budgetId,
    );
  }

  /// Reads categories and the month's budgets, then the summary of the selected
  /// one. Returns whether the read fully succeeded.
  Future<bool> _loadMonth(
    String period, {
    required bool refresh,
    bool keepSelection = false,
    String? select,
    bool force = false,
    bool afterWrite = false,
    bool conflict = false,
  }) async {
    final previous = state;
    if (!force && previous.phase == FinancialLoadPhase.loading) return false;
    final generation = ++_generation;
    final preserved = refresh && previous.isLoaded ? previous : null;
    final sameMonth = preserved != null && preserved.period == period;
    final wantedSelection =
        select ?? (keepSelection ? previous.selectedBudgetId : null);
    state = preserved == null
        ? FinancialBudgetsState.phase(FinancialLoadPhase.loading, period)
        : FinancialBudgetsState.loaded(
            period: period,
            budgets: sameMonth ? preserved.budgets : const [],
            selectedBudgetId: sameMonth ? preserved.selectedBudgetId : null,
            categories: preserved.categories,
            categoryIndex: preserved.categoryIndex,
            summary: sameMonth ? preserved.summary : null,
            summaryPhase: sameMonth
                ? preserved.summaryPhase
                : FinancialBudgetSummaryPhase.none,
            refreshing: true,
            mutationInFlight: afterWrite,
            trusted: preserved.trusted,
            conflictNotice: preserved.conflictNotice,
          );
    try {
      final api = ref.read(financialCoreApiProvider);
      final categories = await api.listCategories();
      final budgets = await api.listBudgets(period);
      if (_disposed || generation != _generation) return false;
      final index = FinancialCategoryIndex.build(categories);
      final selectedId = budgets.any((budget) => budget.id == wantedSelection)
          ? wantedSelection
          : (budgets.isEmpty ? null : budgets.first.id);
      state = FinancialBudgetsState.loaded(
        period: period,
        budgets: budgets,
        selectedBudgetId: selectedId,
        categories: categories,
        categoryIndex: index,
        summaryPhase: selectedId == null
            ? FinancialBudgetSummaryPhase.none
            : FinancialBudgetSummaryPhase.loading,
        mutationInFlight: afterWrite,
        conflictNotice: conflict,
      );
      if (selectedId == null) {
        state = state.copyWith(mutationInFlight: false);
        return true;
      }
      final ok = await _readSummary(selectedId, generation, settle: true);
      return ok;
    } on AuthenticatedApiException catch (error) {
      if (_disposed || generation != _generation) return false;
      _failLoad(error, preserved, period, conflict: conflict);
      return false;
    } on FormatException {
      if (_disposed || generation != _generation) return false;
      _failLoad(
        const FormatException('invalid'),
        preserved,
        period,
        conflict: conflict,
      );
      return false;
    }
  }

  void _failLoad(
    Object error,
    FinancialBudgetsState? preserved,
    String period, {
    bool conflict = false,
  }) {
    final phase = financialPhaseForFailure(error);
    final sameMonth = preserved != null && preserved.period == period;
    if (sameMonth &&
        (phase == FinancialLoadPhase.temporarilyUnavailable ||
            phase == FinancialLoadPhase.invalidResponse)) {
      // Keep what is on screen, but it can no longer be trusted for writes.
      state = FinancialBudgetsState.loaded(
        period: period,
        budgets: preserved.budgets,
        selectedBudgetId: preserved.selectedBudgetId,
        categories: preserved.categories,
        categoryIndex: preserved.categoryIndex,
        summary: preserved.summary,
        summaryPhase:
            preserved.summaryPhase == FinancialBudgetSummaryPhase.loading
            ? FinancialBudgetSummaryPhase.none
            : preserved.summaryPhase,
        refreshFailure: phase == FinancialLoadPhase.invalidResponse
            ? FinancialRefreshFailure.invalidResponse
            : FinancialRefreshFailure.temporarilyUnavailable,
        trusted: false,
        conflictNotice: conflict || preserved.conflictNotice,
      );
      return;
    }
    state = FinancialBudgetsState.phase(phase, period);
  }

  /// Reads the summary of [budgetId]. [settle] clears the write-in-flight flag
  /// once the canonical re-read is complete. Returns whether it succeeded.
  Future<bool> _readSummary(
    String budgetId,
    int generation, {
    bool settle = false,
  }) async {
    try {
      final summary = await ref
          .read(financialCoreApiProvider)
          .getBudgetSummary(budgetId);
      if (_disposed ||
          generation != _generation ||
          state.selectedBudgetId != budgetId) {
        return false;
      }
      state = state.copyWith(
        summary: summary,
        summaryPhase: FinancialBudgetSummaryPhase.ready,
        mutationInFlight: settle ? false : null,
      );
      return true;
    } on AuthenticatedApiException catch (error) {
      if (_disposed ||
          generation != _generation ||
          state.selectedBudgetId != budgetId) {
        return false;
      }
      final phase = financialPhaseForFailure(error);
      if (phase == FinancialLoadPhase.authenticationRequired ||
          phase == FinancialLoadPhase.forbidden ||
          phase == FinancialLoadPhase.primaryResidenceRequired) {
        state = FinancialBudgetsState.phase(phase, state.period);
        return false;
      }
      state = state.copyWith(
        summary: null,
        summaryPhase: FinancialBudgetSummaryPhase.temporarilyUnavailable,
        mutationInFlight: settle ? false : null,
        trusted: settle ? false : null,
      );
      return false;
    } on FormatException {
      if (_disposed ||
          generation != _generation ||
          state.selectedBudgetId != budgetId) {
        return false;
      }
      state = state.copyWith(
        summary: null,
        summaryPhase: FinancialBudgetSummaryPhase.invalidResponse,
        mutationInFlight: settle ? false : null,
        trusted: settle ? false : null,
      );
      return false;
    }
  }
}
