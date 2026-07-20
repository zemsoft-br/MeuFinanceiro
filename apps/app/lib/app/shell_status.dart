part of 'app_shell.dart';

class _TopBar extends StatelessWidget {
  const _TopBar({
    required this.desktop,
    required this.health,
    required this.menuButtonFocusNode,
    required this.onOpenMenu,
  });

  final bool desktop;
  final AsyncValue<ApiHealthSnapshot> health;
  final FocusNode menuButtonFocusNode;
  final VoidCallback onOpenMenu;

  @override
  Widget build(BuildContext context) {
    final presentation = _HealthPresentation.fromAsync(health);

    return DecoratedBox(
      decoration: const BoxDecoration(
        color: AppTokens.white,
        border: Border(
          bottom: BorderSide(color: AppTokens.neutral200),
        ),
      ),
      child: Padding(
        padding: EdgeInsets.symmetric(
          horizontal: desktop ? AppTokens.space32 : AppTokens.space12,
          vertical: AppTokens.space8,
        ),
        child: Row(
          children: [
            if (!desktop)
              IconButton(
                key: AppShell.mobileMenuButtonKey,
                focusNode: menuButtonFocusNode,
                onPressed: onOpenMenu,
                tooltip: 'Abrir menu',
                icon: const Icon(Icons.menu_rounded),
              ),
            if (!desktop) const _Brand(compact: true),
            if (desktop)
              Text(
                'Fundação do cliente',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            const Spacer(),
            Semantics(
              label: 'API: ${presentation.label}',
              container: true,
              child: Row(
                children: [
                  Icon(
                    presentation.icon,
                    size: 18,
                    color: presentation.color,
                    semanticLabel: presentation.label,
                  ),
                  const SizedBox(width: AppTokens.space8),
                  const Text('API'),
                  const SizedBox(width: AppTokens.space8),
                  Text(
                    presentation.label,
                    style: Theme.of(context).textTheme.labelLarge,
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ApiNotice extends StatelessWidget {
  const _ApiNotice({
    required this.health,
    required this.onRefresh,
  });

  final AsyncValue<ApiHealthSnapshot> health;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final presentation = _HealthPresentation.fromAsync(health);

    if (presentation.availability == ApiAvailability.operational) {
      return const SizedBox.shrink();
    }

    if (health.isLoading) {
      return Semantics(
        liveRegion: true,
        label: 'Verificando a conexão com a API.',
        child: const LinearProgressIndicator(
          minHeight: 3,
          color: AppTokens.blue700,
          backgroundColor: AppTokens.blue100,
        ),
      );
    }

    final degraded =
        presentation.availability == ApiAvailability.degraded;

    return Semantics(
      container: true,
      liveRegion: true,
      label: degraded
          ? 'Serviço parcialmente disponível.'
          : 'API indisponível.',
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: degraded ? AppTokens.amber50 : AppTokens.red50,
          border: Border(
            bottom: BorderSide(
              color: degraded ? AppTokens.amber100 : AppTokens.red100,
            ),
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.space16,
            vertical: AppTokens.space12,
          ),
          child: Wrap(
            spacing: AppTokens.space16,
            runSpacing: AppTokens.space8,
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 760),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      degraded
                          ? 'Serviço parcialmente disponível'
                          : 'API indisponível',
                      style: Theme.of(context).textTheme.labelLarge,
                    ),
                    Text(
                      degraded
                          ? 'A interface continua acessível enquanto o '
                              'ambiente é verificado.'
                          : 'A navegação local continua disponível, mas '
                              'operações dependentes da API estão suspensas.',
                    ),
                  ],
                ),
              ),
              TextButton(
                onPressed: onRefresh,
                child: const Text('Tentar novamente'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AppFooter extends StatelessWidget {
  const _AppFooter();

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: AppTokens.white,
        border: Border(
          top: BorderSide(color: AppTokens.neutral200),
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppTokens.space16,
          vertical: AppTokens.space12,
        ),
        child: Wrap(
          spacing: AppTokens.space16,
          runSpacing: AppTokens.space8,
          alignment: WrapAlignment.spaceBetween,
          children: [
            Text(
              'MeuFinanceiro · Fundação do projeto',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: AppTokens.neutral600,
                  ),
            ),
            Text(
              'API: /api/v1/docs',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: AppTokens.neutral600,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}

class _HealthPresentation {
  const _HealthPresentation({
    required this.label,
    required this.icon,
    required this.color,
    required this.availability,
  });

  final String label;
  final IconData icon;
  final Color color;
  final ApiAvailability? availability;

  factory _HealthPresentation.fromAsync(
    AsyncValue<ApiHealthSnapshot> health,
  ) {
    if (health.isLoading) {
      return const _HealthPresentation(
        label: 'Verificando',
        icon: Icons.sync_rounded,
        color: AppTokens.blue700,
        availability: null,
      );
    }

    return switch (health.value?.availability) {
      ApiAvailability.operational => const _HealthPresentation(
          label: 'Operacional',
          icon: Icons.check_circle_rounded,
          color: AppTokens.forest700,
          availability: ApiAvailability.operational,
        ),
      ApiAvailability.degraded => const _HealthPresentation(
          label: 'Atenção',
          icon: Icons.warning_amber_rounded,
          color: AppTokens.amber700,
          availability: ApiAvailability.degraded,
        ),
      ApiAvailability.unavailable || null => const _HealthPresentation(
          label: 'Indisponível',
          icon: Icons.cloud_off_outlined,
          color: AppTokens.red700,
          availability: ApiAvailability.unavailable,
        ),
    };
  }
}
