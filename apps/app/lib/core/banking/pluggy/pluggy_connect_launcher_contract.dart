enum PluggyConnectCallbackType {
  opened,
  closed,
  itemAvailable,
  errorWithoutItem,
  invalidPayload,
}

class PluggyConnectCallback {
  const PluggyConnectCallback._(this.type, [this.itemId]);

  const PluggyConnectCallback.opened()
      : this._(PluggyConnectCallbackType.opened);

  const PluggyConnectCallback.closed()
      : this._(PluggyConnectCallbackType.closed);

  const PluggyConnectCallback.itemAvailable(String itemId)
      : this._(PluggyConnectCallbackType.itemAvailable, itemId);

  const PluggyConnectCallback.errorWithoutItem()
      : this._(PluggyConnectCallbackType.errorWithoutItem);

  const PluggyConnectCallback.invalidPayload()
      : this._(PluggyConnectCallbackType.invalidPayload);

  final PluggyConnectCallbackType type;
  final String? itemId;

  @override
  String toString() => 'PluggyConnectCallback(${type.name}, <redacted>)';
}

class PluggyConnectLaunchException implements Exception {
  const PluggyConnectLaunchException();

  @override
  String toString() => 'Pluggy Connect could not be opened.';
}

abstract interface class PluggyConnectLauncher {
  Future<void> launch({
    required String connectToken,
    String? updateItem,
    required void Function(PluggyConnectCallback callback) onCallback,
  });
}
