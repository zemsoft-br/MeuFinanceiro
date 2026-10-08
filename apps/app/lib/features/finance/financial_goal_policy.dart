import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_format.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';

/// Ergonomic mirror of the goal contract (ADR-0029). The backend stays the final
/// authority on audience, ownership, account eligibility, the CAS version, the
/// currency, availability and every amount; this only keeps obviously invalid
/// options out of the UI. It never computes an allocated amount, a remaining
/// value, a progress or a backing status.

/// Permanent text: an allocation is virtual. Shown wherever one can be made or
/// read, never only in a tooltip.
const financialGoalVirtualNotice =
    'Destinação virtual; não transfere nem bloqueia dinheiro.';

const financialGoalVirtualExplanation =
    'Destinar marca uma parte do saldo que já existe na conta como reservada '
    'para esta meta, apenas como organização. Nenhum dinheiro é movimentado, '
    'nenhum lançamento é criado e o saldo da conta não muda. Despesas '
    'posteriores continuam livres e podem deixar a meta sem lastro: isso é '
    'apenas avisado, nada é ajustado e não há garantia bancária.';

String financialGoalScopeLabel(FinancialVisibilityScope scope) =>
    switch (scope) {
      FinancialVisibilityScope.personal => 'Pessoal',
      FinancialVisibilityScope.household => 'Da casa',
      FinancialVisibilityScope.shared => 'Compartilhada',
    };

String financialGoalOperationLabel(FinancialGoalOperation operation) =>
    switch (operation) {
      FinancialGoalOperation.allocate => 'Destinação',
      FinancialGoalOperation.release => 'Liberação',
    };

/// Status text that never depends on colour.
String financialGoalProgressStatusLabel(FinancialGoalProgressStatus status) =>
    switch (status) {
      FinancialGoalProgressStatus.notStarted => 'Nada destinado ainda',
      FinancialGoalProgressStatus.inProgress => 'Em andamento',
      FinancialGoalProgressStatus.reached => 'Meta atingida',
      FinancialGoalProgressStatus.exceeded => 'Acima do alvo',
    };

String financialGoalBackingStatusLabel(FinancialGoalBackingStatus status) =>
    switch (status) {
      FinancialGoalBackingStatus.covered => 'Com lastro',
      FinancialGoalBackingStatus.insufficient => 'Destinações acima do saldo',
    };

/// Plain-text explanation of an account whose balance fell below what the goals
/// allocated on it. Reported, never repaired.
const financialGoalInsufficientBackingNotice =
    'Destinações acima do saldo atual: o saldo de pelo menos uma conta ficou '
    'abaixo do total destinado às metas. Nada foi ajustado, nenhuma destinação '
    'foi desfeita e isto não é uma garantia bancária. Novas destinações nessa '
    'conta ficam indisponíveis até o saldo cobrir o total; você ainda pode '
    'liberar valores.';

/// Fraction of the bar, `0..1`, from the server's `progressPercent` text using
/// integer parsing only (no money arithmetic, no `double` parsing of amounts).
double financialGoalProgressFraction(String progressPercent) {
  final digits = progressPercent.replaceAll('.', '');
  final hundredths = int.tryParse(digits);
  if (hundredths == null || hundredths < 0) return 0;
  if (hundredths >= 10000) return 1;
  return hundredths / 10000;
}

/// "30%" style label from the server text (drops a redundant `.00`).
String financialGoalProgressLabel(String progressPercent) {
  final trimmed = progressPercent.endsWith('.00')
      ? progressPercent.substring(0, progressPercent.length - 3)
      : progressPercent;
  return '$trimmed%';
}

/// Accounts a *new* allocation could use: same owner, same audience, same
/// currency and ACTIVE. `SHARED` is never eligible. This only filters the picker;
/// the server decides again (and also checks availability).
List<FinancialAccount> eligibleFinancialGoalAccounts({
  required FinancialGoal goal,
  required List<FinancialAccount> accounts,
}) => [
  for (final account in accounts)
    if (account.ownerOperatorId == goal.ownerOperatorId &&
        account.visibilityScope == goal.visibilityScope &&
        account.currency == goal.currency &&
        account.status == FinancialAccountStatus.active)
      account,
];

/// Accounts a release could use: those where the server says this goal holds a
/// value. Archived accounts stay releasable.
List<FinancialGoalAccountSummary> releasableFinancialGoalAccounts(
  FinancialGoalSummary summary,
) => [
  for (final account in summary.accounts)
    if (!account.allocated.isZero) account,
];

/// Why a goal draft cannot be sent. Empty when it can.
enum FinancialGoalDraftIssue {
  titleRequired,
  descriptionTooLong,
  currencyInvalid,
  targetInvalid,
  targetDateInvalid,
  targetDateOutOfRange,
}

final _dateInputPattern = RegExp(r'^([0-9]{4})-([0-9]{2})-([0-9]{2})$');

/// `YYYY-MM-DD` parsed with calendar validation, or null.
DateTime? parseFinancialGoalDate(String text) {
  final match = _dateInputPattern.firstMatch(text);
  if (match == null) return null;
  final year = int.parse(match.group(1)!);
  final month = int.parse(match.group(2)!);
  final day = int.parse(match.group(3)!);
  final date = DateTime.utc(year, month, day);
  if (date.year != year || date.month != month || date.day != day) return null;
  return date;
}

/// A new or changed target date must be between yesterday (a one-day timezone
/// tolerance) and 100 years ahead. Keeping the stored date is never revalidated.
bool isFinancialGoalTargetDateInRange(DateTime date, DateTime today) {
  final base = DateTime.utc(today.year, today.month, today.day);
  final earliest = base.subtract(const Duration(days: 1));
  final latest = DateTime.utc(today.year + 100, 12, 31);
  return !date.isBefore(earliest) && !date.isAfter(latest);
}

List<FinancialGoalDraftIssue> validateFinancialGoalDraft({
  required String title,
  required String description,
  required String currency,
  required String targetText,
  required String targetDateText,
  required DateTime today,
  String? existingTargetDate,
}) {
  final issues = <FinancialGoalDraftIssue>[];
  final trimmed = title.trim();
  if (trimmed.isEmpty || trimmed.length > financialGoalTitleMaxLength) {
    issues.add(FinancialGoalDraftIssue.titleRequired);
  }
  if (description.trim().length > financialGoalDescriptionMaxLength) {
    issues.add(FinancialGoalDraftIssue.descriptionTooLong);
  }
  if (!RegExp(r'^[A-Z]{3}$').hasMatch(currency)) {
    issues.add(FinancialGoalDraftIssue.currencyInvalid);
  }
  if (validateFinancialMoneyInput(targetText, requirePositive: true) != null) {
    issues.add(FinancialGoalDraftIssue.targetInvalid);
  }
  final dateText = targetDateText.trim();
  if (dateText.isNotEmpty && dateText != existingTargetDate) {
    final date = parseFinancialGoalDate(dateText);
    if (date == null) {
      issues.add(FinancialGoalDraftIssue.targetDateInvalid);
    } else if (!isFinancialGoalTargetDateInRange(date, today)) {
      issues.add(FinancialGoalDraftIssue.targetDateOutOfRange);
    }
  }
  return issues;
}

String financialGoalDraftIssueLabel(FinancialGoalDraftIssue issue) =>
    switch (issue) {
      FinancialGoalDraftIssue.titleRequired =>
        'Informe um título de até $financialGoalTitleMaxLength caracteres.',
      FinancialGoalDraftIssue.descriptionTooLong =>
        'A descrição pode ter no máximo $financialGoalDescriptionMaxLength '
            'caracteres.',
      FinancialGoalDraftIssue.currencyInvalid =>
        'Informe a moeda com três letras maiúsculas.',
      FinancialGoalDraftIssue.targetInvalid =>
        'Informe um valor-alvo positivo válido.',
      FinancialGoalDraftIssue.targetDateInvalid =>
        'Informe o prazo como AAAA-MM-DD ou deixe em branco.',
      FinancialGoalDraftIssue.targetDateOutOfRange =>
        'O prazo não pode estar no passado nem a mais de 100 anos.',
    };

/// Why an allocation cannot be sent. Empty when it can.
enum FinancialGoalAllocationIssue { accountRequired, amountInvalid }

List<FinancialGoalAllocationIssue> validateFinancialGoalAllocation({
  required String? accountId,
  required String amountText,
}) => [
  if (accountId == null) FinancialGoalAllocationIssue.accountRequired,
  if (validateFinancialMoneyInput(amountText, requirePositive: true) != null)
    FinancialGoalAllocationIssue.amountInvalid,
];

String financialGoalAllocationIssueLabel(FinancialGoalAllocationIssue issue) =>
    switch (issue) {
      FinancialGoalAllocationIssue.accountRequired => 'Escolha a conta.',
      FinancialGoalAllocationIssue.amountInvalid =>
        'Informe um valor positivo válido.',
    };

/// Audiences a goal can be created for. `SHARED` does not exist in v1.
const financialGoalCreationScopes = <FinancialVisibilityScope>[
  FinancialVisibilityScope.household,
  FinancialVisibilityScope.personal,
];

/// `YYYY-MM-DD` as `DD/MM/YYYY`.
String financialGoalDateLabel(String isoDate) {
  final parts = isoDate.split('-');
  return '${parts[2]}/${parts[1]}/${parts[0]}';
}

/// One account the user may pick for a destinação or a liberação, with the
/// facts the server reported about it (never computed here).
class FinancialGoalAccountOption {
  const FinancialGoalAccountOption({
    required this.accountId,
    required this.label,
    required this.detail,
  });

  final String accountId;
  final String label;
  final String? detail;
}

String _accountName(FinancialAccount? account) =>
    account?.name ?? 'Conta indisponível';

/// Eligible accounts for `Destinar`, each with what the server said about it for
/// this goal when it already backs it.
List<FinancialGoalAccountOption> financialGoalAllocationOptions({
  required FinancialGoal goal,
  required List<FinancialAccount> accounts,
  required FinancialGoalSummary? summary,
}) {
  final known = {
    if (summary != null)
      for (final account in summary.accounts) account.accountId: account,
  };
  return [
    for (final account in eligibleFinancialGoalAccounts(
      goal: goal,
      accounts: accounts,
    ))
      FinancialGoalAccountOption(
        accountId: account.accountId,
        label: account.name,
        detail: known[account.accountId] == null
            ? null
            : 'Saldo ${formatFinancialMoney(known[account.accountId]!.accountBalance)}'
                  ' · destinado em metas '
                  '${formatFinancialMoney(known[account.accountId]!.accountAllocatedTotal)}',
      ),
  ];
}

/// Accounts where this goal holds a value (archived ones included).
List<FinancialGoalAccountOption> financialGoalReleaseOptions({
  required List<FinancialAccount> accounts,
  required FinancialGoalSummary summary,
}) {
  final byId = {for (final account in accounts) account.accountId: account};
  return [
    for (final account in releasableFinancialGoalAccounts(summary))
      FinancialGoalAccountOption(
        accountId: account.accountId,
        label:
            '${_accountName(byId[account.accountId])}'
            '${account.accountStatus == FinancialAccountStatus.archived ? ' (arquivada)' : ''}',
        detail:
            'Destinado a esta meta ${formatFinancialMoney(account.allocated)}',
      ),
  ];
}

/// Name shown for an account of a summary row.
String financialGoalAccountName(
  List<FinancialAccount> accounts,
  String accountId,
) {
  for (final account in accounts) {
    if (account.accountId == accountId) return account.name;
  }
  return 'Conta indisponível';
}
