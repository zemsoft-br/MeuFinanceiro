import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
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
    this.movements = const [],
    this.refreshFailure = FinancialRefreshFailure.none,
    this.openingBalanceMutationInFlight = false,
  });

  const FinancialAccountDetailState.idle()
    : this._(phase: FinancialLoadPhase.idle);
  const FinancialAccountDetailState.phase(FinancialLoadPhase phase)
    : this._(phase: phase);

  FinancialAccountDetailState.loaded({
    required FinancialAccount account,
    required FinancialOpeningBalance? openingBalance,
    required List<FinancialMovement> movements,
    bool refreshing = false,
    bool openingBalanceMutationInFlight = false,
    FinancialRefreshFailure refreshFailure = FinancialRefreshFailure.none,
  }) : this._(
         phase: refreshing
             ? FinancialLoadPhase.refreshing
             : FinancialLoadPhase.loaded,
         account: account,
         openingBalance: openingBalance,
         movements: List<FinancialMovement>.unmodifiable(movements),
         refreshFailure: refreshFailure,
         openingBalanceMutationInFlight: openingBalanceMutationInFlight,
       );

  final FinancialLoadPhase phase;
  final FinancialAccount? account;
  final FinancialOpeningBalance? openingBalance;
  final List<FinancialMovement> movements;
  final FinancialRefreshFailure refreshFailure;
  final bool openingBalanceMutationInFlight;

  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing ||
      openingBalanceMutationInFlight;
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

  @override
  FinancialAccountDetailState build() {
    ref.onDispose(() {
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
    if (account == null || state.openingBalanceMutationInFlight) return false;
    state = FinancialAccountDetailState.loaded(
      account: account,
      openingBalance: state.openingBalance,
      movements: state.movements,
      openingBalanceMutationInFlight: true,
      refreshFailure: state.refreshFailure,
    );
    try {
      final opening = await ref
          .read(financialCoreApiProvider)
          .createOpeningBalance(accountId, input);
      if (opening.money.currency != account.currency) {
        throw const FormatException('opening balance currency mismatch.');
      }
      state = FinancialAccountDetailState.loaded(
        account: account,
        openingBalance: opening,
        movements: state.movements,
      );
      return true;
    } on AuthenticatedApiException catch (error) {
      if (error.statusCode == 409) {
        await _load(refresh: true, force: true);
        return false;
      }
      state = FinancialAccountDetailState.phase(
        financialPhaseForFailure(error),
      );
      return false;
    } on FormatException {
      state = const FinancialAccountDetailState.phase(
        FinancialLoadPhase.invalidResponse,
      );
      return false;
    }
  }

  Future<void> _load({required bool refresh, bool force = false}) async {
    if (!force && (_inFlight || state.isBusy)) return;
    final previous = state;
    final preserve = refresh && previous.account != null;
    final generation = ++_generation;
    _inFlight = true;
    state = preserve
        ? FinancialAccountDetailState.loaded(
            account: previous.account!,
            openingBalance: previous.openingBalance,
            movements: previous.movements,
            refreshing: true,
          )
        : const FinancialAccountDetailState.phase(FinancialLoadPhase.loading);
    try {
      final api = ref.read(financialCoreApiProvider);
      final account = await api.getAccount(accountId);
      final openingBalance = await api.getOpeningBalance(accountId);
      final movements = await api.listMovements(accountId);
      if (openingBalance != null &&
          openingBalance.money.currency != account.currency) {
        throw const FormatException('opening balance currency mismatch.');
      }
      if (movements.any(
        (movement) => movement.money.currency != account.currency,
      )) {
        throw const FormatException('movement currency mismatch.');
      }
      if (!_isCurrent(generation)) return;
      state = FinancialAccountDetailState.loaded(
        account: account,
        openingBalance: openingBalance,
        movements: movements,
      );
    } catch (error) {
      if (!_isCurrent(generation)) return;
      final phase = financialPhaseForFailure(error);
      if (preserve &&
          (phase == FinancialLoadPhase.temporarilyUnavailable ||
              phase == FinancialLoadPhase.invalidResponse)) {
        state = FinancialAccountDetailState.loaded(
          account: previous.account!,
          openingBalance: previous.openingBalance,
          movements: previous.movements,
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
