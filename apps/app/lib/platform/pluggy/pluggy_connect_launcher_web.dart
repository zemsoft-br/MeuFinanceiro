// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:async';
import 'dart:html' as html;
import 'dart:js' as js;

import 'package:meufinanceiro_app/core/banking/pluggy/pluggy_connect_launcher_contract.dart';

const pluggyConnectScriptUrl =
    'https://cdn.pluggy.ai/pluggy-connect/v2.8.2/pluggy-connect.js';
const _scriptElementId = 'meufinanceiro-pluggy-connect-v2-8-2';

PluggyConnectLauncher createPluggyConnectLauncher() =>
    const BrowserPluggyConnectLauncher();

class BrowserPluggyConnectLauncher implements PluggyConnectLauncher {
  const BrowserPluggyConnectLauncher();

  static Future<void>? _scriptLoadFuture;

  @override
  Future<void> launch({
    required String connectToken,
    required void Function(PluggyConnectCallback callback) onCallback,
  }) async {
    _validateSecret(connectToken);
    await _ensureScriptLoaded();

    final constructor = js.context['PluggyConnect'];
    if (constructor is! js.JsFunction) {
      throw const PluggyConnectLaunchException();
    }

    void emit(PluggyConnectCallback callback) {
      try {
        onCallback(callback);
      } catch (_) {
        // Provider callbacks never inherit local UI/controller failures.
      }
    }

    final options = js.JsObject.jsify({
      'connectToken': connectToken,
      'language': 'pt',
      'countries': ['BR'],
      'includeSandbox': false,
      'onOpen': js.allowInterop(() {
        emit(const PluggyConnectCallback.opened());
      }),
      'onClose': js.allowInterop(() {
        emit(const PluggyConnectCallback.closed());
      }),
      'onSuccess': js.allowInterop((dynamic payload) {
        final itemId = _extractSuccessItemId(payload);
        emit(
          itemId == null
              ? const PluggyConnectCallback.invalidPayload()
              : PluggyConnectCallback.itemAvailable(itemId),
        );
      }),
      'onError': js.allowInterop((dynamic payload) {
        final extraction = _extractErrorItemId(payload);
        if (extraction is _FoundItem) {
          emit(PluggyConnectCallback.itemAvailable(extraction.itemId));
        } else if (extraction is _MissingItem) {
          emit(const PluggyConnectCallback.errorWithoutItem());
        } else {
          emit(const PluggyConnectCallback.invalidPayload());
        }
      }),
    });

    try {
      final widget = js.JsObject(constructor, [options]);
      widget.callMethod('init');
    } catch (_) {
      throw const PluggyConnectLaunchException();
    }
  }

  static Future<void> _ensureScriptLoaded() {
    final constructor = js.context['PluggyConnect'];
    if (constructor is js.JsFunction) {
      return Future.value();
    }

    final existing = _scriptLoadFuture;
    if (existing != null) {
      return existing;
    }

    final future = _loadScript();
    _scriptLoadFuture = future;
    return future.catchError((Object error, StackTrace stackTrace) {
      _scriptLoadFuture = null;
      throw const PluggyConnectLaunchException();
    });
  }

  static Future<void> _loadScript() {
    final completer = Completer<void>();
    final head = html.document.head;
    if (head == null) {
      return Future.error(const PluggyConnectLaunchException());
    }
    if (html.document.getElementById(_scriptElementId) != null) {
      return Future.error(const PluggyConnectLaunchException());
    }

    final script = html.ScriptElement()
      ..id = _scriptElementId
      ..src = pluggyConnectScriptUrl
      ..async = true;

    late final StreamSubscription<html.Event> loadSubscription;
    late final StreamSubscription<html.Event> errorSubscription;

    void cleanup() {
      unawaited(loadSubscription.cancel());
      unawaited(errorSubscription.cancel());
    }

    loadSubscription = script.onLoad.listen((_) {
      cleanup();
      if (js.context['PluggyConnect'] is js.JsFunction) {
        if (!completer.isCompleted) {
          completer.complete();
        }
      } else if (!completer.isCompleted) {
        script.remove();
        completer.completeError(const PluggyConnectLaunchException());
      }
    });
    errorSubscription = script.onError.listen((_) {
      cleanup();
      script.remove();
      if (!completer.isCompleted) {
        completer.completeError(const PluggyConnectLaunchException());
      }
    });

    head.append(script);
    return completer.future;
  }
}

String? _extractSuccessItemId(dynamic payload) {
  if (payload is! js.JsObject) {
    return null;
  }
  return _extractBoundedItemId(payload['item']);
}

_ItemExtraction _extractErrorItemId(dynamic payload) {
  if (payload is! js.JsObject) {
    return const _ItemExtraction.invalid();
  }
  final data = payload['data'];
  if (data == null) {
    return const _ItemExtraction.missing();
  }
  if (data is! js.JsObject) {
    return const _ItemExtraction.invalid();
  }
  final item = data['item'];
  if (item == null) {
    return const _ItemExtraction.missing();
  }
  final itemId = _extractBoundedItemId(item);
  return itemId == null
      ? const _ItemExtraction.invalid()
      : _ItemExtraction.found(itemId);
}

String? _extractBoundedItemId(dynamic item) {
  if (item is! js.JsObject) {
    return null;
  }
  final value = item['id'];
  if (value is! String ||
      value.isEmpty ||
      value.length > 512 ||
      value != value.trim() ||
      value.codeUnits.any((unit) => unit < 32 || unit == 127) ||
      value.contains('/') ||
      value.contains(r'\') ||
      value.contains('?') ||
      value.contains('#')) {
    return null;
  }
  return value;
}

void _validateSecret(String value) {
  if (value.isEmpty ||
      value.length > 4096 ||
      value != value.trim() ||
      value.codeUnits.any((unit) => unit < 32 || unit == 127)) {
    throw const PluggyConnectLaunchException();
  }
}

sealed class _ItemExtraction {
  const _ItemExtraction();

  const factory _ItemExtraction.found(String itemId) = _FoundItem;
  const factory _ItemExtraction.missing() = _MissingItem;
  const factory _ItemExtraction.invalid() = _InvalidItem;
}

final class _FoundItem extends _ItemExtraction {
  const _FoundItem(this.itemId);

  final String itemId;
}

final class _MissingItem extends _ItemExtraction {
  const _MissingItem();
}

final class _InvalidItem extends _ItemExtraction {
  const _InvalidItem();
}
