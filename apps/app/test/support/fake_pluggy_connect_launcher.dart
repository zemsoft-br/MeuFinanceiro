import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';

class FakePluggyConnectLaunchCall {
  const FakePluggyConnectLaunchCall({
    required this.connectToken,
    required this.updateItem,
  });

  final String connectToken;
  final String? updateItem;

  @override
  String toString() => 'FakePluggyConnectLaunchCall(<redacted>)';
}

class FakePluggyConnectLauncher implements PluggyConnectLauncher {
  FakePluggyConnectLauncher({this.failOnLaunch = false});

  final bool failOnLaunch;
  final List<FakePluggyConnectLaunchCall> calls = [];
  void Function(PluggyConnectCallback callback)? _callback;

  @override
  Future<void> launch({
    required String connectToken,
    String? updateItem,
    required void Function(PluggyConnectCallback callback) onCallback,
  }) async {
    calls.add(
      FakePluggyConnectLaunchCall(
        connectToken: connectToken,
        updateItem: updateItem,
      ),
    );
    if (failOnLaunch) {
      throw const PluggyConnectLaunchException();
    }
    _callback = onCallback;
  }

  void emit(PluggyConnectCallback callback) {
    _callback?.call(callback);
  }
}
