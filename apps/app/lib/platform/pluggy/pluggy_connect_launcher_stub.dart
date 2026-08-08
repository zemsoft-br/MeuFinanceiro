import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';

PluggyConnectLauncher createPluggyConnectLauncher() =>
    const UnsupportedPluggyConnectLauncher();

class UnsupportedPluggyConnectLauncher implements PluggyConnectLauncher {
  const UnsupportedPluggyConnectLauncher();

  @override
  Future<void> launch({
    required String connectToken,
    String? updateItem,
    required void Function(PluggyConnectCallback callback) onCallback,
  }) {
    throw const PluggyConnectLaunchException();
  }
}
