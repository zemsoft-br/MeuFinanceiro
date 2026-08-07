import 'package:flutter/material.dart';

enum AppRouteId { home, components, system }

class AppDestination {
  const AppDestination({
    required this.id,
    required this.routeName,
    required this.path,
    required this.label,
    required this.shortLabel,
    required this.description,
    required this.icon,
    required this.selectedIcon,
  });

  final AppRouteId id;
  final String routeName;
  final String path;
  final String label;
  final String shortLabel;
  final String description;
  final IconData icon;
  final IconData selectedIcon;
}

abstract final class AppRoutes {
  static const login = 'login';
  static const loginPath = '/login';
  static const home = 'home';
  static const components = 'components';
  static const system = 'system';

  static const destinations = <AppDestination>[
    AppDestination(
      id: AppRouteId.home,
      routeName: home,
      path: '/',
      label: 'Início',
      shortLabel: 'Início',
      description: 'Visão geral da fundação do MeuFinanceiro',
      icon: Icons.home_outlined,
      selectedIcon: Icons.home_rounded,
    ),
    AppDestination(
      id: AppRouteId.components,
      routeName: components,
      path: '/componentes',
      label: 'Componentes',
      shortLabel: 'Componentes',
      description: 'Catálogo de componentes e estados comuns',
      icon: Icons.widgets_outlined,
      selectedIcon: Icons.widgets_rounded,
    ),
    AppDestination(
      id: AppRouteId.system,
      routeName: system,
      path: '/sistema',
      label: 'Sistema',
      shortLabel: 'Sistema',
      description: 'Estado da API e políticas operacionais',
      icon: Icons.monitor_heart_outlined,
      selectedIcon: Icons.monitor_heart_rounded,
    ),
  ];

  static AppDestination? destinationForLocation(String location) {
    final path = Uri.tryParse(location)?.path ?? location;
    for (final destination in destinations) {
      if (destination.path == path) {
        return destination;
      }
    }
    return null;
  }
}
