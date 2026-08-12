import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/features/banking/pluggy/reauthentication/pluggy_reauthentication_controller.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class PluggyReauthenticationScreen extends ConsumerStatefulWidget {
  const PluggyReauthenticationScreen({required this.connectionId, super.key});

  final String connectionId;

  static const titleKey = Key('pluggy-reauthentication-title');
  static const actionButtonKey = Key('pluggy-reauthentication-button');
  static const statusKey = Key('pluggy-reauthentication-status');
  static const localConnectionKey = Key('pluggy-reauthentication-local-result');

  @override
  ConsumerState<PluggyReauthenticationScreen> createState() =>
      _PluggyReauthenticationScreenState();
}

class _PluggyReauthenticationScreenState
    extends ConsumerState<PluggyReauthenticationScreen> {
  final _actionFocusNode = FocusNode(
    debugLabel: 'pluggy-reauthentication-action',
  );

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _actionFocusNode.requestFocus();
      }
    });
  }

  @override
  void dispose() {
    _actionFocusNode.dispose();
    super.dispose();
  }

  void _start() {
    ref
        .read(pluggyReauthenticationControllerProvider.notifier)
        .start(widget.connectionId);
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(pluggyReauthenticationControllerProvider);
    final session = ref.watch(operatorSessionControllerProvider);
    final demoStatus = ref.watch(demoStatusProvider).value;

    ref.listen<PluggyReauthenticationState>(
      pluggyReauthenticationControllerProvider,
      (previous, next) {
        if (next.focusReturnRevision != (previous?.focusReturnRevision ?? 0)) {
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (mounted && _actionFocusNode.canRequestFocus) {
              _actionFocusNode.requestFocus();
            }
          });
        }
      },
    );

    final principal = session.principal;
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
                onPressed: () => context.go(AppRoutes.pluggyConnectPath),
                icon: const Icon(Icons.arrow_back_rounded),
                label: const Text('Voltar para conexão bancária'),
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
                  final intro = const _Intro();
                  final action = _ActionPanel(
                    state: state,
                    prerequisite: prerequisite,
                    canStart: canStart,
                    focusNode: _actionFocusNode,
                    onStart: _start,
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
                      const Expanded(flex: 6, child: _Intro()),
                      const SizedBox(width: AppTokens.space32),
                      Expanded(flex: 4, child: action),
                    ],
                  );
                },
              ),
            ),
          ),
          const SizedBox(height: AppTokens.space24),
          _StatusPanel(state: state),
          const SizedBox(height: AppTokens.space24),
          const _PrivacyPanel(),
        ],
      ),
    );
  }
}

class _Intro extends StatelessWidget {
  const _Intro();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Integrações · Conexão existente',
          style: Theme.of(
            context,
          ).textTheme.labelLarge?.copyWith(color: AppTokens.forest700),
        ),
        const SizedBox(height: AppTokens.space12),
        Semantics(
          header: true,
          child: Text(
            'Atualizar acesso da instituição',
            key: PluggyReauthenticationScreen.titleKey,
            style: Theme.of(context).textTheme.headlineLarge,
          ),
        ),
        const SizedBox(height: AppTokens.space16),
        Text(
          'A Pluggy poderá solicitar uma nova autenticação ou MFA se a instituição exigir. O MeuFinanceiro não recebe nem armazena essas credenciais.',
          style: Theme.of(
            context,
          ).textTheme.bodyLarge?.copyWith(color: AppTokens.neutral700),
        ),
        const SizedBox(height: AppTokens.space20),
        const _FeatureLine(
          icon: Icons.lock_reset_rounded,
          text:
              'O acesso temporário é emitido somente para esta conexão local.',
        ),
        const SizedBox(height: AppTokens.space12),
        const _FeatureLine(
          icon: Icons.password_rounded,
          text: 'Senha e MFA são tratados no ambiente da Pluggy.',
        ),
        const SizedBox(height: AppTokens.space12),
        const _FeatureLine(
          icon: Icons.cancel_outlined,
          text: 'Cancelar esta etapa não remove a conexão existente.',
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

  final PluggyReauthenticationState state;
  final String? prerequisite;
  final bool canStart;
  final FocusNode focusNode;
  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    final label = switch (state.phase) {
      PluggyReauthenticationPhase.requestingToken => 'Preparando…',
      PluggyReauthenticationPhase.loadingWidget => 'Carregando Pluggy…',
      PluggyReauthenticationPhase.widgetOpen => 'Atualização em andamento…',
      PluggyReauthenticationPhase.registeringConnection => 'Validando…',
      PluggyReauthenticationPhase.updated => 'Atualizar novamente',
      PluggyReauthenticationPhase.userCancelled ||
      PluggyReauthenticationPhase.connectionNotFound ||
      PluggyReauthenticationPhase.connectionUnavailable ||
      PluggyReauthenticationPhase.temporarilyUnavailable ||
      PluggyReauthenticationPhase.invalidProviderResponse ||
      PluggyReauthenticationPhase.genericFailure => 'Tentar novamente',
      _ => 'Atualizar conexão',
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
              'Reautenticação',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              prerequisite ??
                  'A conexão será validada no backend antes que o ambiente de atualização seja aberto.',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: prerequisite == null
                    ? AppTokens.neutral700
                    : AppTokens.red700,
              ),
            ),
            const SizedBox(height: AppTokens.space20),
            FilledButton(
              key: PluggyReauthenticationScreen.actionButtonKey,
              focusNode: focusNode,
              onPressed: canStart ? onStart : null,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (state.isBusy)
                    const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  else
                    const Icon(Icons.sync_lock_rounded),
                  const SizedBox(width: AppTokens.space8),
                  Flexible(child: Text(label, textAlign: TextAlign.center)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusPanel extends StatelessWidget {
  const _StatusPanel({required this.state});

  final PluggyReauthenticationState state;

  @override
  Widget build(BuildContext context) {
    final presentation = _statusPresentation(state);
    if (presentation == null) {
      return const SizedBox.shrink();
    }
    return Semantics(
      key: PluggyReauthenticationScreen.statusKey,
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
                Expanded(child: Text(presentation.message)),
              ],
            ),
            if (state.phase == PluggyReauthenticationPhase.updated &&
                state.connectionId != null) ...[
              const SizedBox(height: AppTokens.space16),
              DecoratedBox(
                key: PluggyReauthenticationScreen.localConnectionKey,
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
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.shield_outlined, color: AppTokens.forest700),
            const SizedBox(width: AppTokens.space12),
            Expanded(
              child: Text(
                'O identificador do provedor usado para atualizar a conexão é obtido pelo backend e existe no navegador apenas enquanto o widget está sendo aberto. O retorno do widget é validado novamente antes de atualizar o estado local.',
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
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
      child: const Wrap(
        alignment: WrapAlignment.center,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: AppTokens.space8,
        runSpacing: AppTokens.space4,
        children: [
          Icon(
            Icons.verified_user_outlined,
            size: 18,
            color: AppTokens.forest700,
          ),
          Text('Conexão verificada'),
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
    return 'Entre novamente para atualizar esta conexão.';
  }
  if (!hasPrimaryResidence) {
    return 'Uma residência principal é necessária para atualizar a conexão.';
  }
  if (!demoLoaded) {
    return 'Aguarde a verificação do ambiente antes de continuar.';
  }
  if (demoEnabled) {
    return 'Integrações externas ficam indisponíveis no modo demonstração.';
  }
  return null;
}

_StatusPresentation? _statusPresentation(PluggyReauthenticationState state) {
  if (state.phase == PluggyReauthenticationPhase.idle) {
    return null;
  }
  return switch (state.phase) {
    PluggyReauthenticationPhase.requestingToken => const _StatusPresentation(
      message: 'Validando a conexão e preparando um acesso temporário.',
      icon: Icons.hourglass_top_rounded,
    ),
    PluggyReauthenticationPhase.loadingWidget => const _StatusPresentation(
      message: 'Carregando o ambiente seguro de atualização da Pluggy.',
      icon: Icons.cloud_download_outlined,
    ),
    PluggyReauthenticationPhase.widgetOpen => const _StatusPresentation(
      message: 'Atualização em andamento no ambiente da Pluggy.',
      icon: Icons.open_in_new_rounded,
    ),
    PluggyReauthenticationPhase.registeringConnection =>
      const _StatusPresentation(
        message: 'Confirmando novamente a conexão no MeuFinanceiro.',
        icon: Icons.verified_outlined,
      ),
    PluggyReauthenticationPhase.updated => _StatusPresentation(
      message: state.requiresUserAction
          ? 'A conexão foi atualizada, mas a instituição ainda sinaliza uma ação pendente.'
          : 'A conexão foi atualizada e validada pelo MeuFinanceiro.',
      icon: state.requiresUserAction
          ? Icons.pending_actions_outlined
          : Icons.check_circle_outline_rounded,
    ),
    PluggyReauthenticationPhase.userCancelled => const _StatusPresentation(
      message: 'Atualização cancelada. A conexão existente foi preservada.',
      icon: Icons.cancel_outlined,
    ),
    PluggyReauthenticationPhase.invalidConnectionId =>
      const _StatusPresentation(
        message: 'O identificador local da conexão é inválido.',
        icon: Icons.link_off_rounded,
        isError: true,
      ),
    PluggyReauthenticationPhase.authenticationRequired =>
      const _StatusPresentation(
        message: 'Sua sessão expirou ou foi encerrada. Entre novamente.',
        icon: Icons.lock_outline_rounded,
        isError: true,
      ),
    PluggyReauthenticationPhase.primaryResidenceRequired =>
      const _StatusPresentation(
        message: 'Uma residência principal é necessária para esta operação.',
        icon: Icons.home_outlined,
        isError: true,
      ),
    PluggyReauthenticationPhase.demoUnavailable => const _StatusPresentation(
      message: 'Integrações externas não são executadas no modo demonstração.',
      icon: Icons.science_outlined,
      isError: true,
    ),
    PluggyReauthenticationPhase.connectionNotFound => const _StatusPresentation(
      message: 'A conexão não foi encontrada para a residência autenticada.',
      icon: Icons.search_off_rounded,
      isError: true,
    ),
    PluggyReauthenticationPhase.connectionUnavailable =>
      const _StatusPresentation(
        message: 'Esta conexão não pode ser atualizada neste momento.',
        icon: Icons.block_outlined,
        isError: true,
      ),
    PluggyReauthenticationPhase.temporarilyUnavailable =>
      const _StatusPresentation(
        message:
            'A atualização online está temporariamente indisponível. Tente novamente quando houver internet.',
        icon: Icons.cloud_off_outlined,
        isError: true,
      ),
    PluggyReauthenticationPhase.invalidProviderResponse =>
      const _StatusPresentation(
        message:
            'A resposta da integração não pôde ser validada com segurança.',
        icon: Icons.gpp_bad_outlined,
        isError: true,
      ),
    PluggyReauthenticationPhase.genericFailure => const _StatusPresentation(
      message:
          'Não foi possível concluir a atualização. Nenhum dado sensível foi mantido para retry.',
      icon: Icons.error_outline_rounded,
      isError: true,
    ),
    PluggyReauthenticationPhase.idle => null,
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
