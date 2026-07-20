import 'package:flutter/material.dart';
import 'package:meufinanceiro_app/theme/components/app_badge.dart';
import 'package:meufinanceiro_app/theme/components/app_state_panel.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

class ComponentsCatalogScreen extends StatefulWidget {
  const ComponentsCatalogScreen({super.key});

  static const titleKey = Key('components-title');
  static const residenceFieldKey = Key('residence-name-field');
  static const cycleFieldKey = Key('cycle-start-field');
  static const submitKey = Key('preferences-submit');
  static const successKey = Key('preferences-success');

  @override
  State<ComponentsCatalogScreen> createState() =>
      _ComponentsCatalogScreenState();
}

class _ComponentsCatalogScreenState extends State<ComponentsCatalogScreen> {
  final _formKey = GlobalKey<FormState>();
  final _residenceController = TextEditingController();
  int _cycleStart = 1;
  bool _validated = false;

  static const _allowedCycleDays = [1, 5, 10, 15, 20, 25, 28];

  @override
  void dispose() {
    _residenceController.dispose();
    super.dispose();
  }

  String? _validateResidence(String? rawValue) {
    final value = rawValue?.trim() ?? '';
    if (value.isEmpty) {
      return 'Informe o nome da residência.';
    }
    if (value.length < 3) {
      return 'Use pelo menos 3 caracteres.';
    }
    if (value.length > 60) {
      return 'Use no máximo 60 caracteres.';
    }
    return null;
  }

  String? _validateCycleDay(int? value) {
    if (value == null || !_allowedCycleDays.contains(value)) {
      return 'Selecione um dia inicial válido.';
    }
    return null;
  }

  void _submit() {
    FocusManager.instance.primaryFocus?.unfocus();
    final valid = _formKey.currentState?.validate() ?? false;
    setState(() => _validated = valid);
  }

  void _markDirty([Object? _]) {
    if (_validated) {
      setState(() => _validated = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _PageHeader(
          eyebrow: 'Design system inicial',
          title: 'Componentes e estados comuns',
          description:
              'Referência para manter contribuições consistentes, acessíveis '
              'e previsíveis.',
          titleKey: ComponentsCatalogScreen.titleKey,
        ),
        const SizedBox(height: AppTokens.space32),
        _DocumentationCard(
          title: 'Ações',
          description:
              'Hierarquia visual para decisões primárias, secundárias e '
              'destrutivas.',
          child: Wrap(
            spacing: AppTokens.space12,
            runSpacing: AppTokens.space12,
            children: [
              FilledButton(
                onPressed: () {},
                child: const Text('Salvar alterações'),
              ),
              OutlinedButton(
                onPressed: () {},
                child: const Text('Ação secundária'),
              ),
              TextButton(
                onPressed: () {},
                child: const Text('Ação discreta'),
              ),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: AppTokens.red700,
                  foregroundColor: AppTokens.white,
                ),
                onPressed: () {},
                child: const Text('Remover'),
              ),
              const FilledButton(
                onPressed: null,
                child: Text('Indisponível'),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppTokens.space20),
        const _DocumentationCard(
          title: 'Feedback e status',
          description:
              'Cores sempre acompanhadas por texto para não depender apenas '
              'da percepção visual.',
          child: Wrap(
            spacing: AppTokens.space12,
            runSpacing: AppTokens.space12,
            children: [
              AppBadge(label: 'Neutro'),
              AppBadge(
                label: 'Concluído',
                tone: AppBadgeTone.positive,
              ),
              AppBadge(
                label: 'Atenção',
                tone: AppBadgeTone.warning,
              ),
              AppBadge(
                label: 'Erro',
                tone: AppBadgeTone.negative,
              ),
              AppBadge(
                label: 'Informação',
                tone: AppBadgeTone.info,
              ),
            ],
          ),
        ),
        const SizedBox(height: AppTokens.space20),
        _DocumentationCard(
          title: 'Formulário e validação-base',
          description: 'Exemplo local; nenhum valor é enviado ou persistido.',
          child: Form(
            key: _formKey,
            autovalidateMode: AutovalidateMode.disabled,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 680),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TextFormField(
                    key: ComponentsCatalogScreen.residenceFieldKey,
                    controller: _residenceController,
                    decoration: const InputDecoration(
                      labelText: 'Nome da residência',
                      helperText: 'Entre 3 e 60 caracteres.',
                    ),
                    textInputAction: TextInputAction.next,
                    autofillHints: const [AutofillHints.organizationName],
                    maxLength: 60,
                    validator: _validateResidence,
                    onChanged: _markDirty,
                  ),
                  const SizedBox(height: AppTokens.space16),
                  DropdownButtonFormField<int>(
                    key: ComponentsCatalogScreen.cycleFieldKey,
                    initialValue: _cycleStart,
                    decoration: const InputDecoration(
                      labelText: 'Dia inicial do ciclo',
                    ),
                    items: _allowedCycleDays
                        .map(
                          (day) => DropdownMenuItem(
                            value: day,
                            child: Text('Dia $day'),
                          ),
                        )
                        .toList(),
                    onChanged: (value) {
                      if (value == null) {
                        return;
                      }
                      setState(() => _cycleStart = value);
                      _markDirty();
                    },
                    validator: _validateCycleDay,
                  ),
                  const SizedBox(height: AppTokens.space20),
                  Wrap(
                    spacing: AppTokens.space16,
                    runSpacing: AppTokens.space12,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      FilledButton(
                        key: ComponentsCatalogScreen.submitKey,
                        onPressed: _submit,
                        child: const Text('Validar preferências'),
                      ),
                      if (_validated)
                        Semantics(
                          key: ComponentsCatalogScreen.successKey,
                          liveRegion: true,
                          label: 'Validação concluída.',
                          child: const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                Icons.check_circle_rounded,
                                color: AppTokens.forest700,
                                semanticLabel: 'Sucesso',
                              ),
                              SizedBox(width: AppTokens.space8),
                              Text('Validação concluída.'),
                            ],
                          ),
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: AppTokens.space32),
        const _PageHeader(
          eyebrow: 'Estados reutilizáveis',
          title: 'Carregamento, vazio, erro e indisponibilidade',
          description:
              'Estados explícitos reduzem ambiguidade e não dependem apenas '
              'de cor.',
        ),
        const SizedBox(height: AppTokens.space20),
        LayoutBuilder(
          builder: (context, constraints) {
            final columns = constraints.maxWidth >= 1000
                ? 4
                : constraints.maxWidth >= 620
                    ? 2
                    : 1;
            final width = (constraints.maxWidth -
                    (columns - 1) * AppTokens.space16) /
                columns;

            const states = [
              AppStatePanel(
                kind: AppStateKind.loading,
                title: 'Carregando informações',
                description:
                    'Aguarde enquanto os dados necessários são consultados.',
                compact: true,
              ),
              AppStatePanel(
                kind: AppStateKind.empty,
                title: 'Nenhum item cadastrado',
                description:
                    'Quando houver conteúdo, ele será apresentado aqui.',
                compact: true,
              ),
              AppStatePanel(
                kind: AppStateKind.error,
                title: 'Não foi possível concluir',
                description:
                    'Revise os dados informados e tente novamente.',
                compact: true,
              ),
              AppStatePanel(
                kind: AppStateKind.unavailable,
                title: 'Serviço indisponível',
                description:
                    'A interface permanece acessível enquanto a conexão volta.',
                compact: true,
              ),
            ];

            return Wrap(
              spacing: AppTokens.space16,
              runSpacing: AppTokens.space16,
              children: states
                  .map((state) => SizedBox(width: width, child: state))
                  .toList(),
            );
          },
        ),
      ],
    );
  }
}

class _DocumentationCard extends StatelessWidget {
  const _DocumentationCard({
    required this.title,
    required this.description,
    required this.child,
  });

  final String title;
  final String description;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Semantics(
              header: true,
              child: Text(
                title,
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              description,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: AppTokens.neutral700,
                  ),
            ),
            const SizedBox(height: AppTokens.space20),
            child,
          ],
        ),
      ),
    );
  }
}

class _PageHeader extends StatelessWidget {
  const _PageHeader({
    required this.eyebrow,
    required this.title,
    required this.description,
    this.titleKey,
  });

  final String eyebrow;
  final String title;
  final String description;
  final Key? titleKey;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 760),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            eyebrow,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: AppTokens.forest700,
                ),
          ),
          const SizedBox(height: AppTokens.space4),
          Semantics(
            header: true,
            child: Text(
              title,
              key: titleKey,
              style: Theme.of(context).textTheme.headlineLarge,
            ),
          ),
          const SizedBox(height: AppTokens.space12),
          Text(
            description,
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: AppTokens.neutral700,
                ),
          ),
        ],
      ),
    );
  }
}
