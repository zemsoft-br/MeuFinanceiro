import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/components/app_badge.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({required this.availability, super.key});

  final ApiAvailability? availability;

  static const titleKey = Key('home-title');

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Hero(availability: availability),
          const SizedBox(height: AppTokens.space40),
          const _FeatureSection(),
          const SizedBox(height: AppTokens.space40),
          const _PrinciplesSection(),
        ],
      ),
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.availability});

  final ApiAvailability? availability;

  @override
  Widget build(BuildContext context) {
    final status = switch (availability) {
      null => (label: 'Verificando', tone: AppBadgeTone.neutral),
      ApiAvailability.operational => (
        label: 'Operacional',
        tone: AppBadgeTone.positive,
      ),
      ApiAvailability.degraded => (
        label: 'Atenção',
        tone: AppBadgeTone.warning,
      ),
      ApiAvailability.unavailable => (
        label: 'Indisponível',
        tone: AppBadgeTone.negative,
      ),
    };

    return LayoutBuilder(
      builder: (context, constraints) {
        final stacked = constraints.maxWidth < 760;
        final content = _HeroContent();
        final summary = _FoundationSummary(
          label: status.label,
          tone: status.tone,
          apiAvailable: availability == ApiAvailability.operational,
        );

        return Card(
          clipBehavior: Clip.antiAlias,
          child: Padding(
            padding: EdgeInsets.all(
              stacked ? AppTokens.space24 : AppTokens.space40,
            ),
            child: stacked
                ? Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      content,
                      const SizedBox(height: AppTokens.space32),
                      summary,
                    ],
                  )
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(flex: 6, child: content),
                      const SizedBox(width: AppTokens.space40),
                      Expanded(flex: 4, child: summary),
                    ],
                  ),
          ),
        );
      },
    );
  }
}

class _HeroContent extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const AppBadge(
          label: 'Ambiente de demonstração',
          tone: AppBadgeTone.info,
        ),
        const SizedBox(height: AppTokens.space20),
        Semantics(
          header: true,
          child: Text(
            'A base para organizar as finanças da sua residência.',
            key: HomeScreen.titleKey,
            style: Theme.of(context).textTheme.displaySmall,
          ),
        ),
        const SizedBox(height: AppTokens.space16),
        Text(
          'Esta versão apresenta a navegação, os padrões de interface e '
          'o diagnóstico do MeuFinanceiro. Nenhum dado financeiro real é '
          'solicitado ou armazenado nesta fase.',
          style: Theme.of(
            context,
          ).textTheme.bodyLarge?.copyWith(color: AppTokens.neutral700),
        ),
        const SizedBox(height: AppTokens.space24),
        Wrap(
          spacing: AppTokens.space12,
          runSpacing: AppTokens.space12,
          children: [
            FilledButton(
              onPressed: () => context.goNamed(AppRoutes.components),
              child: const Text('Explorar componentes'),
            ),
            OutlinedButton(
              onPressed: () => context.goNamed(AppRoutes.system),
              child: const Text('Ver estado do sistema'),
            ),
          ],
        ),
      ],
    );
  }
}

class _FoundationSummary extends StatelessWidget {
  const _FoundationSummary({
    required this.label,
    required this.tone,
    required this.apiAvailable,
  });

  final String label;
  final AppBadgeTone tone;
  final bool apiAvailable;

  @override
  Widget build(BuildContext context) {
    const items = [
      'Shell responsivo',
      'Design system inicial',
      'Rotas e deep links',
      'API e PostgreSQL',
    ];

    return DecoratedBox(
      decoration: BoxDecoration(
        color: AppTokens.forest50,
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
        border: Border.all(color: AppTokens.forest100),
      ),
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Fundação técnica',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                AppBadge(label: label, tone: tone),
              ],
            ),
            const SizedBox(height: AppTokens.space20),
            ...items.indexed.map((entry) {
              final isApi = entry.$1 == items.length - 1;
              final available = !isApi || apiAvailable;
              return Padding(
                padding: const EdgeInsets.only(bottom: AppTokens.space12),
                child: Row(
                  children: [
                    Icon(
                      available
                          ? Icons.check_circle_rounded
                          : Icons.remove_circle_outline,
                      size: 20,
                      color: available
                          ? AppTokens.forest700
                          : AppTokens.neutral600,
                      semanticLabel: available ? 'Disponível' : 'Pendente',
                    ),
                    const SizedBox(width: AppTokens.space12),
                    Expanded(child: Text(entry.$2)),
                  ],
                ),
              );
            }),
            const Divider(height: AppTokens.space32),
            const Row(
              children: [
                Icon(
                  Icons.shield_outlined,
                  color: AppTokens.forest700,
                  semanticLabel: 'Privacidade',
                ),
                SizedBox(width: AppTokens.space12),
                Expanded(child: Text('Dados sob controle de quem hospeda.')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _FeatureSection extends StatelessWidget {
  const _FeatureSection();

  static const _features = [
    (
      icon: Icons.account_balance_wallet_outlined,
      title: 'Livro financeiro',
      description: 'Contas, lançamentos e conciliação com rastreabilidade.',
      label: 'Próxima fase',
    ),
    (
      icon: Icons.pie_chart_outline_rounded,
      title: 'Orçamentos',
      description: 'Planejamento mensal configurável para a residência.',
      label: 'Planejado',
    ),
    (
      icon: Icons.credit_card_outlined,
      title: 'Cartões e faturas',
      description: 'Compras, parcelas, fechamento e pagamento sem duplicidade.',
      label: 'Planejado',
    ),
    (
      icon: Icons.flag_outlined,
      title: 'Patrimônio e metas',
      description: 'Visão consolidada e projeções de longo prazo.',
      label: 'Planejado',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionHeading(
          eyebrow: 'Estrutura preparada',
          title: 'Módulos previstos',
          description:
              'Estes cartões documentam direção de produto; ainda não '
              'representam funcionalidades ativas.',
        ),
        const SizedBox(height: AppTokens.space20),
        LayoutBuilder(
          builder: (context, constraints) {
            final columns = constraints.maxWidth >= 1000
                ? 4
                : constraints.maxWidth >= 620
                ? 2
                : 1;
            final width =
                (constraints.maxWidth - (columns - 1) * AppTokens.space16) /
                columns;

            return Wrap(
              spacing: AppTokens.space16,
              runSpacing: AppTokens.space16,
              children: _features.map((feature) {
                return SizedBox(
                  width: width,
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(AppTokens.space24),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Icon(
                            feature.icon,
                            color: AppTokens.forest700,
                            size: 30,
                          ),
                          const SizedBox(height: AppTokens.space20),
                          AppBadge(label: feature.label),
                          const SizedBox(height: AppTokens.space16),
                          Text(
                            feature.title,
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          const SizedBox(height: AppTokens.space8),
                          Text(
                            feature.description,
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(color: AppTokens.neutral700),
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              }).toList(),
            );
          },
        ),
      ],
    );
  }
}

class _PrinciplesSection extends StatelessWidget {
  const _PrinciplesSection();

  static const _principles = [
    (
      title: 'Autohospedado',
      description:
          'Execução local por Docker, sem dependência obrigatória de nuvem.',
    ),
    (
      title: 'Brasil primeiro',
      description:
          'Moeda, calendário e fluxos pensados para pessoa física no Brasil.',
    ),
    (
      title: 'Privacidade padrão',
      description:
          'Telemetria desativada e nenhuma resposta financeira em '
          'cache offline.',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Card(
      color: AppTokens.forest900,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space32),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Princípios do produto',
              style: Theme.of(
                context,
              ).textTheme.labelLarge?.copyWith(color: AppTokens.amber100),
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              'Simples para usar, rigoroso com os dados.',
              style: Theme.of(
                context,
              ).textTheme.headlineMedium?.copyWith(color: AppTokens.white),
            ),
            const SizedBox(height: AppTokens.space24),
            LayoutBuilder(
              builder: (context, constraints) {
                final columns = constraints.maxWidth >= 900 ? 3 : 1;
                final width =
                    (constraints.maxWidth - (columns - 1) * AppTokens.space24) /
                    columns;

                return Wrap(
                  spacing: AppTokens.space24,
                  runSpacing: AppTokens.space24,
                  children: _principles.map((principle) {
                    return SizedBox(
                      width: width,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            principle.title,
                            style: Theme.of(context).textTheme.titleMedium
                                ?.copyWith(color: AppTokens.white),
                          ),
                          const SizedBox(height: AppTokens.space8),
                          Text(
                            principle.description,
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(color: AppTokens.forest100),
                          ),
                        ],
                      ),
                    );
                  }).toList(),
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionHeading extends StatelessWidget {
  const _SectionHeading({
    required this.eyebrow,
    required this.title,
    required this.description,
  });

  final String eyebrow;
  final String title;
  final String description;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final heading = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              eyebrow,
              style: Theme.of(
                context,
              ).textTheme.labelLarge?.copyWith(color: AppTokens.forest700),
            ),
            const SizedBox(height: AppTokens.space4),
            Semantics(
              header: true,
              child: Text(
                title,
                style: Theme.of(context).textTheme.headlineMedium,
              ),
            ),
          ],
        );
        final details = Text(
          description,
          style: Theme.of(
            context,
          ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
        );

        if (constraints.maxWidth < 900) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              heading,
              const SizedBox(height: AppTokens.space12),
              details,
            ],
          );
        }

        return Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(flex: 5, child: heading),
            const SizedBox(width: AppTokens.space24),
            Expanded(flex: 4, child: details),
          ],
        );
      },
    );
  }
}
