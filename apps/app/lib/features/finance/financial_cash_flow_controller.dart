import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

// Read-only cash flow (#265). The controller only reads: it never writes, never
// generates an occurrence and never computes a balance. Every refresh is a new
// canonical read of the accounts and the projection; a failed refresh keeps the
// last canonical result on screen and says it may be stale.

enum FinancialCashFlowPeriod { next30, next60, next90, currentMonth, custom }

enum FinancialCashFlowFailure {
  none,

  /// The server refused the window or selection (too many events, invalid).
  rejected,

  /// The last refresh failed; the result on screen is the previous read.
  staleAfterRefresh,
}

class FinancialCashFlowState {
  const FinancialCashFlowState({
    required this.phase,
    this.cashFlow,
    this.referenceDate,
    this.accounts = const [],
    this.period = FinancialCashFlowPeriod.next30,
    this.customFrom,
    this.customThrough,
    this.selectedAccountIds = const [],
    this.currency,
    this.failure = FinancialCashFlowFailure.none,
  });

  final FinancialLoadPhase phase;
  final FinancialCashFlow? cashFlow;

  /// Server reference date of the last successful read. Kept across failures so
  /// the period presets still work after a refusal.
  final String? referenceDate;

  /// Every account the operator can see (filter options).
  final List<FinancialAccount> accounts;
  final FinancialCashFlowPeriod period;
  final String? customFrom;
  final String? customThrough;

  /// Empty means the server default: every visible active account.
  final List<String> selectedAccountIds;

  /// Currency group being shown (groups are never summed).
  final String? currency;
  final FinancialCashFlowFailure failure;

  bool get isBusy =>
      phase == FinancialLoadPhase.loading ||
      phase == FinancialLoadPhase.refreshing;

  /// Filters can change once the server answered (data or an explicit refusal).
  bool get canFilter =>
      !isBusy &&
      referenceDate != null &&
      (cashFlow != null || failure == FinancialCashFlowFailure.rejected);

  FinancialCashFlowGroup? get group {
    final groups = cashFlow?.groups ?? const <FinancialCashFlowGroup>[];
    for (final group in groups) {
      if (group.currency == currency) return group;
    }
    return groups.isEmpty ? null : groups.first;
  }

  FinancialCashFlowState copyWith({
    FinancialLoadPhase? phase,
    Object? cashFlow = _unchanged,
    Object? referenceDate = _unchanged,
    List<FinancialAccount>? accounts,
    FinancialCashFlowPeriod? period,
    Object? customFrom = _unchanged,
    Object? customThrough = _unchanged,
    List<String>? selectedAccountIds,
    Object? currency = _unchanged,
    FinancialCashFlowFailure? failure,
  }) => FinancialCashFlowState(
    phase: phase ?? this.phase,
    cashFlow: identical(cashFlow, _unchanged)
        ? this.cashFlow
        : cashFlow as FinancialCashFlow?,
    referenceDate: identical(referenceDate, _unchanged)
        ? this.referenceDate
        : referenceDate as String?,
    accounts: accounts ?? this.accounts,
    period: period ?? this.period,
    customFrom: identical(customFrom, _unchanged)
        ? this.customFrom
        : customFrom as String?,
    customThrough: identical(customThrough, _unchanged)
        ? this.customThrough
        : customThrough as String?,
    selectedAccountIds: selectedAccountIds ?? this.selectedAccountIds,
    currency: identical(currency, _unchanged)
        ? this.currency
        : currency as String?,
    failure: failure ?? this.failure,
  );
}

const _unchanged = Object();

final financialCashFlowControllerProvider =
    NotifierProvider.autoDispose<
      FinancialCashFlowController,
      FinancialCashFlowState
    >(FinancialCashFlowController.new);

class FinancialCashFlowController extends Notifier<FinancialCashFlowState> {
  int _generation = 0;
  bool _disposed = false;

  @override
  FinancialCashFlowState build() {
    ref.onDispose(() {
      _disposed = true;
      _generation++;
    });
    return const FinancialCashFlowState(phase: FinancialLoadPhase.idle);
  }

  Future<bool> load() => _read(refresh: false);

  /// Manual refresh: one new canonical read, never a cached or derived value.
  Future<bool> refresh() => _read(refresh: true);

  Future<bool> selectPeriod(FinancialCashFlowPeriod period) {
    if (period == FinancialCashFlowPeriod.custom) return Future.value(false);
    state = state.copyWith(
      period: period,
      customFrom: null,
      customThrough: null,
    );
    return _read(refresh: true);
  }

  /// A custom window, validated against the last server reference date.
  Future<bool> selectCustomWindow(String from, String through) {
    final reference = state.referenceDate;
    final FinancialCashFlowQuery probe;
    try {
      probe = FinancialCashFlowQuery(from: from, through: through);
    } on FormatException {
      return Future.value(false);
    }
    if (reference == null || probe.from!.compareTo(reference) > 0) {
      return Future.value(false);
    }
    state = state.copyWith(
      period: FinancialCashFlowPeriod.custom,
      customFrom: probe.from,
      customThrough: probe.through,
    );
    return _read(refresh: true);
  }

  Future<bool> toggleAccount(String accountId) {
    if (!state.accounts.any((account) => account.accountId == accountId)) {
      return Future.value(false);
    }
    final selected = [...state.selectedAccountIds];
    if (!selected.remove(accountId)) {
      if (selected.length >= financialCashFlowAccountsMax) {
        return Future.value(false);
      }
      selected.add(accountId);
    }
    state = state.copyWith(selectedAccountIds: List.unmodifiable(selected));
    return _read(refresh: true);
  }

  Future<bool> clearAccounts() {
    state = state.copyWith(selectedAccountIds: const []);
    return _read(refresh: true);
  }

  void selectCurrency(String currency) {
    final groups = state.cashFlow?.groups ?? const <FinancialCashFlowGroup>[];
    if (groups.any((group) => group.currency == currency)) {
      state = state.copyWith(currency: currency);
    }
  }

  FinancialCashFlowQuery _query() {
    final ids = state.selectedAccountIds;
    final reference = state.referenceDate;
    switch (state.period) {
      case FinancialCashFlowPeriod.next30:
        return FinancialCashFlowQuery(accountIds: ids);
      case FinancialCashFlowPeriod.next60:
      case FinancialCashFlowPeriod.next90:
        if (reference == null) return FinancialCashFlowQuery(accountIds: ids);
        final days = state.period == FinancialCashFlowPeriod.next60 ? 60 : 90;
        return FinancialCashFlowQuery(
          from: reference,
          through: financialCashFlowAddDays(reference, days - 1),
          accountIds: ids,
        );
      case FinancialCashFlowPeriod.currentMonth:
        if (reference == null) return FinancialCashFlowQuery(accountIds: ids);
        return FinancialCashFlowQuery(
          from: '${reference.substring(0, 7)}-01',
          through: financialCashFlowMonthEnd(reference),
          accountIds: ids,
        );
      case FinancialCashFlowPeriod.custom:
        return FinancialCashFlowQuery(
          from: state.customFrom,
          through: state.customThrough,
          accountIds: ids,
        );
    }
  }

  Future<bool> _read({required bool refresh}) async {
    if (_disposed) return false;
    final generation = ++_generation;
    final previous = state;
    state = previous.copyWith(
      phase: refresh && previous.cashFlow != null
          ? FinancialLoadPhase.refreshing
          : FinancialLoadPhase.loading,
      failure: FinancialCashFlowFailure.none,
    );
    try {
      final api = ref.read(financialCoreApiProvider);
      final accounts = await api.listAccounts();
      if (!_isCurrent(generation)) return false;
      final known = accounts.map((account) => account.accountId).toSet();
      final selected = List<String>.unmodifiable(
        state.selectedAccountIds.where(known.contains),
      );
      state = state.copyWith(accounts: accounts, selectedAccountIds: selected);
      final cashFlow = await api.getCashFlow(_query());
      if (!_isCurrent(generation)) return false;
      final currencies = cashFlow.groups.map((group) => group.currency);
      state = state.copyWith(
        phase: cashFlow.groups.isEmpty
            ? FinancialLoadPhase.empty
            : FinancialLoadPhase.loaded,
        cashFlow: cashFlow,
        referenceDate: cashFlow.referenceDate,
        currency: currencies.contains(state.currency)
            ? state.currency
            : (currencies.isEmpty ? null : currencies.first),
        failure: FinancialCashFlowFailure.none,
      );
      return true;
    } catch (error) {
      if (!_isCurrent(generation)) return false;
      if (error is AuthenticatedApiException && error.statusCode == 422) {
        state = state.copyWith(
          phase: FinancialLoadPhase.loaded,
          cashFlow: null,
          failure: FinancialCashFlowFailure.rejected,
        );
        return false;
      }
      final phase = financialPhaseForFailure(error);
      final keepPrevious =
          previous.cashFlow != null &&
          (phase == FinancialLoadPhase.temporarilyUnavailable ||
              phase == FinancialLoadPhase.invalidResponse);
      state = keepPrevious
          ? state.copyWith(
              phase: previous.cashFlow!.groups.isEmpty
                  ? FinancialLoadPhase.empty
                  : FinancialLoadPhase.loaded,
              cashFlow: previous.cashFlow,
              failure: FinancialCashFlowFailure.staleAfterRefresh,
            )
          : state.copyWith(
              phase: phase,
              cashFlow: null,
              failure: FinancialCashFlowFailure.none,
            );
      return false;
    }
  }

  bool _isCurrent(int generation) => !_disposed && generation == _generation;
}

/// `YYYY-MM-DD` plus [days] calendar days (UTC dates; never money).
String financialCashFlowAddDays(String date, int days) {
  final value = DateTime.parse('${date}T00:00:00Z').add(Duration(days: days));
  return _isoDate(value);
}

/// Last calendar day of the month of `YYYY-MM-DD`.
String financialCashFlowMonthEnd(String date) {
  final value = DateTime.parse('${date}T00:00:00Z');
  return _isoDate(DateTime.utc(value.year, value.month + 1, 0));
}

String _isoDate(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-'
    '${value.month.toString().padLeft(2, '0')}-'
    '${value.day.toString().padLeft(2, '0')}';
