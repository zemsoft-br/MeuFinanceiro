import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/banking/connections/banking_connections_api.dart';
import 'package:meufinanceiro_app/features/banking/connections/banking_connections_controller.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class BankingConnectionsScreen extends ConsumerStatefulWidget {
  const BankingConnectionsScreen({super.key});

  static const titleKey = Key('banking-connections-title');
  static const connectButtonKey = Key('banking-connections-connect');
  static const refreshButtonKey = Key('banking-connections-refresh');
  static const statusKey = Key('banking-connections-status');
  static const listKey = Key('banking-connections-list');
  static const emptyKey = Key('banking-connections-empty');

  static Key connectionCardKey(String connectionId) =>
      Key('banking-connection-$connectionId');

  static Key reauthenticationButtonKey(String connectionId) =>
      Key('banking-connection-reauthenticate-$connectionId');

  @override
  ConsumerState<BankingConnectionsScreen> createState() =>
      _BankingConnectionsScreenState();
}

class _BankingConnectionsScreenState
    extends ConsumerState<BankingConnectionsScreen> {
  final _headingFocusNode = FocusNode(
    debugLabel: 'banking-connections-heading',
  );

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      _headingFocusNode.requestFocus();
      unawaited(ref.read(bankingConnectionsControllerProvider.notifier).load());
    });
  }

  @override
  void dispose() {
    _headingFocusNode.dispose();
    super.dispose();
  }

  void _refresh() {
    unawaited(
      ref.read(bankingConnectionsControllerProvider.notifier).refresh(),
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(bankingConnectionsControllerProvider);
    final refreshEnabled =
        !state.isBusy &&
        state.phase != BankingConnectionsPhase.authenticationRequired &&
        state.phase != BankingConnectionsPhase.forbidden &&
        state.phase != BankingConnectionsPhase.primaryResidenceRequired;

    return FocusTraversalGroup(
      policy: ReadingOrderTraversalPolicy(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Header(
            headingFocusNode: _headingFocusNode,
            refreshing: state.phase == BankingConnectionsPhase.refreshing,
            onConnect: () => context.go(AppRoutes.pluggyConnectPath),
            onRefresh: refreshEnabled ? _refresh : null,
          ),
          const SizedBox(height: AppTokens.space24),
          _RefreshNotice(state: state),
          if (state.refreshFailure != BankingConnectionsRefreshFailure.none)
            const SizedBox(height: AppTokens.space16),
          _Content(
            state: state,
            onRetry: _refresh,
            onConnect: () => context.go(AppRoutes.pluggyConnectPath),
            onReauthenticate: (connectionId) {
              context.go(
                AppRoutes.pluggyReauthenticationLocation(connectionId),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.headingFocusNode,
    required this.refreshing,
    required this.onConnect,
    required this.onRefresh,
  });

  final FocusNode headingFocusNode;
  final bool refreshing;
  final VoidCallback onConnect;
  final VoidCallback? onRefresh;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      alignment: WrapAlignment.spaceBetween,
      crossAxisAlignment: WrapCrossAlignment.center,
      spacing: AppTokens.space16,
      runSpacing: AppTokens.space16,
      children: [
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Open Finance · Residência principal',
                style: Theme.of(
                  context,
                ).textTheme.labelLarge?.copyWith(color: AppTokens.forest700),
              ),
              const SizedBox(height: AppTokens.space8),
              Focus(
                focusNode: headingFocusNode,
                child: Semantics(
                  header: true,
                  child: Text(
                    'Integrações bancárias',
                    key: BankingConnectionsScreen.titleKey,
                    style: Theme.of(context).textTheme.headlineLarge,
                  ),
                ),
              ),
              const SizedBox(height: AppTokens.space8),
              Text(
                'Conexões registradas localmente. Esta tela não consulta instituições financeiras diretamente.',
                style: Theme.of(
                  context,
                ).textTheme.bodyLarge?.copyWith(color: AppTokens.neutral700),
              ),
            ],
          ),
        ),
        Wrap(
          spacing: AppTokens.space8,
          runSpacing: AppTokens.space8,
          children: [
            OutlinedButton.icon(
              key: BankingConnectionsScreen.refreshButtonKey,
              onPressed: onRefresh,
              icon: refreshing
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh_rounded),
              label: Text(refreshing ? 'Atualizando…' : 'Atualizar lista'),
            ),
            FilledButton.icon(
              key: BankingConnectionsScreen.connectButtonKey,
              onPressed: onConnect,
              icon: const Icon(Icons.add_link_rounded),
              label: const Text('Conectar instituição'),
            ),
          ],
        ),
      ],
    );
  }
}

class _RefreshNotice extends StatelessWidget {
  const _RefreshNotice({required this.state});

  final BankingConnectionsState state;

  @override
  Widget build(BuildContext context) {
    final message = switch (state.refreshFailure) {
      BankingConnectionsRefreshFailure.temporarilyUnavailable =>
        'A lista atual foi preservada, mas não foi possível buscar uma versão mais recente.',
      BankingConnectionsRefreshFailure.invalidResponse =>
        'A lista atual foi preservada porque a nova resposta não pôde ser validada com segurança.',
      BankingConnectionsRefreshFailure.none => null,
    };
    if (message == null) {
      return const SizedBox.shrink();
    }
    return Semantics(
      liveRegion: true,
      label: message,
      child: Container(
        padding: const EdgeInsets.all(AppTokens.space16),
        decoration: BoxDecoration(
          color: AppTokens.amber50,
          border: Border.all(color: AppTokens.amber100),
          borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.info_outline_rounded, color: AppTokens.amber700),
            const SizedBox(width: AppTokens.space12),
            Expanded(child: Text(message)),
          ],
        ),
      ),
    );
  }
}

class _Content extends StatelessWidget {
  const _Content({
    required this.state,
    required this.onRetry,
    required this.onConnect,
    required this.onReauthenticate,
  });

  final BankingConnectionsState state;
  final VoidCallback onRetry;
  final VoidCallback onConnect;
  final ValueChanged<String> onReauthenticate;

  @override
  Widget build(BuildContext context) {
    if (state.phase == BankingConnectionsPhase.loading ||
        state.phase == BankingConnectionsPhase.idle) {
      return const _LoadingPanel();
    }
    if (state.phase == BankingConnectionsPhase.empty) {
      return _EmptyPanel(onConnect: onConnect);
    }
    if (state.hasConnections) {
      return _ConnectionsList(
        connections: state.connections,
        onReauthenticate: onReauthenticate,
      );
    }

    final presentation = _failurePresentation(state.phase);
    return _FailurePanel(presentation: presentation, onRetry: onRetry);
  }
}

class _LoadingPanel extends StatelessWidget {
  const _LoadingPanel();

  @override
  Widget build(BuildContext context) {
    return Semantics(
      key: BankingConnectionsScreen.statusKey,
      liveRegion: true,
      label: 'Carregando conexões bancárias locais.',
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.space24),
          child: Row(
            children: [
              const SizedBox.square(
                dimension: 24,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              ),
              const SizedBox(width: AppTokens.space16),
              Expanded(
                child: Text(
                  'Carregando conexões registradas localmente…',
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyPanel extends StatelessWidget {
  const _EmptyPanel({required this.onConnect});

  final VoidCallback onConnect;

  @override
  Widget build(BuildContext context) {
    return Card(
      key: BankingConnectionsScreen.emptyKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(
              Icons.account_balance_outlined,
              size: 36,
              color: AppTokens.forest700,
            ),
            const SizedBox(height: AppTokens.space16),
            Text(
              'Nenhuma instituição conectada',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              'Você pode continuar usando o MeuFinanceiro normalmente ou iniciar uma conexão opcional pelo ambiente da Pluggy.',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
            ),
            const SizedBox(height: AppTokens.space20),
            FilledButton.icon(
              onPressed: onConnect,
              icon: const Icon(Icons.add_link_rounded),
              label: const Text('Conectar instituição'),
            ),
          ],
        ),
      ),
    );
  }
}

class _ConnectionsList extends StatelessWidget {
  const _ConnectionsList({
    required this.connections,
    required this.onReauthenticate,
  });

  final List<LocalBankingConnection> connections;
  final ValueChanged<String> onReauthenticate;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      key: BankingConnectionsScreen.listKey,
      container: true,
      label: '${connections.length} conexões bancárias locais',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var index = 0; index < connections.length; index++) ...[
            _ConnectionCard(
              connection: connections[index],
              onReauthenticate: onReauthenticate,
            ),
            if (index != connections.length - 1)
              const SizedBox(height: AppTokens.space16),
          ],
        ],
      ),
    );
  }
}

class _ConnectionCard extends StatelessWidget {
  const _ConnectionCard({
    required this.connection,
    required this.onReauthenticate,
  });

  final LocalBankingConnection connection;
  final ValueChanged<String> onReauthenticate;

  @override
  Widget build(BuildContext context) {
    final status = _statusPresentation(connection.status);
    return Card(
      key: BankingConnectionsScreen.connectionCardKey(connection.connectionId),
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: AppTokens.space16,
              runSpacing: AppTokens.space12,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _providerLabel(connection.provider),
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: AppTokens.space4),
                    Text(
                      'Conexão registrada no MeuFinanceiro',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppTokens.neutral600,
                      ),
                    ),
                  ],
                ),
                _StatusBadge(presentation: status),
              ],
            ),
            if (connection.requiresUserAction) ...[
              const SizedBox(height: AppTokens.space16),
              const _ActionRequiredNotice(),
            ],
            const SizedBox(height: AppTokens.space16),
            Wrap(
              spacing: AppTokens.space24,
              runSpacing: AppTokens.space12,
              children: [
                _Metadata(
                  label: 'Última sincronização',
                  value: _formatTimestamp(connection.lastSuccessfulSyncAt),
                ),
                _Metadata(
                  label: 'Última tentativa',
                  value: _formatTimestamp(connection.lastAttemptAt),
                ),
                _Metadata(
                  label: 'Atualizado localmente',
                  value: _formatTimestamp(connection.updatedAt),
                ),
              ],
            ),
            if (connection.reauthenticationAvailable) ...[
              const SizedBox(height: AppTokens.space20),
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  key: BankingConnectionsScreen.reauthenticationButtonKey(
                    connection.connectionId,
                  ),
                  onPressed: () => onReauthenticate(connection.connectionId),
                  icon: const Icon(Icons.sync_lock_rounded),
                  label: const Text('Reautenticar'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ActionRequiredNotice extends StatelessWidget {
  const _ActionRequiredNotice();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(AppTokens.space12),
      decoration: BoxDecoration(
        color: AppTokens.amber50,
        border: Border.all(color: AppTokens.amber100),
        borderRadius: BorderRadius.circular(AppTokens.radiusSmall),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.pending_actions_outlined, color: AppTokens.amber700),
          SizedBox(width: AppTokens.space12),
          Expanded(
            child: Text(
              'A conexão sinaliza uma ação do usuário. Consulte somente as ações oferecidas nesta tela.',
            ),
          ),
        ],
      ),
    );
  }
}

class _Metadata extends StatelessWidget {
  const _Metadata({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(minWidth: 180, maxWidth: 260),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: AppTokens.space4),
          Text(
            value,
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
          ),
        ],
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.presentation});

  final _StatusPresentation presentation;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'Estado: ${presentation.label}',
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: AppTokens.space12,
          vertical: AppTokens.space8,
        ),
        decoration: BoxDecoration(
          color: presentation.background,
          border: Border.all(color: presentation.border),
          borderRadius: BorderRadius.circular(AppTokens.radiusSmall),
        ),
        child: Wrap(
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: AppTokens.space8,
          runSpacing: AppTokens.space4,
          children: [
            Icon(presentation.icon, size: 18, color: presentation.foreground),
            Text(
              presentation.label,
              style: Theme.of(
                context,
              ).textTheme.labelLarge?.copyWith(color: presentation.foreground),
            ),
          ],
        ),
      ),
    );
  }
}

class _FailurePanel extends StatelessWidget {
  const _FailurePanel({required this.presentation, required this.onRetry});

  final _FailurePresentation presentation;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      key: BankingConnectionsScreen.statusKey,
      liveRegion: true,
      label: presentation.message,
      child: Container(
        padding: const EdgeInsets.all(AppTokens.space24),
        decoration: BoxDecoration(
          color: AppTokens.red50,
          border: Border.all(color: AppTokens.red100),
          borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.error_outline_rounded, color: AppTokens.red700),
            const SizedBox(height: AppTokens.space12),
            Text(
              presentation.title,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: AppTokens.space8),
            Text(presentation.message),
            if (presentation.retryable) ...[
              const SizedBox(height: AppTokens.space20),
              OutlinedButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Tentar novamente'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

_StatusPresentation _statusPresentation(BankingConnectionStatus status) {
  return switch (status) {
    BankingConnectionStatus.available => const _StatusPresentation(
      label: 'Disponível',
      icon: Icons.check_circle_outline_rounded,
      background: AppTokens.forest50,
      border: AppTokens.forest100,
      foreground: AppTokens.forest700,
    ),
    BankingConnectionStatus.pendingUserAction => const _StatusPresentation(
      label: 'Aguardando ação',
      icon: Icons.pending_actions_outlined,
      background: AppTokens.amber50,
      border: AppTokens.amber100,
      foreground: AppTokens.amber700,
    ),
    BankingConnectionStatus.syncRequested => const _StatusPresentation(
      label: 'Sincronização solicitada',
      icon: Icons.schedule_rounded,
      background: AppTokens.blue50,
      border: AppTokens.blue100,
      foreground: AppTokens.blue700,
    ),
    BankingConnectionStatus.syncing => const _StatusPresentation(
      label: 'Sincronizando',
      icon: Icons.sync_rounded,
      background: AppTokens.blue50,
      border: AppTokens.blue100,
      foreground: AppTokens.blue700,
    ),
    BankingConnectionStatus.partial => const _StatusPresentation(
      label: 'Disponibilidade parcial',
      icon: Icons.info_outline_rounded,
      background: AppTokens.amber50,
      border: AppTokens.amber100,
      foreground: AppTokens.amber700,
    ),
    BankingConnectionStatus.reauthenticationRequired =>
      const _StatusPresentation(
        label: 'Reautenticação necessária',
        icon: Icons.sync_lock_rounded,
        background: AppTokens.amber50,
        border: AppTokens.amber100,
        foreground: AppTokens.amber700,
      ),
    BankingConnectionStatus.temporarilyUnavailable => const _StatusPresentation(
      label: 'Temporariamente indisponível',
      icon: Icons.cloud_off_outlined,
      background: AppTokens.amber50,
      border: AppTokens.amber100,
      foreground: AppTokens.amber700,
    ),
    BankingConnectionStatus.rateLimited => const _StatusPresentation(
      label: 'Aguardando nova tentativa',
      icon: Icons.hourglass_bottom_rounded,
      background: AppTokens.amber50,
      border: AppTokens.amber100,
      foreground: AppTokens.amber700,
    ),
    BankingConnectionStatus.disconnected => const _StatusPresentation(
      label: 'Desconectada',
      icon: Icons.link_off_rounded,
      background: AppTokens.neutral50,
      border: AppTokens.neutral200,
      foreground: AppTokens.neutral700,
    ),
    BankingConnectionStatus.failed => const _StatusPresentation(
      label: 'Falha registrada',
      icon: Icons.error_outline_rounded,
      background: AppTokens.red50,
      border: AppTokens.red100,
      foreground: AppTokens.red700,
    ),
  };
}

_FailurePresentation _failurePresentation(BankingConnectionsPhase phase) {
  return switch (phase) {
    BankingConnectionsPhase.authenticationRequired => const _FailurePresentation(
      title: 'Sessão necessária',
      message:
          'Sua sessão expirou ou foi encerrada. Entre novamente para ver as conexões locais.',
      retryable: false,
    ),
    BankingConnectionsPhase.forbidden => const _FailurePresentation(
      title: 'Acesso não autorizado',
      message:
          'Sua sessão não possui autorização para consultar estas conexões.',
      retryable: false,
    ),
    BankingConnectionsPhase.primaryResidenceRequired =>
      const _FailurePresentation(
        title: 'Residência principal necessária',
        message:
            'Defina uma residência principal antes de consultar as conexões bancárias.',
        retryable: false,
      ),
    BankingConnectionsPhase.invalidResponse => const _FailurePresentation(
      title: 'Resposta incompatível',
      message: 'A lista recebida não pôde ser validada com segurança.',
    ),
    _ => const _FailurePresentation(
      title: 'Lista temporariamente indisponível',
      message:
          'Não foi possível consultar as conexões locais agora. Nenhuma tentativa automática será feita.',
    ),
  };
}

String _providerLabel(String provider) {
  if (provider == 'pluggy') {
    return 'Pluggy · Open Finance';
  }
  return provider.replaceAll('_', ' ');
}

String _formatTimestamp(DateTime? value) {
  if (value == null) {
    return 'Não registrado';
  }
  final utc = value.toUtc();
  String two(int number) => number.toString().padLeft(2, '0');
  return '${two(utc.day)}/${two(utc.month)}/${utc.year} '
      '${two(utc.hour)}:${two(utc.minute)} UTC';
}

class _StatusPresentation {
  const _StatusPresentation({
    required this.label,
    required this.icon,
    required this.background,
    required this.border,
    required this.foreground,
  });

  final String label;
  final IconData icon;
  final Color background;
  final Color border;
  final Color foreground;
}

class _FailurePresentation {
  const _FailurePresentation({
    required this.title,
    required this.message,
    this.retryable = true,
  });

  final String title;
  final String message;
  final bool retryable;
}
