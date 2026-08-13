import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class FinancialAccountCreateScreen extends ConsumerStatefulWidget {
  const FinancialAccountCreateScreen({super.key});

  static const titleKey = Key('financial-account-create-title');
  static const nameFieldKey = Key('financial-account-create-name');
  static const typeFieldKey = Key('financial-account-create-type');
  static const customTypeFieldKey = Key('financial-account-create-custom-type');
  static const currencyFieldKey = Key('financial-account-create-currency');
  static const visibilityFieldKey = Key('financial-account-create-visibility');
  static const submitButtonKey = Key('financial-account-create-submit');

  @override
  ConsumerState<FinancialAccountCreateScreen> createState() =>
      _FinancialAccountCreateScreenState();
}

class _FinancialAccountCreateScreenState
    extends ConsumerState<FinancialAccountCreateScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _customTypeController = TextEditingController();
  final _currencyController = TextEditingController(text: 'BRL');
  final _headingFocusNode = FocusNode(debugLabel: 'financial-account-create-heading');
  FinancialAccountType _type = FinancialAccountType.checking;
  FinancialVisibilityScope _visibility = FinancialVisibilityScope.personal;
  bool _submitting = false;
  String? _submissionError;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _headingFocusNode.requestFocus();
    });
  }

  @override
  void dispose() {
    _nameController.dispose();
    _customTypeController.dispose();
    _currencyController.dispose();
    _headingFocusNode.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_submitting || !(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _submitting = true;
      _submissionError = null;
    });
    try {
      final input = FinancialAccountCreateInput(
        name: _nameController.text.trim(),
        accountType: _type,
        currency: _currencyController.text,
        visibilityScope: _visibility,
        customTypeName: _type == FinancialAccountType.custom
            ? _customTypeController.text.trim()
            : null,
      );
      final account = await ref
          .read(financialAccountsControllerProvider.notifier)
          .createAccount(input);
      if (!mounted) return;
      context.go(AppRoutes.financeAccountDetailLocation(account.accountId));
    } on FormatException {
      if (mounted) {
        setState(() => _submissionError = 'Revise os dados informados.');
      }
    } on AuthenticatedApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _submissionError = switch (financialPhaseForFailure(error)) {
          FinancialLoadPhase.authenticationRequired => 'Sua sessão expirou. Entre novamente.',
          FinancialLoadPhase.forbidden => 'Sua sessão não pode criar esta conta.',
          FinancialLoadPhase.primaryResidenceRequired =>
            'Configure uma residência principal antes de criar a conta.',
          _ => 'Não foi possível criar a conta agora.',
        };
      });
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final custom = _type == FinancialAccountType.custom;
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
          const SizedBox(height: AppTokens.space16),
          Focus(
            focusNode: _headingFocusNode,
            child: Semantics(
              header: true,
              child: Text(
                'Nova conta financeira',
                key: FinancialAccountCreateScreen.titleKey,
                style: Theme.of(context).textTheme.headlineLarge,
              ),
            ),
          ),
          const SizedBox(height: AppTokens.space8),
          Text(
            'Cadastre somente a identidade da conta. Saldo inicial é informado separadamente e saldo corrente não é editável.',
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
              color: AppTokens.neutral700,
            ),
          ),
          const SizedBox(height: AppTokens.space24),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppTokens.space24),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextFormField(
                      key: FinancialAccountCreateScreen.nameFieldKey,
                      controller: _nameController,
                      maxLength: 96,
                      decoration: const InputDecoration(
                        labelText: 'Nome da conta',
                        helperText: 'Ex.: Conta principal, Carteira, Poupança',
                      ),
                      validator: (value) {
                        final normalized = value?.trim() ?? '';
                        return normalized.isEmpty ? 'Informe o nome da conta.' : null;
                      },
                    ),
                    const SizedBox(height: AppTokens.space16),
                    DropdownButtonFormField<FinancialAccountType>(
                      key: FinancialAccountCreateScreen.typeFieldKey,
                      initialValue: _type,
                      decoration: const InputDecoration(labelText: 'Tipo de conta'),
                      items: FinancialAccountType.values
                          .map(
                            (type) => DropdownMenuItem(
                              value: type,
                              child: Text(_typeLabel(type)),
                            ),
                          )
                          .toList(),
                      onChanged: _submitting
                          ? null
                          : (value) {
                              if (value != null) setState(() => _type = value);
                            },
                    ),
                    if (custom) ...[
                      const SizedBox(height: AppTokens.space16),
                      TextFormField(
                        key: FinancialAccountCreateScreen.customTypeFieldKey,
                        controller: _customTypeController,
                        maxLength: 96,
                        decoration: const InputDecoration(
                          labelText: 'Nome do tipo personalizado',
                        ),
                        validator: (value) {
                          if (!custom) return null;
                          return (value?.trim().isEmpty ?? true)
                              ? 'Informe o tipo personalizado.'
                              : null;
                        },
                      ),
                    ],
                    const SizedBox(height: AppTokens.space16),
                    TextFormField(
                      key: FinancialAccountCreateScreen.currencyFieldKey,
                      controller: _currencyController,
                      maxLength: 3,
                      textCapitalization: TextCapitalization.characters,
                      decoration: const InputDecoration(
                        labelText: 'Moeda',
                        helperText: 'Código ISO de três letras, como BRL ou USD',
                      ),
                      validator: (value) {
                        final normalized = value ?? '';
                        return RegExp(r'^[A-Z]{3}$').hasMatch(normalized)
                            ? null
                            : 'Informe uma moeda válida em letras maiúsculas.';
                      },
                    ),
                    const SizedBox(height: AppTokens.space16),
                    DropdownButtonFormField<FinancialVisibilityScope>(
                      key: FinancialAccountCreateScreen.visibilityFieldKey,
                      initialValue: _visibility,
                      decoration: const InputDecoration(labelText: 'Visibilidade'),
                      items: FinancialVisibilityScope.values
                          .map(
                            (scope) => DropdownMenuItem(
                              value: scope,
                              child: Text(_visibilityLabel(scope)),
                            ),
                          )
                          .toList(),
                      onChanged: _submitting
                          ? null
                          : (value) {
                              if (value != null) setState(() => _visibility = value);
                            },
                    ),
                    if (_submissionError != null) ...[
                      const SizedBox(height: AppTokens.space16),
                      Semantics(
                        liveRegion: true,
                        child: Text(
                          _submissionError!,
                          style: TextStyle(color: Theme.of(context).colorScheme.error),
                        ),
                      ),
                    ],
                    const SizedBox(height: AppTokens.space24),
                    Align(
                      alignment: Alignment.centerRight,
                      child: FilledButton.icon(
                        key: FinancialAccountCreateScreen.submitButtonKey,
                        onPressed: _submitting ? null : _submit,
                        icon: _submitting
                            ? const SizedBox.square(
                                dimension: 18,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.save_outlined),
                        label: Text(_submitting ? 'Salvando…' : 'Criar conta'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
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
  FinancialVisibilityScope.household => 'Toda a residência',
};
