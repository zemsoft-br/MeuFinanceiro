part of 'app_shell.dart';

class _Brand extends StatelessWidget {
  const _Brand({required this.onTap, this.compact = false, super.key});

  final VoidCallback onTap;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'MeuFinanceiro — página inicial',
      button: true,
      child: InkWell(
        borderRadius: BorderRadius.circular(AppTokens.radiusSmall),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: AppTokens.space8,
            vertical: AppTokens.space8,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const ExcludeSemantics(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    color: AppTokens.forest900,
                    borderRadius: BorderRadius.all(
                      Radius.circular(AppTokens.radiusSmall),
                    ),
                  ),
                  child: SizedBox(
                    width: 42,
                    height: 42,
                    child: Center(
                      child: Text(
                        'MF',
                        style: TextStyle(
                          color: AppTokens.white,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              if (!compact) ...[
                const SizedBox(width: AppTokens.space12),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'MeuFinanceiro',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    Text(
                      'Cliente Flutter',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppTokens.neutral600,
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _DesktopSidebar extends StatelessWidget {
  const _DesktopSidebar({
    required this.currentLocation,
    required this.onNavigate,
  });

  final String currentLocation;
  final ValueChanged<AppDestination> onNavigate;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: const BoxDecoration(
        color: AppTokens.white,
        border: Border(right: BorderSide(color: AppTokens.neutral200)),
      ),
      child: SafeArea(
        right: false,
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.space16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _Brand(
                onTap: () => onNavigate(AppRoutes.destinations.first),
              ),
              const SizedBox(height: AppTokens.space24),
              Semantics(
                label: 'Navegação principal',
                container: true,
                child: Column(
                  children: AppRoutes.destinations.map((destination) {
                    return Padding(
                      padding: const EdgeInsets.only(bottom: AppTokens.space8),
                      child: _NavigationTile(
                        destination: destination,
                        selected:
                            AppRoutes.destinationForLocation(currentLocation) ==
                            destination,
                        onTap: () => onNavigate(destination),
                      ),
                    );
                  }).toList(),
                ),
              ),
              const Spacer(),
              const Divider(),
              Padding(
                padding: const EdgeInsets.all(AppTokens.space8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Projeto open-source',
                      style: Theme.of(context).textTheme.labelLarge,
                    ),
                    const SizedBox(height: AppTokens.space4),
                    Text(
                      'Não use dados reais nesta fase.',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppTokens.neutral600,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _MobileDrawer extends StatelessWidget {
  const _MobileDrawer({
    required this.currentLocation,
    required this.onNavigate,
    required this.onClose,
  });

  final String currentLocation;
  final ValueChanged<AppDestination> onNavigate;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    return FocusTraversalGroup(
      policy: ReadingOrderTraversalPolicy(),
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: _Brand(
                    key: AppShell.mobileDrawerBrandKey,
                    onTap: () => onNavigate(AppRoutes.destinations.first),
                  ),
                ),
                IconButton(
                  autofocus: true,
                  onPressed: onClose,
                  tooltip: 'Fechar menu',
                  icon: const Icon(Icons.close_rounded),
                ),
              ],
            ),
            const SizedBox(height: AppTokens.space24),
            Semantics(
              label: 'Navegação principal',
              container: true,
              child: Column(
                children: AppRoutes.destinations.map((destination) {
                  return Padding(
                    padding: const EdgeInsets.only(bottom: AppTokens.space8),
                    child: _NavigationTile(
                      destination: destination,
                      selected:
                          AppRoutes.destinationForLocation(currentLocation) ==
                          destination,
                      onTap: () => onNavigate(destination),
                    ),
                  );
                }).toList(),
              ),
            ),
            const Spacer(),
            const Divider(),
            Padding(
              padding: const EdgeInsets.all(AppTokens.space8),
              child: Text(
                'Shell Flutter em migração. O runtime React permanece ativo.',
                style: Theme.of(
                  context,
                ).textTheme.bodySmall?.copyWith(color: AppTokens.neutral600),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NavigationTile extends StatelessWidget {
  const _NavigationTile({
    required this.destination,
    required this.selected,
    required this.onTap,
  });

  final AppDestination destination;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      key: Key('navigation-${destination.routeName}'),
      selected: selected,
      button: true,
      label: destination.label,
      hint: destination.description,
      child: ListTile(
        selected: selected,
        selectedColor: AppTokens.forest900,
        selectedTileColor: AppTokens.forest100,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusSmall),
        ),
        leading: Icon(
          selected ? destination.selectedIcon : destination.icon,
          semanticLabel: destination.label,
        ),
        title: Text(destination.label),
        onTap: onTap,
      ),
    );
  }
}
