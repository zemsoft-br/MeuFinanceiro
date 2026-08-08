import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';
import 'package:meufinanceiro_app/platform/pluggy/pluggy_connect_launcher_stub.dart'
    if (dart.library.html) 'package:meufinanceiro_app/platform/pluggy/pluggy_connect_launcher_web.dart'
    as implementation;

PluggyConnectLauncher createDefaultPluggyConnectLauncher() =>
    implementation.createPluggyConnectLauncher();
