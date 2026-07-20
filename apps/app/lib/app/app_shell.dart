import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class AppShell extends ConsumerStatefulWidget {
  const AppShell({
    required this.currentLocation,
    required this.child,
    super.key,
  });

  final String currentLocation;
  final Widget child;

  static const desktopSidebarKey = Key('desktop-sidebar');
  static const mobileMenuButtonKey = Key('mobile-menu-button');
  static const mobileDrawerKey = Key('mobile-drawer');
  static const mobileNavigationKey = Key('mobile-navigation');
  static const mainContentKey = Key('main-content');

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  final _scaffoldStateKey = GlobalKey<ScaffoldState>();
  final _menuButtonFocusNode = FocusNode(debugLabel: 'mobile-menu-button');

  @override
  void dispose() {
    _menuButtonFocusNode.dispose();
    super.dispose();
  }

  void _openDrawer() {
    _scaffoldStateKey.currentState?.openDrawer();
  }

  void _closeDrawer({bool restoreFocus = true}) {
    final scaffoldState = _scaffoldStateKey.currentState;
    if (scaffoldState?.isDrawerOpen ?? false) {
      Navigator.of(context).maybePop();
    }
    if (restoreFocus) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _menuButtonFocusNode.requestFocus();
        }
      });
    }
  }

  void _handleEscape() {
    if (_scaffoldStateKey.currentState?.isDrawerOpen ?? false) {
      _closeDrawer();
    }
  }

  void _navigate(AppDestination destination) {
    context.goNamed(destination.routeName);
    if (_scaffoldStateKey.currentState?.isDrawerOpen ?? false) {
      _closeDrawer();
    }
  }

  @override
  Widget build(BuildContext context) {
    final health = ref.watch(apiHealthProvider);
    final selectedDestination =
        AppRoutes.destinationForLocation(widget.currentLocation);
    final selectedIndex = selectedDestination == null
        ? 0
        : AppRoutes.destinations.indexOf(selectedDestination);

    return LayoutBuilder(
      builder: (context, constraints) {
        final desktop = constraints.maxWidth >= AppTokens.desktopBreakpoint;

        return Shortcuts(
          shortcuts: const {
            SingleActivator(LogicalKeyboardKey.escape): _CloseOverlayIntent(),
          },
          child: Actions(
            actions: {
              _CloseOverlayIntent: CallbackAction<_CloseOverlayIntent>(
                onInvoke: (_) {
                  _handleEscape();
                  return null;
                },
              ),
            },
            child: Focus(
              autofocus: true,
              child: Scaffold(
                key: _scaffoldStateKey,
                drawerEnableOpenDragGesture: !desktop,
                onDrawerChanged: (open) {
                  if (!open && !desktop) {
                    WidgetsBinding.instance.addPostFrameCallback((_) {
                      if (mounted) {
                        _menuButtonFocusNode.requestFocus();
                      }
                    });
                  }
                },
                drawer: desktop
                    ? null
                    : Drawer(
                        key: AppShell.mobileDrawerKey,
                        width: 300,
                        child: SafeArea(
                          child: _MobileDrawer(
                            currentLocation: widget.currentLocation,
                            onNavigate: _navigate,
                            onClose: _closeDrawer,
                          ),
                        ),
                      ),
                bottomNavigationBar: desktop
                    ? null
                    : NavigationBar(
                        key: AppShell.mobileNavigationKey,
                        selectedIndex: selectedIndex,
                        onDestinationSelected: (index) {
                          _navigate(AppRoutes.destinations[index]);
                        },
                        destinations: AppRoutes.destinations.map((destination) {
                          return NavigationDestination(
                            icon: Icon(destination.icon),
                            selectedIcon: Icon(destination.selectedIcon),
                            label: destination.shortLabel,
                            tooltip: destination.description,
                          );
                        }).toList(),
                      ),
                body: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (desktop)
                      SizedBox(
                        key: AppShell.desktopSidebarKey,
                        width: AppTokens.sidebarWidth,
                        child: _DesktopSidebar(
                          currentLocation: widget.currentLocation,
                          onNavigate: _navigate,
                        ),
                      ),
                    Expanded(
                      child: SafeArea(
                        left: desktop,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            _TopBar(
                              desktop: desktop,
                              health: health,
                              menuButtonFocusNode: _menuButtonFocusNode,
                              onOpenMenu: _openDrawer,
                            ),
                            _ApiNotice(
                              health: health,
                              onRefresh: () =>
                                  ref.invalidate(apiHealthProvider),
                            ),
                            Expanded(
                              child: SingleChildScrollView(
                                key: AppShell.mainContentKey,
                                padding: EdgeInsets.fromLTRB(
                                  desktop
                                      ? AppTokens.space32
                                      : AppTokens.space16,
                                  AppTokens.space24,
                                  desktop
                                      ? AppTokens.space32
                                      : AppTokens.space16,
                                  desktop
                                      ? AppTokens.space32
                                      : AppTokens.space24,
                                ),
                                child: Align(
                                  alignment: Alignment.topCenter,
                                  child: ConstrainedBox(
                                    constraints: const BoxConstraints(
                                      maxWidth: AppTokens.contentMaxWidth,
                                    ),
                                    child: widget.child,
                                  ),
                                ),
                              ),
                            ),
                            const _AppFooter(),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

class _CloseOverlayIntent extends Intent {
  const _CloseOverlayIntent();
}

class _Brand extends StatelessWidget {
  const _Brand({this.compact = false});

  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: 'MeuFinanceiro — página inicial',
      button: true,
      child: InkWell(
        borderRadius: BorderRadius.circular(AppTokens.radiusSmall),
        onTap: () => context.goNamed(AppRoutes.home),
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
        border: Border(
          right: BorderSide(color: AppTokens.neutral200),
        ),
      ),
      child: SafeArea(
        right: false,
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.space16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const _Brand(),
              const SizedBox(height: AppTokens.space24),
              Semantics(
                label: 'Navegação principal',
                container: true,
                child: Column(
                  children: AppRoutes.destinations.map((destination) {
                    return Padding(
                      padding:
                          const EdgeInsets.only(bottom: AppTokens.space8),
                      child: _NavigationTile(
                        destination: destination,
                        selected: AppRoutes.destinationForLocation(
                              currentLocation,
                            ) ==
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
                const Expanded(child: _Brand()),
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
                      selected: AppRoutes.destinationForLocation(
                            currentLocation,
                          ) ==
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
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: AppTokens.neutral600,
                    ),
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
