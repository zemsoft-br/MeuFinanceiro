import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_cash_flow_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/components/app_badge.dart';
import 'package:meufinanceiro_app/theme/components/app_state_panel.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Cash flow #265. Read-only: every figure is the server's projection of the
/// canonical ledger and the recurrence model. Nothing on this screen creates a
/// Movement, an occurrence or any other write; it only reads and navigates.
class FinancialCashFlowScreen extends ConsumerStatefulWidget {
  const FinancialCashFlowScreen({super.key});

  static const titleKey = Key('financial-cash-flow-title');
  static const refreshKey = Key('financial-cash-flow-refresh');
  static const noticeKey = Key('financial-cash-flow-notice');
  static const loadingKey = Key('financial-cash-flow-loading');
  static const emptyKey = Key('financial-cash-flow-empty');
  static const errorKey = Key('financial-cash-flow-error');
  static const rejectedKey = Key('financial-cash-flow-rejected');
  static const staleKey = Key('financial-cash-flow-stale');
  static const statusKey = Key('financial-cash-flow-status');
  static const riskKey = Key('financial-cash-flow-risk');
  static const summaryKey = Key('financial-cash-flow-summary');
  static const comparisonKey = Key('financial-cash-flow-comparison');
  static const accountsKey = Key('financial-cash-flow-accounts');
  static const daysKey = Key('financial-cash-flow-days');
  static const eventsKey = Key('financial-cash-flow-events');
  static const allDaysKey = Key('financial-cash-flow-all-days');
  static const moreEventsKey = Key('financial-cash-flow-more-events');
  static const customPeriodKey = Key('financial-cash-flow-custom-period');
  static const allAccountsKey = Key('financial-cash-flow-all-accounts');
  static const eventDetailKey = Key('financial-cash-flow-event-detail');
  static Key periodKey(FinancialCashFlowPeriod period) =>
      Key('financial-cash-flow-period-${period.name}');
  static Key accountFilterKey(String id) =>
      Key('financial-cash-flow-account-filter-$id');
  static Key currencyKey(String currency) =>
      Key('financial-cash-flow-currency-$currency');
  static Key eventKey(int index) => Key('financial-cash-flow-event-$index');
  static Key issueKey(FinancialCashFlowIssueCode code) =>
      Key('financial-cash-flow-issue-${code.wireValue}');

  @override
  ConsumerState<FinancialCashFlowScreen> createState() =>
      _FinancialCashFlowScreenState();
}

class _FinancialCashFlowScreenState
    extends ConsumerState<FinancialCashFlowScreen> {
  static const _eventPage = 100;

  int _visibleEvents = _eventPage;
  bool _allDays = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        unawaited(
          ref.read(financialCashFlowControllerProvider.notifier).load(),
        );
      }
    });
  }

  void _resetPaging() {
    _visibleEvents = _eventPage;
  }

  Future<void> _pickCustomWindow(FinancialCashFlowState state) async {
    final referenceDate = state.referenceDate;
    if (referenceDate == null) return;
    final reference = DateTime.parse('${referenceDate}T00:00:00Z');
    final cashFlow = state.cashFlow;
    final range = await showDateRangePicker(
      context: context,
      firstDate: DateTime.utc(2000),
      lastDate: reference.add(
        const Duration(days: financialCashFlowWindowMaxDays - 1),
      ),
      initialDateRange: cashFlow == null
          ? null
          : DateTimeRange(
              start: DateTime.parse('${cashFlow.from}T00:00:00Z'),
              end: DateTime.parse('${cashFlow.through}T00:00:00Z'),
            ),
      helpText: 'Período do fluxo de caixa',
    );
    if (range == null || !mounted) return;
    setState(_resetPaging);
    final accepted = await ref
        .read(financialCashFlowControllerProvider.notifier)
        .selectCustomWindow(_isoDate(range.start), _isoDate(range.end));
    if (!accepted && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Período inválido: até 92 dias, começando no máximo na data de '
            'referência.',
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(financialCashFlowControllerProvider);
    final ctl = ref.read(financialCashFlowControllerProvider.notifier);
    final theme = Theme.of(context);
    final cashFlow = state.cashFlow;
    final group = state.group;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: AppTokens.space16,
          runSpacing: AppTokens.space12,
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Finanças · Planejamento',
                  style: theme.textTheme.labelLarge,
                ),
                Text(
                  'Fluxo de caixa',
                  key: FinancialCashFlowScreen.titleKey,
                  style: theme.textTheme.headlineLarge,
                ),
                if (cashFlow != null)
                  Text(
                    'Data de referência: ${_formatDate(cashFlow.referenceDate)} · '
                    'Período: ${_formatDate(cashFlow.from)} a '
                    '${_formatDate(cashFlow.through)} (${cashFlow.days} dias)',
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: AppTokens.neutral700,
                    ),
                  ),
              ],
            ),
            Wrap(
              spacing: AppTokens.space8,
              runSpacing: AppTokens.space8,
              children: [
                OutlinedButton.icon(
                  onPressed: () => context.go(AppRoutes.financePath),
                  icon: const Icon(Icons.arrow_back),
                  label: const Text('Contas'),
                ),
                OutlinedButton.icon(
                  onPressed: () => context.go(AppRoutes.financeRecurrencesPath),
                  icon: const Icon(Icons.event_repeat_rounded),
                  label: const Text('Recorrências'),
                ),
                FilledButton.icon(
                  key: FinancialCashFlowScreen.refreshKey,
                  onPressed: state.isBusy
                      ? null
                      : () {
                          setState(_resetPaging);
                          unawaited(ctl.refresh());
                        },
                  icon: state.phase == FinancialLoadPhase.refreshing
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.refresh_rounded),
                  label: const Text('Atualizar'),
                ),
              ],
            ),
          ],
        ),
        const SizedBox(height: AppTokens.space16),
        _Notice(excluded: cashFlow?.excludedSources ?? const []),
        const SizedBox(height: AppTokens.space12),
        _Filters(
          state: state,
          onPeriod: (period) {
            setState(_resetPaging);
            unawaited(ctl.selectPeriod(period));
          },
          onCustom: () => _pickCustomWindow(state),
          onAccount: (id) {
            setState(_resetPaging);
            unawaited(ctl.toggleAccount(id));
          },
          onAllAccounts: () {
            setState(_resetPaging);
            unawaited(ctl.clearAccounts());
          },
          onCurrency: (currency) {
            setState(_resetPaging);
            ctl.selectCurrency(currency);
          },
        ),
        const SizedBox(height: AppTokens.space16),
        if (state.failure == FinancialCashFlowFailure.staleAfterRefresh) ...[
          const Card(
            key: FinancialCashFlowScreen.staleKey,
            child: ListTile(
              leading: Icon(Icons.warning_amber_rounded),
              title: Text('Não foi possível atualizar'),
              subtitle: Text(
                'Os valores abaixo são da última leitura bem-sucedida e podem '
                'estar desatualizados. Tente atualizar novamente.',
              ),
            ),
          ),
          const SizedBox(height: AppTokens.space12),
        ],
        ..._body(context, state, group, ctl),
      ],
    );
  }

  List<Widget> _body(
    BuildContext context,
    FinancialCashFlowState state,
    FinancialCashFlowGroup? group,
    FinancialCashFlowController ctl,
  ) {
    if (state.failure == FinancialCashFlowFailure.rejected) {
      return const [
        AppStatePanel(
          key: FinancialCashFlowScreen.rejectedKey,
          kind: AppStateKind.error,
          title: 'Leitura recusada pelo servidor',
          description:
              'O período ou a seleção excede o limite de uma leitura (até 92 '
              'dias, 50 contas e 2000 eventos). Reduza o período ou selecione '
              'menos contas. Nada foi omitido em silêncio.',
        ),
      ];
    }
    switch (state.phase) {
      case FinancialLoadPhase.idle:
      case FinancialLoadPhase.loading:
        return const [
          AppStatePanel(
            key: FinancialCashFlowScreen.loadingKey,
            kind: AppStateKind.loading,
            title: 'Calculando o fluxo de caixa',
            description:
                'Lendo saldos, lançamentos e recorrências do servidor.',
          ),
        ];
      case FinancialLoadPhase.empty:
        return const [
          AppStatePanel(
            key: FinancialCashFlowScreen.emptyKey,
            kind: AppStateKind.empty,
            title: 'Nenhuma conta para projetar',
            description:
                'Não há contas ativas visíveis nesta seleção. Cadastre uma conta '
                'ou escolha outras contas no filtro.',
          ),
        ];
      case FinancialLoadPhase.loaded:
      case FinancialLoadPhase.refreshing:
        if (group == null) return const [];
        return [
          _GroupView(
            cashFlow: state.cashFlow!,
            group: group,
            allDays: _allDays,
            visibleEvents: _visibleEvents,
            onToggleDays: () => setState(() => _allDays = !_allDays),
            onMoreEvents: () => setState(() => _visibleEvents += _eventPage),
          ),
        ];
      case FinancialLoadPhase.authenticationRequired:
      case FinancialLoadPhase.forbidden:
      case FinancialLoadPhase.primaryResidenceRequired:
      case FinancialLoadPhase.notFound:
      case FinancialLoadPhase.conflict:
      case FinancialLoadPhase.temporarilyUnavailable:
      case FinancialLoadPhase.invalidResponse:
        final (title, description) = _failureText(state.phase);
        return [
          AppStatePanel(
            key: FinancialCashFlowScreen.errorKey,
            kind: state.phase == FinancialLoadPhase.temporarilyUnavailable
                ? AppStateKind.unavailable
                : AppStateKind.error,
            title: title,
            description: description,
          ),
          const SizedBox(height: AppTokens.space12),
          Wrap(
            spacing: AppTokens.space8,
            children: [
              OutlinedButton(
                onPressed: () => unawaited(ctl.refresh()),
                child: const Text('Tentar novamente'),
              ),
              if (state.phase == FinancialLoadPhase.notFound &&
                  state.selectedAccountIds.isNotEmpty)
                TextButton(
                  onPressed: () => unawaited(ctl.clearAccounts()),
                  child: const Text('Limpar seleção de contas'),
                ),
            ],
          ),
        ];
    }
  }
}

(String, String) _failureText(FinancialLoadPhase phase) => switch (phase) {
  FinancialLoadPhase.authenticationRequired => (
    'Sessão expirada',
    'Entre novamente para consultar o fluxo de caixa.',
  ),
  FinancialLoadPhase.forbidden => (
    'Acesso negado',
    'Sua participação nesta residência não permite consultar o fluxo de caixa.',
  ),
  FinancialLoadPhase.primaryResidenceRequired => (
    'Residência não definida',
    'Defina uma residência principal para consultar o fluxo de caixa.',
  ),
  FinancialLoadPhase.notFound => (
    'Conta indisponível',
    'Uma conta selecionada não existe ou não está mais visível para você.',
  ),
  FinancialLoadPhase.invalidResponse => (
    'Resposta inválida',
    'O servidor respondeu fora do contrato esperado. Nenhum valor foi exibido.',
  ),
  _ => (
    'Fluxo de caixa indisponível',
    'O serviço não respondeu. Verifique a conexão e tente novamente.',
  ),
};

class _Notice extends StatelessWidget {
  const _Notice({required this.excluded});
  final List<String> excluded;

  @override
  Widget build(BuildContext context) {
    final sources = excluded.map(_excludedLabel).join(', ');
    return Card(
      key: FinancialCashFlowScreen.noticeKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Somente leitura. O realizado vem dos lançamentos do livro; o '
              'previsto vem das recorrências (ocorrências geradas e meses ainda '
              'não gerados de regras ativas). Previsto não altera saldo nem '
              'extrato e nada nesta tela cria lançamentos. Transferências mudam '
              'o saldo de cada conta, mas não são receita nem despesa.',
            ),
            if (sources.isNotEmpty) ...[
              const SizedBox(height: AppTokens.space8),
              Text(
                'Não entram na projeção: $sources.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Filters extends StatelessWidget {
  const _Filters({
    required this.state,
    required this.onPeriod,
    required this.onCustom,
    required this.onAccount,
    required this.onAllAccounts,
    required this.onCurrency,
  });

  final FinancialCashFlowState state;
  final ValueChanged<FinancialCashFlowPeriod> onPeriod;
  final VoidCallback onCustom;
  final ValueChanged<String> onAccount;
  final VoidCallback onAllAccounts;
  final ValueChanged<String> onCurrency;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ready = state.canFilter;
    final groups = state.cashFlow?.groups ?? const <FinancialCashFlowGroup>[];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Período', style: theme.textTheme.titleSmall),
            const SizedBox(height: AppTokens.space8),
            Wrap(
              spacing: AppTokens.space8,
              runSpacing: AppTokens.space8,
              children: [
                for (final (period, label) in const [
                  (FinancialCashFlowPeriod.next30, 'Próximos 30 dias'),
                  (FinancialCashFlowPeriod.next60, 'Próximos 60 dias'),
                  (FinancialCashFlowPeriod.next90, 'Próximos 90 dias'),
                  (FinancialCashFlowPeriod.currentMonth, 'Mês atual'),
                ])
                  ChoiceChip(
                    key: FinancialCashFlowScreen.periodKey(period),
                    label: Text(label),
                    selected: state.period == period,
                    onSelected: ready ? (_) => onPeriod(period) : null,
                  ),
                ChoiceChip(
                  key: FinancialCashFlowScreen.customPeriodKey,
                  label: Text(
                    state.period == FinancialCashFlowPeriod.custom &&
                            state.customFrom != null &&
                            state.customThrough != null
                        ? 'Personalizado: ${_formatDate(state.customFrom!)} a '
                              '${_formatDate(state.customThrough!)}'
                        : 'Personalizado…',
                  ),
                  selected: state.period == FinancialCashFlowPeriod.custom,
                  onSelected: ready ? (_) => onCustom() : null,
                ),
              ],
            ),
            const SizedBox(height: AppTokens.space16),
            Text('Contas', style: theme.textTheme.titleSmall),
            const SizedBox(height: AppTokens.space8),
            Wrap(
              spacing: AppTokens.space8,
              runSpacing: AppTokens.space8,
              children: [
                ChoiceChip(
                  key: FinancialCashFlowScreen.allAccountsKey,
                  label: const Text('Todas as contas ativas'),
                  selected: state.selectedAccountIds.isEmpty,
                  onSelected: ready ? (_) => onAllAccounts() : null,
                ),
                for (final account in state.accounts)
                  FilterChip(
                    key: FinancialCashFlowScreen.accountFilterKey(
                      account.accountId,
                    ),
                    label: Text(
                      '${account.name} · ${account.currency}'
                      '${account.status == FinancialAccountStatus.archived ? ' · arquivada' : ''}',
                    ),
                    selected: state.selectedAccountIds.contains(
                      account.accountId,
                    ),
                    onSelected: ready
                        ? (_) => onAccount(account.accountId)
                        : null,
                  ),
              ],
            ),
            if (groups.length > 1) ...[
              const SizedBox(height: AppTokens.space16),
              Text(
                'Moeda (cada moeda é calculada separadamente, sem conversão)',
                style: theme.textTheme.titleSmall,
              ),
              const SizedBox(height: AppTokens.space8),
              Wrap(
                spacing: AppTokens.space8,
                children: [
                  for (final group in groups)
                    ChoiceChip(
                      key: FinancialCashFlowScreen.currencyKey(group.currency),
                      label: Text(group.currency),
                      selected: state.group?.currency == group.currency,
                      onSelected: (_) => onCurrency(group.currency),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _GroupView extends StatelessWidget {
  const _GroupView({
    required this.cashFlow,
    required this.group,
    required this.allDays,
    required this.visibleEvents,
    required this.onToggleDays,
    required this.onMoreEvents,
  });

  final FinancialCashFlow cashFlow;
  final FinancialCashFlowGroup group;
  final bool allDays;
  final int visibleEvents;
  final VoidCallback onToggleDays;
  final VoidCallback onMoreEvents;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 1100;
        final summary = _Summary(cashFlow: cashFlow, group: group);
        final comparison = _Comparison(group: group);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _Status(group: group),
            const SizedBox(height: AppTokens.space12),
            _Risk(group: group, historical: cashFlow.isHistorical),
            const SizedBox(height: AppTokens.space12),
            if (wide)
              IntrinsicHeight(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Expanded(child: summary),
                    const SizedBox(width: AppTokens.space12),
                    Expanded(child: comparison),
                  ],
                ),
              )
            else ...[
              summary,
              const SizedBox(height: AppTokens.space12),
              comparison,
            ],
            const SizedBox(height: AppTokens.space12),
            _Accounts(group: group, cashFlow: cashFlow),
            const SizedBox(height: AppTokens.space12),
            _Days(group: group, allDays: allDays, onToggle: onToggleDays),
            const SizedBox(height: AppTokens.space12),
            _Events(group: group, visible: visibleEvents, onMore: onMoreEvents),
          ],
        );
      },
    );
  }
}

class _Status extends StatelessWidget {
  const _Status({required this.group});
  final FinancialCashFlowGroup group;

  @override
  Widget build(BuildContext context) {
    final (label, tone) = switch (group.projectionStatus) {
      FinancialCashFlowProjectionStatus.complete => (
        'Projeção completa para as fontes consideradas',
        AppBadgeTone.positive,
      ),
      FinancialCashFlowProjectionStatus.incomplete => (
        'Projeção incompleta: valores não confiáveis',
        AppBadgeTone.warning,
      ),
      FinancialCashFlowProjectionStatus.notApplicable => (
        'Sem projeção: período inteiramente no passado',
        AppBadgeTone.neutral,
      ),
    };
    return Card(
      key: FinancialCashFlowScreen.statusKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AppBadge(label: label, tone: tone),
            for (final issue in group.issues) ...[
              const SizedBox(height: AppTokens.space8),
              Row(
                key: FinancialCashFlowScreen.issueKey(issue.code),
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    issue.severity == FinancialCashFlowIssueSeverity.incomplete
                        ? Icons.error_outline
                        : Icons.info_outline,
                    size: 20,
                    color:
                        issue.severity ==
                            FinancialCashFlowIssueSeverity.incomplete
                        ? AppTokens.amber700
                        : AppTokens.blue700,
                  ),
                  const SizedBox(width: AppTokens.space8),
                  Expanded(
                    child: Text(
                      '${issue.severity == FinancialCashFlowIssueSeverity.incomplete ? 'Incompleto' : 'Atenção'}: '
                      '${_issueText(issue, group)}',
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Risk extends StatelessWidget {
  const _Risk({required this.group, required this.historical});
  final FinancialCashFlowGroup group;
  final bool historical;

  @override
  Widget build(BuildContext context) {
    final risk = group.risk;
    final negative = risk.firstNegativeDate;
    final accountsAtRisk = group.accounts
        .where((account) => account.risk.firstNegativeDate != null)
        .toList();
    final String text;
    if (negative != null) {
      text =
          '${historical ? 'Saldo consolidado ficou negativo' : 'Risco de saldo negativo'}'
          ' a partir de ${_formatDate(negative)} '
          '(${risk.negativeDays} dia(s) negativo(s); menor saldo '
          '${formatFinancialMoney(risk.minimumBalance)} em '
          '${_formatDate(risk.minimumBalanceDate)}).';
    } else if (accountsAtRisk.isNotEmpty) {
      text =
          'O saldo consolidado não fica negativo, mas '
          '${accountsAtRisk.length} conta(s) ficam: '
          '${accountsAtRisk.map((a) => '${a.name} em ${_formatDate(a.risk.firstNegativeDate!)}').join('; ')}.';
    } else {
      text =
          'Nenhum saldo negativo no período. Menor saldo: '
          '${formatFinancialMoney(risk.minimumBalance)} em '
          '${_formatDate(risk.minimumBalanceDate)}.';
    }
    final danger = negative != null || accountsAtRisk.isNotEmpty;
    // Without an opening balance the figures start from zero: absence of a
    // deficit can never be claimed, and a computed deficit is only an estimate.
    final missingOpening = group.accounts
        .where((account) => !account.hasOpeningBalance)
        .length;
    if (missingOpening > 0) {
      return Card(
        key: FinancialCashFlowScreen.riskKey,
        color: AppTokens.amber50,
        child: ListTile(
          leading: const Icon(Icons.help_outline, color: AppTokens.amber700),
          title: const Text('Risco de saldo negativo não avaliável'),
          subtitle: Text(
            'Falta saldo inicial em $missingOpening conta(s): os saldos partem de '
            'zero, então não é possível afirmar se haverá saldo negativo.'
            '${danger ? ' Estimativa sem saldo inicial: $text' : ''}',
          ),
        ),
      );
    }
    return Card(
      key: FinancialCashFlowScreen.riskKey,
      color: danger ? AppTokens.red50 : null,
      child: ListTile(
        leading: Icon(
          danger ? Icons.trending_down_rounded : Icons.check_circle_outline,
          color: danger ? AppTokens.red700 : AppTokens.forest700,
        ),
        title: Text(danger ? 'Atenção ao saldo' : 'Saldo sem déficit'),
        subtitle: Text(text),
      ),
    );
  }
}

class _Summary extends StatelessWidget {
  const _Summary({required this.cashFlow, required this.group});
  final FinancialCashFlow cashFlow;
  final FinancialCashFlowGroup group;

  @override
  Widget build(BuildContext context) {
    return Card(
      key: FinancialCashFlowScreen.summaryKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Saldo real × projetado (${group.currency})',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: AppTokens.space12),
            Wrap(
              spacing: AppTokens.space24,
              runSpacing: AppTokens.space12,
              children: [
                _Figure(
                  'Saldo real em ${_formatDate(cashFlow.referenceDate)}',
                  formatFinancialMoney(group.balanceAtReference),
                ),
                _Figure(
                  'Saldo no início (${_formatDate(cashFlow.from)})',
                  formatFinancialMoney(group.startingBalance),
                ),
                _Figure(
                  cashFlow.isHistorical
                      ? 'Saldo em ${_formatDate(cashFlow.through)}'
                      : 'Saldo projetado em ${_formatDate(cashFlow.through)}',
                  formatFinancialMoney(group.closingBalance),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Comparison extends StatelessWidget {
  const _Comparison({required this.group});
  final FinancialCashFlowGroup group;

  @override
  Widget build(BuildContext context) {
    final totals = group.totals;
    final theme = Theme.of(context);
    TableRow row(String label, String realized, String expected) => TableRow(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: AppTokens.space4),
          child: Text(label),
        ),
        Text(realized, textAlign: TextAlign.end),
        Text(expected, textAlign: TextAlign.end),
      ],
    );
    return Card(
      key: FinancialCashFlowScreen.comparisonKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Realizado × previsto no período',
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: AppTokens.space8),
            Table(
              columnWidths: const {
                0: FlexColumnWidth(1.4),
                1: FlexColumnWidth(),
                2: FlexColumnWidth(),
              },
              children: [
                TableRow(
                  children: [
                    Text('', style: theme.textTheme.labelMedium),
                    Text(
                      'Realizado',
                      textAlign: TextAlign.end,
                      style: theme.textTheme.labelMedium,
                    ),
                    Text(
                      'Previsto',
                      textAlign: TextAlign.end,
                      style: theme.textTheme.labelMedium,
                    ),
                  ],
                ),
                row(
                  'Receitas',
                  formatFinancialMoney(totals.realizedIncome),
                  formatFinancialMoney(totals.expectedIncome),
                ),
                row(
                  'Despesas',
                  formatFinancialMoney(totals.realizedExpense),
                  formatFinancialMoney(totals.expectedExpense),
                ),
                row(
                  'Transferências recebidas',
                  formatFinancialMoney(totals.neutralIn),
                  '—',
                ),
                row(
                  'Transferências enviadas',
                  formatFinancialMoney(totals.neutralOut),
                  '—',
                ),
                row(
                  'Efeito líquido no saldo',
                  formatFinancialMoney(totals.realizedNet),
                  formatFinancialMoney(totals.expectedNet),
                ),
                row(
                  'Eventos',
                  '${totals.realizedCount}',
                  '${totals.expectedCount}',
                ),
              ],
            ),
            if (totals.recurrenceRealizedCount > 0) ...[
              const SizedBox(height: AppTokens.space8),
              Text(
                'Recorrências registradas no período: '
                '${totals.recurrenceRealizedCount} · previsto '
                '${formatFinancialMoney(totals.recurrenceRealizedExpected)} · '
                'realizado ${formatFinancialMoney(totals.recurrenceRealizedActual)}',
              ),
            ],
            if (totals.overdueCount > 0) ...[
              const SizedBox(height: AppTokens.space8),
              Text(
                'Previstas vencidas e não registradas: ${totals.overdueCount} '
                '(${formatFinancialMoney(totals.overdueNet)}), incluídas na data '
                'de referência.',
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Accounts extends StatelessWidget {
  const _Accounts({required this.group, required this.cashFlow});
  final FinancialCashFlowGroup group;
  final FinancialCashFlow cashFlow;

  @override
  Widget build(BuildContext context) {
    return Card(
      key: FinancialCashFlowScreen.accountsKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Por conta', style: Theme.of(context).textTheme.titleMedium),
            for (final account in group.accounts)
              ListTile(
                contentPadding: EdgeInsets.zero,
                title: Text(
                  '${account.name}'
                  '${account.status == FinancialAccountStatus.archived ? ' (arquivada)' : ''}',
                ),
                subtitle: Text(
                  [
                    'Real em ${_formatDate(cashFlow.referenceDate)}: '
                        '${formatFinancialMoney(account.balanceAtReference)}',
                    'Projetado em ${_formatDate(cashFlow.through)}: '
                        '${formatFinancialMoney(account.closingBalance)}',
                    if (!account.hasOpeningBalance) 'Sem saldo inicial',
                    if (account.risk.firstNegativeDate != null)
                      'Negativo a partir de '
                          '${_formatDate(account.risk.firstNegativeDate!)}',
                  ].join(' · '),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _Days extends StatelessWidget {
  const _Days({
    required this.group,
    required this.allDays,
    required this.onToggle,
  });
  final FinancialCashFlowGroup group;
  final bool allDays;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final days = allDays
        ? group.days
        : [
            for (final (index, day) in group.days.indexed)
              if (index == 0 ||
                  index == group.days.length - 1 ||
                  day.hasActivity ||
                  day.negative)
                day,
          ];
    return Card(
      key: FinancialCashFlowScreen.daysKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              alignment: WrapAlignment.spaceBetween,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: AppTokens.space12,
              children: [
                Text('Evolução do saldo', style: theme.textTheme.titleMedium),
                TextButton(
                  key: FinancialCashFlowScreen.allDaysKey,
                  onPressed: onToggle,
                  child: Text(
                    allDays
                        ? 'Mostrar só dias com movimento'
                        : 'Mostrar todos os ${group.days.length} dias',
                  ),
                ),
              ],
            ),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                headingTextStyle: theme.textTheme.labelMedium,
                columns: const [
                  DataColumn(label: Text('Data')),
                  DataColumn(label: Text('Tipo')),
                  DataColumn(label: Text('Entradas'), numeric: true),
                  DataColumn(label: Text('Saídas'), numeric: true),
                  DataColumn(label: Text('Transferências'), numeric: true),
                  DataColumn(label: Text('Saldo final'), numeric: true),
                ],
                rows: [
                  for (final day in days)
                    DataRow(
                      color: day.negative
                          ? const WidgetStatePropertyAll(AppTokens.red50)
                          : null,
                      cells: [
                        DataCell(Text(_formatDate(day.date))),
                        DataCell(
                          Text(
                            '${day.projected ? 'Projetado' : 'Realizado'}'
                            '${day.negative ? ' · negativo' : ''}',
                          ),
                        ),
                        DataCell(Text(_inflowText(day))),
                        DataCell(Text(_outflowText(day))),
                        DataCell(Text(formatFinancialMoney(day.neutralNet))),
                        DataCell(
                          Text(
                            formatFinancialMoney(day.closing),
                            style: day.negative
                                ? const TextStyle(
                                    color: AppTokens.red700,
                                    fontWeight: FontWeight.w700,
                                  )
                                : null,
                          ),
                        ),
                      ],
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

String _inflowText(FinancialCashFlowDay day) => [
  if (!day.realizedIncome.isZero)
    'real ${formatFinancialMoney(day.realizedIncome)}',
  if (!day.expectedIncome.isZero)
    'prev. ${formatFinancialMoney(day.expectedIncome)}',
].join(' + ').ifEmpty('—');

String _outflowText(FinancialCashFlowDay day) => [
  if (!day.realizedExpense.isZero)
    'real ${formatFinancialMoney(day.realizedExpense)}',
  if (!day.expectedExpense.isZero)
    'prev. ${formatFinancialMoney(day.expectedExpense)}',
].join(' + ').ifEmpty('—');

extension on String {
  String ifEmpty(String fallback) => isEmpty ? fallback : this;
}

class _Events extends StatelessWidget {
  const _Events({
    required this.group,
    required this.visible,
    required this.onMore,
  });
  final FinancialCashFlowGroup group;
  final int visible;
  final VoidCallback onMore;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final events = group.events;
    final shown = events.take(visible).toList();
    final children = <Widget>[];
    String? currentDate;
    for (final (index, event) in shown.indexed) {
      if (event.date != currentDate) {
        currentDate = event.date;
        children.add(
          Padding(
            padding: const EdgeInsets.only(
              top: AppTokens.space12,
              bottom: AppTokens.space4,
            ),
            child: Text(
              _formatDate(event.date),
              style: theme.textTheme.titleSmall,
            ),
          ),
        );
      }
      children.add(_EventTile(index: index, event: event, group: group));
    }
    return Card(
      key: FinancialCashFlowScreen.eventsKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Eventos usados no cálculo (${events.length})',
              style: theme.textTheme.titleMedium,
            ),
            if (events.isEmpty)
              const Padding(
                padding: EdgeInsets.only(top: AppTokens.space8),
                child: Text(
                  'Nenhum lançamento ou previsão no período para esta seleção.',
                ),
              ),
            ...children,
            if (shown.length < events.length) ...[
              const SizedBox(height: AppTokens.space8),
              Text('Exibindo ${shown.length} de ${events.length} eventos.'),
              TextButton(
                key: FinancialCashFlowScreen.moreEventsKey,
                onPressed: onMore,
                child: const Text('Mostrar mais eventos'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _EventTile extends StatelessWidget {
  const _EventTile({
    required this.index,
    required this.event,
    required this.group,
  });
  final int index;
  final FinancialCashFlowEvent event;
  final FinancialCashFlowGroup group;

  @override
  Widget build(BuildContext context) {
    final account = group.account(event.accountId)?.name ?? 'Conta';
    final (label, tone) = _kindBadge(event);
    return ListTile(
      key: FinancialCashFlowScreen.eventKey(index),
      contentPadding: EdgeInsets.zero,
      onTap: () => showDialog<void>(
        context: context,
        builder: (_) => _EventDetail(event: event, account: account),
      ),
      title: Text(_eventTitle(event)),
      subtitle: Padding(
        padding: const EdgeInsets.only(top: AppTokens.space4),
        child: Wrap(
          spacing: AppTokens.space8,
          runSpacing: AppTokens.space4,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            AppBadge(label: label, tone: tone),
            Text('$account · ${_effectLabel(event)}'),
          ],
        ),
      ),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            formatFinancialMoney(event.amount),
            style: TextStyle(
              fontWeight: FontWeight.w700,
              color: event.amount.isNegative
                  ? AppTokens.red700
                  : AppTokens.forest800,
            ),
          ),
          Text(
            'Saldo: ${formatFinancialMoney(event.balanceAfter)}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _EventDetail extends StatelessWidget {
  const _EventDetail({required this.event, required this.account});
  final FinancialCashFlowEvent event;
  final String account;

  @override
  Widget build(BuildContext context) {
    final rows = <(String, String)>[
      ('Origem', _kindBadge(event).$1),
      ('Conta', account),
      ('Natureza', _effectLabel(event)),
      ('Data no fluxo', _formatDate(event.date)),
      if (event.scheduledDate != null)
        ('Vencimento previsto', _formatDate(event.scheduledDate!)),
      if (event.periodStart != null)
        ('Competência da recorrência', event.periodStart!.substring(0, 7)),
      ('Valor', formatFinancialMoney(event.amount)),
      if (event.expectedAmount != null)
        ('Valor previsto', formatFinancialMoney(event.expectedAmount!)),
      ('Saldo consolidado após', formatFinancialMoney(event.balanceAfter)),
      ('Saldo da conta após', formatFinancialMoney(event.accountBalanceAfter)),
      if (event.ruleVersion != null)
        ('Versão da regra', '${event.ruleVersion}'),
      if (event.movementId != null) ('Lançamento', event.movementId!),
      if (event.reversalOfId != null) ('Estorno de', event.reversalOfId!),
      if (event.transferId != null) ('Transferência', event.transferId!),
      if (event.occurrenceId != null) ('Ocorrência', event.occurrenceId!),
      if (event.recurrenceId != null) ('Recorrência', event.recurrenceId!),
    ];
    return AlertDialog(
      key: FinancialCashFlowScreen.eventDetailKey,
      title: Text(_eventTitle(event)),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(_kindExplanation(event)),
              const SizedBox(height: AppTokens.space12),
              for (final (label, value) in rows)
                Padding(
                  padding: const EdgeInsets.symmetric(
                    vertical: AppTokens.space4,
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 190,
                        child: Text(
                          label,
                          style: Theme.of(context).textTheme.labelMedium,
                        ),
                      ),
                      Expanded(child: SelectableText(value)),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Fechar'),
        ),
      ],
    );
  }
}

class _Figure extends StatelessWidget {
  const _Figure(this.label, this.value);
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(label, style: Theme.of(context).textTheme.labelMedium),
      Text(value, style: Theme.of(context).textTheme.titleLarge),
    ],
  );
}

String _eventTitle(FinancialCashFlowEvent event) {
  if (event.movementRole == FinancialMovementRole.reversal) {
    return 'Estorno de lançamento';
  }
  return event.description ?? 'Lançamento';
}

(String, AppBadgeTone) _kindBadge(FinancialCashFlowEvent event) {
  if (event.overdue) return ('Prevista vencida', AppBadgeTone.negative);
  return switch (event.kind) {
    FinancialCashFlowEventKind.realized => ('Realizado', AppBadgeTone.positive),
    FinancialCashFlowEventKind.expectedOccurrence => (
      'Previsto · ocorrência gerada',
      AppBadgeTone.info,
    ),
    FinancialCashFlowEventKind.expectedRule => (
      'Previsto pela regra · não gerado',
      AppBadgeTone.warning,
    ),
  };
}

String _kindExplanation(FinancialCashFlowEvent event) {
  if (event.overdue) {
    return 'Ocorrência prevista para ${_formatDate(event.scheduledDate!)} que '
        'ainda não foi registrada nem pulada. Ela entra na data de referência '
        'como compromisso pendente; registrá-la é uma ação explícita em '
        'Recorrências.';
  }
  return switch (event.kind) {
    FinancialCashFlowEventKind.realized =>
      event.expectedAmount == null
          ? 'Lançamento já registrado no livro financeiro.'
          : 'Lançamento registrado a partir de uma recorrência; o valor '
                'previsto é exibido para comparação e não é somado.',
    FinancialCashFlowEventKind.expectedOccurrence =>
      'Ocorrência gerada e ainda pendente. Não é um lançamento: não altera o '
          'saldo real nem o extrato.',
    FinancialCashFlowEventKind.expectedRule =>
      'Mês de uma recorrência ativa que ainda não teve ocorrência gerada. '
          'Estimado pelo valor atual da regra; nada é gravado por esta leitura.',
  };
}

String _effectLabel(FinancialCashFlowEvent event) =>
    switch (event.resultEffect) {
      FinancialResultEffect.income => 'Receita',
      FinancialResultEffect.expense => 'Despesa',
      FinancialResultEffect.neutral =>
        event.transferId != null ? 'Transferência' : 'Movimento neutro',
    };

String _issueText(FinancialCashFlowIssue issue, FinancialCashFlowGroup group) {
  final names = issue.accountIds
      .map((id) => group.account(id)?.name)
      .whereType<String>()
      .join(', ');
  final where = names.isEmpty ? '' : ' ($names)';
  final n = issue.count;
  return switch (issue.code) {
    FinancialCashFlowIssueCode.openingBalanceMissing =>
      '$n conta(s) sem saldo inicial$where: os saldos partem de zero e o risco '
          'de saldo negativo não é confiável.',
    FinancialCashFlowIssueCode.openingBalanceAfterWindowStart =>
      '$n conta(s) com saldo inicial dentro do período$where: saldos anteriores '
          'a essa data não são significativos.',
    FinancialCashFlowIssueCode.ruleAccountInactive =>
      '$n recorrência(s) ativa(s) em conta arquivada$where não foram projetadas.',
    FinancialCashFlowIssueCode.overdueOccurrences =>
      '$n prevista(s) vencida(s) e não registrada(s)$where entraram na data de '
          'referência. Registre ou pule em Recorrências.',
    FinancialCashFlowIssueCode.ungeneratedPastOccurrences =>
      '$n vencimento(s) anterior(es) à data de referência$where não têm '
          'ocorrência gerada e não foram projetados (podem já ter sido pagos).',
    FinancialCashFlowIssueCode.pausedRules =>
      '$n recorrência(s) pausada(s)$where não projetam novos meses.',
    FinancialCashFlowIssueCode.historicalWindow =>
      'período inteiramente no passado: apenas o realizado é exibido.',
  };
}

String _excludedLabel(String source) => switch (source) {
  'BUDGETS' => 'orçamentos',
  'GOALS' => 'metas',
  'PROJECTS' => 'projetos',
  'CARDS' => 'cartões e faturas',
  'INSTALLMENTS' => 'parcelamentos',
  'LOANS' => 'empréstimos e financiamentos',
  'BANK_OBSERVATIONS' => 'dados bancários importados',
  _ => source,
};

/// `YYYY-MM-DD` → `DD/MM/YYYY` (text only).
String _formatDate(String value) =>
    '${value.substring(8, 10)}/${value.substring(5, 7)}/${value.substring(0, 4)}';

String _isoDate(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-'
    '${value.month.toString().padLeft(2, '0')}-'
    '${value.day.toString().padLeft(2, '0')}';
