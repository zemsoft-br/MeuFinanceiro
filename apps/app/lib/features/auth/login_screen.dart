import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/core/auth/operator_session.dart';
import 'package:meufinanceiro_app/core/auth/operator_session_controller.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({this.redirectTo, super.key});

  final String? redirectTo;

  static const loginFieldKey = Key('operator-login-field');
  static const passwordFieldKey = Key('operator-password-field');
  static const submitButtonKey = Key('operator-login-submit');
  static const passwordVisibilityKey = Key('operator-password-visibility');

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _loginController = TextEditingController();
  final _passwordController = TextEditingController();
  final _loginFocusNode = FocusNode(debugLabel: 'operator-login');
  final _passwordFocusNode = FocusNode(debugLabel: 'operator-password');
  bool _obscurePassword = true;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _loginFocusNode.requestFocus();
      }
    });
  }

  @override
  void dispose() {
    _passwordController.clear();
    _loginController.dispose();
    _passwordController.dispose();
    _loginFocusNode.dispose();
    _passwordFocusNode.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final session = ref.read(operatorSessionControllerProvider);
    if (session.isBusy || session.isAuthenticated) {
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) {
      return;
    }

    final login = _loginController.text;
    final password = _passwordController.text;
    try {
      await ref
          .read(operatorSessionControllerProvider.notifier)
          .login(login: login, password: password);
    } finally {
      _passwordController.clear();
    }

    if (!mounted) {
      return;
    }
    final updated = ref.read(operatorSessionControllerProvider);
    if (updated.isAuthenticated) {
      context.go(widget.redirectTo ?? '/');
      return;
    }
    if (updated.phase == OperatorSessionPhase.invalidCredentials) {
      _passwordFocusNode.requestFocus();
    }
  }

  void _continueAuthenticated() {
    context.go(widget.redirectTo ?? '/');
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(operatorSessionControllerProvider);
    final theme = Theme.of(context);

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(AppTokens.space16),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(AppTokens.space24),
                  child: session.isAuthenticated
                      ? _AuthenticatedContent(
                          session: session,
                          onContinue: _continueAuthenticated,
                          onLogout: () => ref
                              .read(operatorSessionControllerProvider.notifier)
                              .logout(),
                        )
                      : Form(
                          key: _formKey,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              const _BrandMark(),
                              const SizedBox(height: AppTokens.space24),
                              Text(
                                'Entrar no MeuFinanceiro',
                                style: theme.textTheme.headlineMedium,
                              ),
                              const SizedBox(height: AppTokens.space8),
                              Text(
                                'Use o operador local desta instalação. Sua sessão fica somente na memória deste aplicativo.',
                                style: theme.textTheme.bodyMedium?.copyWith(
                                  color: AppTokens.neutral700,
                                ),
                              ),
                              const SizedBox(height: AppTokens.space24),
                              TextFormField(
                                key: LoginScreen.loginFieldKey,
                                controller: _loginController,
                                focusNode: _loginFocusNode,
                                enabled: !session.isBusy,
                                textInputAction: TextInputAction.next,
                                autocorrect: false,
                                enableSuggestions: false,
                                decoration: const InputDecoration(
                                  labelText: 'Operador',
                                  hintText: 'Digite seu login',
                                  prefixIcon: Icon(
                                    Icons.person_outline_rounded,
                                  ),
                                ),
                                validator: (value) {
                                  final normalized = value?.trim() ?? '';
                                  if (normalized.length < 3 ||
                                      normalized.length > 64) {
                                    return 'Informe um operador válido.';
                                  }
                                  return null;
                                },
                                onFieldSubmitted: (_) {
                                  _passwordFocusNode.requestFocus();
                                },
                              ),
                              const SizedBox(height: AppTokens.space16),
                              TextFormField(
                                key: LoginScreen.passwordFieldKey,
                                controller: _passwordController,
                                focusNode: _passwordFocusNode,
                                enabled: !session.isBusy,
                                obscureText: _obscurePassword,
                                textInputAction: TextInputAction.done,
                                autocorrect: false,
                                enableSuggestions: false,
                                decoration: InputDecoration(
                                  labelText: 'Senha',
                                  prefixIcon: const Icon(
                                    Icons.lock_outline_rounded,
                                  ),
                                  suffixIcon: IconButton(
                                    key: LoginScreen.passwordVisibilityKey,
                                    tooltip: _obscurePassword
                                        ? 'Mostrar senha'
                                        : 'Ocultar senha',
                                    onPressed: session.isBusy
                                        ? null
                                        : () {
                                            setState(() {
                                              _obscurePassword =
                                                  !_obscurePassword;
                                            });
                                          },
                                    icon: Icon(
                                      _obscurePassword
                                          ? Icons.visibility_outlined
                                          : Icons.visibility_off_outlined,
                                    ),
                                  ),
                                ),
                                validator: (value) {
                                  if (value == null || value.isEmpty) {
                                    return 'Informe sua senha.';
                                  }
                                  return null;
                                },
                                onFieldSubmitted: (_) => _submit(),
                              ),
                              const SizedBox(height: AppTokens.space16),
                              _SessionMessage(session: session),
                              const SizedBox(height: AppTokens.space16),
                              FilledButton.icon(
                                key: LoginScreen.submitButtonKey,
                                onPressed: session.isBusy ? null : _submit,
                                icon:
                                    session.phase ==
                                        OperatorSessionPhase.authenticating
                                    ? const SizedBox.square(
                                        dimension: 18,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                        ),
                                      )
                                    : const Icon(Icons.login_rounded),
                                label: Text(
                                  session.phase ==
                                          OperatorSessionPhase.authenticating
                                      ? 'Entrando…'
                                      : 'Entrar',
                                ),
                              ),
                              const SizedBox(height: AppTokens.space16),
                              Text(
                                'O MeuFinanceiro não salva sua senha nem o token de sessão no navegador.',
                                textAlign: TextAlign.center,
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: AppTokens.neutral600,
                                ),
                              ),
                            ],
                          ),
                        ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _BrandMark extends StatelessWidget {
  const _BrandMark();

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 44,
          height: 44,
          decoration: const BoxDecoration(
            color: AppTokens.forest900,
            borderRadius: BorderRadius.all(
              Radius.circular(AppTokens.radiusSmall),
            ),
          ),
          child: const Icon(
            Icons.account_balance_wallet_outlined,
            color: AppTokens.white,
          ),
        ),
        const SizedBox(width: AppTokens.space12),
        Expanded(
          child: Text(
            'MeuFinanceiro',
            style: Theme.of(context).textTheme.titleLarge,
          ),
        ),
      ],
    );
  }
}

class _SessionMessage extends StatelessWidget {
  const _SessionMessage({required this.session});

  final OperatorSessionState session;

  @override
  Widget build(BuildContext context) {
    final message = switch (session.phase) {
      OperatorSessionPhase.invalidCredentials =>
        'Não foi possível entrar com essas credenciais.',
      OperatorSessionPhase.temporarilyUnavailable =>
        'A autenticação está temporariamente indisponível. Tente novamente.',
      OperatorSessionPhase.expiredOrRevoked =>
        'Sua sessão expirou ou foi encerrada. Entre novamente.',
      _ => null,
    };
    if (message == null) {
      return const SizedBox.shrink();
    }

    return Semantics(
      liveRegion: true,
      child: Container(
        padding: const EdgeInsets.all(AppTokens.space12),
        decoration: const BoxDecoration(
          color: AppTokens.red50,
          borderRadius: BorderRadius.all(
            Radius.circular(AppTokens.radiusSmall),
          ),
          border: Border.fromBorderSide(BorderSide(color: AppTokens.red100)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.error_outline_rounded, color: AppTokens.red700),
            const SizedBox(width: AppTokens.space8),
            Expanded(child: Text(message)),
          ],
        ),
      ),
    );
  }
}

class _AuthenticatedContent extends StatelessWidget {
  const _AuthenticatedContent({
    required this.session,
    required this.onContinue,
    required this.onLogout,
  });

  final OperatorSessionState session;
  final VoidCallback onContinue;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    final principal = session.principal!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const _BrandMark(),
        const SizedBox(height: AppTokens.space24),
        Text('Sessão ativa', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: AppTokens.space8),
        Text(
          'Conectado como ${principal.login}.',
          style: Theme.of(context).textTheme.bodyLarge,
        ),
        const SizedBox(height: AppTokens.space24),
        FilledButton(onPressed: onContinue, child: const Text('Continuar')),
        const SizedBox(height: AppTokens.space8),
        OutlinedButton(
          onPressed: session.isBusy ? null : onLogout,
          child: const Text('Encerrar sessão'),
        ),
      ],
    );
  }
}
