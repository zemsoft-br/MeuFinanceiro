import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

// Deterministic categorization rules (#247).
//
// Contract kept by both controllers:
//  * nothing visible changes before the backend confirms (no optimistic state);
//  * a write is sent once; an ambiguous outcome (transport/5xx/invalid 2xx) is
//    never retried automatically;
//  * the backend result is the only source of truth for what happened.

// ---------------------------------------------------------------------------
// Rules: list / create / disable
// ---------------------------------------------------------------------------

class FinancialCategorizationRulesState {
  const FinancialCategorizationRulesState._({
    required this.phase,
    this.rules = const [],
    this.categories = const [],
    this.accounts = const [],
    this.refreshFailure = FinancialRefreshFailure.none,
    this.mutationInFlight = false,
    this.trusted = true,
  });

  const FinancialCategorizationRulesState.idle()
    : this._(phase: FinancialLoadPhase.idle);
  const FinancialCategorizationRulesState.phase(FinancialLoadPhase phase)
    : this._(phase: phase);

  FinancialCategorizationRulesState.loaded({
    required List<FinancialCategorizationRule> rules,
    required List<FinancialCategory> categories,
    required List<FinancialAccount> accounts,
    bool refreshing = false,
    bool mutationInFlight = false,
    bool trusted = true,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
  }) : this._(
         phase: refreshing
             ? FinancialLoadPhase.refreshing
             : FinancialLoadPhase.loaded,
         rules: List<FinancialCategorizationRule>.unmodifiable(rules),
         categories: List<FinancialCategory>.unmodifiable(categories),
         accounts: List<FinancialAccount>.unmodifiable(accounts),
         refreshFailure: refreshFailure,
         mutationInFlight: mutationInFlight,
         trusted: trusted,
       );

  final FinancialLoadPhase phase;
  final List<FinancialCategorizationRule> rules;

  /// Every category the server returned, DISABLED included, so the target of a
  /// historical rule keeps resolving its name.
  final List<FinancialCategory> categories;
  final List<FinancialAccount> accounts;
  final FinancialRefreshFailure refreshFailure;
  final bool mutationInFlight;

  /// False after a write ended with an unknown outcome and the reconciling read
  /// also failed: the visible list may be stale, so writes stay blocked until a
  /// refresh restores the persisted truth.
  final bool trusted;

  bool get isLoaded =>
      phase == FinancialLoadPhase.loaded ||
      phase == FinancialLoadPhase.refreshing;

  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing ||
      mutationInFlight;

  FinancialCategorizationRulesState copyLoaded({
    List<FinancialCategorizationRule>? rules,
    List<FinancialCategory>? categories,
    List<FinancialAccount>? accounts,
    bool refreshing = false,
    bool mutationInFlight = false,
    bool? trusted,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
  }) => FinancialCategorizationRulesState.loaded(
    rules: rules ?? this.rules,
    categories: categories ?? this.categories,
    accounts: accounts ?? this.accounts,
    refreshing: refreshing,
    mutationInFlight: mutationInFlight,
    trusted: trusted ?? this.trusted,
    refreshFailure: refreshFailure,
  );
}

final financialCategorizationRulesControllerProvider =
    NotifierProvider.autoDispose<
      FinancialCategorizationRulesController,
      FinancialCategorizationRulesState
    >(FinancialCategorizationRulesController.new);

class FinancialCategorizationRulesController
    extends Notifier<FinancialCategorizationRulesState> {
  int _generation = 0;
  bool _inFlight = false;
  bool _disposed = false;

  /// Idempotency keys of creation attempts whose outcome is unknown. Only an
  /// identical, user-initiated retry reuses one (the server replays it); any
  /// other material gets a fresh key. Never resent automatically.
  final Map<String, String> _pendingCreateKeys = {};

  @override
  FinancialCategorizationRulesState build() {
    ref.onDispose(() {
      _disposed = true;
      _generation += 1;
      _inFlight = false;
    });
    return const FinancialCategorizationRulesState.idle();
  }

  Future<void> load() => _load(refresh: false);
  Future<void> refresh() => _load(refresh: true);

  /// Creates a new immutable rule. Editing is not a thing: a changed condition,
  /// priority or category is "disable + create".
  Future<FinancialMutationOutcome> createRule(
    FinancialCategorizationRuleCreateInput input,
  ) async {
    final previous = state;
    if (!previous.isLoaded || previous.isBusy || !previous.trusted) {
      return FinancialMutationOutcome.notAllowed;
    }
    final identity = input.attemptIdentity;
    final pendingKey = _pendingCreateKeys[identity];
    final effective = pendingKey == null
        ? input
        : FinancialCategorizationRuleCreateInput(
            matcher: input.matcher,
            pattern: input.pattern,
            targetCategoryId: input.targetCategoryId,
            priority: input.priority,
            accountId: input.accountId,
            resultEffect: input.resultEffect,
            idempotencyKey: pendingKey,
          );
    _pendingCreateKeys[identity] = effective.idempotencyKey;

    state = previous.copyLoaded(mutationInFlight: true);
    try {
      final rule = await ref
          .read(financialCoreApiProvider)
          .createCategorizationRule(effective);
      _pendingCreateKeys.remove(identity);
      if (_disposed) return FinancialMutationOutcome.success;
      state = previous.copyLoaded(
        rules: _withRule(previous.rules, rule),
        refreshFailure: previous.refreshFailure,
      );
      return FinancialMutationOutcome.success;
    } on AuthenticatedApiException catch (error) {
      return _afterRejectedOrUnknown(
        previous,
        error,
        onDefinitive: () => _pendingCreateKeys.remove(identity),
        conflictRefresh: true,
      );
    } on FormatException {
      return _reconcileUnknown(previous, invalid: true);
    }
  }

  /// Disables one rule. Existing classifications are never touched.
  Future<FinancialMutationOutcome> disableRule(String ruleId) async {
    final previous = state;
    if (!previous.isLoaded || previous.isBusy || !previous.trusted) {
      return FinancialMutationOutcome.notAllowed;
    }
    final current = previous.rules.where((item) => item.ruleId == ruleId);
    if (current.isEmpty || !current.first.isActive) {
      return FinancialMutationOutcome.notAllowed;
    }
    state = previous.copyLoaded(mutationInFlight: true);
    try {
      final rule = await ref
          .read(financialCoreApiProvider)
          .disableCategorizationRule(ruleId);
      if (_disposed) return FinancialMutationOutcome.success;
      state = previous.copyLoaded(
        rules: _withRule(previous.rules, rule),
        refreshFailure: previous.refreshFailure,
      );
      return FinancialMutationOutcome.success;
    } on AuthenticatedApiException catch (error) {
      return _afterRejectedOrUnknown(previous, error, conflictRefresh: true);
    } on FormatException {
      return _reconcileUnknown(previous, invalid: true);
    }
  }

  Future<FinancialMutationOutcome> _afterRejectedOrUnknown(
    FinancialCategorizationRulesState previous,
    AuthenticatedApiException error, {
    void Function()? onDefinitive,
    required bool conflictRefresh,
  }) async {
    if (_disposed) return FinancialMutationOutcome.temporarilyUnavailable;
    final phase = financialPhaseForFailure(error);
    if (phase == FinancialLoadPhase.authenticationRequired ||
        phase == FinancialLoadPhase.forbidden) {
      state = FinancialCategorizationRulesState.phase(phase);
      return FinancialMutationOutcome.accessBlocked;
    }
    final status = error.statusCode;
    if (status == 409) {
      onDefinitive?.call();
      await _load(refresh: true, force: true);
      return FinancialMutationOutcome.conflictReconciled;
    }
    if (status == 404 || status == 422) {
      onDefinitive?.call();
      state = previous.copyLoaded(refreshFailure: previous.refreshFailure);
      if (status == 404) await _load(refresh: true, force: true);
      return FinancialMutationOutcome.rejected;
    }
    return _reconcileUnknown(previous, invalid: false);
  }

  /// One canonical read after an unknown write outcome. The write is never
  /// resent; no causality is claimed between it and what the read shows.
  Future<FinancialMutationOutcome> _reconcileUnknown(
    FinancialCategorizationRulesState previous, {
    required bool invalid,
  }) async {
    try {
      final api = ref.read(financialCoreApiProvider);
      final rules = await api.listCategorizationRules();
      if (_disposed) return FinancialMutationOutcome.temporarilyUnavailable;
      state = previous.copyLoaded(rules: rules, trusted: true);
      return FinancialMutationOutcome.unknownOutcomeReconciled;
    } on AuthenticatedApiException catch (error) {
      if (_disposed) return FinancialMutationOutcome.temporarilyUnavailable;
      final phase = financialPhaseForFailure(error);
      if (phase == FinancialLoadPhase.authenticationRequired ||
          phase == FinancialLoadPhase.forbidden) {
        state = FinancialCategorizationRulesState.phase(phase);
        return FinancialMutationOutcome.accessBlocked;
      }
      state = previous.copyLoaded(
        refreshFailure: previous.refreshFailure,
        trusted: false,
      );
      return FinancialMutationOutcome.temporarilyUnavailable;
    } on FormatException {
      if (_disposed) return FinancialMutationOutcome.invalidResponse;
      state = previous.copyLoaded(
        refreshFailure: FinancialRefreshFailure.invalidResponse,
        trusted: false,
      );
      return FinancialMutationOutcome.invalidResponse;
    }
  }

  Future<void> _load({required bool refresh, bool force = false}) async {
    if (!force && (_inFlight || state.isBusy)) return;
    final previous = state;
    final preserve = refresh && previous.isLoaded;
    final generation = ++_generation;
    _inFlight = true;
    state = preserve
        ? previous.copyLoaded(refreshing: true)
        : const FinancialCategorizationRulesState.phase(
            FinancialLoadPhase.loading,
          );
    try {
      // Fixed cost: rules, categories and accounts, independent of list size.
      final api = ref.read(financialCoreApiProvider);
      final rules = await api.listCategorizationRules();
      final categories = await api.listCategories();
      final accounts = await api.listAccounts();
      FinancialCategoryIndex.build(categories);
      if (generation != _generation || !_inFlight) return;
      state = FinancialCategorizationRulesState.loaded(
        rules: rules,
        categories: categories,
        accounts: accounts,
      );
    } catch (error) {
      if (generation != _generation || !_inFlight) return;
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
        state = FinancialCategorizationRulesState.phase(phase);
      }
    } finally {
      if (generation == _generation) _inFlight = false;
    }
  }

  List<FinancialCategorizationRule> _withRule(
    List<FinancialCategorizationRule> rules,
    FinancialCategorizationRule rule,
  ) {
    final replaced = [
      for (final item in rules)
        if (item.ruleId == rule.ruleId) rule else item,
    ];
    return rules.any((item) => item.ruleId == rule.ruleId)
        ? replaced
        : [rule, ...rules];
  }
}

// ---------------------------------------------------------------------------
// Preview + explicit apply for one account
// ---------------------------------------------------------------------------

enum FinancialCategorizationApplyPhase {
  idle,
  previewing,
  previewed,
  applying,

  /// The backend answered; [FinancialCategorizationApplyState.outcome] is the
  /// canonical per-Movement result (possibly partial).
  applied,

  /// The apply POST ended with an unknown outcome. It was NOT resent; the
  /// operator must preview again to see the persisted truth.
  unknownOutcome,
  failed,
}

enum FinancialCategorizationApplyFailure {
  none,
  rejected,
  notFound,
  temporarilyUnavailable,
  invalidResponse,
  accessBlocked,
}

class FinancialCategorizationApplyState {
  const FinancialCategorizationApplyState({
    this.phase = FinancialCategorizationApplyPhase.idle,
    this.preview,
    this.outcome,
    this.failure = FinancialCategorizationApplyFailure.none,
  });

  final FinancialCategorizationApplyPhase phase;
  final FinancialCategorizationPreview? preview;
  final FinancialCategorizationApplyOutcome? outcome;
  final FinancialCategorizationApplyFailure failure;

  bool get isBusy =>
      phase == FinancialCategorizationApplyPhase.previewing ||
      phase == FinancialCategorizationApplyPhase.applying;

  bool get canApply =>
      phase == FinancialCategorizationApplyPhase.previewed &&
      (preview?.applicableItems.isNotEmpty ?? false);
}

final financialCategorizationApplyControllerProvider = NotifierProvider
    .autoDispose
    .family<
      FinancialCategorizationApplyController,
      FinancialCategorizationApplyState,
      String
    >((accountId) => FinancialCategorizationApplyController(accountId));

class FinancialCategorizationApplyController
    extends Notifier<FinancialCategorizationApplyState> {
  FinancialCategorizationApplyController(this.accountId);

  final String accountId;
  bool _disposed = false;

  @override
  FinancialCategorizationApplyState build() {
    ref.onDispose(() => _disposed = true);
    return const FinancialCategorizationApplyState();
  }

  /// Read-only evaluation. Never writes, reserves or guarantees anything.
  Future<void> preview() async {
    if (state.isBusy) return;
    state = const FinancialCategorizationApplyState(
      phase: FinancialCategorizationApplyPhase.previewing,
    );
    try {
      final preview = await ref
          .read(financialCoreApiProvider)
          .previewCategorizationRules(accountId);
      if (_disposed) return;
      state = FinancialCategorizationApplyState(
        phase: FinancialCategorizationApplyPhase.previewed,
        preview: preview,
      );
    } on AuthenticatedApiException catch (error) {
      if (_disposed) return;
      state = FinancialCategorizationApplyState(
        phase: FinancialCategorizationApplyPhase.failed,
        failure: _failureFor(error),
      );
    } on FormatException {
      if (_disposed) return;
      state = const FinancialCategorizationApplyState(
        phase: FinancialCategorizationApplyPhase.failed,
        failure: FinancialCategorizationApplyFailure.invalidResponse,
      );
    }
  }

  /// Sends exactly the Movement/rule pairs of the last preview, once. The
  /// result shown is the backend response; a failure is never retried and never
  /// reported as success.
  Future<void> apply() async {
    if (!state.canApply) return;
    final preview = state.preview!;
    final items = preview.applicableItems;
    state = FinancialCategorizationApplyState(
      phase: FinancialCategorizationApplyPhase.applying,
      preview: preview,
    );
    try {
      final outcome = await ref
          .read(financialCoreApiProvider)
          .applyCategorizationRules(accountId, items);
      if (_disposed) return;
      state = FinancialCategorizationApplyState(
        phase: FinancialCategorizationApplyPhase.applied,
        preview: preview,
        outcome: outcome,
      );
    } on AuthenticatedApiException catch (error) {
      if (_disposed) return;
      final failure = _failureFor(error);
      final definitive =
          failure == FinancialCategorizationApplyFailure.rejected ||
          failure == FinancialCategorizationApplyFailure.notFound ||
          failure == FinancialCategorizationApplyFailure.accessBlocked;
      state = FinancialCategorizationApplyState(
        phase: definitive
            ? FinancialCategorizationApplyPhase.failed
            : FinancialCategorizationApplyPhase.unknownOutcome,
        failure: failure,
      );
    } on FormatException {
      if (_disposed) return;
      // A 2xx that cannot be validated: the writes may have happened.
      state = const FinancialCategorizationApplyState(
        phase: FinancialCategorizationApplyPhase.unknownOutcome,
        failure: FinancialCategorizationApplyFailure.invalidResponse,
      );
    }
  }

  void reset() {
    if (state.isBusy) return;
    state = const FinancialCategorizationApplyState();
  }

  FinancialCategorizationApplyFailure _failureFor(
    AuthenticatedApiException error,
  ) {
    final phase = financialPhaseForFailure(error);
    if (phase == FinancialLoadPhase.authenticationRequired ||
        phase == FinancialLoadPhase.forbidden ||
        phase == FinancialLoadPhase.primaryResidenceRequired) {
      return FinancialCategorizationApplyFailure.accessBlocked;
    }
    if (error.statusCode == 404) {
      return FinancialCategorizationApplyFailure.notFound;
    }
    if (error.statusCode == 409 || error.statusCode == 422) {
      return FinancialCategorizationApplyFailure.rejected;
    }
    return FinancialCategorizationApplyFailure.temporarilyUnavailable;
  }
}
