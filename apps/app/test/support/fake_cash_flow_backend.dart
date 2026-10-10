import 'dart:convert';

import 'package:meufinanceiro_app/core/auth/auth_http.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/core/auth/session_token_vault.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

import 'fake_auth_transport.dart';
import 'fake_finance_backend.dart';

// Synthetic, contract-shaped cash flow responses (#265). Every figure is decided
// here by hand, exactly as the server would send it: the client never derives
// money, so these fixtures are the only place numbers come from.

const cashFlowCheckingId = '41000000-0000-4000-8000-000000000001';
const cashFlowSavingsId = '41000000-0000-4000-8000-000000000002';
const cashFlowArchivedId = '41000000-0000-4000-8000-000000000003';
const cashFlowRuleId = '42000000-0000-4000-8000-000000000001';
const cashFlowOccurrenceId = '43000000-0000-4000-8000-000000000001';
const cashFlowMovementId = '44000000-0000-4000-8000-000000000001';
const cashFlowTransferId = '45000000-0000-4000-8000-000000000001';

Map<String, Object?> cashFlowMoney(String amount, [String currency = 'BRL']) =>
    {'amount': amount, 'currency': currency};

Map<String, Object?> cashFlowAccountListItem(
  String id, {
  String name = 'Corrente',
  String currency = 'BRL',
  bool archived = false,
}) => {
  'accountId': id,
  'ownerOperatorId': financeTestOwnerId,
  'visibilityScope': 'HOUSEHOLD',
  'accountType': 'CHECKING',
  'customTypeName': null,
  'name': name,
  'currency': currency,
  'status': archived ? 'ARCHIVED' : 'ACTIVE',
  'createdAt': '2026-09-01T12:00:00Z',
  'updatedAt': archived ? '2026-09-02T12:00:00Z' : '2026-09-01T12:00:00Z',
  'archivedAt': archived ? '2026-09-02T12:00:00Z' : null,
};

String cashFlowDate(String start, int offset) {
  final value = DateTime.parse(
    '${start}T00:00:00Z',
  ).add(Duration(days: offset));
  return '${value.year.toString().padLeft(4, '0')}-'
      '${value.month.toString().padLeft(2, '0')}-'
      '${value.day.toString().padLeft(2, '0')}';
}

Map<String, Object?> cashFlowRisk({
  String minimum = '1000',
  String minimumDate = '2026-10-10',
  String? firstNegative,
  int negativeDays = 0,
  String currency = 'BRL',
}) => {
  'minimumBalance': cashFlowMoney(minimum, currency),
  'minimumBalanceDate': minimumDate,
  'firstNegativeDate': firstNegative,
  'negativeDays': negativeDays,
};

Map<String, Object?> cashFlowTotals({String currency = 'BRL'}) => {
  'realizedIncome': cashFlowMoney('2000', currency),
  'realizedExpense': cashFlowMoney('300', currency),
  'neutralIn': cashFlowMoney('0', currency),
  'neutralOut': cashFlowMoney('500', currency),
  'realizedNet': cashFlowMoney('1200', currency),
  'expectedIncome': cashFlowMoney('0', currency),
  'expectedExpense': cashFlowMoney('2500', currency),
  'expectedNet': cashFlowMoney('-2500', currency),
  'overdueCount': 0,
  'overdueNet': cashFlowMoney('0', currency),
  'recurrenceRealizedCount': 0,
  'recurrenceRealizedExpected': cashFlowMoney('0', currency),
  'recurrenceRealizedActual': cashFlowMoney('0', currency),
  'realizedCount': 3,
  'expectedCount': 1,
};

Map<String, Object?> cashFlowAccountSummary(
  String id, {
  String name = 'Corrente',
  String currency = 'BRL',
  bool opening = true,
  String? firstNegative,
  String minimumDate = '2026-10-10',
}) => {
  'accountId': id,
  'name': name,
  'accountType': 'CHECKING',
  'visibilityScope': 'HOUSEHOLD',
  'status': 'ACTIVE',
  'hasOpeningBalance': opening,
  'openingBalanceDate': opening ? '2026-09-01' : null,
  'startingBalance': cashFlowMoney('1000', currency),
  'balanceAtReference': cashFlowMoney('2200', currency),
  'realizedNet': cashFlowMoney('1200', currency),
  'expectedNet': cashFlowMoney('-2500', currency),
  'closingBalance': cashFlowMoney('-300', currency),
  'risk': cashFlowRisk(
    minimum: firstNegative == null ? '1000' : '-300',
    minimumDate: firstNegative ?? minimumDate,
    firstNegative: firstNegative,
    negativeDays: firstNegative == null ? 0 : 20,
    currency: currency,
  ),
};

Map<String, Object?> cashFlowEvent({
  required String date,
  String kind = 'REALIZED',
  String accountId = cashFlowCheckingId,
  String amount = '-300',
  String effect = 'EXPENSE',
  String? description = 'Mercado',
  String? movementId = cashFlowMovementId,
  String? role = 'STANDARD',
  String? transferId,
  String? occurrenceId,
  String? recurrenceId,
  int? ruleVersion,
  String? periodStart,
  String? scheduledDate,
  bool overdue = false,
  String? expectedAmount,
  String balanceAfter = '700',
  String currency = 'BRL',
}) => {
  'date': date,
  'kind': kind,
  'accountId': accountId,
  'amount': cashFlowMoney(amount, currency),
  'resultEffect': effect,
  'description': description,
  'movementId': movementId,
  'movementRole': role,
  'reversalOfId': null,
  'transferId': transferId,
  'occurrenceId': occurrenceId,
  'recurrenceId': recurrenceId,
  'ruleVersion': ruleVersion,
  'periodStart': periodStart,
  'scheduledDate': scheduledDate,
  'overdue': overdue,
  'expectedAmount': expectedAmount == null
      ? null
      : cashFlowMoney(expectedAmount, currency),
  'balanceAfter': cashFlowMoney(balanceAfter, currency),
  'accountBalanceAfter': cashFlowMoney(balanceAfter, currency),
};

/// The vertical scenario of the issue as the server answers it: income,
/// expense and a transfer realized; October rent generated (PENDING) and
/// projected into a deficit from the 20th.
List<Map<String, Object?>> cashFlowVerticalEvents() => [
  cashFlowEvent(
    date: '2026-10-10',
    amount: '2000',
    effect: 'INCOME',
    description: 'Salário',
    balanceAfter: '3000',
  ),
  cashFlowEvent(
    date: '2026-10-10',
    amount: '-300',
    description: 'Mercado',
    movementId: '44000000-0000-4000-8000-000000000002',
    balanceAfter: '2700',
  ),
  cashFlowEvent(
    date: '2026-10-10',
    amount: '-500',
    effect: 'NEUTRAL',
    description: 'Reserva',
    movementId: '44000000-0000-4000-8000-000000000003',
    transferId: cashFlowTransferId,
    balanceAfter: '2200',
  ),
  cashFlowEvent(
    date: '2026-10-20',
    kind: 'EXPECTED_OCCURRENCE',
    amount: '-2500',
    description: 'Aluguel',
    movementId: null,
    role: null,
    occurrenceId: cashFlowOccurrenceId,
    recurrenceId: cashFlowRuleId,
    ruleVersion: 1,
    periodStart: '2026-10-01',
    scheduledDate: '2026-10-20',
    expectedAmount: '-2500',
    balanceAfter: '-300',
  ),
];

Map<String, Object?> cashFlowGroup({
  String currency = 'BRL',
  String from = '2026-10-10',
  int days = 30,
  String referenceDate = '2026-10-10',
  List<Map<String, Object?>>? events,
  List<Map<String, Object?>>? accounts,
  List<Map<String, Object?>> issues = const [],
  String status = 'COMPLETE',
  String? firstNegative = '2026-10-20',
}) {
  final dayList = <Map<String, Object?>>[];
  for (var index = 0; index < days; index++) {
    final date = cashFlowDate(from, index);
    final negative =
        firstNegative != null && date.compareTo(firstNegative) >= 0;
    final closing = negative
        ? '-300'
        : (date.compareTo('2026-10-10') >= 0 ? '2200' : '1000');
    dayList.add({
      'date': date,
      'opening': cashFlowMoney(index == 0 ? '1000' : closing, currency),
      'realizedIncome': cashFlowMoney(index == 0 ? '2000' : '0', currency),
      'realizedExpense': cashFlowMoney(index == 0 ? '300' : '0', currency),
      'expectedIncome': cashFlowMoney('0', currency),
      'expectedExpense': cashFlowMoney(
        date == firstNegative ? '2500' : '0',
        currency,
      ),
      'neutralNet': cashFlowMoney(index == 0 ? '-500' : '0', currency),
      'closing': cashFlowMoney(closing, currency),
      'projected': date.compareTo(referenceDate) >= 0,
      'negative': negative,
    });
  }
  return {
    'currency': currency,
    'projectionStatus': status,
    'issues': issues,
    'startingBalance': cashFlowMoney('1000', currency),
    'balanceAtReference': cashFlowMoney('2200', currency),
    'closingBalance': cashFlowMoney('-300', currency),
    'totals': cashFlowTotals(currency: currency),
    'risk': firstNegative == null
        ? cashFlowRisk(currency: currency, minimumDate: from)
        : cashFlowRisk(
            minimum: '-300',
            minimumDate: firstNegative,
            firstNegative: firstNegative,
            negativeDays: 20,
            currency: currency,
          ),
    'accounts':
        accounts ??
        [
          cashFlowAccountSummary(
            cashFlowCheckingId,
            currency: currency,
            firstNegative: firstNegative,
            minimumDate: from,
          ),
        ],
    'days': dayList,
    'events': events ?? cashFlowVerticalEvents(),
  };
}

Map<String, Object?> cashFlowResponse({
  String referenceDate = '2026-10-10',
  String from = '2026-10-10',
  int days = 30,
  List<Map<String, Object?>>? groups,
}) => {
  'referenceDate': referenceDate,
  'from': from,
  'through': cashFlowDate(from, days - 1),
  'days': days,
  'calculatedAt': '2026-10-10T12:00:00Z',
  'excludedSources': const [
    'BUDGETS',
    'GOALS',
    'PROJECTS',
    'CARDS',
    'INSTALLMENTS',
    'LOANS',
    'BANK_OBSERVATIONS',
  ],
  'groups':
      groups ??
      [cashFlowGroup(from: from, days: days, referenceDate: referenceDate)],
};

/// Answers `GET finance/accounts` and `GET finance/cash-flow`; anything else is
/// a test failure (the cash flow screen must never write).
class FakeCashFlowBackend {
  FakeCashFlowBackend({
    List<Map<String, Object?>>? accounts,
    Object? Function(Uri uri)? cashFlow,
  }) : accounts = accounts ?? [cashFlowAccountListItem(cashFlowCheckingId)],
       cashFlow = cashFlow ?? ((_) => cashFlowResponse());

  List<Map<String, Object?>> accounts;

  /// A JSON-encodable body, an [AuthHttpResponse] to send as is, or a future
  /// of one (to hold a response back).
  Object? Function(Uri uri) cashFlow;
  final List<Uri> cashFlowCalls = [];
  final List<AuthHttpMethod> methods = [];
  int accountReads = 0;

  late final FakeAuthTransport transport = FakeAuthTransport((
    uri,
    method,
    timeout,
    headers,
    body,
  ) async {
    methods.add(method);
    if (method != AuthHttpMethod.get || body != null) {
      throw StateError('cash flow must never write: $method ${uri.path}');
    }
    if (uri.path.endsWith('/finance/accounts')) {
      accountReads++;
      return AuthHttpResponse(
        statusCode: 200,
        body: jsonEncode({'accounts': accounts}),
      );
    }
    if (uri.path.endsWith('/finance/cash-flow')) {
      cashFlowCalls.add(uri);
      final answer = cashFlow(uri);
      if (answer is Future<AuthHttpResponse>) return await answer;
      if (answer is AuthHttpResponse) return answer;
      return AuthHttpResponse(statusCode: 200, body: jsonEncode(answer));
    }
    throw StateError('unexpected route: $method ${uri.path}');
  });

  FinancialCoreApi get api => FinancialCoreApi(
    AuthenticatedApiClient(
      transport: transport,
      tokenVault: SessionTokenVault()..store(financeTestToken),
      apiBaseUri: Uri.parse('http://localhost/api/v1/'),
      timeout: const Duration(seconds: 2),
      onUnauthorized: () {},
    ),
  );
}
