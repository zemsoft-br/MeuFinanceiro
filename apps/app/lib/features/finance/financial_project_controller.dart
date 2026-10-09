import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:meufinanceiro_app/core/auth/authenticated_api_client.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_api.dart';
import 'package:meufinanceiro_app/features/finance/financial_core_controller.dart';

// Projects #262. Server computes monetary realization and authorization.
// Never synthesize a successful write or resend one after a transport error.

enum FinancialProjectWriteOutcome {
  confirmed,
  conflict,
  rejected,
  readOnly,
  unknown,
  accessBlocked,
  notAllowed,
}

class FinancialProjectsState {
  const FinancialProjectsState({
    required this.phase,
    this.projects = const [],
    this.selectedId,
    this.summary,
    this.busy = false,
    this.trusted = true,
    this.conflict = false,
  });

  final FinancialLoadPhase phase;
  final List<FinancialProject> projects;
  final String? selectedId;
  final FinancialProjectSummary? summary;
  final bool busy;
  final bool trusted;
  final bool conflict;

  bool get loaded =>
      phase == FinancialLoadPhase.loaded ||
      phase == FinancialLoadPhase.empty ||
      phase == FinancialLoadPhase.refreshing;

  FinancialProject? get selected {
    for (final project in projects) {
      if (project.id == selectedId) return project;
    }
    return null;
  }

  FinancialProjectsState copyWith({
    FinancialLoadPhase? phase,
    List<FinancialProject>? projects,
    Object? selectedId = _unchanged,
    Object? summary = _unchanged,
    bool? busy,
    bool? trusted,
    bool? conflict,
  }) => FinancialProjectsState(
    phase: phase ?? this.phase,
    projects: projects ?? this.projects,
    selectedId: identical(selectedId, _unchanged)
        ? this.selectedId
        : selectedId as String?,
    summary: identical(summary, _unchanged)
        ? this.summary
        : summary as FinancialProjectSummary?,
    busy: busy ?? this.busy,
    trusted: trusted ?? this.trusted,
    conflict: conflict ?? this.conflict,
  );
}

const _unchanged = Object();

final financialProjectsControllerProvider =
    NotifierProvider.autoDispose<
      FinancialProjectsController,
      FinancialProjectsState
    >(FinancialProjectsController.new);

class FinancialProjectsController extends Notifier<FinancialProjectsState> {
  bool _disposed = false;
  bool _reading = false;
  int _epoch = 0;
  final Map<String, String> _createKeys = {};

  @override
  FinancialProjectsState build() {
    ref.onDispose(() {
      _disposed = true;
      _epoch++;
      _createKeys.clear();
    });
    return const FinancialProjectsState(phase: FinancialLoadPhase.idle);
  }

  Future<bool> load() => _refresh(false);

  Future<bool> refresh() => _refresh(true);

  Future<bool> select(String id) async {
    if (_disposed || state.busy || _reading) return false;
    if (!state.projects.any((project) => project.id == id)) return false;
    state = state.copyWith(selectedId: id, summary: null);
    return _refresh(true);
  }

  void dismissConflict() {
    if (state.conflict) state = state.copyWith(conflict: false);
  }

  bool _canWrite() =>
      !_disposed && state.loaded && !_reading && !state.busy && state.trusted;

  Future<FinancialProjectWriteOutcome> create(
    FinancialProjectCreateInput input,
  ) async {
    if (!_canWrite()) return FinancialProjectWriteOutcome.notAllowed;
    final attempt = input.attemptKey;
    final sent = input.withIdempotencyKey(
      _createKeys[attempt] ?? input.idempotencyKey,
    );
    _createKeys[attempt] = sent.idempotencyKey;
    state = state.copyWith(busy: true, conflict: false);
    FinancialProjectWriteOutcome outcome;
    String? createdId;
    try {
      final project = await ref
          .read(financialCoreApiProvider)
          .createProject(sent);
      if (_disposed) return FinancialProjectWriteOutcome.unknown;
      createdId = project.id;
      // Selection is tentative until list AND summary are read canonically.
      // Keep the same idempotency key if that read cannot be verified.
      state = state.copyWith(selectedId: project.id);
      outcome = FinancialProjectWriteOutcome.confirmed;
    } on AuthenticatedApiException catch (error) {
      if (error.statusCode == 409 ||
          error.statusCode == 404 ||
          error.statusCode == 422) {
        _createKeys.remove(attempt);
      }
      outcome = _outcome(error);
    } on FormatException {
      outcome = FinancialProjectWriteOutcome.unknown;
    } catch (_) {
      outcome = FinancialProjectWriteOutcome.unknown;
    }
    final result = await _afterWrite(outcome, createdId: createdId);
    if (result == FinancialProjectWriteOutcome.confirmed) {
      _createKeys.remove(attempt);
    }
    return result;
  }

  Future<FinancialProjectWriteOutcome> replace(
    String projectId,
    FinancialProjectReplaceInput input,
  ) async {
    final project = state.projects.where((p) => p.id == projectId).firstOrNull;
    if (!_canWrite() ||
        project == null ||
        !project.canEdit ||
        input.expectedVersion != project.version ||
        input.currency != project.currency) {
      return FinancialProjectWriteOutcome.notAllowed;
    }
    state = state.copyWith(busy: true, conflict: false);
    FinancialProjectWriteOutcome outcome;
    FinancialProject? applied;
    try {
      applied = await ref
          .read(financialCoreApiProvider)
          .replaceProject(projectId, input);
      outcome = FinancialProjectWriteOutcome.confirmed;
    } on AuthenticatedApiException catch (error) {
      outcome = _outcome(error);
    } on FormatException {
      outcome = FinancialProjectWriteOutcome.unknown;
    } catch (_) {
      outcome = FinancialProjectWriteOutcome.unknown;
    }
    final reconciled = await _afterWrite(outcome);
    if (reconciled != FinancialProjectWriteOutcome.confirmed ||
        applied == null) {
      return reconciled;
    }
    // A second writer may have changed the project between PUT and the GET.
    // Do not report our edit as current unless the canonical list AND
    // summary agree on the exact returned revision and authored material.
    final listed = state.projects.where((p) => p.id == projectId).firstOrNull;
    final detail = state.summary?.project;
    final currentMatches =
        listed != null &&
        detail != null &&
        state.selectedId == projectId &&
        listed.version == applied.version &&
        detail.version == applied.version &&
        listed.title == applied.title &&
        detail.title == applied.title &&
        listed.description == applied.description &&
        detail.description == applied.description &&
        listed.planned.amount == applied.planned.amount &&
        detail.planned.amount == applied.planned.amount &&
        listed.planned.currency == applied.planned.currency &&
        detail.planned.currency == applied.planned.currency &&
        listed.targetDate == applied.targetDate &&
        detail.targetDate == applied.targetDate;
    return currentMatches
        ? FinancialProjectWriteOutcome.confirmed
        : FinancialProjectWriteOutcome.unknown;
  }

  Future<FinancialProjectWriteOutcome> reviseLink(
    String movementId,
    FinancialProjectLinkInput input,
  ) async {
    if (!_canWrite()) return FinancialProjectWriteOutcome.notAllowed;
    state = state.copyWith(busy: true, conflict: false);
    FinancialProjectWriteOutcome outcome;
    String? writtenId;
    try {
      final revision = await ref
          .read(financialCoreApiProvider)
          .reviseProjectLink(movementId, input);
      writtenId = revision.id;
      outcome = FinancialProjectWriteOutcome.confirmed;
    } on AuthenticatedApiException catch (error) {
      outcome = _outcome(error);
    } on FormatException {
      outcome = FinancialProjectWriteOutcome.unknown;
    } catch (_) {
      outcome = FinancialProjectWriteOutcome.unknown;
    }
    // Reconciliation must not infer link state from project totals alone.
    final reconciled = await _afterWrite(outcome);
    if (_disposed || !state.trusted) {
      return FinancialProjectWriteOutcome.unknown;
    }
    try {
      final current = await ref
          .read(financialCoreApiProvider)
          .getProjectLink(movementId);
      if (reconciled == FinancialProjectWriteOutcome.confirmed &&
          current?.id != writtenId) {
        // A second writer may already have superseded our successful POST.
        // Do not announce that the requested project is currently selected.
        return FinancialProjectWriteOutcome.unknown;
      }
    } catch (_) {
      state = state.copyWith(trusted: false);
      return FinancialProjectWriteOutcome.unknown;
    }
    return reconciled;
  }

  FinancialProjectWriteOutcome _outcome(AuthenticatedApiException error) {
    final phase = financialPhaseForFailure(error);
    if (phase == FinancialLoadPhase.authenticationRequired ||
        phase == FinancialLoadPhase.primaryResidenceRequired) {
      return FinancialProjectWriteOutcome.accessBlocked;
    }
    if (error.statusCode == 403) return FinancialProjectWriteOutcome.readOnly;
    if (error.statusCode == 409) return FinancialProjectWriteOutcome.conflict;
    if (error.statusCode == 404 || error.statusCode == 422) {
      return FinancialProjectWriteOutcome.rejected;
    }
    return FinancialProjectWriteOutcome.unknown;
  }

  /// A write response is not a reconciled success. No extra POST is sent.
  Future<FinancialProjectWriteOutcome> _afterWrite(
    FinancialProjectWriteOutcome outcome, {
    String? createdId,
  }) async {
    if (_disposed) return FinancialProjectWriteOutcome.unknown;
    final readSucceeded = await _refresh(true, afterWrite: true);
    if (_disposed) return FinancialProjectWriteOutcome.unknown;
    final createdVisible =
        createdId == null ||
        (state.selectedId == createdId &&
            state.summary?.project.id == createdId &&
            state.projects.any((project) => project.id == createdId));
    final trusted = readSucceeded && state.trusted && createdVisible;
    state = state.copyWith(
      busy: false,
      trusted: trusted,
      conflict: trusted && outcome == FinancialProjectWriteOutcome.conflict,
    );
    if (!trusted) return FinancialProjectWriteOutcome.unknown;
    return outcome;
  }

  Future<bool> _refresh(bool refresh, {bool afterWrite = false}) async {
    if (_disposed || _reading || (state.busy && !afterWrite)) return false;
    final generation = ++_epoch;
    _reading = true;
    final previous = state;
    state = previous.copyWith(
      phase: refresh && previous.loaded
          ? FinancialLoadPhase.refreshing
          : FinancialLoadPhase.loading,
    );
    try {
      final api = ref.read(financialCoreApiProvider);
      final projects = await api.listProjects();
      if (_disposed || generation != _epoch) return false;
      var selected = previous.selectedId;
      if (!projects.any((p) => p.id == selected)) {
        selected = projects.isEmpty ? null : projects.first.id;
      }
      final summary = selected == null
          ? null
          : await api.getProjectSummary(selected);
      if (_disposed || generation != _epoch) return false;
      state = FinancialProjectsState(
        phase: projects.isEmpty
            ? FinancialLoadPhase.empty
            : FinancialLoadPhase.loaded,
        projects: List<FinancialProject>.unmodifiable(projects),
        selectedId: selected,
        summary: summary,
        busy: previous.busy && afterWrite,
        trusted: true,
        conflict: previous.conflict,
      );
      return true;
    } catch (error) {
      if (_disposed || generation != _epoch) return false;
      final phase = financialPhaseForFailure(error);
      if (afterWrite && previous.projects.isNotEmpty) {
        // Could not establish the canonical post-write state: block writes.
        state = previous.copyWith(
          phase: previous.phase == FinancialLoadPhase.empty
              ? FinancialLoadPhase.empty
              : FinancialLoadPhase.loaded,
          busy: true,
          trusted: false,
        );
      } else {
        state = FinancialProjectsState(
          phase: phase,
          projects: previous.projects,
          selectedId: previous.selectedId,
          summary: null,
          trusted: false,
        );
      }
      return false;
    } finally {
      if (generation == _epoch) _reading = false;
    }
  }
}
