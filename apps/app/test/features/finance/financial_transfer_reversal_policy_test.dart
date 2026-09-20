import 'package:flutter_test/flutter_test.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_transfer_reversal_policy.dart';

const _accountId = '40000000-0000-4000-8000-000000000004';
const _destinationAccountId = '41000000-0000-4000-8000-000000000041';
const _movementId = '81000000-0000-4000-8000-000000000081';
const _destinationMovementId = '82000000-0000-4000-8000-000000000082';
const _transferId = '80000000-0000-4000-8000-000000000008';
const _reversalTransferId = '83000000-0000-4000-8000-000000000083';
const _reversalSourceMovementId = '84000000-0000-4000-8000-000000000084';
const _reversalDestinationMovementId =
    '85000000-0000-4000-8000-000000000085';

void main() {
  test('returns standard transfer for its neutral movement leg', () {
    final transfer = reversibleTransferForMovement(
      movement: _movement(
        movementId: _movementId,
        effect: FinancialResultEffect.neutral,
      ),
      transfers: [_standardTransfer],
    );

    expect(transfer?.transferId, _transferId);
  });

  test('returns null after the transfer has a reversal relation', () {
    final transfer = reversibleTransferForMovement(
      movement: _movement(
        movementId: _movementId,
        effect: FinancialResultEffect.neutral,
      ),
      transfers: [_standardTransfer, _reversalTransfer],
    );

    expect(transfer, isNull);
  });

  test('never treats a non-neutral movement as transfer reversal target', () {
    final transfer = reversibleTransferForMovement(
      movement: _movement(
        movementId: _movementId,
        effect: FinancialResultEffect.expense,
      ),
      transfers: [_standardTransfer],
    );

    expect(transfer, isNull);
  });

  test('fails closed when one movement maps to multiple transfers', () {
    final duplicate = FinancialTransfer(
      transferId: '86000000-0000-4000-8000-000000000086',
      sourceAccountId: _accountId,
      destinationAccountId: _destinationAccountId,
      currency: 'BRL',
      sourceMovementId: _movementId,
      destinationMovementId: '87000000-0000-4000-8000-000000000087',
      role: FinancialTransferRole.standard,
      reversalOfId: null,
      createdAt: DateTime.utc(2026, 11, 5),
    );

    expect(
      () => reversibleTransferForMovement(
        movement: _movement(
          movementId: _movementId,
          effect: FinancialResultEffect.neutral,
        ),
        transfers: [_standardTransfer, duplicate],
      ),
      throwsA(isA<FormatException>()),
    );
  });
}

FinancialMovement _movement({
  required String movementId,
  required FinancialResultEffect effect,
}) => FinancialMovement(
  movementId: movementId,
  accountId: _accountId,
  money: FinancialMoneyWire(amount: '-10.00', currency: 'BRL'),
  resultEffect: effect,
  role: FinancialMovementRole.standard,
  effectiveDate: '2026-11-05',
  competenceDate: '2026-11-05',
  description: 'Smoke Alpha Transferência',
  reversalOfId: null,
  reversalReason: null,
  createdAt: DateTime.utc(2026, 11, 5),
);

final _standardTransfer = FinancialTransfer(
  transferId: _transferId,
  sourceAccountId: _accountId,
  destinationAccountId: _destinationAccountId,
  currency: 'BRL',
  sourceMovementId: _movementId,
  destinationMovementId: _destinationMovementId,
  role: FinancialTransferRole.standard,
  reversalOfId: null,
  createdAt: DateTime(2026, 11, 5),
);

final _reversalTransfer = FinancialTransfer(
  transferId: _reversalTransferId,
  sourceAccountId: _destinationAccountId,
  destinationAccountId: _accountId,
  currency: 'BRL',
  sourceMovementId: _reversalSourceMovementId,
  destinationMovementId: _reversalDestinationMovementId,
  role: FinancialTransferRole.reversal,
  reversalOfId: _transferId,
  createdAt: DateTime(2026, 11, 5),
);
