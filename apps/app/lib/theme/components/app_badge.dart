import 'package:flutter/material.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

enum AppBadgeTone { neutral, positive, warning, negative, info }

class AppBadge extends StatelessWidget {
  const AppBadge({
    required this.label,
    this.tone = AppBadgeTone.neutral,
    super.key,
  });

  final String label;
  final AppBadgeTone tone;

  @override
  Widget build(BuildContext context) {
    final colors = switch (tone) {
      AppBadgeTone.neutral => (
        background: AppTokens.neutral100,
        foreground: AppTokens.neutral700,
      ),
      AppBadgeTone.positive => (
        background: AppTokens.forest100,
        foreground: AppTokens.forest900,
      ),
      AppBadgeTone.warning => (
        background: AppTokens.amber100,
        foreground: AppTokens.amber700,
      ),
      AppBadgeTone.negative => (
        background: AppTokens.red100,
        foreground: AppTokens.red700,
      ),
      AppBadgeTone.info => (
        background: AppTokens.blue100,
        foreground: AppTokens.blue700,
      ),
    };

    return Semantics(
      label: label,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: colors.background,
          borderRadius: BorderRadius.circular(999),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          child: Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
              color: colors.foreground,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ),
    );
  }
}
