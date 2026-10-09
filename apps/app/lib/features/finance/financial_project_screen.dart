import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';
import 'package:meufinanceiro_app/features/finance/financial_project_controller.dart';
import 'package:meufinanceiro_app/routing/app_routes.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Projects #262. Existing expenses only: categorization does not post a
/// Movement or reserve funds. Values are read from the server, never calculated
/// in the widget. Writes reconcile rather than patching the current screen.
class FinancialProjectScreen extends ConsumerStatefulWidget {
  const FinancialProjectScreen({super.key});

  static const titleKey = Key('financial-project-title');
  static const createKey = Key('financial-project-create');
  static const refreshKey = Key('financial-project-refresh');
  static const listKey = Key('financial-project-list');
  static const summaryKey = Key('financial-project-summary');
  static const emptyKey = Key('financial-project-empty');
  static const errorKey = Key('financial-project-error');
  static const noticeKey = Key('financial-project-analytic-notice');
  static const conflictKey = Key('financial-project-conflict');
  static const readOnlyKey = Key('financial-project-readonly');
  static const editKey = Key('financial-project-edit');
  static Key projectKey(String id) => Key('financial-project-row-$id');

  @override
  ConsumerState<FinancialProjectScreen> createState() =>
      _FinancialProjectScreenState();
}

class _FinancialProjectScreenState
    extends ConsumerState<FinancialProjectScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        unawaited(
          ref.read(financialProjectsControllerProvider.notifier).load(),
        );
      }
    });
  }

  Future<void> _openEditor(FinancialProject? project) async {
    final result = await showDialog<Object>(
      context: context,
      builder: (_) => _ProjectEditorDialog(project: project),
    );
    if (result == null || !mounted) return;
    final ctl = ref.read(financialProjectsControllerProvider.notifier);
    FinancialProjectWriteOutcome outcome;
    if (result is FinancialProjectCreateInput) {
      outcome = await ctl.create(result);
    } else if (result is FinancialProjectReplaceInput && project != null) {
      outcome = await ctl.replace(project.id, result);
    } else {
      return;
    }
    if (!mounted) return;
    final message = switch (outcome) {
      FinancialProjectWriteOutcome.confirmed =>
        'Operação confirmada. Dados reconciliados com o servidor.',
      FinancialProjectWriteOutcome.conflict =>
        'O projeto mudou. Confira a versão atual antes de editar.',
      FinancialProjectWriteOutcome.rejected =>
        'O servidor recusou a solicitação.',
      FinancialProjectWriteOutcome.readOnly =>
        'Você não tem permissão para alterar este projeto.',
      FinancialProjectWriteOutcome.notAllowed =>
        'Atualize os dados antes de tentar novamente.',
      FinancialProjectWriteOutcome.accessBlocked =>
        'Acesso à residência indisponível.',
      FinancialProjectWriteOutcome.unknown =>
        'Resultado incerto. Não repita a operação sem conferir os dados.',
    };
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(financialProjectsControllerProvider);
    final ctl = ref.read(financialProjectsControllerProvider.notifier);
    final isReady = state.loaded && state.trusted && !state.busy;
    final project = state.selected;
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
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                Text(
                  'Projetos financeiros',
                  key: FinancialProjectScreen.titleKey,
                  style: Theme.of(context).textTheme.headlineLarge,
                ),
              ],
            ),
            Wrap(
              spacing: AppTokens.space8,
              children: [
                OutlinedButton.icon(
                  onPressed: () => context.go(AppRoutes.financePath),
                  icon: const Icon(Icons.arrow_back),
                  label: const Text('Contas'),
                ),
                OutlinedButton.icon(
                  key: FinancialProjectScreen.refreshKey,
                  onPressed: state.busy ? null : () => unawaited(ctl.refresh()),
                  icon: const Icon(Icons.refresh),
                  label: const Text('Atualizar'),
                ),
                FilledButton.icon(
                  key: FinancialProjectScreen.createKey,
                  onPressed: isReady ? () => _openEditor(null) : null,
                  icon: const Icon(Icons.add),
                  label: const Text('Novo projeto'),
                ),
              ],
            ),
          ],
        ),
        const SizedBox(height: AppTokens.space16),
        Card(
          key: FinancialProjectScreen.noticeKey,
          child: const Padding(
            padding: EdgeInsets.all(AppTokens.space16),
            child: Text(
              'Um projeto apenas agrupa despesas existentes. Associar uma '
              'despesa não cria lançamento, não transfere e não bloqueia '
              'dinheiro. O realizado considera estornos integrais.',
            ),
          ),
        ),
        const SizedBox(height: AppTokens.space12),
        if (state.conflict)
          Card(
            key: FinancialProjectScreen.conflictKey,
            child: ListTile(
              title: const Text('Conflito detectado'),
              subtitle: const Text(
                'A versão anterior não foi aplicada. Revise o plano atual.',
              ),
              trailing: IconButton(
                tooltip: 'Dispensar aviso',
                onPressed: ctl.dismissConflict,
                icon: const Icon(Icons.close),
              ),
            ),
          ),
        if (!state.trusted)
          const Card(
            child: ListTile(
              title: Text('Dados ainda não reconciliados'),
              subtitle: Text(
                'As alterações estão bloqueadas até atualizar com sucesso.',
              ),
            ),
          ),
        if (state.phase == FinancialLoadPhase.loading ||
            state.phase == FinancialLoadPhase.idle)
          const Center(child: CircularProgressIndicator())
        else if (!state.loaded)
          Card(
            key: FinancialProjectScreen.errorKey,
            child: ListTile(
              title: const Text('Projetos indisponíveis'),
              subtitle: const Text('Confira o acesso e tente atualizar.'),
              trailing: TextButton(
                onPressed: () => unawaited(ctl.refresh()),
                child: const Text('Tentar novamente'),
              ),
            ),
          )
        else if (state.projects.isEmpty)
          const Card(
            key: FinancialProjectScreen.emptyKey,
            child: Padding(
              padding: EdgeInsets.all(AppTokens.space24),
              child: Text('Nenhum projeto cadastrado nesta residência.'),
            ),
          )
        else ...[
          Wrap(
            key: FinancialProjectScreen.listKey,
            spacing: AppTokens.space8,
            runSpacing: AppTokens.space8,
            children: [
              for (final item in state.projects)
                ChoiceChip(
                  key: FinancialProjectScreen.projectKey(item.id),
                  selected: item.id == state.selectedId,
                  label: Text(item.title),
                  onSelected: state.busy
                      ? null
                      : (_) => unawaited(ctl.select(item.id)),
                ),
            ],
          ),
          const SizedBox(height: AppTokens.space16),
          if (project != null)
            Card(
              key: FinancialProjectScreen.summaryKey,
              child: Padding(
                padding: const EdgeInsets.all(AppTokens.space16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      alignment: WrapAlignment.spaceBetween,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          project.title,
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                        if (project.canEdit)
                          TextButton.icon(
                            key: FinancialProjectScreen.editKey,
                            onPressed: isReady
                                ? () => _openEditor(project)
                                : null,
                            icon: const Icon(Icons.edit),
                            label: const Text('Editar plano'),
                          )
                        else
                          const Text(
                            'Somente leitura',
                            key: FinancialProjectScreen.readOnlyKey,
                          ),
                      ],
                    ),
                    Text(
                      project.visibilityScope ==
                              FinancialVisibilityScope.household
                          ? 'Projeto da residência'
                          : 'Projeto pessoal',
                    ),
                    const SizedBox(height: AppTokens.space8),
                    if (state.summary == null)
                      const LinearProgressIndicator()
                    else
                      _SummaryDetails(summary: state.summary!),
                  ],
                ),
              ),
            ),
        ],
      ],
    );
  }
}

class _SummaryDetails extends StatelessWidget {
  const _SummaryDetails({required this.summary});
  final FinancialProjectSummary summary;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: AppTokens.space24,
          runSpacing: AppTokens.space12,
          children: [
            _Figure('Planejado', formatFinancialMoney(summary.project.planned)),
            _Figure('Realizado', formatFinancialMoney(summary.realized)),
            _Figure('Restante', formatFinancialMoney(summary.remaining)),
            _Figure('Excedente', formatFinancialMoney(summary.excess)),
          ],
        ),
        const SizedBox(height: AppTokens.space12),
        Text(
          'Progresso: ${summary.progressPercent}% · '
          '${summary.progressStatus.wireValue}',
        ),
        const SizedBox(height: AppTokens.space12),
        Text(
          'Despesas associadas: ${summary.expenseCount}',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        if (summary.expenses.isEmpty)
          const Text('Nenhuma despesa vinculada.')
        else
          for (final expense in summary.expenses)
            ListTile(
              title: Text(expense.description ?? 'Despesa sem descrição'),
              subtitle: Text(
                '${expense.effectiveDate} · '
                '${expense.reversed ? 'Estornada integralmente' : 'Despesa original'}',
              ),
              trailing: Text(formatFinancialMoney(expense.realized)),
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
      Text(value, style: Theme.of(context).textTheme.titleMedium),
    ],
  );
}

class _ProjectEditorDialog extends StatefulWidget {
  const _ProjectEditorDialog({this.project});
  final FinancialProject? project;

  @override
  State<_ProjectEditorDialog> createState() => _ProjectEditorDialogState();
}

class _ProjectEditorDialogState extends State<_ProjectEditorDialog> {
  late final TextEditingController _title;
  late final TextEditingController _description;
  late final TextEditingController _currency;
  late final TextEditingController _planned;
  late final TextEditingController _date;
  late FinancialVisibilityScope _scope;
  String? _error;

  @override
  void initState() {
    super.initState();
    final existing = widget.project;
    _title = TextEditingController(text: existing?.title ?? '');
    _description = TextEditingController(text: existing?.description ?? '');
    _currency = TextEditingController(text: existing?.currency ?? 'BRL');
    _planned = TextEditingController(text: existing?.planned.amount ?? '');
    _date = TextEditingController(text: existing?.targetDate ?? '');
    _scope = existing?.visibilityScope ?? FinancialVisibilityScope.household;
  }

  @override
  void dispose() {
    _title.dispose();
    _description.dispose();
    _currency.dispose();
    _planned.dispose();
    _date.dispose();
    super.dispose();
  }

  void _submit() {
    try {
      final amount = normalizeFinancialMoneyInput(_planned.text.trim());
      final existing = widget.project;
      final date = _date.text.trim().isEmpty ? null : _date.text.trim();
      final result = existing == null
          ? FinancialProjectCreateInput(
              title: _title.text,
              description: _description.text,
              visibilityScope: _scope,
              currency: _currency.text,
              plannedAmount: amount,
              targetDate: date,
            )
          : FinancialProjectReplaceInput(
              expectedVersion: existing.version,
              title: _title.text,
              description: _description.text,
              currency: existing.currency,
              plannedAmount: amount,
              targetDate: date,
            );
      Navigator.pop(context, result);
    } on FormatException {
      setState(() => _error = 'Revise título, valor, moeda e prazo.');
    }
  }

  @override
  Widget build(BuildContext context) {
    final editing = widget.project != null;
    return AlertDialog(
      title: Text(editing ? 'Editar projeto' : 'Novo projeto'),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'O orçamento é planejamento. Despesas são vinculadas '
                'separadamente e não alteram o lançamento original.',
              ),
              TextField(
                controller: _title,
                maxLength: 96,
                decoration: const InputDecoration(labelText: 'Título'),
              ),
              TextField(
                controller: _description,
                maxLength: 280,
                decoration: const InputDecoration(
                  labelText: 'Descrição (opcional)',
                ),
              ),
              DropdownButtonFormField<FinancialVisibilityScope>(
                initialValue: _scope,
                items: const [
                  DropdownMenuItem(
                    value: FinancialVisibilityScope.personal,
                    child: Text('Pessoal'),
                  ),
                  DropdownMenuItem(
                    value: FinancialVisibilityScope.household,
                    child: Text('Residência'),
                  ),
                ],
                onChanged: editing
                    ? null
                    : (scope) {
                        if (scope != null) setState(() => _scope = scope);
                      },
                decoration: const InputDecoration(labelText: 'Visibilidade'),
              ),
              TextField(
                controller: _currency,
                readOnly: editing,
                maxLength: 3,
                decoration: const InputDecoration(
                  labelText: 'Moeda (ex.: BRL)',
                ),
              ),
              TextField(
                controller: _planned,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: const InputDecoration(labelText: 'Orçamento total'),
              ),
              TextField(
                controller: _date,
                decoration: const InputDecoration(
                  labelText: 'Prazo (opcional, AAAA-MM-DD)',
                ),
              ),
              if (_error != null) Text(_error!),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancelar'),
        ),
        FilledButton(onPressed: _submit, child: const Text('Salvar')),
      ],
    );
  }
}
