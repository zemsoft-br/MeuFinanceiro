import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/features/banking/connections/banking_connections_api.dart';

enum BankingConnectionsPhase {
  idle,
  loading,
  loaded,
  empty,
  refreshing,
  authenticationRequired,
  forbidden,
  primaryResidenceRequired,
  temporarilyUnavailable,
  invalidResponse,
}

enum BankingConnectionsRefreshFailure {
  none,
  temporarilyUnavailable,
  invalidResponse,
}

class BankingConnectionsState {
  const BankingConnectionsState._({
    required this.phase,
    this.connections = const [],
    this.refreshFailure = BankingConnectionsRefreshFailure.none,
  });

  const BankingConnectionsState.idle()
      : this._(phase: BankingConnectionsPhase.idle);

  const BankingConnectionsState.phase(BankingConnectionsPhase phase)
      : this._(phase: phase);

  BankingConnectionsState.loaded(
    List<LocalBankingConnection> connections, {
    BankingConnectionsRefreshFailure refreshFailure =
        BankingConnectionsRefreshFailure.none,
    bool refreshing = false,
  }) : this._(
          phase: refreshing
              ? BankingConnectionsPhase.refreshing
              : BankingConnectionsPhase.loaded,
          connections: List<LocalBankingConnection>.unmodifiable(connections),
          refreshFailure: refreshFailure,
        );

  final BankingConnectionsPhase phase;
  final List<LocalBankingConnection> connections;
  final BankingConnectionsRefreshFailure refreshFailure;

  bool get isBusy =>
      phase == BankingConnectionsPhase.loading ||
      phase == BankingConnectionsPhase.refreshing;

  bool get hasConnections => connections.isNotEmpty;

  @override
  String toString() =>
      'BankingConnectionsState(${phase.name}, count=${connections.length}, refreshFailure=${refreshFailure.name})';
}

final bankingConnectionsApiProvider = Provider<BankingConnectionsApi>(
  (ref) => BankingConnectionsApi(ref.watch(authenticatedApiClientProvider)),
);

final bankingConnectionsControllerProvider = NotifierProvider.autoDispose<
    BankingConnectionsController, BankingConnectionsState>(
  BankingConnectionsController.new,
);

class BankingConnectionsController
    extends AutoDisposeNotifier<BankingConnectionsState> {
  int _generation = 0;
  bool _inFlight = false;

  @override
  BankingConnectionsState build() {
    ref.onDispose(() {
      _generation += 1;
      _inFlight = false;
    });
    return const BankingConnectionsState.idle();
  }

  Future<void> load() => _load(refresh: false);

  Future<void> refresh() => _load(refresh: true);

  Future<void> _load({required bool refresh}) async {
    if (_inFlight || state.isBusy) {
      return;
    }

    final previousConnections = state.connections;
    final preserveOnFailure = refresh && previousConnections.isNotEmpty;
    final generation = ++_generation;
    _inFlight = true;
    state = preserveOnFailure
        ? BankingConnectionsState.loaded(
            previousConnections,
            refreshing: true,
          )
        : const BankingConnectionsState.phase(BankingConnectionsPhase.loading);

    try {
      final connections = await ref.read(bankingConnectionsApiProvider).listConnections();
      if (!_isCurrent(generation)) {
        return;
      }
      state = connections.isEmpty
          ? const BankingConnectionsState.phase(BankingConnectionsPhase.empty)
          : BankingConnectionsState.loaded(connections);
    } catch (error) {
      if (!_isCurrent(generation)) {
        return;
      }
      final phase = _phaseForFailure(error);
      if (preserveOnFailure &&
          (phase == BankingConnectionsPhase.temporarilyUnavailable ||
              phase == BankingConnectionsPhase.invalidResponse)) {
        state = BankingConnectionsState.loaded(
          previousConnections,
          refreshFailure: phase == BankingConnectionsPhase.invalidResponse
              ? BankingConnectionsRefreshFailure.invalidResponse
              : BankingConnectionsRefreshFailure.temporarilyUnavailable,
        );
      } else {
        state = BankingConnectionsState.phase(phase);
      }
    } finally {
      if (generation == _generation) {
        _inFlight = false;
      }
    }
  }

  bool _isCurrent(int generation) => generation == _generation && _inFlight;
}

BankingConnectionsPhase _phaseForFailure(Object error) {
  if (error is FormatException) {
    return BankingConnectionsPhase.invalidResponse;
  }
  if (error is AuthenticatedApiException) {
    if (error.failure == AuthenticatedApiFailure.authenticationRequired ||
        error.statusCode == 401) {
      return BankingConnectionsPhase.authenticationRequired;
    }
    if (error.failure == AuthenticatedApiFailure.forbidden ||
        error.statusCode == 403) {
      return BankingConnectionsPhase.forbidden;
    }
    if (error.statusCode == 409) {
      return BankingConnectionsPhase.primaryResidenceRequired;
    }
    if (error.failure == AuthenticatedApiFailure.temporarilyUnavailable ||
        error.failure == AuthenticatedApiFailure.transportFailure ||
        (error.statusCode != null && error.statusCode! >= 500)) {
      return BankingConnectionsPhase.temporarilyUnavailable;
    }
  }
  return BankingConnectionsPhase.temporarilyUnavailable;
}
