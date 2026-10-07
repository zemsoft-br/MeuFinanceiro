import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_money_input.dart';

/// Ergonomic mirror of the recurrence contract (ADR-0027). The backend stays the
/// final authority on audience, ownership, the account, the currency, the monthly
/// calendar (including the clamped day), the CAS version and every amount; this
/// only keeps obviously invalid input out of the UI. It never computes a balance,
/// a realized amount or a scheduled date.

/// Shown wherever a forecast is. A forecast is not a fact.
const financialRecurrenceForecastNotice =
    'Previsto não altera o saldo nem o extrato. Somente Registrar cria um '
    'lançamento real, e só depois da sua confirmação.';

/// Shown in the confirmation that creates the real Movement.
const financialRecurrenceRealizeNotice =
    'Registrar cria um lançamento real nesta conta e altera o saldo. O valor '
    'pode ser diferente do previsto e as datas são as que você informar.';

String financialRecurrenceStatusLabel(FinancialRecurrenceStatus status) =>
    switch (status) {
      FinancialRecurrenceStatus.active => 'Ativa',
      FinancialRecurrenceStatus.paused => 'Pausada',
    };

String financialOccurrenceStatusLabel(FinancialOccurrenceStatus status) =>
    switch (status) {
      FinancialOccurrenceStatus.pending => 'Prevista',
      FinancialOccurrenceStatus.realized => 'Registrada',
      FinancialOccurrenceStatus.skipped => 'Pulada',
      FinancialOccurrenceStatus.superseded => 'Substituída',
    };

/// What a status means for the ledger, in plain text (never only a colour).
String financialOccurrenceStatusHint(FinancialOccurrenceStatus status) =>
    switch (status) {
      FinancialOccurrenceStatus.pending =>
        'Previsão: não afeta o saldo até ser registrada.',
      FinancialOccurrenceStatus.realized =>
        'Registrada: gerou um lançamento real.',
      FinancialOccurrenceStatus.skipped =>
        'Pulada: não gerou lançamento e não afeta o saldo.',
      FinancialOccurrenceStatus.superseded =>
        'Substituída por uma edição da recorrência.',
    };

String financialOccurrenceMovementStateLabel(
  FinancialOccurrenceMovementState state,
) => switch (state) {
  FinancialOccurrenceMovementState.active => 'Lançamento ativo',
  FinancialOccurrenceMovementState.reversed =>
    'Lançamento estornado (a ocorrência continua registrada)',
};

String financialRecurrenceEffectLabel(FinancialResultEffect effect) =>
    switch (effect) {
      FinancialResultEffect.income => 'Receita',
      FinancialResultEffect.expense => 'Despesa',
      FinancialResultEffect.neutral => 'Neutro',
    };

/// "Todo dia 10" and, when the day may not exist in every month, why it moves.
String financialRecurrenceScheduleLabel(int dayOfMonth) => dayOfMonth > 28
    ? 'Todo dia $dayOfMonth (no último dia do mês quando o dia não existir)'
    : 'Todo dia $dayOfMonth';

/// "10/10/2026" from a `YYYY-MM-DD` date.
String financialRecurrenceDateLabel(String date) =>
    '${date.substring(8, 10)}/${date.substring(5, 7)}/${date.substring(0, 4)}';

final _datePattern = RegExp(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$');

/// Whether [value] is a real calendar date written as `YYYY-MM-DD`.
bool isFinancialRecurrenceDate(String value) {
  if (!_datePattern.hasMatch(value)) return false;
  final parsed = DateTime.tryParse('${value}T00:00:00Z');
  if (parsed == null) return false;
  final canonical =
      '${parsed.year.toString().padLeft(4, '0')}-'
      '${parsed.month.toString().padLeft(2, '0')}-'
      '${parsed.day.toString().padLeft(2, '0')}';
  return canonical == value;
}

/// Accounts a rule may be created on: the operator's own ACTIVE accounts (only
/// the owner writes). The server validates ownership, status and currency again.
List<FinancialAccount> eligibleFinancialRecurrenceAccounts({
  required Iterable<FinancialAccount> accounts,
  required String operatorId,
}) {
  final eligible = accounts
      .where(
        (account) =>
            account.status == FinancialAccountStatus.active &&
            account.ownerOperatorId == operatorId,
      )
      .toList();
  eligible.sort((a, b) {
    final byName = a.name.toLowerCase().compareTo(b.name.toLowerCase());
    return byName != 0 ? byName : a.accountId.compareTo(b.accountId);
  });
  return List.unmodifiable(eligible);
}

/// Why a rule draft cannot be sent. Empty when it can.
enum FinancialRecurrenceDraftIssue {
  descriptionRequired,
  accountRequired,
  accountUnavailable,
  amountInvalid,
  startDateInvalid,
  dayInvalid,
  endDateInvalid,
  endBeforeStart,
}

List<FinancialRecurrenceDraftIssue> validateFinancialRecurrenceDraft({
  required String description,
  required String? accountId,
  required Iterable<FinancialAccount> eligibleAccounts,
  required bool editing,
  required String amountText,
  required String startDate,
  required String dayText,
  required String endDate,
}) {
  final issues = <FinancialRecurrenceDraftIssue>[];
  final trimmed = description.trim();
  if (trimmed.isEmpty ||
      trimmed.length > financialRecurrenceDescriptionMaxLength) {
    issues.add(FinancialRecurrenceDraftIssue.descriptionRequired);
  }
  if (!editing) {
    if (accountId == null) {
      issues.add(FinancialRecurrenceDraftIssue.accountRequired);
    } else if (!eligibleAccounts.any(
      (account) => account.accountId == accountId,
    )) {
      issues.add(FinancialRecurrenceDraftIssue.accountUnavailable);
    }
  }
  if (validateFinancialMoneyInput(amountText, requirePositive: true) != null) {
    issues.add(FinancialRecurrenceDraftIssue.amountInvalid);
  }
  final startValid = isFinancialRecurrenceDate(startDate.trim());
  if (!editing && !startValid) {
    issues.add(FinancialRecurrenceDraftIssue.startDateInvalid);
  }
  final day = int.tryParse(dayText.trim());
  if (day == null || day < 1 || day > 31) {
    issues.add(FinancialRecurrenceDraftIssue.dayInvalid);
  }
  final end = endDate.trim();
  if (end.isNotEmpty) {
    if (!isFinancialRecurrenceDate(end)) {
      issues.add(FinancialRecurrenceDraftIssue.endDateInvalid);
    } else if (startValid && end.compareTo(startDate.trim()) < 0) {
      issues.add(FinancialRecurrenceDraftIssue.endBeforeStart);
    }
  }
  return issues;
}

String financialRecurrenceDraftIssueLabel(
  FinancialRecurrenceDraftIssue issue,
) => switch (issue) {
  FinancialRecurrenceDraftIssue.descriptionRequired =>
    'Informe uma descrição de até $financialRecurrenceDescriptionMaxLength '
        'caracteres.',
  FinancialRecurrenceDraftIssue.accountRequired => 'Escolha a conta.',
  FinancialRecurrenceDraftIssue.accountUnavailable =>
    'A conta escolhida não está disponível: use uma conta ativa que seja sua.',
  FinancialRecurrenceDraftIssue.amountInvalid =>
    'Informe um valor esperado positivo.',
  FinancialRecurrenceDraftIssue.startDateInvalid =>
    'Informe a data de início no formato AAAA-MM-DD.',
  FinancialRecurrenceDraftIssue.dayInvalid =>
    'Informe o dia do mês, de 1 a 31.',
  FinancialRecurrenceDraftIssue.endDateInvalid =>
    'Informe o término no formato AAAA-MM-DD ou deixe em branco.',
  FinancialRecurrenceDraftIssue.endBeforeStart =>
    'O término não pode ser anterior ao início.',
};

/// Why a registration cannot be sent. Empty when it can.
enum FinancialRealizeDraftIssue {
  amountInvalid,
  effectiveDateInvalid,
  competenceDateInvalid,
}

List<FinancialRealizeDraftIssue> validateFinancialRealizeDraft({
  required String amountText,
  required String effectiveDate,
  required String competenceDate,
}) {
  return [
    if (validateFinancialMoneyInput(amountText, requirePositive: true) != null)
      FinancialRealizeDraftIssue.amountInvalid,
    if (!isFinancialRecurrenceDate(effectiveDate.trim()))
      FinancialRealizeDraftIssue.effectiveDateInvalid,
    if (!isFinancialRecurrenceDate(competenceDate.trim()))
      FinancialRealizeDraftIssue.competenceDateInvalid,
  ];
}

String financialRealizeDraftIssueLabel(FinancialRealizeDraftIssue issue) =>
    switch (issue) {
      FinancialRealizeDraftIssue.amountInvalid =>
        'Informe o valor real, positivo.',
      FinancialRealizeDraftIssue.effectiveDateInvalid =>
        'Informe a data efetiva no formato AAAA-MM-DD.',
      FinancialRealizeDraftIssue.competenceDateInvalid =>
        'Informe a data de competência no formato AAAA-MM-DD.',
    };

// --- assisted suggestions (#256, ADR-0028) ----------------------------------------

/// Shown wherever a suggestion is. A suggestion is derived, never a fact.
const financialRecurrenceSuggestionNotice =
    'Detectamos um padrão; nada será criado sem sua confirmação.';

/// Shown in the review that creates the recurrence from a suggestion.
const financialRecurrenceSuggestionReviewNotice =
    'Criar a recorrência não gera previsões nem lançamentos e não altera o '
    'saldo. Revise os campos: é você quem confirma.';

String financialSuggestionReasonLabel(FinancialSuggestionReason reason) =>
    switch (reason) {
      FinancialSuggestionReason.exactDescription =>
        'A descrição é igual em todas as cobranças (sem diferenciar '
            'maiúsculas e sem contar espaços nas pontas).',
      FinancialSuggestionReason.consecutiveMonths =>
        'As cobranças aconteceram em meses seguidos.',
      FinancialSuggestionReason.onePerMonth => 'Há uma única cobrança por mês.',
      FinancialSuggestionReason.dayWindow =>
        'As cobranças caem em dias próximos do mês (no máximo 3 dias de '
            'diferença).',
      FinancialSuggestionReason.amountFixed =>
        'O valor é o mesmo em todas as cobranças.',
      FinancialSuggestionReason.amountVariable =>
        'O valor variou entre as cobranças.',
    };

/// "Todo dia 10 · 3 meses seguidos".
String financialSuggestionPatternLabel(FinancialRecurrenceSuggestion item) =>
    '${financialRecurrenceScheduleLabel(item.suggestedDayOfMonth)} · '
    '${item.evidence.length} meses seguidos';

/// First day of the month after [lastObservedDate] (`YYYY-MM-DD`): the review is
/// pre-filled so the new rule does not start on a month that already happened.
/// The user can change it; the server validates every field again.
String financialSuggestionDefaultStartDate(String lastObservedDate) {
  var year = int.parse(lastObservedDate.substring(0, 4));
  var month = int.parse(lastObservedDate.substring(5, 7)) + 1;
  if (month > 12) {
    month = 1;
    year += 1;
  }
  return '${year.toString().padLeft(4, '0')}-'
      '${month.toString().padLeft(2, '0')}-01';
}
