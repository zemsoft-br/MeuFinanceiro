import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class FinancialAccountsScreen extends ConsumerStatefulWidget {
  const FinancialAccountsScreen({super.key});

  static const titleKey = Key('financial-accounts-title');
  static const createButtonKey = Key('financial-accounts-create');
  static const refreshButtonKey = Key('financial-accounts-refresh');
  static const emptyKey = Key('financial-accounts-empty');
  static const listKey = Key('financial-accounts-list');

  static Key accountCardKey(String accountId) =>
      Key('financial-account-$accountId');

  @override
  ConsumerState<FinancialAccountsScreen> createState() =>
      _FinancialAccountsScreenState();
}

class _FinancialAccountsScreenState
    extends ConsumerState<FinancialAccountsScreen> {
  final _headingFocusNode = FocusNode(debugLabel: 'financial-accounts-heading');

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _headingFocusNode.requestFocus();
      unawaited(ref.read(financialAccountsControllerProvider.notifier).load());
    });
  }

  @override
  void dispose() {
    _headingFocusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(financialAccountsControllerProvider);
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
                      'Finanças · Residência principal',
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
                          'Contas financeiras',
                          key: FinancialAccountsScreen.titleKey,
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Text(
                      'Contas canônicas da residência. O saldo corrente será exibido somente quando a consulta de saldo estiver disponível.',
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                        color: AppTokens.neutral700,
                      ),
                    ),
                  ],
                ),
              ),
              Wrap(
                spacing: AppTokens.space8,
                runSpacing: AppTokens.space8,
                children: [
                  OutlinedButton.icon(
                    key: FinancialAccountsScreen.refreshButtonKey,
                    onPressed: refreshEnabled
                        ? () => unawaited(
                            ref
                                .read(
                                  financialAccountsControllerProvider.notifier,
                                )
                                .refresh(),
                          )
                        : null,
                    icon: state.phase == FinancialLoadPhase.refreshing
                        ? const SizedBox.square(
                            dimension: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.refresh_rounded),
                    label: const Text('Atualizar'),
                  ),
                  FilledButton.icon(
                    key: FinancialAccountsScreen.createButtonKey,
                    onPressed: () =>
                        context.go(AppRoutes.financeAccountCreatePath),
                    icon: const Icon(Icons.add_rounded),
                    label: const Text('Nova conta'),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppTokens.space24),
          if (state.refreshFailure != FinancialRefreshFailure.none) ...[
            _RefreshNotice(failure: state.refreshFailure),
            const SizedBox(height: AppTokens.space16),
          ],
          _AccountsContent(
            state: state,
            onRetry: () => unawaited(
              ref.read(financialAccountsControllerProvider.notifier).refresh(),
            ),
          ),
        ],
      ),
    );
  }
}

class _AccountsContent extends StatelessWidget {
  const _AccountsContent({required this.state, required this.onRetry});

  final FinancialAccountsState state;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    if (state.phase == FinancialLoadPhase.idle ||
        state.phase == FinancialLoadPhase.loading) {
      return const _StatusCard(
        icon: Icons.hourglass_top_rounded,
        title: 'Carregando contas…',
        message: 'Buscando somente os recursos visíveis na residência atual.',
        loading: true,
      );
    }
    if (state.phase == FinancialLoadPhase.empty) {
      return Card(
        key: FinancialAccountsScreen.emptyKey,
        child: const Padding(
          padding: EdgeInsets.all(AppTokens.space24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.account_balance_wallet_outlined, size: 36),
              SizedBox(height: AppTokens.space16),
              Text('Nenhuma conta financeira cadastrada'),
              SizedBox(height: AppTokens.space8),
              Text(
                'Crie a primeira conta para começar a registrar sua base financeira.',
              ),
            ],
          ),
        ),
      );
    }
    if (state.accounts.isNotEmpty) {
      return Column(
        key: FinancialAccountsScreen.listKey,
        children: state.accounts
            .map(
              (account) => Padding(
                padding: const EdgeInsets.only(bottom: AppTokens.space12),
                child: _AccountCard(account: account),
              ),
            )
            .toList(),
      );
    }

    final presentation = _failurePresentation(state.phase);
    return _StatusCard(
      icon: presentation.$1,
      title: presentation.$2,
      message: presentation.$3,
      actionLabel: presentation.$4 ? 'Tentar novamente' : null,
      onAction: presentation.$4 ? onRetry : null,
    );
  }
}

class _AccountCard extends StatelessWidget {
  const _AccountCard({required this.account});

  final FinancialAccount account;

  @override
  Widget build(BuildContext context) {
    return Card(
      key: FinancialAccountsScreen.accountCardKey(account.accountId),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppTokens.radiusMedium),
        onTap: () => context.go(
          AppRoutes.financeAccountDetailLocation(account.accountId),
        ),
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.space20),
          child: Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: AppTokens.space16,
            runSpacing: AppTokens.space12,
            children: [
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 700),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      account.name,
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: AppTokens.space4),
                    Text(
                      '${_accountTypeLabel(account.accountType)} · ${account.currency} · ${_visibilityLabel(account.visibilityScope)}',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: AppTokens.neutral700,
                      ),
                    ),
                    const SizedBox(height: AppTokens.space4),
                    Text(
                      account.status == FinancialAccountStatus.active
                          ? 'Conta ativa'
                          : 'Conta arquivada',
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded),
            ],
          ),
        ),
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
        'Os dados atuais foram preservados, mas a atualização não pôde ser concluída.',
      FinancialRefreshFailure.invalidResponse =>
        'Os dados atuais foram preservados porque a nova resposta não passou na validação de segurança.',
      FinancialRefreshFailure.none => '',
    };
    if (message.isEmpty) return const SizedBox.shrink();
    return Semantics(
      liveRegion: true,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(AppTokens.space16),
          child: Row(
            children: [
              const Icon(Icons.info_outline_rounded),
              const SizedBox(width: AppTokens.space12),
              Expanded(child: Text(message)),
            ],
          ),
        ),
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({
    required this.icon,
    required this.title,
    required this.message,
    this.loading = false,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String message;
  final bool loading;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (loading)
              const SizedBox.square(
                dimension: 24,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              )
            else
              Icon(icon, size: 32),
            const SizedBox(height: AppTokens.space16),
            Text(title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: AppTokens.space8),
            Text(message),
            if (actionLabel != null && onAction != null) ...[
              const SizedBox(height: AppTokens.space16),
              OutlinedButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}

(IconData, String, String, bool) _failurePresentation(
  FinancialLoadPhase phase,
) {
  return switch (phase) {
    FinancialLoadPhase.authenticationRequired => (
      Icons.lock_outline_rounded,
      'Sessão necessária',
      'Entre novamente para acessar as informações financeiras.',
      false,
    ),
    FinancialLoadPhase.forbidden => (
      Icons.block_rounded,
      'Acesso não permitido',
      'Sua sessão não possui acesso a este recurso financeiro.',
      false,
    ),
    FinancialLoadPhase.primaryResidenceRequired => (
      Icons.home_work_outlined,
      'Residência principal necessária',
      'Configure uma residência principal antes de usar o módulo financeiro.',
      false,
    ),
    FinancialLoadPhase.notFound => (
      Icons.search_off_rounded,
      'Recurso não encontrado',
      'O recurso não existe ou não está disponível para esta sessão.',
      false,
    ),
    FinancialLoadPhase.invalidResponse => (
      Icons.warning_amber_rounded,
      'Resposta inválida',
      'A resposta recebida não pôde ser validada com segurança.',
      true,
    ),
    _ => (
      Icons.cloud_off_outlined,
      'Serviço temporariamente indisponível',
      'Não foi possível carregar as informações financeiras agora.',
      true,
    ),
  };
}

String _accountTypeLabel(FinancialAccountType type) => switch (type) {
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
