import 'dart:convert';

import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';

final _financialResourceIdPattern = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
);
final _uuidPattern = RegExp(
  r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
);
final _moneyPattern = RegExp(
  r'^-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$',
);
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
  String toString() => 'FinancialMoneyWire(currency=$currency, amount=<redacted>)';
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
    if (accountType == FinancialAccountType.custom && normalizedCustom == null) {
      throw const FormatException('customTypeName is required.');
    }
    if (accountType != FinancialAccountType.custom && normalizedCustom != null) {
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

  Future<FinancialAccount> createAccount(FinancialAccountCreateInput input) async {
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
    final movements = List<FinancialMovement>.unmodifiable(raw.map(_parseMovement));
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
  final normalized = _boundedText(raw, fieldName, maxLength: 32);
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
}) => value == null ? null : _boundedText(value, fieldName, maxLength: maxLength);

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
