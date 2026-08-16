import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class FinancialAccountDetailScreen extends ConsumerStatefulWidget {
  const FinancialAccountDetailScreen({required this.accountId, super.key});

  final String accountId;

  static const titleKey = Key('financial-account-detail-title');
  static const refreshButtonKey = Key('financial-account-detail-refresh');
  static const openingBalanceKey = Key(
    'financial-account-detail-opening-balance',
  );
  static const movementsKey = Key('financial-account-detail-movements');
  static const createOpeningButtonKey = Key(
    'financial-account-detail-create-opening',
  );

  @override
  ConsumerState<FinancialAccountDetailScreen> createState() =>
      _FinancialAccountDetailScreenState();
}

class _FinancialAccountDetailScreenState
    extends ConsumerState<FinancialAccountDetailScreen> {
  final _headingFocusNode = FocusNode(
    debugLabel: 'financial-account-detail-heading',
  );

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _headingFocusNode.requestFocus();
      unawaited(
        ref
            .read(
              financialAccountDetailControllerProvider(
                widget.accountId,
              ).notifier,
            )
            .load(),
      );
    });
  }

  @override
  void dispose() {
    _headingFocusNode.dispose();
    super.dispose();
  }

  Future<void> _createOpeningBalance(FinancialAccount account) async {
    final result = await showDialog<FinancialOpeningBalanceCreateInput>(
      context: context,
      builder: (context) => _OpeningBalanceDialog(account: account),
    );
    if (result == null || !mounted) return;
    final created = await ref
        .read(
          financialAccountDetailControllerProvider(widget.accountId).notifier,
        )
        .createOpeningBalance(result);
    if (!mounted) return;
    final message = created
        ? 'Saldo inicial cadastrado.'
        : 'O detalhe foi atualizado com o estado persistido.';
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final provider = financialAccountDetailControllerProvider(widget.accountId);
    final state = ref.watch(provider);
    final account = state.account;
    final refreshEnabled =
        !state.isBusy &&
        state.phase != FinancialLoadPhase.authenticationRequired &&
        state.phase != FinancialLoadPhase.forbidden &&
        state.phase != FinancialLoadPhase.primaryResidenceRequired;

    return FocusTraversalGroup(
      policy: ReadingOrderTraversalPolicy(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => context.go(AppRoutes.financePath),
              icon: const Icon(Icons.arrow_back_rounded),
              label: const Text('Voltar para Finanças'),
            ),
          ),
          const SizedBox(height: AppTokens.space12),
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: AppTokens.space16,
            runSpacing: AppTokens.space16,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Finanças · Conta',
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                        color: AppTokens.forest700,
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Focus(
                      focusNode: _headingFocusNode,
                      child: Semantics(
                        header: true,
                        child: Text(
                          account?.name ?? 'Detalhes da conta',
                          key: FinancialAccountDetailScreen.titleKey,
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Text(
                      'Saldo inicial e Movements são exibidos como registros canônicos. O saldo corrente ainda não é calculado nesta tela.',
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                        color: AppTokens.neutral700,
                      ),
                    ),
                  ],
                ),
              ),
              OutlinedButton.icon(
                key: FinancialAccountDetailScreen.refreshButtonKey,
                onPressed: refreshEnabled
                    ? () => unawaited(ref.read(provider.notifier).refresh())
                    : null,
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
          const SizedBox(height: AppTokens.space24),
          if (state.refreshFailure != FinancialRefreshFailure.none) ...[
            _RefreshNotice(failure: state.refreshFailure),
            const SizedBox(height: AppTokens.space16),
          ],
          if (account == null)
            _FailureOrLoading(
              phase: state.phase,
              onRetry: () => unawaited(ref.read(provider.notifier).refresh()),
            )
          else ...[
            _AccountIdentityCard(account: account),
            const SizedBox(height: AppTokens.space16),
            _OpeningBalanceCard(
              account: account,
              openingBalance: state.openingBalance,
              mutationInFlight: state.openingBalanceMutationInFlight,
              onCreate:
                  state.openingBalance == null &&
                      account.status == FinancialAccountStatus.active
                  ? () => unawaited(_createOpeningBalance(account))
                  : null,
            ),
            const SizedBox(height: AppTokens.space16),
            _MovementsCard(movements: state.movements),
          ],
        ],
      ),
    );
  }
}

class _AccountIdentityCard extends StatelessWidget {
  const _AccountIdentityCard({required this.account});
  final FinancialAccount account;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Wrap(
          spacing: AppTokens.space24,
          runSpacing: AppTokens.space12,
          children: [
            _Metadata(label: 'Tipo', value: _typeLabel(account.accountType)),
            _Metadata(label: 'Moeda', value: account.currency),
            _Metadata(
              label: 'Visibilidade',
              value: _visibilityLabel(account.visibilityScope),
            ),
            _Metadata(
              label: 'Status',
              value: account.status == FinancialAccountStatus.active
                  ? 'Ativa'
                  : 'Arquivada',
            ),
          ],
        ),
      ),
    );
  }
}

class _OpeningBalanceCard extends StatelessWidget {
  const _OpeningBalanceCard({
    required this.account,
    required this.openingBalance,
    required this.mutationInFlight,
    required this.onCreate,
  });

  final FinancialAccount account;
  final FinancialOpeningBalance? openingBalance;
  final bool mutationInFlight;
  final VoidCallback? onCreate;

  @override
  Widget build(BuildContext context) {
    final opening = openingBalance;
    return Card(
      key: FinancialAccountDetailScreen.openingBalanceKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Saldo inicial',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: AppTokens.space8),
            if (opening == null) ...[
              Text(
                'Saldo inicial não informado.',
                style: Theme.of(context).textTheme.bodyLarge,
              ),
              const SizedBox(height: AppTokens.space4),
              Text(
                'A ausência de registro não significa saldo zero.',
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
              ),
              if (onCreate != null) ...[
                const SizedBox(height: AppTokens.space16),
                FilledButton.icon(
                  key: FinancialAccountDetailScreen.createOpeningButtonKey,
                  onPressed: mutationInFlight ? null : onCreate,
                  icon: mutationInFlight
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.add_rounded),
                  label: const Text('Informar saldo inicial'),
                ),
              ],
            ] else
              Wrap(
                spacing: AppTokens.space24,
                runSpacing: AppTokens.space12,
                children: [
                  _Metadata(label: 'Valor', value: _moneyLabel(opening.money)),
                  _Metadata(
                    label: 'Data efetiva',
                    value: _dateLabel(opening.effectiveDate),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

class _MovementsCard extends StatelessWidget {
  const _MovementsCard({required this.movements});
  final List<FinancialMovement> movements;

  @override
  Widget build(BuildContext context) {
    return Card(
      key: FinancialAccountDetailScreen.movementsKey,
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Movimentações',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              'Eventos STANDARD e REVERSAL permanecem visíveis separadamente.',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
            ),
            const SizedBox(height: AppTokens.space16),
            if (movements.isEmpty)
              const Text('Nenhuma movimentação registrada nesta conta.')
            else
              ...movements.map(
                (movement) => Padding(
                  padding: const EdgeInsets.only(bottom: AppTokens.space12),
                  child: _MovementRow(movement: movement),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _MovementRow extends StatelessWidget {
  const _MovementRow({required this.movement});
  final FinancialMovement movement;

  @override
  Widget build(BuildContext context) {
    final reversal = movement.role == FinancialMovementRole.reversal;
    final label = reversal
        ? movement.reversalReason ?? 'Reversão'
        : movement.description ?? 'Movimentação';
    return Container(
      padding: const EdgeInsets.all(AppTokens.space16),
      decoration: BoxDecoration(
        border: Border.all(color: AppTokens.neutral200),
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
      ),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: AppTokens.space16,
        runSpacing: AppTokens.space8,
        children: [
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 650),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label, style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: AppTokens.space4),
                Text(
                  '${_dateLabel(movement.effectiveDate)} · ${_effectLabel(movement.resultEffect)} · ${reversal ? 'Reversão' : 'Original'}',
                  style: Theme.of(
                    context,
                  ).textTheme.bodySmall?.copyWith(color: AppTokens.neutral700),
                ),
              ],
            ),
          ),
          Semantics(
            label:
                '${reversal ? 'Reversão' : 'Movimento'}: ${_moneyLabel(movement.money)}',
            child: Text(
              _moneyLabel(movement.money),
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
        ],
      ),
    );
  }
}

class _OpeningBalanceDialog extends StatefulWidget {
  const _OpeningBalanceDialog({required this.account});
  final FinancialAccount account;

  @override
  State<_OpeningBalanceDialog> createState() => _OpeningBalanceDialogState();
}

class _OpeningBalanceDialogState extends State<_OpeningBalanceDialog> {
  final _formKey = GlobalKey<FormState>();
  final _amountController = TextEditingController();
  late final TextEditingController _dateController;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    _dateController = TextEditingController(
      text:
          '${now.year.toString().padLeft(4, '0')}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}',
    );
  }

  @override
  void dispose() {
    _amountController.dispose();
    _dateController.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    try {
      Navigator.of(context).pop(
        FinancialOpeningBalanceCreateInput(
          amount: _amountController.text,
          currency: widget.account.currency,
          effectiveDate: _dateController.text,
        ),
      );
    } on FormatException {
      _formKey.currentState?.validate();
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Informar saldo inicial'),
      content: SizedBox(
        width: 460,
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                controller: _amountController,
                autofocus: true,
                decoration: InputDecoration(
                  labelText: 'Valor em ${widget.account.currency}',
                  helperText: 'Use ponto como separador decimal, ex.: 1250.50',
                ),
                validator: (value) {
                  final source = value ?? '';
                  return RegExp(
                        r'^-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$',
                      ).hasMatch(source)
                      ? null
                      : 'Informe um valor decimal válido.';
                },
              ),
              const SizedBox(height: AppTokens.space16),
              TextFormField(
                controller: _dateController,
                decoration: const InputDecoration(
                  labelText: 'Data efetiva',
                  helperText: 'Formato AAAA-MM-DD',
                ),
                validator: (value) =>
                    RegExp(
                      r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$',
                    ).hasMatch(value ?? '')
                    ? null
                    : 'Informe a data no formato AAAA-MM-DD.',
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Salvar')),
      ],
    );
  }
}

class _Metadata extends StatelessWidget {
  const _Metadata({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(minWidth: 140),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: Theme.of(context).textTheme.labelMedium),
          const SizedBox(height: AppTokens.space4),
          Text(value, style: Theme.of(context).textTheme.bodyLarge),
        ],
      ),
    );
  }
}

class _RefreshNotice extends StatelessWidget {
  const _RefreshNotice({required this.failure});
  final FinancialRefreshFailure failure;

  @override
  Widget build(BuildContext context) {
    final message = switch (failure) {
      FinancialRefreshFailure.temporarilyUnavailable =>
        'O detalhe atual foi preservado, mas não foi possível atualizá-lo.',
      FinancialRefreshFailure.invalidResponse =>
        'O detalhe atual foi preservado porque a nova resposta não pôde ser validada.',
      FinancialRefreshFailure.none => '',
    };
    return message.isEmpty
        ? const SizedBox.shrink()
        : Card(
            child: Padding(
              padding: const EdgeInsets.all(AppTokens.space16),
              child: Text(message),
            ),
          );
  }
}

class _FailureOrLoading extends StatelessWidget {
  const _FailureOrLoading({required this.phase, required this.onRetry});
  final FinancialLoadPhase phase;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    if (phase == FinancialLoadPhase.idle ||
        phase == FinancialLoadPhase.loading) {
      return const Card(
        child: Padding(
          padding: EdgeInsets.all(AppTokens.space24),
          child: Row(
            children: [
              SizedBox.square(
                dimension: 24,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              ),
              SizedBox(width: AppTokens.space16),
              Expanded(child: Text('Carregando detalhes financeiros…')),
            ],
          ),
        ),
      );
    }
    final content = switch (phase) {
      FinancialLoadPhase.notFound => (
        'Conta não encontrada',
        'A conta não existe ou não está visível para esta sessão.',
        false,
      ),
      FinancialLoadPhase.authenticationRequired => (
        'Sessão necessária',
        'Entre novamente para acessar a conta.',
        false,
      ),
      FinancialLoadPhase.forbidden => (
        'Acesso não permitido',
        'Sua sessão não possui acesso a esta conta.',
        false,
      ),
      FinancialLoadPhase.primaryResidenceRequired => (
        'Residência principal necessária',
        'Configure uma residência principal para usar Finanças.',
        false,
      ),
      FinancialLoadPhase.invalidResponse => (
        'Resposta inválida',
        'A resposta recebida não pôde ser validada com segurança.',
        true,
      ),
      _ => (
        'Serviço temporariamente indisponível',
        'Não foi possível carregar a conta agora.',
        true,
      ),
    };
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(content.$1, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: AppTokens.space8),
            Text(content.$2),
            if (content.$3) ...[
              const SizedBox(height: AppTokens.space16),
              OutlinedButton(
                onPressed: onRetry,
                child: const Text('Tentar novamente'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

String _moneyLabel(FinancialMoneyWire money) =>
    '${money.currency} ${money.amount.replaceFirst('.', ',')}';

String _dateLabel(String value) {
  final parts = value.split('-');
  return parts.length == 3 ? '${parts[2]}/${parts[1]}/${parts[0]}' : value;
}

String _typeLabel(FinancialAccountType type) => switch (type) {
  FinancialAccountType.checking => 'Conta corrente',
  FinancialAccountType.savings => 'Poupança',
  FinancialAccountType.cash => 'Dinheiro',
  FinancialAccountType.digitalWallet => 'Carteira digital',
  FinancialAccountType.investment => 'Investimento',
  FinancialAccountType.benefit => 'Benefício',
  FinancialAccountType.custom => 'Personalizada',
};

String _visibilityLabel(FinancialVisibilityScope scope) => switch (scope) {
  FinancialVisibilityScope.personal => 'Pessoal',
  FinancialVisibilityScope.shared => 'Compartilhada',
  FinancialVisibilityScope.household => 'Residência',
};

String _effectLabel(FinancialResultEffect effect) => switch (effect) {
  FinancialResultEffect.income => 'Receita',
  FinancialResultEffect.expense => 'Despesa',
  FinancialResultEffect.neutral => 'Neutro',
};
