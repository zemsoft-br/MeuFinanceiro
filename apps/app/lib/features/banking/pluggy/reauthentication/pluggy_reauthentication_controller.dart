import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher.dart';
import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_api.dart';

final _uuidPattern = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
);

enum PluggyReauthenticationPhase {
  idle,
  requestingToken,
  loadingWidget,
  widgetOpen,
  registeringConnection,
  updated,
  userCancelled,
  invalidConnectionId,
  authenticationRequired,
  primaryResidenceRequired,
  demoUnavailable,
  connectionNotFound,
  connectionUnavailable,
  temporarilyUnavailable,
  invalidProviderResponse,
  genericFailure,
}

class PluggyReauthenticationState {
  const PluggyReauthenticationState._({
    required this.phase,
    this.connectionId,
    this.connectionStatus,
    this.requiresUserAction = false,
    this.focusReturnRevision = 0,
  });

  const PluggyReauthenticationState.idle()
    : this._(phase: PluggyReauthenticationPhase.idle);

  const PluggyReauthenticationState.phase(PluggyReauthenticationPhase phase)
    : this._(phase: phase);

  PluggyReauthenticationState.updated(RegisteredPluggyConnection connection)
    : this._(
        phase: PluggyReauthenticationPhase.updated,
        connectionId: connection.connectionId,
        connectionStatus: connection.status,
        requiresUserAction: connection.requiresUserAction,
      );

  final PluggyReauthenticationPhase phase;
  final String? connectionId;
  final String? connectionStatus;
  final bool requiresUserAction;
  final int focusReturnRevision;

  bool get isBusy => switch (phase) {
    PluggyReauthenticationPhase.requestingToken ||
    PluggyReauthenticationPhase.loadingWidget ||
    PluggyReauthenticationPhase.widgetOpen ||
    PluggyReauthenticationPhase.registeringConnection => true,
    _ => false,
  };

  PluggyReauthenticationState withFocusReturn(int revision) =>
      PluggyReauthenticationState._(
        phase: phase,
        connectionId: connectionId,
        connectionStatus: connectionStatus,
        requiresUserAction: requiresUserAction,
        focusReturnRevision: revision,
      );

  @override
  String toString() =>
      'PluggyReauthenticationState(${phase.name}, <local-result>)';
}

final pluggyReauthenticationLauncherProvider = Provider<PluggyConnectLauncher>(
  (ref) => createDefaultPluggyConnectLauncher(),
);

final pluggyReauthenticationApiProvider = Provider<PluggyConnectApi>(
  (ref) => PluggyConnectApi(ref.watch(authenticatedApiClientProvider)),
);

final pluggyReauthenticationControllerProvider =
    NotifierProvider.autoDispose<
      PluggyReauthenticationController,
      PluggyReauthenticationState
    >(PluggyReauthenticationController.new);

class PluggyReauthenticationController
    extends Notifier<PluggyReauthenticationState> {
  int _generation = 0;
  int _focusReturnRevision = 0;
  bool _flowActive = false;
  bool _widgetOpen = false;
  String? _expectedUpdateItem;
  Future<void> _callbackTail = Future.value();

  @override
  PluggyReauthenticationState build() {
    ref.onDispose(() {
      _generation += 1;
      _flowActive = false;
      _widgetOpen = false;
      _expectedUpdateItem = null;
    });
    return const PluggyReauthenticationState.idle();
  }

  Future<void> start(String connectionId) async {
    if (_flowActive || state.isBusy) {
      return;
    }
    if (!_isCanonicalUuid(connectionId)) {
      state = const PluggyReauthenticationState.phase(
        PluggyReauthenticationPhase.invalidConnectionId,
      );
      return;
    }

    final session = ref.read(operatorSessionControllerProvider);
    final principal = session.principal;
    if (!session.isAuthenticated || principal == null) {
      state = const PluggyReauthenticationState.phase(
        PluggyReauthenticationPhase.authenticationRequired,
      );
      return;
    }
    if (!principal.isInstallationAdmin) {
      state = const PluggyReauthenticationState.phase(
        PluggyReauthenticationPhase.genericFailure,
      );
      return;
    }
    if (principal.primaryResidenceId == null) {
      state = const PluggyReauthenticationState.phase(
        PluggyReauthenticationPhase.primaryResidenceRequired,
      );
      return;
    }

    final demoStatus = ref.read(demoStatusProvider).value;
    if (demoStatus == null) {
      state = const PluggyReauthenticationState.phase(
        PluggyReauthenticationPhase.temporarilyUnavailable,
      );
      return;
    }
    if (demoStatus.enabled) {
      state = const PluggyReauthenticationState.phase(
        PluggyReauthenticationPhase.demoUnavailable,
      );
      return;
    }

    final generation = ++_generation;
    _flowActive = true;
    _widgetOpen = false;
    _expectedUpdateItem = null;
    state = const PluggyReauthenticationState.phase(
      PluggyReauthenticationPhase.requestingToken,
    );

    EphemeralPluggyUpdateMaterial? material;
    try {
      material = await ref
          .read(pluggyReauthenticationApiProvider)
          .issueReauthenticationMaterial(connectionId);
      if (!_isCurrent(generation)) {
        material.clear();
        return;
      }

      final launchMaterial = material.take();
      _expectedUpdateItem = launchMaterial.updateItem;
      state = const PluggyReauthenticationState.phase(
        PluggyReauthenticationPhase.loadingWidget,
      );
      try {
        await ref
            .read(pluggyReauthenticationLauncherProvider)
            .launch(
              connectToken: launchMaterial.connectToken,
              updateItem: launchMaterial.updateItem,
              onCallback: (callback) {
                _enqueueCallback(generation, callback);
              },
            );
      } finally {
        material.clear();
      }
    } catch (error) {
      material?.clear();
      if (!_isCurrent(generation)) {
        return;
      }
      _flowActive = false;
      _widgetOpen = false;
      _expectedUpdateItem = null;
      state = PluggyReauthenticationState.phase(
        _phaseForFailure(error, registering: false),
      );
    }
  }

  void cancelFromScreen() {
    _generation += 1;
    _flowActive = false;
    _widgetOpen = false;
    _expectedUpdateItem = null;
    state = const PluggyReauthenticationState.idle();
  }

  void reset() {
    if (_flowActive || state.isBusy) {
      return;
    }
    _expectedUpdateItem = null;
    state = const PluggyReauthenticationState.idle();
  }

  void _enqueueCallback(int generation, PluggyConnectCallback callback) {
    if (!_isCurrent(generation)) {
      return;
    }
    _callbackTail = _callbackTail
        .then((_) async {
          if (_isCurrent(generation)) {
            await _processCallback(generation, callback);
          }
        })
        .catchError((Object error, StackTrace stackTrace) {
          if (_isCurrent(generation)) {
            _flowActive = false;
            _widgetOpen = false;
            _expectedUpdateItem = null;
            state = const PluggyReauthenticationState.phase(
              PluggyReauthenticationPhase.genericFailure,
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
        if (state.phase == PluggyReauthenticationPhase.loadingWidget) {
          state = const PluggyReauthenticationState.phase(
            PluggyReauthenticationPhase.widgetOpen,
          );
        }
        return;
      case PluggyConnectCallbackType.closed:
        _widgetOpen = false;
        if (state.phase == PluggyReauthenticationPhase.registeringConnection) {
          return;
        }
        _flowActive = false;
        _expectedUpdateItem = null;
        if (state.phase == PluggyReauthenticationPhase.widgetOpen ||
            state.phase == PluggyReauthenticationPhase.loadingWidget) {
          state = const PluggyReauthenticationState.phase(
            PluggyReauthenticationPhase.userCancelled,
          );
        }
        state = state.withFocusReturn(++_focusReturnRevision);
        return;
      case PluggyConnectCallbackType.errorWithoutItem:
        if (state.phase == PluggyReauthenticationPhase.updated) {
          return;
        }
        state = const PluggyReauthenticationState.phase(
          PluggyReauthenticationPhase.genericFailure,
        );
        return;
      case PluggyConnectCallbackType.invalidPayload:
        if (state.phase == PluggyReauthenticationPhase.updated) {
          return;
        }
        state = const PluggyReauthenticationState.phase(
          PluggyReauthenticationPhase.invalidProviderResponse,
        );
        return;
      case PluggyConnectCallbackType.itemAvailable:
        if (state.phase == PluggyReauthenticationPhase.updated) {
          return;
        }
        final itemId = callback.itemId;
        final expectedItem = _expectedUpdateItem;
        if (itemId == null || expectedItem == null || itemId != expectedItem) {
          state = const PluggyReauthenticationState.phase(
            PluggyReauthenticationPhase.invalidProviderResponse,
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
    state = const PluggyReauthenticationState.phase(
      PluggyReauthenticationPhase.registeringConnection,
    );
    try {
      final connection = await ref
          .read(pluggyReauthenticationApiProvider)
          .registerItem(itemId);
      if (!_isCurrent(generation)) {
        return;
      }
      _expectedUpdateItem = null;
      state = PluggyReauthenticationState.updated(connection);
      if (!_widgetOpen) {
        _flowActive = false;
        state = state.withFocusReturn(++_focusReturnRevision);
      }
    } catch (error) {
      if (!_isCurrent(generation)) {
        return;
      }
      _expectedUpdateItem = null;
      state = PluggyReauthenticationState.phase(
        _phaseForFailure(error, registering: true),
      );
      if (!_widgetOpen) {
        _flowActive = false;
        state = state.withFocusReturn(++_focusReturnRevision);
      }
    }
  }

  bool _isCurrent(int generation) => generation == _generation && _flowActive;
}

bool _isCanonicalUuid(String value) =>
    value.length == 36 && value == value.trim() && _uuidPattern.hasMatch(value);

PluggyReauthenticationPhase _phaseForFailure(
  Object error, {
  required bool registering,
}) {
  if (error is FormatException) {
    return PluggyReauthenticationPhase.invalidProviderResponse;
  }
  if (error is PluggyConnectLaunchException) {
    return PluggyReauthenticationPhase.temporarilyUnavailable;
  }
  if (error is AuthenticatedApiException) {
    if (error.failure == AuthenticatedApiFailure.authenticationRequired ||
        error.statusCode == 401) {
      return PluggyReauthenticationPhase.authenticationRequired;
    }
    return switch (error.statusCode) {
      403 => PluggyReauthenticationPhase.connectionUnavailable,
      404 when registering =>
        PluggyReauthenticationPhase.invalidProviderResponse,
      404 => PluggyReauthenticationPhase.connectionNotFound,
      409 => PluggyReauthenticationPhase.connectionUnavailable,
      502 => PluggyReauthenticationPhase.invalidProviderResponse,
      503 => PluggyReauthenticationPhase.temporarilyUnavailable,
      _ when error.failure == AuthenticatedApiFailure.transportFailure =>
        PluggyReauthenticationPhase.temporarilyUnavailable,
      _ when error.failure == AuthenticatedApiFailure.temporarilyUnavailable =>
        PluggyReauthenticationPhase.temporarilyUnavailable,
      _ => PluggyReauthenticationPhase.genericFailure,
    };
  }
  return PluggyReauthenticationPhase.genericFailure;
}
