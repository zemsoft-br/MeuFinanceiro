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
    this.balance,
    this.statement,
    this.accounts = const [],
    this.refreshFailure = FinancialRefreshFailure.none,
    this.openingBalanceMutationInFlight = false,
    this.operationMutationInFlight = false,
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
    bool refreshing = false,
    bool openingBalanceMutationInFlight = false,
    bool operationMutationInFlight = false,
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
         refreshFailure: refreshFailure,
         openingBalanceMutationInFlight: openingBalanceMutationInFlight,
         operationMutationInFlight: operationMutationInFlight,
       );

  final FinancialLoadPhase phase;
  final FinancialAccount? account;
  final FinancialOpeningBalance? openingBalance;
  final FinancialBalanceSnapshot? balance;
  final FinancialStatement? statement;
  final List<FinancialAccount> accounts;
  final FinancialRefreshFailure refreshFailure;
  final bool openingBalanceMutationInFlight;
  final bool operationMutationInFlight;

  List<FinancialMovement> get movements => List<FinancialMovement>.unmodifiable(
    statement?.entries.map((entry) => entry.movement) ?? const [],
  );

  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing ||
      openingBalanceMutationInFlight ||
      operationMutationInFlight;
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
    final balance = state.balance;
    final statement = state.statement;
    if (account == null ||
        balance == null ||
        statement == null ||
        state.openingBalanceMutationInFlight) {
      return false;
    }
    final previous = state;
    state = FinancialAccountDetailState.loaded(
      account: account,
      openingBalance: previous.openingBalance,
      balance: balance,
      statement: statement,
      accounts: previous.accounts,
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
    state = FinancialAccountDetailState.loaded(
      account: account,
      openingBalance: previous.openingBalance,
      balance: balance,
      statement: statement,
      accounts: previous.accounts,
      operationMutationInFlight: true,
      refreshFailure: previous.refreshFailure,
    );
    try {
      await operation(ref.read(financialCoreApiProvider));
      await _load(refresh: true, force: true);
      return true;
    } on AuthenticatedApiException catch (error) {
      if (error.statusCode == 409 || error.statusCode == 422) {
        state = FinancialAccountDetailState.loaded(
          account: account,
          openingBalance: previous.openingBalance,
          balance: balance,
          statement: statement,
          accounts: previous.accounts,
        );
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
    state = FinancialAccountDetailState.loaded(
      account: previous.account!,
      openingBalance: previous.openingBalance,
      balance: previous.balance!,
      statement: previous.statement!,
      accounts: previous.accounts,
      refreshFailure: FinancialRefreshFailure.temporarilyUnavailable,
    );
  }

  void _restoreInvalidResponse(FinancialAccountDetailState previous) {
    state = FinancialAccountDetailState.loaded(
      account: previous.account!,
      openingBalance: previous.openingBalance,
      balance: previous.balance!,
      statement: previous.statement!,
      accounts: previous.accounts,
      refreshFailure: FinancialRefreshFailure.invalidResponse,
    );
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
        ? FinancialAccountDetailState.loaded(
            account: previous.account!,
            openingBalance: previous.openingBalance,
            balance: previous.balance!,
            statement: previous.statement!,
            accounts: previous.accounts,
            refreshing: true,
          )
        : const FinancialAccountDetailState.phase(FinancialLoadPhase.loading);
    try {
      final api = ref.read(financialCoreApiProvider);
      final account = await api.getAccount(accountId);
      final openingBalance = await api.getOpeningBalance(accountId);
      final balance = await api.getBalance(accountId);
      final statement = await api.getStatement(accountId);
      final accounts = await api.listAccounts();

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
      if (!_isCurrent(generation)) return;
      state = FinancialAccountDetailState.loaded(
        account: account,
        openingBalance: openingBalance,
        balance: balance,
        statement: statement,
        accounts: accounts,
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
          balance: previous.balance!,
          statement: previous.statement!,
          accounts: previous.accounts,
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
