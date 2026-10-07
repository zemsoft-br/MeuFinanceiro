import 'package:flutter/material.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_controller.dart';
import 'package:meufinanceiro_app/features/finance/financial_recurrence_policy.dart';
import 'package:meufinanceiro_app/theme/components/app_badge.dart';
import 'package:meufinanceiro_app/theme/tokens.dart';

/// "Sugestões" (#256): monthly patterns the server derived from realized Movements.
///
/// A suggestion is not a Movement, an occurrence or a recurrence and never changes
/// a balance. The only actions are an explicit **Criar recorrência** (opens a
/// review of every field; the server creates one canonical recurrence) and an
/// explicit **Dispensar** (personal: it never affects other members). The section
/// detects nothing and computes nothing: it shows what the server returned.
class FinancialRecurrenceSuggestionsSection extends StatelessWidget {
  const FinancialRecurrenceSuggestionsSection({
    required this.state,
    required this.writable,
    required this.onCreate,
    required this.onDismiss,
    super.key,
  });

  final FinancialRecurrencesState state;
  final bool writable;
  final ValueChanged<FinancialRecurrenceSuggestion> onCreate;
  final ValueChanged<FinancialRecurrenceSuggestion> onDismiss;

  static const sectionKey = Key('financial-suggestions');
  static const noticeKey = Key('financial-suggestions-notice');
  static const emptyKey = Key('financial-suggestions-empty');
  static const unavailableKey = Key('financial-suggestions-unavailable');
  static Key cardKey(String fingerprint) =>
      Key('financial-suggestion-$fingerprint');
  static Key patternKey(String fingerprint) =>
      Key('financial-suggestion-pattern-$fingerprint');
  static Key evidenceKey(String fingerprint) =>
      Key('financial-suggestion-evidence-$fingerprint');
  static Key amountKey(String fingerprint) =>
      Key('financial-suggestion-amount-$fingerprint');
  static Key reasonsKey(String fingerprint) =>
      Key('financial-suggestion-reasons-$fingerprint');
  static Key behaviorKey(String fingerprint) =>
      Key('financial-suggestion-behavior-$fingerprint');
  static Key readOnlyKey(String fingerprint) =>
      Key('financial-suggestion-readonly-$fingerprint');
  static Key createKey(String fingerprint) =>
      Key('financial-suggestion-create-$fingerprint');
  static Key dismissKey(String fingerprint) =>
      Key('financial-suggestion-dismiss-$fingerprint');
  static const dismissConfirmKey = Key('financial-suggestion-dismiss-confirm');
  static const dismissCancelKey = Key('financial-suggestion-dismiss-cancel');

  @override
  Widget build(BuildContext context) {
    final items = state.suggestions;
    return Column(
      key: sectionKey,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          header: true,
          child: Text(
            state.suggestionsUnavailable
                ? 'Sugestões'
                : 'Sugestões (${items.length})',
            style: Theme.of(context).textTheme.titleLarge,
          ),
        ),
        const SizedBox(height: AppTokens.space8),
        const Text(financialRecurrenceSuggestionNotice, key: noticeKey),
        const SizedBox(height: AppTokens.space12),
        if (state.suggestionsUnavailable)
          const Card(
            key: unavailableKey,
            child: Padding(
              padding: EdgeInsets.all(AppTokens.space16),
              child: Text(
                'Não foi possível carregar as sugestões agora. As suas '
                'recorrências abaixo não foram afetadas. Use Atualizar para '
                'tentar de novo; nada é reenviado automaticamente.',
              ),
            ),
          )
        else if (items.isEmpty)
          const Text(
            'Nenhum padrão mensal detectado nos últimos 12 meses.',
            key: emptyKey,
          )
        else
          for (final item in items) ...[
            _SuggestionCard(
              item: item,
              accountName: state.accountById(item.accountId)?.name,
              writable: writable,
              onCreate: () => onCreate(item),
              onDismiss: () => onDismiss(item),
            ),
            const SizedBox(height: AppTokens.space12),
          ],
      ],
    );
  }
}

class _SuggestionCard extends StatelessWidget {
  const _SuggestionCard({
    required this.item,
    required this.accountName,
    required this.writable,
    required this.onCreate,
    required this.onDismiss,
  });

  final FinancialRecurrenceSuggestion item;
  final String? accountName;
  final bool writable;
  final VoidCallback onCreate;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final fingerprint = item.fingerprint;
    return Card(
      key: FinancialRecurrenceSuggestionsSection.cardKey(fingerprint),
      child: Padding(
        padding: const EdgeInsets.all(AppTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Wrap(
              spacing: AppTokens.space8,
              runSpacing: AppTokens.space8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                Text(
                  item.description,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                AppBadge(
                  key: FinancialRecurrenceSuggestionsSection.behaviorKey(
                    fingerprint,
                  ),
                  label: item.isVariable ? 'Valor variável' : 'Valor fixo',
                  tone: item.isVariable
                      ? AppBadgeTone.warning
                      : AppBadgeTone.info,
                ),
                if (!item.canAccept)
                  AppBadge(
                    key: FinancialRecurrenceSuggestionsSection.readOnlyKey(
                      fingerprint,
                    ),
                    label: 'Somente leitura',
                    tone: AppBadgeTone.warning,
                  ),
              ],
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              '${accountName ?? 'Conta'} · ${item.currency} · despesa',
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
            ),
            Text(
              financialSuggestionPatternLabel(item),
              key: FinancialRecurrenceSuggestionsSection.patternKey(
                fingerprint,
              ),
            ),
            const SizedBox(height: AppTokens.space8),
            Text(
              item.isVariable
                  ? 'Valor variável: de ${formatFinancialMoney(item.minAmount)} '
                        'a ${formatFinancialMoney(item.maxAmount)}; último '
                        '${formatFinancialMoney(item.lastAmount)}. A '
                        'recorrência usará ${formatFinancialMoney(item.suggestedExpectedAmount)} '
                        'como previsão (você pode mudar).'
                  : 'Valor fixo: ${formatFinancialMoney(item.suggestedExpectedAmount)}.',
              key: FinancialRecurrenceSuggestionsSection.amountKey(fingerprint),
            ),
            const SizedBox(height: AppTokens.space8),
            Column(
              key: FinancialRecurrenceSuggestionsSection.evidenceKey(
                fingerprint,
              ),
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Cobranças observadas',
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                for (final entry in item.evidence)
                  Text(
                    '${financialRecurrenceDateLabel(entry.effectiveDate)} · '
                    '${formatFinancialMoney(entry.amount)}',
                  ),
              ],
            ),
            const SizedBox(height: AppTokens.space8),
            Column(
              key: FinancialRecurrenceSuggestionsSection.reasonsKey(
                fingerprint,
              ),
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Por que sugerimos',
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                for (final reason in item.reasonCodes)
                  Text('• ${financialSuggestionReasonLabel(reason)}'),
              ],
            ),
            if (!item.canAccept)
              Padding(
                padding: const EdgeInsets.only(top: AppTokens.space8),
                child: Text(
                  'Você pode ver esta sugestão, mas só quem é dono da conta '
                  'pode criar a recorrência. Dispensar vale só para você.',
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: AppTokens.neutral700),
                ),
              ),
            const SizedBox(height: AppTokens.space12),
            Wrap(
              spacing: AppTokens.space8,
              runSpacing: AppTokens.space8,
              children: [
                if (item.canAccept)
                  FilledButton.icon(
                    key: FinancialRecurrenceSuggestionsSection.createKey(
                      fingerprint,
                    ),
                    onPressed: writable ? onCreate : null,
                    icon: const Icon(Icons.add_rounded),
                    label: const Text('Criar recorrência'),
                  ),
                OutlinedButton.icon(
                  key: FinancialRecurrenceSuggestionsSection.dismissKey(
                    fingerprint,
                  ),
                  onPressed: writable ? onDismiss : null,
                  icon: const Icon(Icons.visibility_off_outlined),
                  label: const Text('Dispensar'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
