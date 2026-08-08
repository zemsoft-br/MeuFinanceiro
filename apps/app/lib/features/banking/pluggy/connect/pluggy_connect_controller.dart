import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher.dart';
import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_api.dart';

enum PluggyConnectPhase {
  idle,
  requestingToken,
  loadingWidget,
  widgetOpen,
  registeringConnection,
  connected,
  userCancelled,
  authenticationRequired,
  primaryResidenceRequired,
  demoUnavailable,
  providerUnavailable,
  configurationRequired,
  temporarilyUnavailable,
  connectionConflict,
  invalidProviderResponse,
  genericFailure,
}

class PluggyConnectState {
  const PluggyConnectState._({
    required this.phase,
    this.connectionId,
    this.connectionStatus,
    this.requiresUserAction = false,
    this.focusReturnRevision = 0,
  });

  const PluggyConnectState.idle() : this._(phase: PluggyConnectPhase.idle);

  const PluggyConnectState.phase(PluggyConnectPhase phase)
      : this._(phase: phase);

  PluggyConnectState.connected(RegisteredPluggyConnection connection)
      : this._(
          phase: PluggyConnectPhase.connected,
          connectionId: connection.connectionId,
          connectionStatus: connection.status,
          requiresUserAction: connection.requiresUserAction,
        );

  final PluggyConnectPhase phase;
  final String? connectionId;
  final String? connectionStatus;
  final bool requiresUserAction;
  final int focusReturnRevision;

  bool get isBusy => switch (phase) {
        PluggyConnectPhase.requestingToken ||
        PluggyConnectPhase.loadingWidget ||
        PluggyConnectPhase.widgetOpen ||
        PluggyConnectPhase.registeringConnection => true,
        _ => false,
      };

  PluggyConnectState withFocusReturn(int revision) => PluggyConnectState._(
        phase: phase,
        connectionId: connectionId,
        connectionStatus: connectionStatus,
        requiresUserAction: requiresUserAction,
        focusReturnRevision: revision,
      );

  @override
  String toString() => 'PluggyConnectState(${phase.name}, <local-result>)';
}

final pluggyConnectLauncherProvider = Provider<PluggyConnectLauncher>(
  (ref) => createDefaultPluggyConnectLauncher(),
);

final pluggyConnectApiProvider = Provider<PluggyConnectApi>(
  (ref) => PluggyConnectApi(ref.watch(authenticatedApiClientProvider)),
);

final pluggyConnectControllerProvider =
    NotifierProvider.autoDispose<PluggyConnectController, PluggyConnectState>(
      PluggyConnectController.new,
    );

class PluggyConnectController extends AutoDisposeNotifier<PluggyConnectState> {
  int _generation = 0;
  int _focusReturnRevision = 0;
  bool _flowActive = false;
  bool _widgetOpen = false;
  Future<void> _callbackTail = Future.value();

  @override
  PluggyConnectState build() {
    ref.onDispose(() {
      _generation += 1;
      _flowActive = false;
      _widgetOpen = false;
    });
    return const PluggyConnectState.idle();
  }

  Future<void> start() async {
    if (_flowActive || state.isBusy) {
      return;
    }

    final session = ref.read(operatorSessionControllerProvider);
    final principal = session.principal;
    if (!session.isAuthenticated || principal == null) {
      state = const PluggyConnectState.phase(
        PluggyConnectPhase.authenticationRequired,
      );
      return;
    }
    if (!principal.isInstallationAdmin) {
      state = const PluggyConnectState.phase(PluggyConnectPhase.genericFailure);
      return;
    }
    if (principal.primaryResidenceId == null) {
      state = const PluggyConnectState.phase(
        PluggyConnectPhase.primaryResidenceRequired,
      );
      return;
    }

    final demo = ref.read(demoStatusProvider);
    final demoStatus = demo.value;
    if (demoStatus == null) {
      state = const PluggyConnectState.phase(
        PluggyConnectPhase.temporarilyUnavailable,
      );
      return;
    }
    if (demoStatus.enabled) {
      state = const PluggyConnectState.phase(
        PluggyConnectPhase.demoUnavailable,
      );
      return;
    }

    final generation = ++_generation;
    _flowActive = true;
    _widgetOpen = false;
    state = const PluggyConnectState.phase(PluggyConnectPhase.requestingToken);

    EphemeralConnectToken? token;
    try {
      token = await ref.read(pluggyConnectApiProvider).issueToken();
      if (!_isCurrent(generation)) {
        token.clear();
        return;
      }

      state = const PluggyConnectState.phase(PluggyConnectPhase.loadingWidget);
      final secret = token.take();
      try {
        await ref.read(pluggyConnectLauncherProvider).launch(
              connectToken: secret,
              onCallback: (callback) {
                _enqueueCallback(generation, callback);
              },
            );
      } finally {
        token.clear();
      }
    } catch (error) {
      token?.clear();
      if (!_isCurrent(generation)) {
        return;
      }
      _flowActive = false;
      _widgetOpen = false;
      state = PluggyConnectState.phase(
        _phaseForFailure(error, registering: false),
      );
    }
  }

  void cancelFromScreen() {
    _generation += 1;
    _flowActive = false;
    _widgetOpen = false;
    state = const PluggyConnectState.idle();
  }

  void reset() {
    if (_flowActive || state.isBusy) {
      return;
    }
    state = const PluggyConnectState.idle();
  }

  void _enqueueCallback(int generation, PluggyConnectCallback callback) {
    if (!_isCurrent(generation)) {
      return;
    }
    _callbackTail = _callbackTail.then((_) async {
      if (_isCurrent(generation)) {
        await _processCallback(generation, callback);
      }
    }).catchError((Object error, StackTrace stackTrace) {
      if (_isCurrent(generation)) {
        _flowActive = false;
        _widgetOpen = false;
        state = const PluggyConnectState.phase(
          PluggyConnectPhase.genericFailure,
        );
      }
    });
  }

  Future<void> _processCallback(
    int generation,
    PluggyConnectCallback callback,
  ) async {
    switch (callback.type) {
      case PluggyConnectCallbackType.opened:
        _widgetOpen = true;
        if (state.phase == PluggyConnectPhase.loadingWidget) {
          state = const PluggyConnectState.phase(PluggyConnectPhase.widgetOpen);
        }
        return;
      case PluggyConnectCallbackType.closed:
        _widgetOpen = false;
        if (state.phase == PluggyConnectPhase.registeringConnection) {
          return;
        }
        _flowActive = false;
        if (state.phase == PluggyConnectPhase.widgetOpen ||
            state.phase == PluggyConnectPhase.loadingWidget) {
          state = const PluggyConnectState.phase(
            PluggyConnectPhase.userCancelled,
          );
        }
        state = state.withFocusReturn(++_focusReturnRevision);
        return;
      case PluggyConnectCallbackType.errorWithoutItem:
        state = const PluggyConnectState.phase(PluggyConnectPhase.genericFailure);
        return;
      case PluggyConnectCallbackType.invalidPayload:
        state = const PluggyConnectState.phase(
          PluggyConnectPhase.invalidProviderResponse,
        );
        return;
      case PluggyConnectCallbackType.itemAvailable:
        final itemId = callback.itemId;
        if (itemId == null) {
          state = const PluggyConnectState.phase(
            PluggyConnectPhase.invalidProviderResponse,
          );
          return;
        }
        await _registerItem(generation, itemId);
        return;
    }
  }

  Future<void> _registerItem(int generation, String itemId) async {
    if (!_isCurrent(generation)) {
      return;
    }
    state = const PluggyConnectState.phase(
      PluggyConnectPhase.registeringConnection,
    );
    try {
      final connection = await ref.read(pluggyConnectApiProvider).registerItem(
            itemId,
          );
      if (!_isCurrent(generation)) {
        return;
      }
      state = PluggyConnectState.connected(connection);
      if (!_widgetOpen) {
        _flowActive = false;
        state = state.withFocusReturn(++_focusReturnRevision);
      }
    } catch (error) {
      if (!_isCurrent(generation)) {
        return;
      }
      state = PluggyConnectState.phase(
        _phaseForFailure(error, registering: true),
      );
      if (!_widgetOpen) {
        _flowActive = false;
        state = state.withFocusReturn(++_focusReturnRevision);
      }
    }
  }

  bool _isCurrent(int generation) =>
      generation == _generation && _flowActive;
}

PluggyConnectPhase _phaseForFailure(
  Object error, {
  required bool registering,
}) {
  if (error is FormatException) {
    return PluggyConnectPhase.invalidProviderResponse;
  }
  if (error is PluggyConnectLaunchException) {
    return PluggyConnectPhase.temporarilyUnavailable;
  }
  if (error is AuthenticatedApiException) {
    if (error.failure == AuthenticatedApiFailure.authenticationRequired ||
        error.statusCode == 401) {
      return PluggyConnectPhase.authenticationRequired;
    }
    return switch (error.statusCode) {
      403 when registering => PluggyConnectPhase.connectionConflict,
      404 when registering => PluggyConnectPhase.invalidProviderResponse,
      404 => PluggyConnectPhase.providerUnavailable,
      409 when registering => PluggyConnectPhase.connectionConflict,
      409 => PluggyConnectPhase.configurationRequired,
      502 => PluggyConnectPhase.invalidProviderResponse,
      503 => PluggyConnectPhase.temporarilyUnavailable,
      _ when error.failure == AuthenticatedApiFailure.transportFailure =>
        PluggyConnectPhase.temporarilyUnavailable,
      _ when error.failure == AuthenticatedApiFailure.temporarilyUnavailable =>
        PluggyConnectPhase.temporarilyUnavailable,
      _ => PluggyConnectPhase.genericFailure,
    };
  }
  return PluggyConnectPhase.genericFailure;
}
