import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/demo/demo_status.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

part 'shell_navigation.dart';
part 'shell_status.dart';

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
  static const mobileDrawerBrandKey = Key('mobile-drawer-brand');
  static const mobileNavigationKey = Key('mobile-navigation');
  static const demoNoticeKey = Key('demo-notice');
  static const mainContentKey = Key('main-content');

  @override
  ConsumerState<AppShell> createState() => _AppShellState();
}

class _AppShellState extends ConsumerState<AppShell> {
  final _scaffoldStateKey = GlobalKey<ScaffoldState>();
  final _menuButtonFocusNode = FocusNode(debugLabel: 'mobile-menu-button');
  final _mainContentFocusNode = FocusNode(debugLabel: 'main-content');
  bool _restoreMenuFocusAfterDrawerClose = true;

  @override
  void dispose() {
    _menuButtonFocusNode.dispose();
    _mainContentFocusNode.dispose();
    super.dispose();
  }

  void _openDrawer() {
    _scaffoldStateKey.currentState?.openDrawer();
  }

  void _closeDrawer({bool restoreMenuFocus = true}) {
    _restoreMenuFocusAfterDrawerClose = restoreMenuFocus;
    if (_scaffoldStateKey.currentState?.isDrawerOpen ?? false) {
      Navigator.of(context).maybePop();
    }
  }

  void _focusMainContent() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _mainContentFocusNode.requestFocus();
      }
    });
  }

  void _handleEscape() {
    if (_scaffoldStateKey.currentState?.isDrawerOpen ?? false) {
      _closeDrawer();
    }
  }

  void _navigate(AppDestination destination) {
    final drawerOpen = _scaffoldStateKey.currentState?.isDrawerOpen ?? false;
    if (drawerOpen) {
      _closeDrawer(restoreMenuFocus: false);
    }
    context.goNamed(destination.routeName);
    if (!drawerOpen) {
      _focusMainContent();
    }
  }

  @override
  Widget build(BuildContext context) {
    final health = ref.watch(apiHealthProvider);
    final demoStatus = ref.watch(demoStatusProvider);
    final selectedDestination = AppRoutes.destinationForLocation(
      widget.currentLocation,
    );
    final selectedIndex = selectedDestination == null
        ? null
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
                  if (open || desktop) {
                    return;
                  }
                  final focusNode = _restoreMenuFocusAfterDrawerClose
                      ? _menuButtonFocusNode
                      : _mainContentFocusNode;
                  _restoreMenuFocusAfterDrawerClose = true;
                  WidgetsBinding.instance.addPostFrameCallback((_) {
                    if (mounted) {
                      focusNode.requestFocus();
                    }
                  });
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
                bottomNavigationBar: desktop || selectedIndex == null
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
                              onNavigateHome: () =>
                                  _navigate(AppRoutes.destinations.first),
                              onOpenMenu: _openDrawer,
                            ),
                            _DemoNotice(status: demoStatus),
                            _ApiNotice(
                              health: health,
                              onRefresh: () =>
                                  ref.invalidate(apiHealthProvider),
                            ),
                            Expanded(
                              child: Focus(
                                key: AppShell.mainContentKey,
                                focusNode: _mainContentFocusNode,
                                child: Semantics(
                                  container: true,
                                  label: 'Conteúdo principal',
                                  child: SingleChildScrollView(
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
