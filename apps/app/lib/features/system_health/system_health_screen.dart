import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/health/api_health.dart';
import 'package:meufinanceiro_app/theme/components/app_badge.dart';
import 'package:meufinanceiro_app/theme/components/app_state_panel.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class SystemHealthScreen extends ConsumerWidget {
  const SystemHealthScreen({super.key});

  static const titleKey = Key('system-title');
  static const refreshKey = Key('health-refresh');

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(apiHealthProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _PageHeader(),
        const SizedBox(height: AppTokens.space32),
        LayoutBuilder(
          builder: (context, constraints) {
            final stacked = constraints.maxWidth < 760;
            final cards = [
              Expanded(
                child: _HealthCard(
                  health: health,
                  onRefresh: () => ref.invalidate(apiHealthProvider),
                ),
              ),
              const Expanded(child: _InstallCard()),
            ];

            if (stacked) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _HealthCard(
                    health: health,
                    onRefresh: () => ref.invalidate(apiHealthProvider),
                  ),
                  const SizedBox(height: AppTokens.space16),
                  const _InstallCard(),
                ],
              );
            }

            return IntrinsicHeight(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  cards[0],
                  const SizedBox(width: AppTokens.space16),
                  cards[1],
                ],
              ),
            );
          },
        ),
        const SizedBox(height: AppTokens.space24),
        const _CachePolicyCard(),
      ],
    );
  }
}

class _PageHeader extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 760),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Diagnóstico local',
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: AppTokens.forest700,
                ),
          ),
          const SizedBox(height: AppTokens.space4),
          Semantics(
            header: true,
            child: Text(
              'Estado do sistema e instalação',
              key: SystemHealthScreen.titleKey,
              style: Theme.of(context).textTheme.headlineLarge,
            ),
          ),
          const SizedBox(height: AppTokens.space12),
          Text(
            'Acompanhe a disponibilidade dos serviços. A instalação e a '
            'política PWA final serão validadas na fase de troca do runtime.',
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: AppTokens.neutral700,
                ),
          ),
        ],
      ),
    );
  }
}

class _HealthCard extends StatelessWidget {
  const _HealthCard({
    required this.health,
    required this.onRefresh,
  });

  final AsyncValue<ApiHealthSnapshot> health;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final snapshot = health.value;
    final presentation = _presentation(health);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(
                  Icons.monitor_heart_outlined,
                  size: 30,
                  color: AppTokens.forest700,
                  semanticLabel: 'Diagnóstico da API',
                ),
                const Spacer(),
                AppBadge(
                  label: presentation.label,
                  tone: presentation.tone,
                ),
              ],
            ),
            const SizedBox(height: AppTokens.space20),
            Semantics(
              header: true,
              child: Text(
                'API e persistência',
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            const SizedBox(height: AppTokens.space16),
            if (health.isLoading)
              const AppStatePanel(
                kind: AppStateKind.loading,
                title: 'Verificando o ambiente',
                description:
                    'A disponibilidade da API está sendo consultada.',
                compact: true,
              )
            else
              _HealthDetails(snapshot: snapshot),
            const SizedBox(height: AppTokens.space20),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                key: SystemHealthScreen.refreshKey,
                onPressed: health.isLoading ? null : onRefresh,
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('Atualizar estado'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  static ({String label, AppBadgeTone tone}) _presentation(
    AsyncValue<ApiHealthSnapshot> health,
  ) {
    if (health.isLoading) {
      return (label: 'Verificando', tone: AppBadgeTone.neutral);
    }

    return switch (health.value?.availability) {
      ApiAvailability.operational => (
          label: 'Operacional',
          tone: AppBadgeTone.positive,
        ),
      ApiAvailability.degraded => (
          label: 'Atenção',
          tone: AppBadgeTone.warning,
        ),
      ApiAvailability.unavailable || null => (
          label: 'Indisponível',
          tone: AppBadgeTone.negative,
        ),
    };
  }
}

class _HealthDetails extends StatelessWidget {
  const _HealthDetails({required this.snapshot});

  final ApiHealthSnapshot? snapshot;

  @override
  Widget build(BuildContext context) {
    final readiness = snapshot?.readiness;
    final rows = [
      ('Processo', readiness?.process ?? 'não verificado'),
      ('Banco', readiness?.database ?? 'não verificado'),
      ('Schema', readiness?.schema ?? 'não verificado'),
      (
        'Última verificação',
        snapshot == null ? '—' : _formatTime(snapshot!.checkedAt),
      ),
    ];

    return Semantics(
      container: true,
      label: rows.map((row) => '${row.$1}: ${row.$2}').join('. '),
      child: Column(
        children: rows.map((row) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: AppTokens.space8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    row.$1,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: AppTokens.neutral700,
                        ),
                  ),
                ),
                const SizedBox(width: AppTokens.space16),
                Flexible(
                  child: Text(
                    row.$2,
                    textAlign: TextAlign.end,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  static String _formatTime(DateTime value) {
    String twoDigits(int number) => number.toString().padLeft(2, '0');
    return '${twoDigits(value.hour)}:${twoDigits(value.minute)}:'
        '${twoDigits(value.second)}';
  }
}

class _InstallCard extends StatelessWidget {
  const _InstallCard();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                Icon(
                  Icons.install_desktop_outlined,
                  size: 30,
                  color: AppTokens.forest700,
                  semanticLabel: 'Instalação',
                ),
                Spacer(),
                AppBadge(
                  label: 'Fase C',
                  tone: AppBadgeTone.info,
                ),
              ],
            ),
            const SizedBox(height: AppTokens.space20),
            Semantics(
              header: true,
              child: Text(
                'Instalar MeuFinanceiro',
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            const SizedBox(height: AppTokens.space12),
            Text(
              'O build Flutter já compila para Web. Manifesto, service worker, '
              'headers e fluxo de instalação serão auditados junto da troca '
              'controlada do runtime.',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: AppTokens.neutral700,
                  ),
            ),
            const SizedBox(height: AppTokens.space20),
            const AppStatePanel(
              kind: AppStateKind.unavailable,
              title: 'Instalação ainda não habilitada',
              description:
                  'Use o shell React ativo até a conclusão da Fase C.',
              compact: true,
            ),
          ],
        ),
      ),
    );
  }
}

class _CachePolicyCard extends StatelessWidget {
  const _CachePolicyCard();

  @override
  Widget build(BuildContext context) {
    return Card(
      color: AppTokens.forest50,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(
              Icons.shield_outlined,
              color: AppTokens.forest700,
              size: 30,
              semanticLabel: 'Política de cache',
            ),
            const SizedBox(width: AppTokens.space16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Política offline preservada',
                    style: Theme.of(context).textTheme.labelLarge?.copyWith(
                          color: AppTokens.forest700,
                        ),
                  ),
                  const SizedBox(height: AppTokens.space4),
                  Semantics(
                    header: true,
                    child: Text(
                      'Respostas da API não pertencem ao cache do shell.',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  const SizedBox(height: AppTokens.space8),
                  Text(
                    'Tokens, respostas de saúde e futuros dados financeiros '
                    'permanecem fora da política de cache. A implementação '
                    'produtiva será auditada na Fase C.',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: AppTokens.neutral700,
                        ),
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
