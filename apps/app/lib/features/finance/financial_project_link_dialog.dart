import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// Opens on a single Movement: no one-GET-per-row load in the statement.
///
/// The account and Movement are already read from the canonical account
/// detail. Only the backend decides if an expense can be associated. The
/// returned intent contains the *observed* current predecessor, never a
/// locally assumed revision, and the caller must send it once and re-read.
class FinancialProjectLinkDialog extends ConsumerStatefulWidget {
  const FinancialProjectLinkDialog({
    required this.account,
    required this.movement,
    super.key,
  });

  final FinancialAccount account;
  final FinancialMovement movement;

  static const dialogKey = Key('financial-project-link-dialog');
  static const projectKey = Key('financial-project-link-project');
  static const unlinkKey = Key('financial-project-link-unlink');
  static const saveKey = Key('financial-project-link-save');
  static const errorKey = Key('financial-project-link-error');
  static const loadingKey = Key('financial-project-link-loading');
  static const currentKey = Key('financial-project-link-current');
  static const historyKey = Key('financial-project-link-history');

  @override
  ConsumerState<FinancialProjectLinkDialog> createState() =>
      _FinancialProjectLinkDialogState();
}

class _FinancialProjectLinkDialogState
    extends ConsumerState<FinancialProjectLinkDialog> {
  bool _loading = true;
  bool _historyLoading = false;
  String? _loadError;
  List<FinancialProject> _eligible = const [];
  FinancialProjectLink? _current;
  String? _selected;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final api = ref.read(financialCoreApiProvider);
      // Exactly two reads per opened editor, never one per statement row.
      final projects = await api.listProjects();
      final link = await api.getProjectLink(widget.movement.movementId);
      if (!mounted) return;
      final candidates = projects
          .where(
            (project) =>
                project.canEdit &&
                project.ownerOperatorId == widget.account.ownerOperatorId &&
                project.visibilityScope == widget.account.visibilityScope &&
                project.currency == widget.account.currency,
          )
          .toList(growable: false);
      if (link?.projectId != null &&
          !candidates.any((p) => p.id == link!.projectId)) {
        setState(() {
          _loading = false;
          _loadError =
              'A associação atual não está disponível. Atualize a conta.';
        });
        return;
      }
      setState(() {
        _eligible = candidates;
        _current = link;
        _selected = link?.projectId;
        _loading = false;
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _loadError =
              'Não foi possível consultar projetos e associação atual.';
        });
      }
    }
  }

  bool get _isActive => widget.account.status == FinancialAccountStatus.active;

  bool get _canSave {
    if (_loading || _loadError != null) return false;
    if (_selected == _current?.projectId) return false;
    if (_selected == null && _current == null) return false;
    if (_selected != null && !_isActive) return false;
    return true;
  }

  void _confirm() {
    if (!_canSave) return;
    Navigator.of(context).pop(
      FinancialProjectLinkInput(
        projectId: _selected,
        expectedPredecessorId: _current?.id,
      ),
    );
  }

  /// History is an explicitly requested bounded GET, not a statement N+1.
  Future<void> _showHistory() async {
    if (_historyLoading || _current == null) return;
    setState(() => _historyLoading = true);
    try {
      final revisions = await ref
          .read(financialCoreApiProvider)
          .getProjectLinkHistory(widget.movement.movementId);
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Histórico de associação'),
          content: SizedBox(
            width: 520,
            child: ListView(
              shrinkWrap: true,
              children: [
                for (final revision in revisions)
                  ListTile(
                    title: Text(
                      revision.projectId == null
                          ? 'Revisão ${revision.revision} — desvinculado'
                          : 'Revisão ${revision.revision} — '
                                '${_projectTitle(revision.projectId!)}',
                    ),
                    subtitle: Text(
                      'Registrado em: ${revision.createdAt.toLocal()}',
                    ),
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Fechar'),
            ),
          ],
        ),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Não foi possível consultar o histórico.'),
        ),
      );
    } finally {
      if (mounted) setState(() => _historyLoading = false);
    }
  }

  String _projectTitle(String id) {
    for (final item in _eligible) {
      if (item.id == id) return item.title;
    }
    return 'Projeto indisponível';
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      key: FinancialProjectLinkDialog.dialogKey,
      title: const Text('Associar despesa a projeto'),
      content: SizedBox(
        width: 580,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              widget.movement.description ?? 'Despesa existente',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: AppTokens.space8),
            Text(formatFinancialMoney(widget.movement.money)),
            const SizedBox(height: AppTokens.space12),
            const Text(
              'A associação só organiza o realizado. Ela não altera o '
              'lançamento, saldo, orçamento mensal ou categoria.',
            ),
            const SizedBox(height: AppTokens.space16),
            if (_loading)
              const CircularProgressIndicator(
                key: FinancialProjectLinkDialog.loadingKey,
              )
            else if (_loadError != null)
              Text(_loadError!, key: FinancialProjectLinkDialog.errorKey)
            else ...[
              Text(
                _current?.projectId == null
                    ? 'Sem projeto associado.'
                    : 'Associação atual: ${_eligible.where((p) => p.id == _current!.projectId).first.title}',
                key: FinancialProjectLinkDialog.currentKey,
              ),
              const SizedBox(height: AppTokens.space8),
              if (_isActive && _eligible.isNotEmpty)
                DropdownButtonFormField<String?>(
                  key: FinancialProjectLinkDialog.projectKey,
                  initialValue: _selected,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Projeto'),
                  items: [
                    const DropdownMenuItem<String?>(
                      value: null,
                      child: Text('Nenhum projeto'),
                    ),
                    for (final project in _eligible)
                      DropdownMenuItem<String?>(
                        value: project.id,
                        child: Text(project.title),
                      ),
                  ],
                  onChanged: (value) => setState(() => _selected = value),
                ),
              if (!_isActive)
                const Text(
                  'Conta arquivada: só é possível desvincular '
                  'uma despesa anteriormente associada.',
                ),
              if (_eligible.isEmpty && _current == null)
                const Text(
                  'Nenhum projeto compatível. Crie um projeto do mesmo '
                  'proprietário, audiência e moeda.',
                ),
              if (_current != null)
                TextButton.icon(
                  key: FinancialProjectLinkDialog.historyKey,
                  onPressed: _historyLoading ? null : _showHistory,
                  icon: const Icon(Icons.history),
                  label: const Text('Ver histórico'),
                ),
              if (_current?.projectId != null)
                TextButton.icon(
                  key: FinancialProjectLinkDialog.unlinkKey,
                  onPressed: () => setState(() => _selected = null),
                  icon: const Icon(Icons.link_off),
                  label: const Text('Desvincular'),
                ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          key: FinancialProjectLinkDialog.saveKey,
          onPressed: _canSave ? _confirm : null,
          child: const Text('Confirmar'),
        ),
      ],
    );
  }
}
