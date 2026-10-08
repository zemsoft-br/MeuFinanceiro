import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

// Financial goals (#260, ADR-0029).
//
// A goal is planning and an allocation is a virtual, append-only event. This
// controller only reads the goals and the server-derived summary and sends the
// goal writes. Contract:
//  * destinado/restante/progress/backing come from the server on every read and
//    are never computed, cached or patched here;
//  * nothing is optimistic: after any write answer (success, 409, 403, 404, 422,
//    5xx, transport, invalid 2xx) the goals are read again (one canonical
//    re-read) and replace the state;
//  * a write is sent once. A stale `expectedVersion` (409) is never retried or
//    re-based: the user sees the current goal and edits again explicitly. An
//    ambiguous create/allocation keeps its idempotency key only for an explicit,
//    identical retry that the server replays;
//  * the cost is fixed: the accounts, the goals and one summary, never a request
//    per goal, account or event.

/// What the last goal action ended with. Never claims more than the server said.
enum FinancialGoalActionOutcome {
  /// The goal was created (confirmed by the backend).
  created,

  /// The planning data was replaced (confirmed by the backend).
  updated,

  /// A virtual allocation was appended (confirmed by the backend).
  allocated,

  /// A virtual release was appended (confirmed by the backend).
  released,

  /// 409: the goal changed since it was read, or the request conflicts with the
  /// current state (available balance, allocated value, limit). Nothing was
  /// written; the current state was read.
  conflict,

  /// 404/422: the backend refused the request. Nothing was written.
  rejected,

  /// 403 with the access still valid: the goal is read-only for this operator.
  readOnly,

  /// Transport/5xx/invalid response: the write may or may not have happened. It
  /// was NOT resent; the goals were read again.
  unknownOutcome,

  /// Refused locally before any request (busy, untrusted, read-only, invalid).
  notAllowed,

  /// 401/403/residence: the access is gone; the screen phase says so.
  accessBlocked,
}

class FinancialGoalActionResult {
  const FinancialGoalActionResult(
    this.outcome, {
    this.reconciled = true,
    this.goalId,
  });

  final FinancialGoalActionOutcome outcome;

  /// False when the canonical re-read after the action also failed: the visible
  /// state may be stale and writes stay blocked until a refresh succeeds.
  final bool reconciled;

  /// The created/updated goal (confirmed), when there is one.
  final String? goalId;
}

/// State of the summary of the selected goal.
enum FinancialGoalSummaryPhase {
  none,
  loading,
  ready,
  temporarilyUnavailable,
  invalidResponse,
}

class FinancialGoalsState {
  const FinancialGoalsState._({
    required this.phase,
    this.goals = const [],
    this.selectedGoalId,
    this.summary,
    this.summaryPhase = FinancialGoalSummaryPhase.none,
    this.accounts = const [],
    this.refreshFailure = FinancialRefreshFailure.none,
    this.mutationInFlight = false,
    this.trusted = true,
    this.conflictNotice = false,
  });

  const FinancialGoalsState.idle() : this._(phase: FinancialLoadPhase.idle);

  const FinancialGoalsState.phase(FinancialLoadPhase phase)
    : this._(phase: phase);

  FinancialGoalsState.loaded({
    required List<FinancialGoalListItem> goals,
    required String? selectedGoalId,
    required List<FinancialAccount> accounts,
    FinancialGoalSummary? summary,
    FinancialGoalSummaryPhase summaryPhase = FinancialGoalSummaryPhase.none,
    bool refreshing = false,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
    bool mutationInFlight = false,
    bool trusted = true,
    bool conflictNotice = false,
  }) : this._(
         phase: refreshing
             ? FinancialLoadPhase.refreshing
             : goals.isEmpty
             ? FinancialLoadPhase.empty
             : FinancialLoadPhase.loaded,
         goals: List<FinancialGoalListItem>.unmodifiable(goals),
         selectedGoalId: selectedGoalId,
         summary: summary,
         summaryPhase: summaryPhase,
         accounts: List<FinancialAccount>.unmodifiable(accounts),
         refreshFailure: refreshFailure,
         mutationInFlight: mutationInFlight,
         trusted: trusted,
         conflictNotice: conflictNotice,
       );

  final FinancialLoadPhase phase;
  final List<FinancialGoalListItem> goals;
  final String? selectedGoalId;

  /// Server-derived summary of [selectedGoalId]; null until it is read.
  final FinancialGoalSummary? summary;
  final FinancialGoalSummaryPhase summaryPhase;

  /// The accounts the operator can see; only used to name and filter them.
  final List<FinancialAccount> accounts;
  final FinancialRefreshFailure refreshFailure;
  final bool mutationInFlight;

  /// False when a canonical re-read after a write failed: the state may be stale.
  final bool trusted;

  /// The last write lost a compare-and-swap (or conflicted with the state).
  final bool conflictNotice;

  bool get isLoaded =>
      phase == FinancialLoadPhase.loaded ||
      phase == FinancialLoadPhase.empty ||
      phase == FinancialLoadPhase.refreshing;

  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing ||
      summaryPhase == FinancialGoalSummaryPhase.loading ||
      mutationInFlight;

  FinancialGoalListItem? get selected {
    final id = selectedGoalId;
    if (id == null) return null;
    for (final item in goals) {
      if (item.goal.id == id) return item;
    }
    return null;
  }

  FinancialAccount? accountById(String accountId) {
    for (final account in accounts) {
      if (account.accountId == accountId) return account;
    }
    return null;
  }

  FinancialGoalsState copyWith({
    List<FinancialGoalListItem>? goals,
    Object? selectedGoalId = _unset,
    Object? summary = _unset,
    FinancialGoalSummaryPhase? summaryPhase,
    List<FinancialAccount>? accounts,
    bool refreshing = false,
    FinancialRefreshFailure? refreshFailure,
    bool? mutationInFlight,
    bool? trusted,
    bool? conflictNotice,
  }) => FinancialGoalsState.loaded(
    goals: goals ?? this.goals,
    selectedGoalId: identical(selectedGoalId, _unset)
        ? this.selectedGoalId
        : selectedGoalId as String?,
    accounts: accounts ?? this.accounts,
    summary: identical(summary, _unset)
        ? this.summary
        : summary as FinancialGoalSummary?,
    summaryPhase: summaryPhase ?? this.summaryPhase,
    refreshing: refreshing,
    refreshFailure: refreshFailure ?? this.refreshFailure,
    mutationInFlight: mutationInFlight ?? this.mutationInFlight,
    trusted: trusted ?? this.trusted,
    conflictNotice: conflictNotice ?? this.conflictNotice,
  );
}

const Object _unset = Object();

/// Injectable clock so date rules are deterministic in tests.
final financialGoalClockProvider = Provider<DateTime Function()>(
  (ref) => DateTime.now,
);

final financialGoalsControllerProvider =
    NotifierProvider.autoDispose<FinancialGoalsController, FinancialGoalsState>(
      FinancialGoalsController.new,
    );

class FinancialGoalsController extends Notifier<FinancialGoalsState> {
  int _generation = 0;
  bool _disposed = false;

  /// Idempotency keys of attempts whose outcome is unknown. Only an identical,
  /// user-initiated retry reuses one (the server replays it).
  final Map<String, String> _createKeys = {};
  final Map<String, String> _allocationKeys = {};

  @override
  FinancialGoalsState build() {
    ref.onDispose(() {
      _disposed = true;
      _generation += 1;
    });
    return const FinancialGoalsState.idle();
  }

  Future<void> load() => _loadAll(refresh: false);

  Future<void> refresh() =>
      _loadAll(refresh: state.isLoaded, keepSelection: true, force: true);

  /// Selects another goal and reads its summary.
  Future<void> select(String goalId) async {
    final previous = state;
    if (!previous.isLoaded ||
        previous.mutationInFlight ||
        previous.phase == FinancialLoadPhase.refreshing ||
        previous.selectedGoalId == goalId ||
        !previous.goals.any((item) => item.goal.id == goalId)) {
      return;
    }
    final generation = ++_generation;
    state = previous.copyWith(
      selectedGoalId: goalId,
      summary: null,
      summaryPhase: FinancialGoalSummaryPhase.loading,
      conflictNotice: false,
    );
    await _readSummary(goalId, generation);
  }

  /// Retries only the summary of the selected goal (the goals are fine).
  Future<void> reloadSummary() async {
    final previous = state;
    final id = previous.selectedGoalId;
    if (!previous.isLoaded ||
        id == null ||
        previous.mutationInFlight ||
        previous.summaryPhase == FinancialGoalSummaryPhase.loading) {
      return;
    }
    final generation = ++_generation;
    state = previous.copyWith(
      summary: null,
      summaryPhase: FinancialGoalSummaryPhase.loading,
    );
    await _readSummary(id, generation);
  }

  void dismissConflictNotice() {
    if (state.isLoaded && state.conflictNotice) {
      state = state.copyWith(conflictNotice: false);
    }
  }

  /// Creates a goal. One POST; the answer is the only truth and the goals are
  /// always read again afterwards.
  Future<FinancialGoalActionResult> createGoal(
    FinancialGoalCreateInput input,
  ) async {
    final previous = state;
    if (!_canWrite(previous)) {
      return const FinancialGoalActionResult(
        FinancialGoalActionOutcome.notAllowed,
      );
    }
    final attempt = input.attemptKey;
    final send = input.withIdempotencyKey(
      _createKeys[attempt] ?? input.idempotencyKey,
    );
    _createKeys[attempt] = send.idempotencyKey;
    state = previous.copyWith(mutationInFlight: true, conflictNotice: false);
    try {
      final created = await ref.read(financialCoreApiProvider).createGoal(send);
      _createKeys.remove(attempt);
      return _reconcile(
        FinancialGoalActionOutcome.created,
        select: created.id,
        goalId: created.id,
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
      return _reconcile(FinancialGoalActionOutcome.unknownOutcome);
    }
  }

  /// Replaces the planning data of [goalId] under CAS. One PUT, never retried.
  Future<FinancialGoalActionResult> replaceGoal(
    String goalId,
    FinancialGoalReplaceInput input,
  ) async {
    final previous = state;
    final item = previous.goals
        .where((candidate) => candidate.goal.id == goalId)
        .firstOrNull;
    if (item == null ||
        !_canWrite(previous) ||
        !item.goal.canEdit ||
        input.expectedVersion != item.goal.version ||
        input.currency != item.goal.currency) {
      return const FinancialGoalActionResult(
        FinancialGoalActionOutcome.notAllowed,
      );
    }
    state = previous.copyWith(mutationInFlight: true, conflictNotice: false);
    try {
      final updated = await ref
          .read(financialCoreApiProvider)
          .replaceGoal(goalId, input);
      return _reconcile(
        FinancialGoalActionOutcome.updated,
        select: updated.id,
        goalId: updated.id,
      );
    } on AuthenticatedApiException catch (error) {
      return _afterFailedWrite(error);
    } on FormatException {
      return _reconcile(FinancialGoalActionOutcome.unknownOutcome);
    }
  }

  /// Appends one explicit virtual allocation or release. One POST, never
  /// retried; the goals and the summary are read again afterwards.
  Future<FinancialGoalActionResult> allocate(
    String goalId,
    FinancialGoalAllocationInput input,
  ) async {
    final previous = state;
    final item = previous.goals
        .where((candidate) => candidate.goal.id == goalId)
        .firstOrNull;
    if (item == null ||
        !_canWrite(previous) ||
        !item.goal.canEdit ||
        input.currency != item.goal.currency) {
      return const FinancialGoalActionResult(
        FinancialGoalActionOutcome.notAllowed,
      );
    }
    final attempt = '$goalId\u001e${input.attemptKey}';
    final send = input.withIdempotencyKey(
      _allocationKeys[attempt] ?? input.idempotencyKey,
    );
    _allocationKeys[attempt] = send.idempotencyKey;
    state = previous.copyWith(mutationInFlight: true, conflictNotice: false);
    try {
      final event = await ref
          .read(financialCoreApiProvider)
          .allocateGoal(goalId, send);
      _allocationKeys.remove(attempt);
      return _reconcile(
        event.operation == FinancialGoalOperation.allocate
            ? FinancialGoalActionOutcome.allocated
            : FinancialGoalActionOutcome.released,
        select: goalId,
        goalId: goalId,
      );
    } on AuthenticatedApiException catch (error) {
      final status = error.statusCode;
      if (status == 409 || status == 404 || status == 422) {
        _allocationKeys.remove(attempt);
      }
      return _afterFailedWrite(error);
    } on FormatException {
      return _reconcile(FinancialGoalActionOutcome.unknownOutcome);
    }
  }

  bool _canWrite(FinancialGoalsState state) =>
      state.isLoaded &&
      state.phase != FinancialLoadPhase.refreshing &&
      state.trusted &&
      !state.isBusy;

  Future<FinancialGoalActionResult> _afterFailedWrite(
    AuthenticatedApiException error,
  ) async {
    if (_disposed) {
      return const FinancialGoalActionResult(
        FinancialGoalActionOutcome.unknownOutcome,
        reconciled: false,
      );
    }
    final status = error.statusCode;
    if (status == 409) {
      return _reconcile(FinancialGoalActionOutcome.conflict, conflict: true);
    }
    if (status == 404 || status == 422) {
      return _reconcile(FinancialGoalActionOutcome.rejected);
    }
    final phase = financialPhaseForFailure(error);
    if (phase == FinancialLoadPhase.authenticationRequired ||
        phase == FinancialLoadPhase.primaryResidenceRequired) {
      state = FinancialGoalsState.phase(phase);
      return const FinancialGoalActionResult(
        FinancialGoalActionOutcome.accessBlocked,
        reconciled: false,
      );
    }
    if (phase == FinancialLoadPhase.forbidden) {
      // 403 is also "you may read it but not edit it": the canonical re-read
      // tells the two apart (a lost residence fails the read with 403 too).
      return _reconcile(FinancialGoalActionOutcome.readOnly);
    }
    // Timeout/transport/5xx: unknown. Never resent; read the truth once.
    return _reconcile(FinancialGoalActionOutcome.unknownOutcome);
  }

  /// One canonical read after any write answer. The write is never repeated.
  Future<FinancialGoalActionResult> _reconcile(
    FinancialGoalActionOutcome outcome, {
    String? select,
    String? goalId,
    bool conflict = false,
  }) async {
    if (_disposed) {
      return FinancialGoalActionResult(
        outcome,
        reconciled: false,
        goalId: goalId,
      );
    }
    final reconciled = await _loadAll(
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
    return FinancialGoalActionResult(
      blocked ? FinancialGoalActionOutcome.accessBlocked : outcome,
      reconciled: reconciled,
      goalId: goalId,
    );
  }

  /// Reads the accounts and the goals, then the summary of the selected one.
  /// Returns whether the read fully succeeded.
  Future<bool> _loadAll({
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
    final wantedSelection =
        select ?? (keepSelection ? previous.selectedGoalId : null);
    state = preserved == null
        ? const FinancialGoalsState.phase(FinancialLoadPhase.loading)
        : FinancialGoalsState.loaded(
            goals: preserved.goals,
            selectedGoalId: preserved.selectedGoalId,
            accounts: preserved.accounts,
            summary: preserved.summary,
            summaryPhase: preserved.summaryPhase,
            refreshing: true,
            mutationInFlight: afterWrite,
            trusted: preserved.trusted,
            conflictNotice: preserved.conflictNotice,
          );
    try {
      final api = ref.read(financialCoreApiProvider);
      final accounts = await api.listAccounts();
      final goals = await api.listGoals();
      if (_disposed || generation != _generation) return false;
      final selectedId = goals.any((item) => item.goal.id == wantedSelection)
          ? wantedSelection
          : (goals.isEmpty ? null : goals.first.goal.id);
      state = FinancialGoalsState.loaded(
        goals: goals,
        selectedGoalId: selectedId,
        accounts: accounts,
        summaryPhase: selectedId == null
            ? FinancialGoalSummaryPhase.none
            : FinancialGoalSummaryPhase.loading,
        mutationInFlight: afterWrite,
        conflictNotice: conflict,
      );
      if (selectedId == null) {
        state = state.copyWith(mutationInFlight: false);
        return true;
      }
      return _readSummary(selectedId, generation, settle: true);
    } on AuthenticatedApiException catch (error) {
      if (_disposed || generation != _generation) return false;
      _failLoad(error, preserved, conflict: conflict);
      return false;
    } on FormatException {
      if (_disposed || generation != _generation) return false;
      _failLoad(
        const FormatException('invalid'),
        preserved,
        conflict: conflict,
      );
      return false;
    }
  }

  void _failLoad(
    Object error,
    FinancialGoalsState? preserved, {
    bool conflict = false,
  }) {
    final phase = financialPhaseForFailure(error);
    if (preserved != null &&
        (phase == FinancialLoadPhase.temporarilyUnavailable ||
            phase == FinancialLoadPhase.invalidResponse)) {
      // Keep what is on screen, but it can no longer be trusted for writes.
      state = FinancialGoalsState.loaded(
        goals: preserved.goals,
        selectedGoalId: preserved.selectedGoalId,
        accounts: preserved.accounts,
        summary: preserved.summary,
        summaryPhase:
            preserved.summaryPhase == FinancialGoalSummaryPhase.loading
            ? FinancialGoalSummaryPhase.none
            : preserved.summaryPhase,
        refreshFailure: phase == FinancialLoadPhase.invalidResponse
            ? FinancialRefreshFailure.invalidResponse
            : FinancialRefreshFailure.temporarilyUnavailable,
        trusted: false,
        conflictNotice: conflict || preserved.conflictNotice,
      );
      return;
    }
    state = FinancialGoalsState.phase(phase);
  }

  /// Reads the summary of [goalId]. [settle] clears the write-in-flight flag once
  /// the canonical re-read is complete. Returns whether it succeeded.
  Future<bool> _readSummary(
    String goalId,
    int generation, {
    bool settle = false,
  }) async {
    try {
      final summary = await ref
          .read(financialCoreApiProvider)
          .getGoalSummary(goalId);
      if (_disposed ||
          generation != _generation ||
          state.selectedGoalId != goalId) {
        return false;
      }
      state = state.copyWith(
        summary: summary,
        summaryPhase: FinancialGoalSummaryPhase.ready,
        mutationInFlight: settle ? false : null,
      );
      return true;
    } on AuthenticatedApiException catch (error) {
      if (_disposed ||
          generation != _generation ||
          state.selectedGoalId != goalId) {
        return false;
      }
      final phase = financialPhaseForFailure(error);
      if (phase == FinancialLoadPhase.authenticationRequired ||
          phase == FinancialLoadPhase.forbidden ||
          phase == FinancialLoadPhase.primaryResidenceRequired) {
        state = FinancialGoalsState.phase(phase);
        return false;
      }
      state = state.copyWith(
        summary: null,
        summaryPhase: FinancialGoalSummaryPhase.temporarilyUnavailable,
        mutationInFlight: settle ? false : null,
        trusted: settle ? false : null,
      );
      return false;
    } on FormatException {
      if (_disposed ||
          generation != _generation ||
          state.selectedGoalId != goalId) {
        return false;
      }
      state = state.copyWith(
        summary: null,
        summaryPhase: FinancialGoalSummaryPhase.invalidResponse,
        mutationInFlight: settle ? false : null,
        trusted: settle ? false : null,
      );
      return false;
    }
  }
}
