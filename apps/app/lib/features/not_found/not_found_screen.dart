import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/components/app_state_panel.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class NotFoundScreen extends StatelessWidget {
  const NotFoundScreen({required this.location, super.key});

  final String location;

  static const titleKey = Key('not-found-title');

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 640),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const AppStatePanel(
              kind: AppStateKind.error,
              title: 'Página não encontrada',
              description:
                  'O endereço informado não corresponde a uma rota disponível.',
            ),
            const SizedBox(height: AppTokens.space20),
            Semantics(
              label: 'Endereço não encontrado: $location',
              child: Text(
                location,
                key: titleKey,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: AppTokens.neutral700,
                    ),
              ),
            ),
            const SizedBox(height: AppTokens.space20),
            FilledButton(
              onPressed: () => context.goNamed(AppRoutes.home),
              child: const Text('Voltar ao início'),
            ),
          ],
        ),
      ),
    );
  }
}
