import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/features/finance/financial_budget_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

// Manual monthly recurrences (#254).
//
// A recurrence is planning and an occurrence is a forecast: neither is a financial
// fact. Only Registrar creates a Movement, and only the server does it. This
// controller pages months, reads the rules and the month's occurrences, and sends
// the explicit commands. Contract:
//  * what is shown (status, link to the Movement, amounts) comes from the server on
//    every read and is never computed, cached or patched here;
//  * nothing is optimistic: after any write answer (success, 409, 403, 404, 422,
//    5xx, transport, invalid 2xx) the screen is read again (one canonical re-read)
//    and replaces the state;
//  * a write is sent once and never retried automatically. A stale
//    `expectedVersion` (409) is never re-based: the user sees the current rule and
//    edits again explicitly. An ambiguous create or registration keeps its
//    idempotency key only for an explicit, identical retry that the server
//    replays (so a retry can never register twice);
//  * the cost per screen is fixed: accounts, rules and one month of occurrences,
//    never a request per rule or per occurrence.

/// What the last action ended with. Never claims more than the server said.
enum FinancialRecurrenceActionOutcome {
  created,
  updated,
  paused,
  resumed,
  generated,
  skipped,
  realized,

  /// 409: stale version, paused rule, occurrence no longer pending, or an
  /// idempotency conflict. Nothing was written; the current state was read.
  conflict,

  /// 404/422: the backend refused the request. Nothing was written.
  rejected,

  /// 403 with the access still valid: read-only for this operator.
  readOnly,

  /// Transport/5xx/invalid response: the write may or may not have happened. It
  /// was NOT resent; the screen was read again.
  unknownOutcome,

  /// Refused locally before any request (busy, untrusted, read-only, invalid).
  notAllowed,

  /// 401/403/residence: the access is gone; the screen phase says so.
  accessBlocked,
}

class FinancialRecurrenceActionResult {
  const FinancialRecurrenceActionResult(
    this.outcome, {
    this.reconciled = true,
    this.supersededCount,
    this.createdCount,
  });

  final FinancialRecurrenceActionOutcome outcome;

  /// False when the canonical re-read after the action also failed: what is on
  /// screen may be stale and writes stay blocked until a refresh succeeds.
  final bool reconciled;

  /// For an edit: the future PENDING occurrences the server superseded.
  final int? supersededCount;

  /// For a generation: the forecasts the server created (zero on a replay).
  final int? createdCount;
}

class FinancialRecurrencesState {
  const FinancialRecurrencesState._({
    required this.phase,
    required this.period,
    this.recurrences = const [],
    this.occurrences = const [],
    this.accounts = const [],
    this.refreshFailure = FinancialRefreshFailure.none,
    this.mutationInFlight = false,
    this.trusted = true,
    this.conflictNotice = false,
  });

  const FinancialRecurrencesState.idle(String period)
    : this._(phase: FinancialLoadPhase.idle, period: period);

  const FinancialRecurrencesState.phase(FinancialLoadPhase phase, String period)
    : this._(phase: phase, period: period);

  FinancialRecurrencesState.loaded({
    required String period,
    required List<FinancialRecurrence> recurrences,
    required List<FinancialRecurrenceOccurrence> occurrences,
    required List<FinancialAccount> accounts,
    bool refreshing = false,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
    bool mutationInFlight = false,
    bool trusted = true,
    bool conflictNotice = false,
  }) : this._(
         phase: refreshing
             ? FinancialLoadPhase.refreshing
             : recurrences.isEmpty
             ? FinancialLoadPhase.empty
             : FinancialLoadPhase.loaded,
         period: period,
         recurrences: List<FinancialRecurrence>.unmodifiable(recurrences),
         occurrences: List<FinancialRecurrenceOccurrence>.unmodifiable(
           occurrences,
         ),
         accounts: List<FinancialAccount>.unmodifiable(accounts),
         refreshFailure: refreshFailure,
         mutationInFlight: mutationInFlight,
         trusted: trusted,
         conflictNotice: conflictNotice,
       );

  final FinancialLoadPhase phase;

  /// The month whose occurrences are shown, `YYYY-MM`.
  final String period;
  final List<FinancialRecurrence> recurrences;

  /// The month's forecasts and registrations (SUPERSEDED are never listed).
  final List<FinancialRecurrenceOccurrence> occurrences;
  final List<FinancialAccount> accounts;
  final FinancialRefreshFailure refreshFailure;
  final bool mutationInFlight;

  /// False when a canonical re-read after a write failed: the view may be stale.
  final bool trusted;

  /// The last write lost a compare-and-swap or hit a state conflict.
  final bool conflictNotice;

  bool get isLoaded =>
      phase == FinancialLoadPhase.loaded ||
      phase == FinancialLoadPhase.empty ||
      phase == FinancialLoadPhase.refreshing;

  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing ||
      mutationInFlight;

  FinancialRecurrence? recurrenceById(String id) {
    for (final recurrence in recurrences) {
      if (recurrence.id == id) return recurrence;
    }
    return null;
  }

  FinancialRecurrenceOccurrence? occurrenceById(String id) {
    for (final occurrence in occurrences) {
      if (occurrence.id == id) return occurrence;
    }
    return null;
  }

  FinancialAccount? accountById(String id) {
    for (final account in accounts) {
      if (account.accountId == id) return account;
    }
    return null;
  }

  FinancialRecurrencesState copyWith({
    bool? mutationInFlight,
    bool? trusted,
    bool? conflictNotice,
  }) => FinancialRecurrencesState.loaded(
    period: period,
    recurrences: recurrences,
    occurrences: occurrences,
    accounts: accounts,
    refreshing: phase == FinancialLoadPhase.refreshing,
    refreshFailure: refreshFailure,
    mutationInFlight: mutationInFlight ?? this.mutationInFlight,
    trusted: trusted ?? this.trusted,
    conflictNotice: conflictNotice ?? this.conflictNotice,
  );
}

/// Injectable clock so the initial month is deterministic in tests.
final financialRecurrenceClockProvider = Provider<DateTime Function()>(
  (ref) => DateTime.now,
);

final financialRecurrencesControllerProvider =
    NotifierProvider.autoDispose<
      FinancialRecurrencesController,
      FinancialRecurrencesState
    >(FinancialRecurrencesController.new);

class _Done {
  const _Done(this.outcome, {this.supersededCount, this.createdCount});

  final FinancialRecurrenceActionOutcome outcome;
  final int? supersededCount;
  final int? createdCount;
}

class FinancialRecurrencesController
    extends Notifier<FinancialRecurrencesState> {
  int _generation = 0;
  bool _disposed = false;

  /// Idempotency keys of attempts whose outcome is unknown. Only an identical,
  /// user-initiated retry reuses one (the server replays it).
  final Map<String, String> _createKeys = {};
  final Map<String, String> _realizeKeys = {};

  @override
  FinancialRecurrencesState build() {
    ref.onDispose(() {
      _disposed = true;
      _generation += 1;
    });
    final now = ref.read(financialRecurrenceClockProvider)();
    return FinancialRecurrencesState.idle(currentFinancialBudgetPeriod(now));
  }

  Future<void> load() => _read(state.period, refresh: false);

  Future<void> refresh() =>
      _read(state.period, refresh: state.isLoaded, force: true);

  /// Shows another month of occurrences.
  Future<void> setPeriod(String period) async {
    if (state.mutationInFlight || period == state.period) return;
    await _read(period, refresh: state.isLoaded, force: true);
  }

  Future<void> nextMonth() =>
      setPeriod(shiftFinancialBudgetPeriod(state.period, 1));

  Future<void> previousMonth() =>
      setPeriod(shiftFinancialBudgetPeriod(state.period, -1));

  void dismissConflictNotice() {
    if (state.isLoaded && state.conflictNotice) {
      state = state.copyWith(conflictNotice: false);
    }
  }

  /// Creates a rule. One POST; the answer is the only truth.
  Future<FinancialRecurrenceActionResult> createRecurrence(
    FinancialRecurrenceCreateInput input,
  ) async {
    if (!_canWrite(state)) return _notAllowed();
    final attempt = input.attemptKey;
    final send = input.withIdempotencyKey(
      _createKeys[attempt] ?? input.idempotencyKey,
    );
    _createKeys[attempt] = send.idempotencyKey;
    return _write(() async {
      await ref.read(financialCoreApiProvider).createRecurrence(send);
      _createKeys.remove(attempt);
      return const _Done(FinancialRecurrenceActionOutcome.created);
    }, onDefiniteFailure: () => _createKeys.remove(attempt));
  }

  /// Edits [recurrenceId] under CAS. One PUT, never retried or re-based.
  Future<FinancialRecurrenceActionResult> replaceRecurrence(
    String recurrenceId,
    FinancialRecurrenceReplaceInput input,
  ) async {
    final rule = state.recurrenceById(recurrenceId);
    if (rule == null ||
        !_canWrite(state) ||
        !rule.canEdit ||
        input.expectedVersion != rule.version) {
      return _notAllowed();
    }
    return _write(() async {
      final result = await ref
          .read(financialCoreApiProvider)
          .replaceRecurrence(recurrenceId, input);
      return _Done(
        FinancialRecurrenceActionOutcome.updated,
        supersededCount: result.supersededCount,
      );
    });
  }

  Future<FinancialRecurrenceActionResult> pause(String recurrenceId) async {
    final rule = state.recurrenceById(recurrenceId);
    if (rule == null || !_canWrite(state) || !rule.canEdit || rule.isPaused) {
      return _notAllowed();
    }
    return _write(() async {
      await ref.read(financialCoreApiProvider).pauseRecurrence(recurrenceId);
      return const _Done(FinancialRecurrenceActionOutcome.paused);
    });
  }

  Future<FinancialRecurrenceActionResult> resume(String recurrenceId) async {
    final rule = state.recurrenceById(recurrenceId);
    if (rule == null || !_canWrite(state) || !rule.canEdit || !rule.isPaused) {
      return _notAllowed();
    }
    return _write(() async {
      await ref.read(financialCoreApiProvider).resumeRecurrence(recurrenceId);
      return const _Done(FinancialRecurrenceActionOutcome.resumed);
    });
  }

  /// Explicitly generates the forecast of the shown month for one rule. Nothing
  /// is generated by reading or by time passing.
  Future<FinancialRecurrenceActionResult> generateForShownMonth(
    String recurrenceId,
  ) async {
    final rule = state.recurrenceById(recurrenceId);
    if (rule == null || !_canWrite(state) || !rule.canEdit || rule.isPaused) {
      return _notAllowed();
    }
    final period = state.period;
    return _write(() async {
      final result = await ref
          .read(financialCoreApiProvider)
          .generateOccurrences(
            recurrenceId,
            fromPeriod: period,
            throughPeriod: period,
          );
      return _Done(
        FinancialRecurrenceActionOutcome.generated,
        createdCount: result.createdCount,
      );
    });
  }

  /// PENDING -> SKIPPED. Creates no Movement.
  Future<FinancialRecurrenceActionResult> skip(String occurrenceId) async {
    final occurrence = state.occurrenceById(occurrenceId);
    if (occurrence == null ||
        !_canWrite(state) ||
        !occurrence.canEdit ||
        occurrence.status != FinancialOccurrenceStatus.pending) {
      return _notAllowed();
    }
    return _write(() async {
      await ref.read(financialCoreApiProvider).skipOccurrence(occurrenceId);
      return const _Done(FinancialRecurrenceActionOutcome.skipped);
    });
  }

  /// Registrar: the one explicit act that creates a real Movement. One POST; an
  /// ambiguous answer is never resent here.
  Future<FinancialRecurrenceActionResult> realize(
    String occurrenceId,
    FinancialRecurrenceRealizeInput input,
  ) async {
    final occurrence = state.occurrenceById(occurrenceId);
    if (occurrence == null ||
        !_canWrite(state) ||
        !occurrence.canEdit ||
        occurrence.status != FinancialOccurrenceStatus.pending ||
        input.currency != occurrence.expected.currency) {
      return _notAllowed();
    }
    final attempt = input.attemptKey(occurrenceId);
    final send = input.withIdempotencyKey(
      _realizeKeys[attempt] ?? input.idempotencyKey,
    );
    _realizeKeys[attempt] = send.idempotencyKey;
    return _write(() async {
      await ref
          .read(financialCoreApiProvider)
          .realizeOccurrence(occurrenceId, send);
      _realizeKeys.remove(attempt);
      return const _Done(FinancialRecurrenceActionOutcome.realized);
    }, onDefiniteFailure: () => _realizeKeys.remove(attempt));
  }

  FinancialRecurrenceActionResult _notAllowed() =>
      const FinancialRecurrenceActionResult(
        FinancialRecurrenceActionOutcome.notAllowed,
      );

  bool _canWrite(FinancialRecurrencesState state) =>
      state.isLoaded &&
      state.phase != FinancialLoadPhase.refreshing &&
      state.trusted &&
      !state.isBusy;

  /// Sends one write and always reads the truth afterwards.
  Future<FinancialRecurrenceActionResult> _write(
    Future<_Done> Function() send, {
    void Function()? onDefiniteFailure,
  }) async {
    state = state.copyWith(mutationInFlight: true, conflictNotice: false);
    try {
      final done = await send();
      return _reconcile(
        done.outcome,
        supersededCount: done.supersededCount,
        createdCount: done.createdCount,
      );
    } on AuthenticatedApiException catch (error) {
      final status = error.statusCode;
      if (status == 409 || status == 404 || status == 422) {
        onDefiniteFailure?.call();
      }
      return _afterFailedWrite(error);
    } on FormatException {
      // A 2xx that cannot be validated: the write may have happened. The key
      // stays for an explicit identical retry; nothing is resent here.
      return _reconcile(FinancialRecurrenceActionOutcome.unknownOutcome);
    }
  }

  Future<FinancialRecurrenceActionResult> _afterFailedWrite(
    AuthenticatedApiException error,
  ) async {
    if (_disposed) {
      return const FinancialRecurrenceActionResult(
        FinancialRecurrenceActionOutcome.unknownOutcome,
        reconciled: false,
      );
    }
    final status = error.statusCode;
    if (status == 409) {
      return _reconcile(
        FinancialRecurrenceActionOutcome.conflict,
        conflict: true,
      );
    }
    if (status == 404 || status == 422) {
      return _reconcile(FinancialRecurrenceActionOutcome.rejected);
    }
    final phase = financialPhaseForFailure(error);
    if (phase == FinancialLoadPhase.authenticationRequired ||
        phase == FinancialLoadPhase.primaryResidenceRequired) {
      state = FinancialRecurrencesState.phase(phase, state.period);
      return const FinancialRecurrenceActionResult(
        FinancialRecurrenceActionOutcome.accessBlocked,
        reconciled: false,
      );
    }
    if (phase == FinancialLoadPhase.forbidden) {
      // 403 is also "you may read it but not change it": the canonical re-read
      // tells the two apart (a lost residence fails the read with 403 too).
      return _reconcile(FinancialRecurrenceActionOutcome.readOnly);
    }
    // Timeout/transport/5xx: unknown. Never resent; read the truth once.
    return _reconcile(FinancialRecurrenceActionOutcome.unknownOutcome);
  }

  /// One canonical read after any write answer. The write is never repeated.
  Future<FinancialRecurrenceActionResult> _reconcile(
    FinancialRecurrenceActionOutcome outcome, {
    bool conflict = false,
    int? supersededCount,
    int? createdCount,
  }) async {
    if (_disposed) {
      return FinancialRecurrenceActionResult(
        outcome,
        reconciled: false,
        supersededCount: supersededCount,
        createdCount: createdCount,
      );
    }
    final reconciled = await _read(
      state.period,
      refresh: true,
      force: true,
      afterWrite: true,
      conflict: conflict,
    );
    final blocked =
        state.phase == FinancialLoadPhase.authenticationRequired ||
        state.phase == FinancialLoadPhase.forbidden ||
        state.phase == FinancialLoadPhase.primaryResidenceRequired;
    return FinancialRecurrenceActionResult(
      blocked ? FinancialRecurrenceActionOutcome.accessBlocked : outcome,
      reconciled: reconciled,
      supersededCount: supersededCount,
      createdCount: createdCount,
    );
  }

  /// Reads accounts, the rules and the month's occurrences. Returns whether the
  /// read fully succeeded.
  Future<bool> _read(
    String period, {
    required bool refresh,
    bool force = false,
    bool afterWrite = false,
    bool conflict = false,
  }) async {
    final previous = state;
    if (!force && previous.phase == FinancialLoadPhase.loading) return false;
    final generation = ++_generation;
    final preserved = refresh && previous.isLoaded ? previous : null;
    final sameMonth = preserved != null && preserved.period == period;
    state = preserved == null
        ? FinancialRecurrencesState.phase(FinancialLoadPhase.loading, period)
        : FinancialRecurrencesState.loaded(
            period: period,
            recurrences: preserved.recurrences,
            occurrences: sameMonth ? preserved.occurrences : const [],
            accounts: preserved.accounts,
            refreshing: true,
            mutationInFlight: afterWrite,
            trusted: preserved.trusted,
            conflictNotice: preserved.conflictNotice,
          );
    try {
      final api = ref.read(financialCoreApiProvider);
      final accounts = await api.listAccounts();
      final recurrences = await api.listRecurrences();
      final occurrences = await api.listOccurrences(
        fromPeriod: period,
        throughPeriod: period,
      );
      if (_disposed || generation != _generation) return false;
      state = FinancialRecurrencesState.loaded(
        period: period,
        recurrences: recurrences,
        occurrences: occurrences,
        accounts: accounts,
        conflictNotice: conflict,
      );
      return true;
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
    FinancialRecurrencesState? preserved,
    String period, {
    bool conflict = false,
  }) {
    final phase = financialPhaseForFailure(error);
    final sameMonth = preserved != null && preserved.period == period;
    if (sameMonth &&
        (phase == FinancialLoadPhase.temporarilyUnavailable ||
            phase == FinancialLoadPhase.invalidResponse)) {
      // Keep what is on screen, but it can no longer be trusted for writes.
      state = FinancialRecurrencesState.loaded(
        period: period,
        recurrences: preserved.recurrences,
        occurrences: preserved.occurrences,
        accounts: preserved.accounts,
        refreshFailure: phase == FinancialLoadPhase.invalidResponse
            ? FinancialRefreshFailure.invalidResponse
            : FinancialRefreshFailure.temporarilyUnavailable,
        trusted: false,
        conflictNotice: conflict || preserved.conflictNotice,
      );
      return;
    }
    state = FinancialRecurrencesState.phase(phase, period);
  }
}
