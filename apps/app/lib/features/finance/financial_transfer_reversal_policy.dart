import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';

FinancialTransfer? reversibleTransferForMovement({
  required FinancialMovement movement,
  required Iterable<FinancialTransfer> transfers,
}) {
  if (movement.role != FinancialMovementRole.standard ||
      movement.resultEffect != FinancialResultEffect.neutral) {
    return null;
  }

  final transferList = List<FinancialTransfer>.unmodifiable(transfers);
  final reversedTransferIds = transferList
      .where((item) => item.role == FinancialTransferRole.reversal)
      .map((item) => item.reversalOfId)
      .whereType<String>()
      .toSet();

  FinancialTransfer? match;
  for (final transfer in transferList) {
    if (transfer.role != FinancialTransferRole.standard ||
        reversedTransferIds.contains(transfer.transferId)) {
      continue;
    }
    final ownsMovement =
        transfer.sourceMovementId == movement.movementId ||
        transfer.destinationMovementId == movement.movementId;
    if (!ownsMovement) {
      continue;
    }
    if (match != null) {
      throw const FormatException(
        'movement maps to multiple reversible transfers.',
      );
    }
    match = transfer;
  }
  return match;
}
