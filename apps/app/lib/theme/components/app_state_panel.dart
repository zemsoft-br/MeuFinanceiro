import 'package:flutter/material.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

enum AppStateKind { loading, empty, error, unavailable }

class AppStatePanel extends StatelessWidget {
  const AppStatePanel({
    required this.kind,
    required this.title,
    required this.description,
    this.compact = false,
    super.key,
  });

  final AppStateKind kind;
  final String title;
  final String description;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final presentation = switch (kind) {
      AppStateKind.loading => (
        icon: Icons.hourglass_top_rounded,
        color: AppTokens.blue700,
        semantics: 'Carregando',
      ),
      AppStateKind.empty => (
        icon: Icons.inbox_outlined,
        color: AppTokens.neutral700,
        semantics: 'Vazio',
      ),
      AppStateKind.error => (
        icon: Icons.error_outline_rounded,
        color: AppTokens.red700,
        semantics: 'Erro',
      ),
      AppStateKind.unavailable => (
        icon: Icons.cloud_off_outlined,
        color: AppTokens.amber700,
        semantics: 'Indisponível',
      ),
    };

    return Semantics(
      container: true,
      label: '${presentation.semantics}: $title. $description',
      liveRegion: kind == AppStateKind.loading || kind == AppStateKind.error,
      child: Card(
        child: Padding(
          padding: EdgeInsets.all(
            compact ? AppTokens.space20 : AppTokens.space32,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (kind == AppStateKind.loading)
                SizedBox(
                  width: 28,
                  height: 28,
                  child: CircularProgressIndicator(
                    value: 0.65,
                    strokeWidth: 3,
                    color: presentation.color,
                    semanticsLabel: 'Carregando',
                    semanticsValue: '65 por cento',
                  ),
                )
              else
                Icon(
                  presentation.icon,
                  color: presentation.color,
                  size: 30,
                  semanticLabel: presentation.semantics,
                ),
              const SizedBox(height: AppTokens.space16),
              Text(title, style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: AppTokens.space8),
              Text(
                description,
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
