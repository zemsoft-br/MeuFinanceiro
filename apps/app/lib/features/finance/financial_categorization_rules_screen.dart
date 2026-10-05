import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_categorization_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_category_policy.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Deterministic categorization rules: list, create and disable.
///
/// Rules are immutable. There is no edit: changing a condition, the priority or
/// the target category means disabling the rule and creating a new one.
class FinancialCategorizationRulesScreen extends ConsumerStatefulWidget {
  const FinancialCategorizationRulesScreen({super.key});

  static const titleKey = Key('financial-rules-title');
  static const refreshButtonKey = Key('financial-rules-refresh');
  static const createButtonKey = Key('financial-rules-create');
  static const emptyKey = Key('financial-rules-empty');
  static const untrustedNoticeKey = Key('financial-rules-untrusted');
  static const dialogKey = Key('financial-rule-create-dialog');
  static const patternFieldKey = Key('financial-rule-pattern');
  static const matcherExactKey = Key('financial-rule-matcher-exact');
  static const matcherContainsKey = Key('financial-rule-matcher-contains');
  static const categoryFieldKey = Key('financial-rule-category');
  static const accountFieldKey = Key('financial-rule-account');
  static const effectFieldKey = Key('financial-rule-effect');
  static const priorityFieldKey = Key('financial-rule-priority');
  static const submitKey = Key('financial-rule-submit');

  static Key ruleKey(String ruleId) => Key('financial-rule-$ruleId');
  static Key disableKey(String ruleId) => Key('financial-rule-disable-$ruleId');
  static const disableConfirmKey = Key('financial-rule-disable-confirm');

  @override
  ConsumerState<FinancialCategorizationRulesScreen> createState() =>
      _FinancialCategorizationRulesScreenState();
}

class _FinancialCategorizationRulesScreenState
    extends ConsumerState<FinancialCategorizationRulesScreen> {
  final _headingFocusNode = FocusNode(debugLabel: 'financial-rules-heading');

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _headingFocusNode.requestFocus();
      unawaited(
        ref
            .read(financialCategorizationRulesControllerProvider.notifier)
            .load(),
      );
    });
  }

  @override
  void dispose() {
    _headingFocusNode.dispose();
    super.dispose();
  }

  Future<void> _create(FinancialCategorizationRulesState state) async {
    final operatorId = ref
        .read(operatorSessionControllerProvider)
        .principal
        ?.operatorId;
    if (operatorId == null) return;
    final input = await showDialog<FinancialCategorizationRuleCreateInput>(
      context: context,
      builder: (_) => _RuleCreateDialog(
        categories: state.categories,
        accounts: state.accounts,
        operatorId: operatorId,
      ),
    );
    if (input == null || !mounted) return;
    final outcome = await ref
        .read(financialCategorizationRulesControllerProvider.notifier)
        .createRule(input);
    if (!mounted) return;
    _announce(switch (outcome) {
      FinancialMutationOutcome.success => 'Regra criada.',
      FinancialMutationOutcome.notAllowed =>
        'Atualize a lista antes de criar regras.',
      FinancialMutationOutcome.rejected =>
        'A regra foi recusada. Revise a categoria e a conta.',
      FinancialMutationOutcome.conflictReconciled =>
        'O estado mudou e a lista foi atualizada. Revise e tente novamente.',
      FinancialMutationOutcome.unknownOutcomeReconciled =>
        'Não foi possível confirmar a criação. A lista foi atualizada; se a '
            'regra não aparecer, você pode tentar novamente com segurança.',
      FinancialMutationOutcome.invalidResponse =>
        'A resposta não pôde ser validada. Atualize a lista.',
      FinancialMutationOutcome.accessBlocked => 'Acesso indisponível.',
      FinancialMutationOutcome.temporarilyUnavailable =>
        'Serviço indisponível. A criação não foi confirmada e não será '
            'reenviada automaticamente.',
    });
  }

  Future<void> _disable(FinancialCategorizationRule rule) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Desabilitar regra'),
        content: const Text(
          'A regra deixa de ser usada em novas aplicações. Classificações já '
          'feitas por ela não são alteradas e continuam podendo ser '
          'modificadas manualmente.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            key: FinancialCategorizationRulesScreen.disableConfirmKey,
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Desabilitar'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final outcome = await ref
        .read(financialCategorizationRulesControllerProvider.notifier)
        .disableRule(rule.ruleId);
    if (!mounted) return;
    _announce(switch (outcome) {
      FinancialMutationOutcome.success => 'Regra desabilitada.',
      FinancialMutationOutcome.notAllowed =>
        'Esta regra não pode ser desabilitada agora.',
      FinancialMutationOutcome.rejected =>
        'A regra não pôde ser desabilitada. A lista foi atualizada.',
      FinancialMutationOutcome.conflictReconciled =>
        'O estado mudou e a lista foi atualizada.',
      FinancialMutationOutcome.unknownOutcomeReconciled =>
        'Não foi possível confirmar o resultado. A lista foi atualizada com o '
            'estado atual.',
      FinancialMutationOutcome.invalidResponse =>
        'A resposta não pôde ser validada. Atualize a lista.',
      FinancialMutationOutcome.accessBlocked => 'Acesso indisponível.',
      FinancialMutationOutcome.temporarilyUnavailable =>
        'Serviço indisponível. O resultado não foi confirmado.',
    });
  }

  void _announce(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(financialCategorizationRulesControllerProvider);
    final operatorId = ref.watch(
      operatorSessionControllerProvider.select(
        (session) => session.principal?.operatorId,
      ),
    );
    final refreshEnabled =
        !state.isBusy &&
        state.phase != FinancialLoadPhase.authenticationRequired &&
        state.phase != FinancialLoadPhase.forbidden &&
        state.phase != FinancialLoadPhase.primaryResidenceRequired;
    final canCreate = state.isLoaded && !state.isBusy && state.trusted;

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
                      'Finanças · Organização',
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
                          'Regras de categorização',
                          key: FinancialCategorizationRulesScreen.titleKey,
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                      ),
                    ),
                    const SizedBox(height: AppTokens.space8),
                    Text(
                      'Regras só sugerem a primeira categoria de lançamentos '
                      'ainda sem classificação e só atuam quando você aplica, '
                      'em uma conta, depois de ver a pré-visualização. Em caso '
                      'de empate de prioridade nada é classificado. Regras não '
                      'são editáveis: para mudar uma, desabilite-a e crie '
                      'outra.',
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
                    key: FinancialCategorizationRulesScreen.refreshButtonKey,
                    onPressed: refreshEnabled
                        ? () => unawaited(
                            ref
                                .read(
                                  financialCategorizationRulesControllerProvider
                                      .notifier,
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
                    key: FinancialCategorizationRulesScreen.createButtonKey,
                    onPressed: canCreate
                        ? () => unawaited(_create(state))
                        : null,
                    icon: const Icon(Icons.add_rounded),
                    label: const Text('Nova regra'),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: AppTokens.space24),
          if (state.refreshFailure != FinancialRefreshFailure.none) ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(AppTokens.space16),
                child: Text(
                  state.refreshFailure ==
                          FinancialRefreshFailure.invalidResponse
                      ? 'A lista atual foi preservada porque a nova resposta '
                            'não pôde ser validada.'
                      : 'A lista atual foi preservada, mas não foi possível '
                            'atualizá-la.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          if (state.isLoaded && !state.trusted) ...[
            const Card(
              key: FinancialCategorizationRulesScreen.untrustedNoticeKey,
              child: Padding(
                padding: EdgeInsets.all(AppTokens.space16),
                child: Text(
                  'A lista exibida pode estar desatualizada. Use Atualizar '
                  'antes de criar ou desabilitar regras.',
                ),
              ),
            ),
            const SizedBox(height: AppTokens.space16),
          ],
          _Content(
            state: state,
            operatorId: operatorId,
            onDisable: (rule) => unawaited(_disable(rule)),
            onRetry: () => unawaited(
              ref
                  .read(financialCategorizationRulesControllerProvider.notifier)
                  .refresh(),
            ),
          ),
        ],
      ),
    );
  }
}

class _Content extends StatelessWidget {
  const _Content({
    required this.state,
    required this.operatorId,
    required this.onDisable,
    required this.onRetry,
  });

  final FinancialCategorizationRulesState state;
  final String? operatorId;
  final ValueChanged<FinancialCategorizationRule> onDisable;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    if (!state.isLoaded) {
      return _PhaseCard(phase: state.phase, onRetry: onRetry);
    }
    if (state.rules.isEmpty) {
      return const Card(
        key: FinancialCategorizationRulesScreen.emptyKey,
        child: Padding(
          padding: EdgeInsets.all(AppTokens.space24),
          child: Text(
            'Nenhuma regra criada ainda. Crie uma regra para classificar '
            'automaticamente lançamentos recorrentes.',
          ),
        ),
      );
    }
    final index = _safeIndex(state.categories);
    final accounts = {
      for (final account in state.accounts) account.accountId: account,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final rule in state.rules)
          Padding(
            padding: const EdgeInsets.only(bottom: AppTokens.space12),
            child: _RuleCard(
              rule: rule,
              categoryLabel: _categoryLabel(index, rule.targetCategoryId),
              accountLabel: rule.accountId == null
                  ? 'Todas as contas'
                  : (accounts[rule.accountId]?.name ?? 'Conta indisponível'),
              canDisable:
                  rule.isActive &&
                  !state.isBusy &&
                  state.trusted &&
                  operatorId != null &&
                  operatorId == rule.createdByOperatorId,
              onDisable: () => onDisable(rule),
            ),
          ),
      ],
    );
  }
}

FinancialCategoryIndex _safeIndex(List<FinancialCategory> categories) {
  try {
    return FinancialCategoryIndex.build(categories);
  } on FormatException {
    return FinancialCategoryIndex.empty;
  }
}

String _categoryLabel(FinancialCategoryIndex index, String categoryId) {
  final category = index.byId(categoryId);
  final path = index.pathLabel(categoryId);
  if (category == null || path == null) return 'Categoria indisponível';
  return category.isActive ? path : '$path (indisponível)';
}

class _RuleCard extends StatelessWidget {
  const _RuleCard({
    required this.rule,
    required this.categoryLabel,
    required this.accountLabel,
    required this.canDisable,
    required this.onDisable,
  });

  final FinancialCategorizationRule rule;
  final String categoryLabel;
  final String accountLabel;
  final bool canDisable;
  final VoidCallback onDisable;

  @override
  Widget build(BuildContext context) {
    final matcher = switch (rule.matcher) {
      FinancialCategorizationMatcher.exact => 'A descrição é igual a',
      FinancialCategorizationMatcher.contains => 'A descrição contém',
    };
    final effect = switch (rule.resultEffect) {
      FinancialResultEffect.income => 'Somente receitas',
      FinancialResultEffect.expense => 'Somente despesas',
      _ => 'Receitas e despesas',
    };
    return Card(
      key: FinancialCategorizationRulesScreen.ruleKey(rule.ruleId),
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: AppTokens.space16,
          runSpacing: AppTokens.space12,
          children: [
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 600),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '$matcher “${rule.pattern}”',
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: AppTokens.space4),
                  Text(
                    'Categoria: $categoryLabel · Prioridade ${rule.priority}',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: AppTokens.space4),
                  Text(
                    '$accountLabel · $effect',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: AppTokens.space4),
                  Text(
                    rule.isActive ? 'Ativa' : 'Desabilitada',
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: rule.isActive
                          ? AppTokens.forest700
                          : AppTokens.neutral700,
                    ),
                  ),
                ],
              ),
            ),
            if (rule.isActive)
              OutlinedButton.icon(
                key: FinancialCategorizationRulesScreen.disableKey(rule.ruleId),
                onPressed: canDisable ? onDisable : null,
                icon: const Icon(Icons.block_rounded),
                label: const Text('Desabilitar'),
              ),
          ],
        ),
      ),
    );
  }
}

class _PhaseCard extends StatelessWidget {
  const _PhaseCard({required this.phase, required this.onRetry});

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
              Expanded(child: Text('Carregando regras…')),
            ],
          ),
        ),
      );
    }
    final (title, description, retry) = switch (phase) {
      FinancialLoadPhase.authenticationRequired => (
        'Sessão necessária',
        'Entre novamente para acessar as regras.',
        false,
      ),
      FinancialLoadPhase.forbidden => (
        'Acesso não permitido',
        'Sua sessão não possui acesso às regras.',
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
        'Não foi possível carregar as regras agora.',
        true,
      ),
    };
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: AppTokens.space8),
            Text(description),
            if (retry) ...[
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

class _RuleCreateDialog extends StatefulWidget {
  const _RuleCreateDialog({
    required this.categories,
    required this.accounts,
    required this.operatorId,
  });

  final List<FinancialCategory> categories;
  final List<FinancialAccount> accounts;
  final String operatorId;

  @override
  State<_RuleCreateDialog> createState() => _RuleCreateDialogState();
}

class _RuleCreateDialogState extends State<_RuleCreateDialog> {
  final _formKey = GlobalKey<FormState>();
  final _pattern = TextEditingController();
  final _priority = TextEditingController(text: '10');
  FinancialCategorizationMatcher _matcher =
      FinancialCategorizationMatcher.contains;
  String? _categoryId;
  String? _accountId;
  FinancialResultEffect? _effect;

  @override
  void dispose() {
    _pattern.dispose();
    _priority.dispose();
    super.dispose();
  }

  List<FinancialAccount> get _ownedAccounts => widget.accounts
      .where(
        (account) =>
            account.status == FinancialAccountStatus.active &&
            account.ownerOperatorId == widget.operatorId,
      )
      .toList(growable: false);

  /// ACTIVE categories the backend would accept as a target: HOUSEHOLD, or the
  /// operator's own PERSONAL one; with an account, the account's audience matrix.
  List<FinancialCategory> get _eligibleCategories {
    final index = _safeIndex(widget.categories);
    final selected = _accountId == null
        ? null
        : _ownedAccounts
              .where((item) => item.accountId == _accountId)
              .firstOrNull;
    final eligible = index.all.where((category) {
      if (!category.isActive) return false;
      if (selected != null) {
        return isFinancialCategoryEligibleForAccount(
          category: category,
          account: selected,
        );
      }
      return category.visibilityScope == FinancialVisibilityScope.household ||
          (category.visibilityScope == FinancialVisibilityScope.personal &&
              category.ownerOperatorId == widget.operatorId);
    }).toList();
    eligible.sort(
      (a, b) => (index.pathLabel(a.categoryId) ?? a.name)
          .toLowerCase()
          .compareTo((index.pathLabel(b.categoryId) ?? b.name).toLowerCase()),
    );
    return eligible;
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false) || _categoryId == null) {
      return;
    }
    try {
      Navigator.of(context).pop(
        FinancialCategorizationRuleCreateInput(
          matcher: _matcher,
          pattern: _pattern.text,
          targetCategoryId: _categoryId!,
          priority: int.parse(_priority.text.trim()),
          accountId: _accountId,
          resultEffect: _effect,
        ),
      );
    } on FormatException {
      setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) {
    final index = _safeIndex(widget.categories);
    final categories = _eligibleCategories;
    final categoryValue =
        categories.any((item) => item.categoryId == _categoryId)
        ? _categoryId
        : null;
    return AlertDialog(
      key: FinancialCategorizationRulesScreen.dialogKey,
      title: const Text('Nova regra de categorização'),
      content: SizedBox(
        width: 480,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextFormField(
                  key: FinancialCategorizationRulesScreen.patternFieldKey,
                  controller: _pattern,
                  maxLength: financialCategorizationPatternMaxLength,
                  decoration: const InputDecoration(
                    labelText: 'Texto da descrição',
                    helperText:
                        'Maiúsculas e minúsculas são ignoradas; acentos e '
                        'pontuação contam.',
                  ),
                  validator: _validatePattern,
                ),
                const SizedBox(height: AppTokens.space8),
                RadioGroup<FinancialCategorizationMatcher>(
                  groupValue: _matcher,
                  onChanged: (value) {
                    if (value != null) setState(() => _matcher = value);
                  },
                  child: const Column(
                    children: [
                      RadioListTile<FinancialCategorizationMatcher>(
                        key: FinancialCategorizationRulesScreen
                            .matcherContainsKey,
                        value: FinancialCategorizationMatcher.contains,
                        title: Text('A descrição contém o texto'),
                      ),
                      RadioListTile<FinancialCategorizationMatcher>(
                        key: FinancialCategorizationRulesScreen.matcherExactKey,
                        value: FinancialCategorizationMatcher.exact,
                        title: Text('A descrição é exatamente o texto'),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: AppTokens.space8),
                DropdownButtonFormField<String?>(
                  key: FinancialCategorizationRulesScreen.accountFieldKey,
                  initialValue: _accountId,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Conta'),
                  items: [
                    const DropdownMenuItem<String?>(
                      value: null,
                      child: Text('Todas as minhas contas'),
                    ),
                    for (final account in _ownedAccounts)
                      DropdownMenuItem<String?>(
                        value: account.accountId,
                        child: Text(account.name),
                      ),
                  ],
                  onChanged: (value) => setState(() {
                    _accountId = value;
                    _categoryId = null;
                  }),
                ),
                const SizedBox(height: AppTokens.space8),
                DropdownButtonFormField<FinancialResultEffect?>(
                  key: FinancialCategorizationRulesScreen.effectFieldKey,
                  initialValue: _effect,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Tipo'),
                  items: const [
                    DropdownMenuItem<FinancialResultEffect?>(
                      value: null,
                      child: Text('Receitas e despesas'),
                    ),
                    DropdownMenuItem<FinancialResultEffect?>(
                      value: FinancialResultEffect.income,
                      child: Text('Somente receitas'),
                    ),
                    DropdownMenuItem<FinancialResultEffect?>(
                      value: FinancialResultEffect.expense,
                      child: Text('Somente despesas'),
                    ),
                  ],
                  onChanged: (value) => setState(() => _effect = value),
                ),
                const SizedBox(height: AppTokens.space8),
                // Rebuilt whenever the account changes: the eligible targets
                // depend on the account audience.
                KeyedSubtree(
                  key: ValueKey('financial-rule-category-for-$_accountId'),
                  child: DropdownButtonFormField<String>(
                    key: FinancialCategorizationRulesScreen.categoryFieldKey,
                    initialValue: categoryValue,
                    isExpanded: true,
                    decoration: const InputDecoration(
                      labelText: 'Categoria de destino',
                    ),
                    items: [
                      for (final category in categories)
                        DropdownMenuItem<String>(
                          value: category.categoryId,
                          child: Text(
                            index.pathLabel(category.categoryId) ??
                                category.name,
                          ),
                        ),
                    ],
                    onChanged: (value) => setState(() => _categoryId = value),
                    validator: (value) =>
                        value == null ? 'Escolha uma categoria ativa.' : null,
                  ),
                ),
                const SizedBox(height: AppTokens.space8),
                TextFormField(
                  key: FinancialCategorizationRulesScreen.priorityFieldKey,
                  controller: _priority,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Prioridade (1 a 1000)',
                    helperText:
                        'Vence a de maior prioridade. Empate: nada é '
                        'classificado.',
                  ),
                  validator: _validatePriority,
                ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialCategorizationRulesScreen.submitKey,
          onPressed: _submit,
          child: const Text('Criar regra'),
        ),
      ],
    );
  }
}

String? _validatePattern(String? value) {
  final trimmed = (value ?? '').trim();
  if (trimmed.isEmpty ||
      trimmed.runes.length > financialCategorizationPatternMaxLength ||
      trimmed.codeUnits.any((unit) => unit < 32 || unit == 127)) {
    return 'Informe um texto válido de até 256 caracteres.';
  }
  return null;
}

String? _validatePriority(String? value) {
  final source = (value ?? '').trim();
  final parsed = RegExp(r'^[0-9]{1,4}$').hasMatch(source)
      ? int.tryParse(source)
      : null;
  if (parsed == null ||
      parsed < financialCategorizationPriorityMin ||
      parsed > financialCategorizationPriorityMax) {
    return 'Informe um número de 1 a 1000.';
  }
  return null;
}
