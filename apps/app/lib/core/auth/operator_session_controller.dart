import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/auth_transport.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_service.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';

final authTransportProvider = Provider<AuthTransport>(
  (ref) => createDefaultAuthTransport(),
);

final authApiBaseUriProvider = Provider<Uri>(
  (ref) => Uri.base.resolve('/api/v1/'),
);

final authRequestTimeoutProvider = Provider<Duration>(
  (ref) => const Duration(seconds: 10),
);

final sessionTokenVaultProvider = Provider<SessionTokenVault>((ref) {
  final vault = SessionTokenVault();
  ref.onDispose(vault.clear);
  return vault;
});

final operatorSessionServiceProvider = Provider<OperatorSessionService>((ref) {
  return OperatorSessionService(
    transport: ref.watch(authTransportProvider),
    apiBaseUri: ref.watch(authApiBaseUriProvider),
    timeout: ref.watch(authRequestTimeoutProvider),
  );
});

final operatorSessionControllerProvider =
    NotifierProvider<OperatorSessionController, OperatorSessionState>(
      OperatorSessionController.new,
    );

class OperatorSessionController extends Notifier<OperatorSessionState> {
  int _operationGeneration = 0;

  @override
  OperatorSessionState build() {
    final vault = ref.read(sessionTokenVaultProvider);
    ref.onDispose(() {
      _operationGeneration += 1;
      vault.clear();
    });
    return const OperatorSessionState.signedOut();
  }

  Future<void> login({required String login, required String password}) async {
    if (state.isBusy) {
      return;
    }

    final generation = ++_operationGeneration;
    ref.read(sessionTokenVaultProvider).clear();
    state = const OperatorSessionState.authenticating();

    try {
      final issued = await ref
          .read(operatorSessionServiceProvider)
          .login(login: login, password: password);
      if (generation != _operationGeneration) {
        return;
      }
      ref.read(sessionTokenVaultProvider).store(issued.accessToken);
      state = OperatorSessionState.authenticated(issued.principal);
    } on InvalidOperatorCredentials {
      if (generation == _operationGeneration) {
        state = const OperatorSessionState.invalidCredentials();
      }
    } catch (_) {
      if (generation == _operationGeneration) {
        ref.read(sessionTokenVaultProvider).clear();
        state = const OperatorSessionState.temporarilyUnavailable();
      }
    }
  }

  Future<void> logout() async {
    final generation = ++_operationGeneration;
    final token = ref.read(sessionTokenVaultProvider).take();
    state = const OperatorSessionState.signingOut();

    try {
      if (token != null) {
        await ref.read(operatorSessionServiceProvider).logout(token);
      }
    } catch (_) {
      // Logout is fail-closed locally. The bearer reference has already been
      // removed before the network request starts.
    } finally {
      if (generation == _operationGeneration) {
        state = const OperatorSessionState.signedOut();
      }
    }
  }

  void invalidateFromUnauthorized() {
    _operationGeneration += 1;
    ref.read(sessionTokenVaultProvider).clear();
    state = const OperatorSessionState.expiredOrRevoked();
  }

  void clearError() {
    if (state.phase == OperatorSessionPhase.invalidCredentials ||
        state.phase == OperatorSessionPhase.temporarilyUnavailable ||
        state.phase == OperatorSessionPhase.expiredOrRevoked) {
      state = const OperatorSessionState.signedOut();
    }
  }
}
