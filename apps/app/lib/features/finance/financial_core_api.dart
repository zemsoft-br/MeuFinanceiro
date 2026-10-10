import 'dart:convert';
import 'dart:math';

import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';

part 'financial_budget_api.dart';
part 'financial_cash_flow_api.dart';
part 'financial_categorization_rules_api.dart';
part 'financial_goal_api.dart';
part 'financial_project_api.dart';
part 'financial_pending_api.dart';
part 'financial_recurrence_api.dart';
part 'financial_recurrence_suggestion_api.dart';

final _financialResourceIdPattern = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
);
final _uuidPattern = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
);
final _moneyPattern = RegExp(r'^-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$');
final _zeroMoneyPattern = RegExp(r'^-?0(?:\.0{1,8})?$');
final _currencyPattern = RegExp(r'^[A-Z]{3}$');
final _datePattern = RegExp(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$');
final _timezoneSuffixPattern = RegExp(r'(Z|[+-][0-9]{2}:[0-9]{2})$');

const _accountKeys = <String>{
  'accountId',
  'ownerOperatorId',
  'visibilityScope',
  'accountType',
  'customTypeName',
  'name',
  'currency',
  'status',
  'createdAt',
  'updatedAt',
  'archivedAt',
};
const _openingBalanceKeys = <String>{
  'openingBalanceId',
  'accountId',
  'money',
  'effectiveDate',
  'createdAt',
};
const _movementKeys = <String>{
  'movementId',
  'accountId',
  'money',
  'resultEffect',
  'role',
  'effectiveDate',
  'competenceDate',
  'description',
  'reversalOfId',
  'reversalReason',
  'createdAt',
};
const _moneyKeys = <String>{'amount', 'currency'};
const _transferKeys = <String>{
  'transferId',
  'sourceAccountId',
  'destinationAccountId',
  'currency',
  'sourceMovementId',
  'destinationMovementId',
  'role',
  'reversalOfId',
  'createdAt',
};
const _balanceKeys = <String>{
  'accountId',
  'currency',
  'openingBalance',
  'movementNet',
  'currentBalance',
  'movementCount',
  'calculatedAt',
};
const _statementKeys = <String>{
  'accountId',
  'currency',
  'openingBalance',
  'entries',
  'closingBalance',
  'calculatedAt',
};
const _statementEntryKeys = <String>{'movement', 'balanceAfter'};
const _categoryKeys = <String>{
  'categoryId',
  'ownerOperatorId',
  'visibilityScope',
  'parentId',
  'name',
  'status',
  'createdAt',
  'updatedAt',
  'disabledAt',
};
const _categoriesKeys = <String>{'categories'};
const _allocationKeys = <String>{
  'allocationSetId',
  'movementId',
  'revision',
  'supersedesId',
  'allocations',
  'createdAt',
};
const _allocationShareKeys = <String>{'categoryId', 'money'};
const _allocationsKeys = <String>{'accountId', 'movementAllocations'};
const _maxAllocationShares = 50;

enum FinancialAccountType {
  checking('CHECKING'),
  savings('SAVINGS'),
  cash('CASH'),
  digitalWallet('DIGITAL_WALLET'),
  investment('INVESTMENT'),
  benefit('BENEFIT'),
  custom('CUSTOM');

  const FinancialAccountType(this.wireValue);
  final String wireValue;

  static FinancialAccountType parse(Object? value) =>
      _enumByWire(values, value, 'accountType', (item) => item.wireValue);
}

enum FinancialVisibilityScope {
  personal('PERSONAL'),
  shared('SHARED'),
  household('HOUSEHOLD');

  const FinancialVisibilityScope(this.wireValue);
  final String wireValue;

  static FinancialVisibilityScope parse(Object? value) =>
      _enumByWire(values, value, 'visibilityScope', (item) => item.wireValue);
}

enum FinancialAccountStatus {
  active('ACTIVE'),
  archived('ARCHIVED');

  const FinancialAccountStatus(this.wireValue);
  final String wireValue;

  static FinancialAccountStatus parse(Object? value) =>
      _enumByWire(values, value, 'status', (item) => item.wireValue);
}

enum FinancialResultEffect {
  income('INCOME'),
  expense('EXPENSE'),
  neutral('NEUTRAL');

  const FinancialResultEffect(this.wireValue);
  final String wireValue;

  static FinancialResultEffect parse(Object? value) =>
      _enumByWire(values, value, 'resultEffect', (item) => item.wireValue);
}

enum FinancialMovementRole {
  standard('STANDARD'),
  reversal('REVERSAL');

  const FinancialMovementRole(this.wireValue);
  final String wireValue;

  static FinancialMovementRole parse(Object? value) =>
      _enumByWire(values, value, 'role', (item) => item.wireValue);
}

enum FinancialTransferRole {
  standard('STANDARD'),
  reversal('REVERSAL');

  const FinancialTransferRole(this.wireValue);
  final String wireValue;

  static FinancialTransferRole parse(Object? value) =>
      _enumByWire(values, value, 'role', (item) => item.wireValue);
}

enum FinancialCategoryStatus {
  active('ACTIVE'),
  disabled('DISABLED');

  const FinancialCategoryStatus(this.wireValue);
  final String wireValue;

  static FinancialCategoryStatus parse(Object? value) =>
      _enumByWire(values, value, 'status', (item) => item.wireValue);
}

enum FinancialManualEntryKind { income, expense }

class FinancialMoneyWire {
  FinancialMoneyWire({required String amount, required String currency})
    : amount = _decimalAmount(amount, 'amount'),
      currency = _currency(currency, 'currency');

  final String amount;
  final String currency;

  bool get isNegative => amount.startsWith('-') && !isZero;
  bool get isZero => _zeroMoneyPattern.hasMatch(amount);

  Map<String, Object?> toJson() => {'amount': amount, 'currency': currency};

  @override
  String toString() =>
      'FinancialMoneyWire(currency=$currency, amount=<redacted>)';
}

class FinancialAccount {
  const FinancialAccount({
    required this.accountId,
    required this.ownerOperatorId,
    required this.visibilityScope,
    required this.accountType,
    required this.customTypeName,
    required this.name,
    required this.currency,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
    required this.archivedAt,
  });

  final String accountId;
  final String ownerOperatorId;
  final FinancialVisibilityScope visibilityScope;
  final FinancialAccountType accountType;
  final String? customTypeName;
  final String name;
  final String currency;
  final FinancialAccountStatus status;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? archivedAt;
}

class FinancialOpeningBalance {
  const FinancialOpeningBalance({
    required this.openingBalanceId,
    required this.accountId,
    required this.money,
    required this.effectiveDate,
    required this.createdAt,
  });

  final String openingBalanceId;
  final String accountId;
  final FinancialMoneyWire money;
  final String effectiveDate;
  final DateTime createdAt;
}

class FinancialMovement {
  const FinancialMovement({
    required this.movementId,
    required this.accountId,
    required this.money,
    required this.resultEffect,
    required this.role,
    required this.effectiveDate,
    required this.competenceDate,
    required this.description,
    required this.reversalOfId,
    required this.reversalReason,
    required this.createdAt,
  });

  final String movementId;
  final String accountId;
  final FinancialMoneyWire money;
  final FinancialResultEffect resultEffect;
  final FinancialMovementRole role;
  final String effectiveDate;
  final String competenceDate;
  final String? description;
  final String? reversalOfId;
  final String? reversalReason;
  final DateTime createdAt;
}

class FinancialTransfer {
  const FinancialTransfer({
    required this.transferId,
    required this.sourceAccountId,
    required this.destinationAccountId,
    required this.currency,
    required this.sourceMovementId,
    required this.destinationMovementId,
    required this.role,
    required this.reversalOfId,
    required this.createdAt,
  });

  final String transferId;
  final String sourceAccountId;
  final String destinationAccountId;
  final String currency;
  final String sourceMovementId;
  final String destinationMovementId;
  final FinancialTransferRole role;
  final String? reversalOfId;
  final DateTime createdAt;
}

class FinancialBalanceSnapshot {
  const FinancialBalanceSnapshot({
    required this.accountId,
    required this.currency,
    required this.openingBalance,
    required this.movementNet,
    required this.currentBalance,
    required this.movementCount,
    required this.calculatedAt,
  });

  final String accountId;
  final String currency;
  final FinancialMoneyWire? openingBalance;
  final FinancialMoneyWire movementNet;
  final FinancialMoneyWire currentBalance;
  final int movementCount;
  final DateTime calculatedAt;
}

class FinancialStatementEntry {
  const FinancialStatementEntry({
    required this.movement,
    required this.balanceAfter,
  });

  final FinancialMovement movement;
  final FinancialMoneyWire balanceAfter;
}

class FinancialStatement {
  const FinancialStatement({
    required this.accountId,
    required this.currency,
    required this.openingBalance,
    required this.entries,
    required this.closingBalance,
    required this.calculatedAt,
  });

  final String accountId;
  final String currency;
  final FinancialMoneyWire? openingBalance;
  final List<FinancialStatementEntry> entries;
  final FinancialMoneyWire closingBalance;
  final DateTime calculatedAt;
}

class FinancialCategory {
  const FinancialCategory({
    required this.categoryId,
    required this.ownerOperatorId,
    required this.visibilityScope,
    required this.parentId,
    required this.name,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
    required this.disabledAt,
  });

  final String categoryId;
  final String ownerOperatorId;
  final FinancialVisibilityScope visibilityScope;
  final String? parentId;
  final String name;
  final FinancialCategoryStatus status;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? disabledAt;

  bool get isActive => status == FinancialCategoryStatus.active;
}

class FinancialAllocationShare {
  const FinancialAllocationShare({
    required this.categoryId,
    required this.money,
  });

  final String categoryId;
  final FinancialMoneyWire money;
}

class FinancialMovementAllocation {
  const FinancialMovementAllocation({
    required this.allocationSetId,
    required this.movementId,
    required this.revision,
    required this.supersedesId,
    required this.allocations,
    required this.createdAt,
  });

  final String allocationSetId;
  final String movementId;
  final int revision;
  final String? supersedesId;
  final List<FinancialAllocationShare> allocations;
  final DateTime createdAt;

  String get currency => allocations.first.money.currency;
}

class FinancialAccountCreateInput {
  const FinancialAccountCreateInput({
    required this.name,
    required this.accountType,
    required this.currency,
    required this.visibilityScope,
    this.customTypeName,
  });

  final String name;
  final FinancialAccountType accountType;
  final String currency;
  final FinancialVisibilityScope visibilityScope;
  final String? customTypeName;

  Map<String, Object?> toJson() {
    final normalizedName = _boundedText(name, 'name', maxLength: 96);
    final normalizedCurrency = _currency(currency, 'currency');
    final normalizedCustom = customTypeName == null
        ? null
        : _boundedText(customTypeName, 'customTypeName', maxLength: 96);
    if (accountType == FinancialAccountType.custom &&
        normalizedCustom == null) {
      throw const FormatException('customTypeName is required.');
    }
    if (accountType != FinancialAccountType.custom &&
        normalizedCustom != null) {
      throw const FormatException('customTypeName is invalid.');
    }
    return {
      'name': normalizedName,
      'accountType': accountType.wireValue,
      'customTypeName': normalizedCustom,
      'currency': normalizedCurrency,
      'visibilityScope': visibilityScope.wireValue,
    };
  }
}

class FinancialOpeningBalanceCreateInput {
  FinancialOpeningBalanceCreateInput({
    required String amount,
    required String currency,
    required String effectiveDate,
  }) : amount = _decimalAmount(amount, 'amount'),
       currency = _currency(currency, 'currency'),
       effectiveDate = _date(effectiveDate, 'effectiveDate');

  final String amount;
  final String currency;
  final String effectiveDate;

  Map<String, Object?> toJson() => {
    'amount': amount,
    'currency': currency,
    'effectiveDate': effectiveDate,
  };
}

class FinancialManualEntryCreateInput {
  FinancialManualEntryCreateInput({
    required String amount,
    required String currency,
    required String effectiveDate,
    required String competenceDate,
    required String description,
    String? idempotencyKey,
  }) : idempotencyKey = _idempotencyKey(idempotencyKey ?? _newUuidV4()),
       amount = _positiveDecimalAmount(amount, 'amount'),
       currency = _currency(currency, 'currency'),
       effectiveDate = _date(effectiveDate, 'effectiveDate'),
       competenceDate = _date(competenceDate, 'competenceDate'),
       description = _boundedText(description, 'description', maxLength: 256);

  final String idempotencyKey;
  final String amount;
  final String currency;
  final String effectiveDate;
  final String competenceDate;
  final String description;

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'amount': amount,
    'currency': currency,
    'effectiveDate': effectiveDate,
    'competenceDate': competenceDate,
    'description': description,
  };
}

class FinancialMovementReversalInput {
  FinancialMovementReversalInput({
    required String effectiveDate,
    required String competenceDate,
    required String reason,
    String? idempotencyKey,
  }) : idempotencyKey = _idempotencyKey(idempotencyKey ?? _newUuidV4()),
       effectiveDate = _date(effectiveDate, 'effectiveDate'),
       competenceDate = _date(competenceDate, 'competenceDate'),
       reason = _boundedText(reason, 'reason', maxLength: 256);

  final String idempotencyKey;
  final String effectiveDate;
  final String competenceDate;
  final String reason;

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'effectiveDate': effectiveDate,
    'competenceDate': competenceDate,
    'reason': reason,
  };
}

class FinancialTransferCreateInput {
  FinancialTransferCreateInput({
    required String sourceAccountId,
    required String destinationAccountId,
    required String amount,
    required String currency,
    required String effectiveDate,
    required String competenceDate,
    required String description,
    String? idempotencyKey,
  }) : idempotencyKey = _idempotencyKey(idempotencyKey ?? _newUuidV4()),
       sourceAccountId = _financialResourceId(
         sourceAccountId,
         'sourceAccountId',
       ),
       destinationAccountId = _financialResourceId(
         destinationAccountId,
         'destinationAccountId',
       ),
       amount = _positiveDecimalAmount(amount, 'amount'),
       currency = _currency(currency, 'currency'),
       effectiveDate = _date(effectiveDate, 'effectiveDate'),
       competenceDate = _date(competenceDate, 'competenceDate'),
       description = _boundedText(description, 'description', maxLength: 256) {
    if (this.sourceAccountId == this.destinationAccountId) {
      throw const FormatException('transfer accounts must differ.');
    }
  }

  final String idempotencyKey;
  final String sourceAccountId;
  final String destinationAccountId;
  final String amount;
  final String currency;
  final String effectiveDate;
  final String competenceDate;
  final String description;

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'sourceAccountId': sourceAccountId,
    'destinationAccountId': destinationAccountId,
    'amount': amount,
    'currency': currency,
    'effectiveDate': effectiveDate,
    'competenceDate': competenceDate,
    'description': description,
  };
}

class FinancialTransferReversalInput {
  FinancialTransferReversalInput({
    required String effectiveDate,
    required String competenceDate,
    required String reason,
    String? idempotencyKey,
  }) : idempotencyKey = _idempotencyKey(idempotencyKey ?? _newUuidV4()),
       effectiveDate = _date(effectiveDate, 'effectiveDate'),
       competenceDate = _date(competenceDate, 'competenceDate'),
       reason = _boundedText(reason, 'reason', maxLength: 256);

  final String idempotencyKey;
  final String effectiveDate;
  final String competenceDate;
  final String reason;

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'effectiveDate': effectiveDate,
    'competenceDate': competenceDate,
    'reason': reason,
  };
}

class FinancialCategoryCreateInput {
  FinancialCategoryCreateInput({
    required String name,
    required this.visibilityScope,
    String? parentId,
  }) : name = _boundedText(name.trim(), 'name', maxLength: 96),
       parentId = parentId == null
           ? null
           : _financialResourceId(parentId, 'parentId') {
    if (visibilityScope == FinancialVisibilityScope.shared) {
      throw const FormatException('visibilityScope is not supported.');
    }
  }

  final String name;
  final FinancialVisibilityScope visibilityScope;
  final String? parentId;

  Map<String, Object?> toJson() => {
    'name': name,
    'visibilityScope': visibilityScope.wireValue,
    if (parentId != null) 'parentId': parentId,
  };
}

class FinancialAllocationShareInput {
  FinancialAllocationShareInput({
    required String categoryId,
    required String amount,
    required String currency,
  }) : categoryId = _financialResourceId(categoryId, 'categoryId'),
       amount = _nonZeroDecimalAmount(amount, 'amount'),
       currency = _currency(currency, 'currency');

  final String categoryId;
  final String amount;
  final String currency;

  Map<String, Object?> toJson() => {
    'categoryId': categoryId,
    'amount': amount,
    'currency': currency,
  };
}

class FinancialMovementAllocationCreateInput {
  FinancialMovementAllocationCreateInput({
    required List<FinancialAllocationShareInput> allocations,
    String? idempotencyKey,
  }) : idempotencyKey = _idempotencyKey(idempotencyKey ?? _newUuidV4()),
       allocations = List<FinancialAllocationShareInput>.unmodifiable(
         allocations,
       ) {
    if (this.allocations.isEmpty ||
        this.allocations.length > _maxAllocationShares) {
      throw const FormatException('allocations are invalid.');
    }
    final categories = this.allocations.map((item) => item.categoryId).toSet();
    if (categories.length != this.allocations.length) {
      throw const FormatException('allocation categories must be unique.');
    }
    final currencies = this.allocations.map((item) => item.currency).toSet();
    if (currencies.length != 1) {
      throw const FormatException('allocation currencies must match.');
    }
  }

  /// Classifies 100% of a Movement in one category, reusing the exact
  /// canonical Movement money: sign and decimal text are never recomputed.
  factory FinancialMovementAllocationCreateInput.single({
    required String categoryId,
    required FinancialMoneyWire movementMoney,
    String? idempotencyKey,
  }) => FinancialMovementAllocationCreateInput(
    allocations: [
      FinancialAllocationShareInput(
        categoryId: categoryId,
        amount: movementMoney.amount,
        currency: movementMoney.currency,
      ),
    ],
    idempotencyKey: idempotencyKey,
  );

  final String idempotencyKey;
  final List<FinancialAllocationShareInput> allocations;

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'allocations': allocations.map((item) => item.toJson()).toList(),
  };
}

/// A new append-only revision of an existing classification. The predecessor
/// is explicit: it is always the `allocationSetId` the editor was opened on.
class FinancialMovementAllocationRevisionInput {
  FinancialMovementAllocationRevisionInput({
    required String supersedesId,
    required List<FinancialAllocationShareInput> allocations,
    String? idempotencyKey,
  }) : supersedesId = _financialResourceId(supersedesId, 'supersedesId'),
       idempotencyKey = _idempotencyKey(idempotencyKey ?? _newUuidV4()),
       allocations = List<FinancialAllocationShareInput>.unmodifiable(
         allocations,
       ) {
    if (this.allocations.isEmpty ||
        this.allocations.length > _maxAllocationShares) {
      throw const FormatException('allocations are invalid.');
    }
    final categories = this.allocations.map((item) => item.categoryId).toSet();
    if (categories.length != this.allocations.length) {
      throw const FormatException('allocation categories must be unique.');
    }
    final currencies = this.allocations.map((item) => item.currency).toSet();
    if (currencies.length != 1) {
      throw const FormatException('allocation currencies must match.');
    }
  }

  final String idempotencyKey;
  final String supersedesId;
  final List<FinancialAllocationShareInput> allocations;

  Map<String, Object?> toJson() => {
    'idempotencyKey': idempotencyKey,
    'supersedesId': supersedesId,
    'allocations': allocations.map((item) => item.toJson()).toList(),
  };
}

class FinancialCoreApi {
  const FinancialCoreApi(this.client);

  final AuthenticatedApiClient client;

  Future<List<FinancialAccount>> listAccounts() async {
    final response = await client.get('finance/accounts');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: const {'accounts'},
      label: 'financial accounts response',
    );
    final raw = root['accounts'];
    if (raw is! List || raw.length > 1000) {
      throw const FormatException('accounts is invalid.');
    }
    return List<FinancialAccount>.unmodifiable(raw.map(_parseAccount));
  }

  Future<FinancialAccount> getAccount(String accountId) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.get('finance/accounts/$id');
    final account = _parseAccount(
      _decodeJsonObject(response.body, 'financial account response'),
    );
    if (account.accountId != id) {
      throw const FormatException('financial account identity mismatch.');
    }
    return account;
  }

  Future<FinancialAccount> createAccount(
    FinancialAccountCreateInput input,
  ) async {
    final response = await client.post(
      'finance/accounts',
      jsonBody: input.toJson(),
    );
    return _parseAccount(
      _decodeJsonObject(response.body, 'financial account response'),
    );
  }

  Future<FinancialOpeningBalance?> getOpeningBalance(String accountId) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.get('finance/accounts/$id/opening-balance');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: const {'openingBalance'},
      label: 'opening balance response',
    );
    final raw = root['openingBalance'];
    if (raw == null) return null;
    final opening = _parseOpeningBalance(raw);
    if (opening.accountId != id) {
      throw const FormatException('opening balance account mismatch.');
    }
    return opening;
  }

  Future<FinancialOpeningBalance> createOpeningBalance(
    String accountId,
    FinancialOpeningBalanceCreateInput input,
  ) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.post(
      'finance/accounts/$id/opening-balance',
      jsonBody: input.toJson(),
    );
    final opening = _parseOpeningBalance(
      _decodeJsonObject(response.body, 'opening balance response'),
    );
    if (opening.accountId != id || opening.money.currency != input.currency) {
      throw const FormatException('opening balance response mismatch.');
    }
    return opening;
  }

  Future<List<FinancialMovement>> listMovements(String accountId) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.get('finance/accounts/$id/movements');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: const {'movements'},
      label: 'financial movements response',
    );
    final raw = root['movements'];
    if (raw is! List || raw.length > 10000) {
      throw const FormatException('movements is invalid.');
    }
    final movements = List<FinancialMovement>.unmodifiable(
      raw.map(_parseMovement),
    );
    if (movements.any((item) => item.accountId != id)) {
      throw const FormatException('movement account mismatch.');
    }
    return movements;
  }

  Future<FinancialMovement> getMovement(String movementId) async {
    final id = _financialResourceId(movementId, 'movementId');
    final response = await client.get('finance/movements/$id');
    final movement = _parseMovement(
      _decodeJsonObject(response.body, 'financial movement response'),
    );
    if (movement.movementId != id) {
      throw const FormatException('financial movement identity mismatch.');
    }
    return movement;
  }

  Future<FinancialMovement> createManualEntry(
    String accountId,
    FinancialManualEntryKind kind,
    FinancialManualEntryCreateInput input,
  ) async {
    final id = _financialResourceId(accountId, 'accountId');
    final endpoint = switch (kind) {
      FinancialManualEntryKind.income => 'income',
      FinancialManualEntryKind.expense => 'expense',
    };
    final response = await client.post(
      'finance/accounts/$id/$endpoint',
      jsonBody: input.toJson(),
    );
    final movement = _parseMovement(
      _decodeJsonObject(response.body, 'financial movement response'),
    );
    if (movement.accountId != id ||
        movement.money.currency != input.currency ||
        movement.role != FinancialMovementRole.standard) {
      throw const FormatException('financial movement response mismatch.');
    }
    final expectedEffect = kind == FinancialManualEntryKind.income
        ? FinancialResultEffect.income
        : FinancialResultEffect.expense;
    if (movement.resultEffect != expectedEffect) {
      throw const FormatException('financial movement effect mismatch.');
    }
    return movement;
  }

  Future<FinancialMovement> reverseMovement(
    String movementId,
    FinancialMovementReversalInput input,
  ) async {
    final id = _financialResourceId(movementId, 'movementId');
    final response = await client.post(
      'finance/movements/$id/reversal',
      jsonBody: input.toJson(),
    );
    final movement = _parseMovement(
      _decodeJsonObject(response.body, 'financial movement reversal response'),
    );
    if (movement.role != FinancialMovementRole.reversal ||
        movement.reversalOfId != id) {
      throw const FormatException('financial movement reversal mismatch.');
    }
    return movement;
  }

  Future<FinancialTransfer> createTransfer(
    FinancialTransferCreateInput input,
  ) async {
    final response = await client.post(
      'finance/transfers',
      jsonBody: input.toJson(),
    );
    final transfer = _parseTransfer(
      _decodeJsonObject(response.body, 'financial transfer response'),
    );
    if (transfer.sourceAccountId != input.sourceAccountId ||
        transfer.destinationAccountId != input.destinationAccountId ||
        transfer.currency != input.currency ||
        transfer.role != FinancialTransferRole.standard) {
      throw const FormatException('financial transfer response mismatch.');
    }
    return transfer;
  }

  Future<List<FinancialTransfer>> listTransfers(String accountId) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.get('finance/accounts/$id/transfers');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: const {'transfers'},
      label: 'financial transfers response',
    );
    final raw = root['transfers'];
    if (raw is! List || raw.length > 10000) {
      throw const FormatException('transfers is invalid.');
    }
    final transfers = List<FinancialTransfer>.unmodifiable(
      raw.map(_parseTransfer),
    );
    if (transfers.any(
      (item) => item.sourceAccountId != id && item.destinationAccountId != id,
    )) {
      throw const FormatException('transfer account mismatch.');
    }
    return transfers;
  }

  Future<FinancialTransfer> reverseTransfer(
    String transferId,
    FinancialTransferReversalInput input,
  ) async {
    final id = _financialResourceId(transferId, 'transferId');
    final response = await client.post(
      'finance/transfers/$id/reversal',
      jsonBody: input.toJson(),
    );
    final transfer = _parseTransfer(
      _decodeJsonObject(response.body, 'financial transfer reversal response'),
    );
    if (transfer.role != FinancialTransferRole.reversal ||
        transfer.reversalOfId != id) {
      throw const FormatException('financial transfer reversal mismatch.');
    }
    return transfer;
  }

  Future<FinancialBalanceSnapshot> getBalance(String accountId) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.get('finance/accounts/$id/balance');
    final snapshot = _parseBalance(
      _decodeJsonObject(response.body, 'financial balance response'),
    );
    if (snapshot.accountId != id) {
      throw const FormatException('financial balance account mismatch.');
    }
    return snapshot;
  }

  Future<FinancialStatement> getStatement(String accountId) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.get('finance/accounts/$id/statement');
    final statement = _parseStatement(
      _decodeJsonObject(response.body, 'financial statement response'),
    );
    if (statement.accountId != id ||
        statement.entries.any((entry) => entry.movement.accountId != id)) {
      throw const FormatException('financial statement account mismatch.');
    }
    return statement;
  }

  Future<List<FinancialCategory>> listCategories() async {
    final response = await client.get('finance/categories');
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _categoriesKeys,
      label: 'financial categories response',
    );
    final raw = root['categories'];
    if (raw is! List || raw.length > 10000) {
      throw const FormatException('categories is invalid.');
    }
    final categories = List<FinancialCategory>.unmodifiable(
      raw.map(_parseCategory),
    );
    if (categories.map((item) => item.categoryId).toSet().length !=
        categories.length) {
      throw const FormatException('duplicate category identity.');
    }
    return categories;
  }

  Future<FinancialCategory> createCategory(
    FinancialCategoryCreateInput input,
  ) async {
    final response = await client.post(
      'finance/categories',
      jsonBody: input.toJson(),
    );
    final category = _parseCategory(
      _decodeJsonObject(response.body, 'financial category response'),
    );
    if (category.visibilityScope != input.visibilityScope ||
        category.parentId != input.parentId ||
        category.name != input.name ||
        category.status != FinancialCategoryStatus.active) {
      throw const FormatException('financial category response mismatch.');
    }
    return category;
  }

  /// One bulk read: the current allocation of every classified Movement of the
  /// account, never one request per Movement.
  Future<List<FinancialMovementAllocation>> listCurrentMovementAllocations(
    String accountId,
  ) async {
    final id = _financialResourceId(accountId, 'accountId');
    final response = await client.get(
      'finance/accounts/$id/movement-allocations',
    );
    final root = _strictJsonObject(
      response.body,
      allowedKeys: _allocationsKeys,
      label: 'financial movement allocations response',
    );
    if (_financialResourceId(root['accountId'], 'accountId') != id) {
      throw const FormatException('movement allocations account mismatch.');
    }
    final raw = root['movementAllocations'];
    if (raw is! List || raw.length > 10000) {
      throw const FormatException('movementAllocations is invalid.');
    }
    final allocations = List<FinancialMovementAllocation>.unmodifiable(
      raw.map(_parseMovementAllocation),
    );
    final movementIds = allocations.map((item) => item.movementId).toSet();
    if (movementIds.length != allocations.length) {
      throw const FormatException('duplicate current movement allocation.');
    }
    return allocations;
  }

  Future<FinancialMovementAllocation> createMovementAllocation(
    String movementId,
    FinancialMovementAllocationCreateInput input,
  ) async {
    final id = _financialResourceId(movementId, 'movementId');
    final response = await client.post(
      'finance/movements/$id/allocation',
      jsonBody: input.toJson(),
    );
    final allocation = _parseMovementAllocation(
      _decodeJsonObject(response.body, 'financial allocation response'),
    );
    if (allocation.movementId != id ||
        allocation.revision != 1 ||
        allocation.supersedesId != null ||
        !_sameShares(allocation.allocations, input.allocations)) {
      throw const FormatException('financial allocation response mismatch.');
    }
    return allocation;
  }

  /// Appends a revision. The movement id travels only in the path and the
  /// predecessor only in the body; a response that is not exactly that revision
  /// is never accepted silently.
  Future<FinancialMovementAllocation> reviseMovementAllocation(
    String movementId,
    FinancialMovementAllocationRevisionInput input,
  ) async {
    final id = _financialResourceId(movementId, 'movementId');
    final response = await client.post(
      'finance/movements/$id/allocation/revisions',
      jsonBody: input.toJson(),
    );
    final allocation = _parseMovementAllocation(
      _decodeJsonObject(response.body, 'financial allocation response'),
    );
    if (allocation.movementId != id ||
        allocation.revision < 2 ||
        allocation.supersedesId != input.supersedesId ||
        !_sameShares(allocation.allocations, input.allocations)) {
      throw const FormatException('financial allocation response mismatch.');
    }
    return allocation;
  }
}

FinancialAccount _parseAccount(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _accountKeys, label: 'account');
  final accountType = FinancialAccountType.parse(values['accountType']);
  final customTypeName = _optionalBoundedText(
    values['customTypeName'],
    'customTypeName',
    maxLength: 96,
  );
  if (accountType == FinancialAccountType.custom && customTypeName == null) {
    throw const FormatException('custom account type name is required.');
  }
  if (accountType != FinancialAccountType.custom && customTypeName != null) {
    throw const FormatException('custom account type name is invalid.');
  }

  final status = FinancialAccountStatus.parse(values['status']);
  final createdAt = _timestamp(values['createdAt'], 'createdAt');
  final updatedAt = _timestamp(values['updatedAt'], 'updatedAt');
  final archivedAt = _optionalTimestamp(values['archivedAt'], 'archivedAt');
  if (updatedAt.isBefore(createdAt)) {
    throw const FormatException('account timestamps are invalid.');
  }
  if (status == FinancialAccountStatus.active && archivedAt != null) {
    throw const FormatException('active account archive state is invalid.');
  }
  if (status == FinancialAccountStatus.archived && archivedAt == null) {
    throw const FormatException('archived account timestamp is required.');
  }
  if (archivedAt != null && archivedAt.isBefore(createdAt)) {
    throw const FormatException('account archive timestamp is invalid.');
  }

  return FinancialAccount(
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    ownerOperatorId: _uuid(values['ownerOperatorId'], 'ownerOperatorId'),
    visibilityScope: FinancialVisibilityScope.parse(values['visibilityScope']),
    accountType: accountType,
    customTypeName: customTypeName,
    name: _boundedText(values['name'], 'name', maxLength: 96),
    currency: _currency(values['currency'], 'currency'),
    status: status,
    createdAt: createdAt,
    updatedAt: updatedAt,
    archivedAt: archivedAt,
  );
}

FinancialOpeningBalance _parseOpeningBalance(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _openingBalanceKeys,
    label: 'opening balance',
  );
  return FinancialOpeningBalance(
    openingBalanceId: _financialResourceId(
      values['openingBalanceId'],
      'openingBalanceId',
    ),
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    money: _parseMoney(values['money']),
    effectiveDate: _date(values['effectiveDate'], 'effectiveDate'),
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
  );
}

FinancialMovement _parseMovement(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _movementKeys, label: 'movement');
  final role = FinancialMovementRole.parse(values['role']);
  final description = _optionalBoundedText(
    values['description'],
    'description',
    maxLength: 256,
  );
  final reversalOfId = values['reversalOfId'] == null
      ? null
      : _financialResourceId(values['reversalOfId'], 'reversalOfId');
  final reversalReason = _optionalBoundedText(
    values['reversalReason'],
    'reversalReason',
    maxLength: 256,
  );
  if (role == FinancialMovementRole.standard &&
      (description == null || reversalOfId != null || reversalReason != null)) {
    throw const FormatException('standard movement shape is invalid.');
  }
  if (role == FinancialMovementRole.reversal &&
      (description != null || reversalOfId == null || reversalReason == null)) {
    throw const FormatException('reversal movement shape is invalid.');
  }
  final money = _parseMoney(values['money']);
  final effect = FinancialResultEffect.parse(values['resultEffect']);
  if (role == FinancialMovementRole.standard &&
      effect == FinancialResultEffect.income &&
      (money.isNegative || money.isZero)) {
    throw const FormatException('income movement sign is invalid.');
  }
  if (role == FinancialMovementRole.standard &&
      effect == FinancialResultEffect.expense &&
      (!money.isNegative || money.isZero)) {
    throw const FormatException('expense movement sign is invalid.');
  }
  if (money.isZero) {
    throw const FormatException('movement amount must not be zero.');
  }
  return FinancialMovement(
    movementId: _financialResourceId(values['movementId'], 'movementId'),
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    money: money,
    resultEffect: effect,
    role: role,
    effectiveDate: _date(values['effectiveDate'], 'effectiveDate'),
    competenceDate: _date(values['competenceDate'], 'competenceDate'),
    description: description,
    reversalOfId: reversalOfId,
    reversalReason: reversalReason,
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
  );
}

FinancialTransfer _parseTransfer(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _transferKeys, label: 'transfer');
  final role = FinancialTransferRole.parse(values['role']);
  final reversalOfId = values['reversalOfId'] == null
      ? null
      : _financialResourceId(values['reversalOfId'], 'reversalOfId');
  if (role == FinancialTransferRole.standard && reversalOfId != null) {
    throw const FormatException('standard transfer reversal state is invalid.');
  }
  if (role == FinancialTransferRole.reversal && reversalOfId == null) {
    throw const FormatException('transfer reversal reference is required.');
  }
  return FinancialTransfer(
    transferId: _financialResourceId(values['transferId'], 'transferId'),
    sourceAccountId: _financialResourceId(
      values['sourceAccountId'],
      'sourceAccountId',
    ),
    destinationAccountId: _financialResourceId(
      values['destinationAccountId'],
      'destinationAccountId',
    ),
    currency: _currency(values['currency'], 'currency'),
    sourceMovementId: _financialResourceId(
      values['sourceMovementId'],
      'sourceMovementId',
    ),
    destinationMovementId: _financialResourceId(
      values['destinationMovementId'],
      'destinationMovementId',
    ),
    role: role,
    reversalOfId: reversalOfId,
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
  );
}

FinancialBalanceSnapshot _parseBalance(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _balanceKeys, label: 'balance');
  final currency = _currency(values['currency'], 'currency');
  final opening = values['openingBalance'] == null
      ? null
      : _parseMoney(values['openingBalance']);
  final movementNet = _parseMoney(values['movementNet']);
  final currentBalance = _parseMoney(values['currentBalance']);
  final movementCount = values['movementCount'];
  if (movementCount is! int || movementCount < 0) {
    throw const FormatException('movementCount is invalid.');
  }
  if ((opening != null && opening.currency != currency) ||
      movementNet.currency != currency ||
      currentBalance.currency != currency) {
    throw const FormatException('balance currency mismatch.');
  }
  return FinancialBalanceSnapshot(
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    currency: currency,
    openingBalance: opening,
    movementNet: movementNet,
    currentBalance: currentBalance,
    movementCount: movementCount,
    calculatedAt: _timestamp(values['calculatedAt'], 'calculatedAt'),
  );
}

FinancialStatementEntry _parseStatementEntry(Object? raw, String currency) {
  final values = _strictMap(
    raw,
    allowedKeys: _statementEntryKeys,
    label: 'statement entry',
  );
  final movement = _parseMovement(values['movement']);
  final balanceAfter = _parseMoney(values['balanceAfter']);
  if (movement.money.currency != currency ||
      balanceAfter.currency != currency) {
    throw const FormatException('statement entry currency mismatch.');
  }
  return FinancialStatementEntry(
    movement: movement,
    balanceAfter: balanceAfter,
  );
}

FinancialStatement _parseStatement(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _statementKeys,
    label: 'statement',
  );
  final currency = _currency(values['currency'], 'currency');
  final opening = values['openingBalance'] == null
      ? null
      : _parseMoney(values['openingBalance']);
  final closing = _parseMoney(values['closingBalance']);
  final rawEntries = values['entries'];
  if (rawEntries is! List || rawEntries.length > 10000) {
    throw const FormatException('statement entries are invalid.');
  }
  final entries = List<FinancialStatementEntry>.unmodifiable(
    rawEntries.map((entry) => _parseStatementEntry(entry, currency)),
  );
  if ((opening != null && opening.currency != currency) ||
      closing.currency != currency) {
    throw const FormatException('statement currency mismatch.');
  }
  return FinancialStatement(
    accountId: _financialResourceId(values['accountId'], 'accountId'),
    currency: currency,
    openingBalance: opening,
    entries: entries,
    closingBalance: closing,
    calculatedAt: _timestamp(values['calculatedAt'], 'calculatedAt'),
  );
}

FinancialCategory _parseCategory(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _categoryKeys, label: 'category');
  final scope = FinancialVisibilityScope.parse(values['visibilityScope']);
  if (scope == FinancialVisibilityScope.shared) {
    throw const FormatException('category visibility is not supported.');
  }
  final categoryId = _financialResourceId(values['categoryId'], 'categoryId');
  final parentId = values['parentId'] == null
      ? null
      : _financialResourceId(values['parentId'], 'parentId');
  if (parentId == categoryId) {
    throw const FormatException('category must not be its own parent.');
  }
  final status = FinancialCategoryStatus.parse(values['status']);
  final createdAt = _timestamp(values['createdAt'], 'createdAt');
  final updatedAt = _timestamp(values['updatedAt'], 'updatedAt');
  final disabledAt = _optionalTimestamp(values['disabledAt'], 'disabledAt');
  if (updatedAt.isBefore(createdAt)) {
    throw const FormatException('category timestamps are invalid.');
  }
  if (status == FinancialCategoryStatus.active && disabledAt != null) {
    throw const FormatException('active category disable state is invalid.');
  }
  if (status == FinancialCategoryStatus.disabled && disabledAt == null) {
    throw const FormatException('disabled category timestamp is required.');
  }
  return FinancialCategory(
    categoryId: categoryId,
    ownerOperatorId: _uuid(values['ownerOperatorId'], 'ownerOperatorId'),
    visibilityScope: scope,
    parentId: parentId,
    name: _boundedText(values['name'], 'name', maxLength: 96),
    status: status,
    createdAt: createdAt,
    updatedAt: updatedAt,
    disabledAt: disabledAt,
  );
}

FinancialMovementAllocation _parseMovementAllocation(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _allocationKeys,
    label: 'movement allocation',
  );
  final revision = values['revision'];
  if (revision is! int || revision < 1) {
    throw const FormatException('revision is invalid.');
  }
  final supersedesId = values['supersedesId'] == null
      ? null
      : _financialResourceId(values['supersedesId'], 'supersedesId');
  if ((revision == 1) != (supersedesId == null)) {
    throw const FormatException('allocation revision chain is invalid.');
  }
  final rawShares = values['allocations'];
  if (rawShares is! List ||
      rawShares.isEmpty ||
      rawShares.length > _maxAllocationShares) {
    throw const FormatException('allocations are invalid.');
  }
  final shares = List<FinancialAllocationShare>.unmodifiable(
    rawShares.map(_parseAllocationShare),
  );
  if (shares.map((item) => item.categoryId).toSet().length != shares.length) {
    throw const FormatException('allocation categories must be unique.');
  }
  if (shares.map((item) => item.money.currency).toSet().length != 1) {
    throw const FormatException('allocation currencies must match.');
  }
  final allocationSetId = _financialResourceId(
    values['allocationSetId'],
    'allocationSetId',
  );
  if (supersedesId == allocationSetId) {
    throw const FormatException('allocation must not supersede itself.');
  }
  return FinancialMovementAllocation(
    allocationSetId: allocationSetId,
    movementId: _financialResourceId(values['movementId'], 'movementId'),
    revision: revision,
    supersedesId: supersedesId,
    allocations: shares,
    createdAt: _timestamp(values['createdAt'], 'createdAt'),
  );
}

FinancialAllocationShare _parseAllocationShare(Object? raw) {
  final values = _strictMap(
    raw,
    allowedKeys: _allocationShareKeys,
    label: 'allocation share',
  );
  return FinancialAllocationShare(
    categoryId: _financialResourceId(values['categoryId'], 'categoryId'),
    money: _parseMoney(values['money']),
  );
}

bool _sameShares(
  List<FinancialAllocationShare> actual,
  List<FinancialAllocationShareInput> expected,
) {
  if (actual.length != expected.length) return false;
  final byCategory = {for (final item in actual) item.categoryId: item.money};
  for (final item in expected) {
    final money = byCategory[item.categoryId];
    if (money == null ||
        money.currency != item.currency ||
        _canonicalDecimal(money.amount) != _canonicalDecimal(item.amount)) {
      return false;
    }
  }
  return true;
}

/// Text-only decimal normalization ("-75.250" == "-75.25"); never a double.
String _canonicalDecimal(String amount) {
  final negative = amount.startsWith('-');
  final unsigned = negative ? amount.substring(1) : amount;
  final parts = unsigned.split('.');
  var fraction = parts.length == 2 ? parts[1] : '';
  while (fraction.endsWith('0')) {
    fraction = fraction.substring(0, fraction.length - 1);
  }
  final body = fraction.isEmpty ? parts.first : '${parts.first}.$fraction';
  return negative && body != '0' ? '-$body' : body;
}

FinancialMoneyWire _parseMoney(Object? raw) {
  final values = _strictMap(raw, allowedKeys: _moneyKeys, label: 'money');
  final amount = values['amount'];
  final currency = values['currency'];
  if (amount is! String || currency is! String) {
    throw const FormatException('money must use string fields.');
  }
  return FinancialMoneyWire(amount: amount, currency: currency);
}

T _enumByWire<T>(
  List<T> values,
  Object? raw,
  String fieldName,
  String Function(T item) wire,
) {
  // Bounded, but above the longest wire value of every enum here (for example
  // OPENING_BALANCE_AFTER_WINDOW_START has 34 characters).
  final normalized = _boundedText(raw, fieldName, maxLength: 64);
  for (final item in values) {
    if (wire(item) == normalized) return item;
  }
  throw FormatException('$fieldName is invalid.');
}

Map<String, Object?> _decodeJsonObject(String source, String label) {
  final Object? decoded;
  try {
    decoded = jsonDecode(source);
  } on FormatException {
    throw FormatException('$label is not valid JSON.');
  }
  if (decoded is! Map) {
    throw FormatException('$label must be an object.');
  }
  return decoded.map<String, Object?>(
    (key, value) => MapEntry(key.toString(), value),
  );
}

Map<String, Object?> _strictJsonObject(
  String source, {
  required Set<String> allowedKeys,
  required String label,
}) => _strictMap(
  _decodeJsonObject(source, label),
  allowedKeys: allowedKeys,
  label: label,
);

Map<String, Object?> _strictMap(
  Object? raw, {
  required Set<String> allowedKeys,
  required String label,
}) {
  if (raw is! Map) throw FormatException('$label must be an object.');
  final values = raw.map<String, Object?>(
    (key, value) => MapEntry(key.toString(), value),
  );
  if (values.length != allowedKeys.length ||
      values.keys.any((key) => !allowedKeys.contains(key)) ||
      allowedKeys.any((key) => !values.containsKey(key))) {
    throw FormatException('$label has an incompatible shape.');
  }
  return values;
}

String _boundedText(Object? value, String fieldName, {required int maxLength}) {
  if (value is! String ||
      value.isEmpty ||
      value.length > maxLength ||
      value != value.trim() ||
      value.codeUnits.any((unit) => unit < 32 || unit == 127)) {
    throw FormatException('$fieldName is invalid.');
  }
  return value;
}

String? _optionalBoundedText(
  Object? value,
  String fieldName, {
  required int maxLength,
}) =>
    value == null ? null : _boundedText(value, fieldName, maxLength: maxLength);

String _financialResourceId(Object? value, String fieldName) {
  final normalized = _boundedText(value, fieldName, maxLength: 36);
  if (!_financialResourceIdPattern.hasMatch(normalized)) {
    throw FormatException('$fieldName is invalid.');
  }
  return normalized.toLowerCase();
}

String _uuid(Object? value, String fieldName) {
  final normalized = _boundedText(value, fieldName, maxLength: 36);
  if (!_uuidPattern.hasMatch(normalized)) {
    throw FormatException('$fieldName is invalid.');
  }
  return normalized.toLowerCase();
}

String _currency(Object? value, String fieldName) {
  final normalized = _boundedText(value, fieldName, maxLength: 3);
  if (!_currencyPattern.hasMatch(normalized)) {
    throw FormatException('$fieldName is invalid.');
  }
  return normalized;
}

String _decimalAmount(Object? value, String fieldName) {
  final normalized = _boundedText(value, fieldName, maxLength: 32);
  if (!_moneyPattern.hasMatch(normalized)) {
    throw FormatException('$fieldName is invalid.');
  }
  return normalized;
}

String _positiveDecimalAmount(Object? value, String fieldName) {
  final normalized = _decimalAmount(value, fieldName);
  if (normalized.startsWith('-') || _zeroMoneyPattern.hasMatch(normalized)) {
    throw FormatException('$fieldName must be positive.');
  }
  return normalized;
}

String _nonZeroDecimalAmount(Object? value, String fieldName) {
  final normalized = _decimalAmount(value, fieldName);
  if (_zeroMoneyPattern.hasMatch(normalized)) {
    throw FormatException('$fieldName must not be zero.');
  }
  return normalized;
}

String _idempotencyKey(Object? value) {
  final normalized = _financialResourceId(value, 'idempotencyKey');
  return normalized;
}

String _newUuidV4() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes
      .map((byte) => byte.toRadixString(16).padLeft(2, '0'))
      .join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-'
      '${hex.substring(20)}';
}

String _date(Object? value, String fieldName) {
  final normalized = _boundedText(value, fieldName, maxLength: 10);
  if (!_datePattern.hasMatch(normalized)) {
    throw FormatException('$fieldName is invalid.');
  }
  final parsed = DateTime.tryParse('${normalized}T00:00:00Z');
  final canonical = parsed == null
      ? null
      : '${parsed.year.toString().padLeft(4, '0')}-${parsed.month.toString().padLeft(2, '0')}-${parsed.day.toString().padLeft(2, '0')}';
  if (parsed == null || canonical != normalized) {
    throw FormatException('$fieldName is invalid.');
  }
  return normalized;
}

DateTime _timestamp(Object? value, String fieldName) {
  final source = _boundedText(value, fieldName, maxLength: 64);
  if (!_timezoneSuffixPattern.hasMatch(source)) {
    throw FormatException('$fieldName must include a timezone.');
  }
  final parsed = DateTime.tryParse(source);
  if (parsed == null) throw FormatException('$fieldName is invalid.');
  return parsed.toUtc();
}

DateTime? _optionalTimestamp(Object? value, String fieldName) =>
    value == null ? null : _timestamp(value, fieldName);
