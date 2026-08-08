import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/connect/pluggy_connect_controller.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class PluggyConnectScreen extends ConsumerStatefulWidget {
  const PluggyConnectScreen({super.key});

  static const titleKey = Key('pluggy-connect-title');
  static const connectButtonKey = Key('pluggy-connect-button');
  static const statusKey = Key('pluggy-connect-status');
  static const localConnectionKey = Key('pluggy-local-connection');

  @override
  ConsumerState<PluggyConnectScreen> createState() => _PluggyConnectScreenState();
}

class _PluggyConnectScreenState extends ConsumerState<PluggyConnectScreen> {
  final _connectFocusNode = FocusNode(debugLabel: 'pluggy-connect-action');
  late final PluggyConnectController _controller;

  @override
  void initState() {
    super.initState();
    _controller = ref.read(pluggyConnectControllerProvider.notifier);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _connectFocusNode.requestFocus();
      }
    });
  }

  @override
  void dispose() {
    _controller.cancelFromScreen();
    _connectFocusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(pluggyConnectControllerProvider);
    final session = ref.watch(operatorSessionControllerProvider);
    final demo = ref.watch(demoStatusProvider);

    ref.listen<PluggyConnectState>(pluggyConnectControllerProvider, (
      previous,
      next,
    ) {
      final shouldReturnFocus =
          next.focusReturnRevision != (previous?.focusReturnRevision ?? 0) ||
          (previous?.isBusy == true && !next.isBusy);
      if (shouldReturnFocus) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted && _connectFocusNode.canRequestFocus) {
            _connectFocusNode.requestFocus();
          }
        });
      }
    });

    final principal = session.principal;
    final demoStatus = demo.value;
    final prerequisite = _prerequisiteMessage(
      authenticated: session.isAuthenticated,
      hasPrimaryResidence: principal?.primaryResidenceId != null,
      demoLoaded: demoStatus != null,
      demoEnabled: demoStatus?.enabled == true,
    );
    final canStart = prerequisite == null && !state.isBusy;

    return Semantics(
      container: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: AppTokens.space16,
            runSpacing: AppTokens.space8,
            children: [
              TextButton.icon(
                onPressed: () => context.go('/'),
                icon: const Icon(Icons.arrow_back_rounded),
                label: const Text('Voltar ao início'),
              ),
              const _SecurityChip(),
            ],
          ),
          const SizedBox(height: AppTokens.space16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppTokens.space24),
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final stacked = constraints.maxWidth < 760;
                  final intro = _Intro(state: state);
                  final action = _ActionPanel(
                    state: state,
                    prerequisite: prerequisite,
                    canStart: canStart,
                    focusNode: _connectFocusNode,
                    onStart: _controller.start,
                  );
                  if (stacked) {
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        intro,
                        const SizedBox(height: AppTokens.space24),
                        action,
                      ],
                    );
                  }
                  return Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(flex: 6, child: intro),
                      const SizedBox(width: AppTokens.space32),
                      Expanded(flex: 4, child: action),
                    ],
                  );
                },
              ),
            ),
          ),
          const SizedBox(height: AppTokens.space24),
          _StatusPanel(state: state, prerequisite: prerequisite),
          const SizedBox(height: AppTokens.space24),
          const _PrivacyPanel(),
        ],
      ),
    );
  }
}

class _Intro extends StatelessWidget {
  const _Intro({required this.state});

  final PluggyConnectState state;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Integrações · Conexão bancária',
          style: Theme.of(context).textTheme.labelLarge?.copyWith(
                color: AppTokens.forest700,
              ),
        ),
        const SizedBox(height: AppTokens.space12),
        Semantics(
          header: true,
          child: Text(
            'Conectar instituição financeira',
            key: PluggyConnectScreen.titleKey,
            style: Theme.of(context).textTheme.headlineLarge,
          ),
        ),
        const SizedBox(height: AppTokens.space16),
        Text(
          'A conexão é opcional. Ao continuar, o ambiente seguro da Pluggy será aberto para você escolher a instituição e concluir a autorização.',
          style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                color: AppTokens.neutral700,
              ),
        ),
        const SizedBox(height: AppTokens.space20),
        const _FeatureLine(
          icon: Icons.lock_outline_rounded,
          text: 'Senha bancária e MFA não são armazenados pelo MeuFinanceiro.',
        ),
        const SizedBox(height: AppTokens.space12),
        const _FeatureLine(
          icon: Icons.wifi_rounded,
          text: 'A conexão depende de internet e não cria fila offline.',
        ),
        const SizedBox(height: AppTokens.space12),
        const _FeatureLine(
          icon: Icons.account_balance_wallet_outlined,
          text: 'Você pode continuar usando o MeuFinanceiro sem conectar um banco.',
        ),
      ],
    );
  }
}

class _ActionPanel extends StatelessWidget {
  const _ActionPanel({
    required this.state,
    required this.prerequisite,
    required this.canStart,
    required this.focusNode,
    required this.onStart,
  });

  final PluggyConnectState state;
  final String? prerequisite;
  final bool canStart;
  final FocusNode focusNode;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    final label = switch (state.phase) {
      PluggyConnectPhase.requestingToken => 'Preparando…',
      PluggyConnectPhase.loadingWidget => 'Carregando Pluggy…',
      PluggyConnectPhase.widgetOpen => 'Conexão em andamento…',
      PluggyConnectPhase.registeringConnection => 'Validando conexão…',
      PluggyConnectPhase.connected => 'Conectar outra instituição',
      PluggyConnectPhase.userCancelled => 'Tentar novamente',
      PluggyConnectPhase.providerUnavailable ||
      PluggyConnectPhase.configurationRequired ||
      PluggyConnectPhase.temporarilyUnavailable ||
      PluggyConnectPhase.connectionConflict ||
      PluggyConnectPhase.invalidProviderResponse ||
      PluggyConnectPhase.genericFailure => 'Tentar novamente',
      _ => 'Conectar instituição',
    };

    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppTokens.forest50,
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
        border: Border.all(color: AppTokens.forest100),
      ),
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Iniciar conexão',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              prerequisite ??
                  'O MeuFinanceiro solicitará um acesso temporário ao backend e abrirá a Pluggy somente após sua ação.',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: prerequisite == null
                        ? AppTokens.neutral700
                        : AppTokens.red700,
                  ),
            ),
            const SizedBox(height: AppTokens.space20),
            FilledButton.icon(
              key: PluggyConnectScreen.connectButtonKey,
              focusNode: focusNode,
              onPressed: canStart ? onStart : null,
              icon: state.isBusy
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.add_link_rounded),
              label: Text(label),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusPanel extends StatelessWidget {
  const _StatusPanel({required this.state, required this.prerequisite});

  final PluggyConnectState state;
  final String? prerequisite;

  @override
  Widget build(BuildContext context) {
    final presentation = _statusPresentation(state, prerequisite);
    if (presentation == null) {
      return const SizedBox.shrink();
    }

    return Semantics(
      key: PluggyConnectScreen.statusKey,
      liveRegion: true,
      label: presentation.message,
      child: Container(
        padding: const EdgeInsets.all(AppTokens.space16),
        decoration: BoxDecoration(
          color: presentation.isError ? AppTokens.red50 : AppTokens.white,
          borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
          border: Border.all(
            color: presentation.isError
                ? AppTokens.red100
                : AppTokens.neutral200,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  presentation.icon,
                  color: presentation.isError
                      ? AppTokens.red700
                      : AppTokens.forest700,
                ),
                const SizedBox(width: AppTokens.space12),
                Expanded(
                  child: Text(
                    presentation.message,
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                ),
              ],
            ),
            if (state.phase == PluggyConnectPhase.connected &&
                state.connectionId != null) ...[
              const SizedBox(height: AppTokens.space16),
              DecoratedBox(
                key: PluggyConnectScreen.localConnectionKey,
                decoration: BoxDecoration(
                  color: AppTokens.neutral50,
                  borderRadius: BorderRadius.circular(AppTokens.radiusSmall),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(AppTokens.space12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Identificador local',
                        style: Theme.of(context).textTheme.labelLarge,
                      ),
                      const SizedBox(height: AppTokens.space4),
                      SelectableText(state.connectionId!),
                      if (state.connectionStatus != null) ...[
                        const SizedBox(height: AppTokens.space8),
                        Text('Estado local: ${state.connectionStatus}'),
                      ],
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _PrivacyPanel extends StatelessWidget {
  const _PrivacyPanel();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.shield_outlined, color: AppTokens.forest700),
                const SizedBox(width: AppTokens.space12),
                Expanded(
                  child: Text(
                    'Como a conexão é protegida',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppTokens.space12),
            Text(
              'O retorno do widget não autoriza nada sozinho. O backend confere a conexão diretamente na Pluggy e associa somente o identificador local à residência autenticada.',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: AppTokens.neutral700,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SecurityChip extends StatelessWidget {
  const _SecurityChip();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppTokens.space12,
        vertical: AppTokens.space8,
      ),
      decoration: BoxDecoration(
        color: AppTokens.forest50,
        borderRadius: BorderRadius.circular(AppTokens.radiusSmall),
        border: Border.all(color: AppTokens.forest100),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.verified_user_outlined, size: 18, color: AppTokens.forest700),
          SizedBox(width: AppTokens.space8),
          Text('Sessão autenticada'),
        ],
      ),
    );
  }
}

class _FeatureLine extends StatelessWidget {
  const _FeatureLine({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 20, color: AppTokens.forest700),
        const SizedBox(width: AppTokens.space12),
        Expanded(child: Text(text)),
      ],
    );
  }
}

String? _prerequisiteMessage({
  required bool authenticated,
  required bool hasPrimaryResidence,
  required bool demoLoaded,
  required bool demoEnabled,
}) {
  if (!authenticated) {
    return 'Entre novamente para iniciar uma conexão bancária.';
  }
  if (!hasPrimaryResidence) {
    return 'Uma residência principal é necessária antes de conectar uma instituição.';
  }
  if (!demoLoaded) {
    return 'Aguarde a verificação do ambiente antes de iniciar a conexão.';
  }
  if (demoEnabled) {
    return 'Integrações externas ficam indisponíveis no modo demonstração.';
  }
  return null;
}

_StatusPresentation? _statusPresentation(
  PluggyConnectState state,
  String? prerequisite,
) {
  if (state.phase == PluggyConnectPhase.idle) {
    if (prerequisite == null) {
      return null;
    }
    return _StatusPresentation(
      message: prerequisite,
      icon: Icons.info_outline_rounded,
      isError: true,
    );
  }

  return switch (state.phase) {
    PluggyConnectPhase.requestingToken => const _StatusPresentation(
        message: 'Preparando um acesso temporário para abrir a Pluggy.',
        icon: Icons.hourglass_top_rounded,
      ),
    PluggyConnectPhase.loadingWidget => const _StatusPresentation(
        message: 'Carregando o ambiente de conexão da Pluggy.',
        icon: Icons.cloud_download_outlined,
      ),
    PluggyConnectPhase.widgetOpen => const _StatusPresentation(
        message: 'Conexão em andamento no ambiente da Pluggy.',
        icon: Icons.open_in_new_rounded,
      ),
    PluggyConnectPhase.registeringConnection => const _StatusPresentation(
        message: 'Validando a conexão no backend do MeuFinanceiro.',
        icon: Icons.verified_outlined,
      ),
    PluggyConnectPhase.connected => _StatusPresentation(
        message: state.requiresUserAction
            ? 'Conexão registrada. A instituição ainda sinaliza uma ação ou autorização pendente.'
            : 'Instituição conectada e validada pelo MeuFinanceiro.',
        icon: state.requiresUserAction
            ? Icons.pending_actions_outlined
            : Icons.check_circle_outline_rounded,
      ),
    PluggyConnectPhase.userCancelled => const _StatusPresentation(
        message: 'Conexão cancelada. Nenhuma nova conexão foi registrada.',
        icon: Icons.cancel_outlined,
      ),
    PluggyConnectPhase.authenticationRequired => const _StatusPresentation(
        message: 'Sua sessão expirou ou foi encerrada. Entre novamente.',
        icon: Icons.lock_outline_rounded,
        isError: true,
      ),
    PluggyConnectPhase.primaryResidenceRequired => const _StatusPresentation(
        message: 'Uma residência principal é necessária para conectar um banco.',
        icon: Icons.home_outlined,
        isError: true,
      ),
    PluggyConnectPhase.demoUnavailable => const _StatusPresentation(
        message: 'Integrações externas não são executadas no modo demonstração.',
        icon: Icons.science_outlined,
        isError: true,
      ),
    PluggyConnectPhase.providerUnavailable => const _StatusPresentation(
        message: 'A integração Pluggy não está disponível nesta instalação.',
        icon: Icons.link_off_rounded,
        isError: true,
      ),
    PluggyConnectPhase.configurationRequired => const _StatusPresentation(
        message: 'A integração Pluggy precisa ser configurada e habilitada no backend.',
        icon: Icons.settings_outlined,
        isError: true,
      ),
    PluggyConnectPhase.temporarilyUnavailable => const _StatusPresentation(
        message: 'A conexão online está temporariamente indisponível. Tente novamente quando houver internet.',
        icon: Icons.cloud_off_outlined,
        isError: true,
      ),
    PluggyConnectPhase.connectionConflict => const _StatusPresentation(
        message: 'Não foi possível associar esta conexão à residência autenticada.',
        icon: Icons.warning_amber_rounded,
        isError: true,
      ),
    PluggyConnectPhase.invalidProviderResponse => const _StatusPresentation(
        message: 'A resposta da integração não pôde ser validada com segurança.',
        icon: Icons.gpp_bad_outlined,
        isError: true,
      ),
    PluggyConnectPhase.genericFailure => const _StatusPresentation(
        message: 'Não foi possível concluir a conexão. Nenhum dado sensível foi mantido para retry.',
        icon: Icons.error_outline_rounded,
        isError: true,
      ),
    PluggyConnectPhase.idle => null,
  };
}

class _StatusPresentation {
  const _StatusPresentation({
    required this.message,
    required this.icon,
    this.isError = false,
  });

  final String message;
  final IconData icon;
  final bool isError;
}
