export type ApiState = 'checking' | 'online' | 'degraded' | 'offline'

export interface ApiReadiness {
  status: 'ok' | 'degraded' | 'unknown'
  process: 'ok' | 'unknown'
  database: 'ok' | 'unavailable' | 'unknown'
  schema: 'ok' | 'outdated' | 'unavailable' | 'unknown'
  currentRevision: string | null
  expectedRevision: string | null
}

const UNKNOWN_READINESS: ApiReadiness = {
  status: 'unknown',
  process: 'unknown',
  database: 'unknown',
  schema: 'unknown',
  currentRevision: null,
  expectedRevision: null,
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function enumValue<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && allowed.includes(value as T) ? (value as T) : fallback
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

export function apiStateFromResponse(ok: boolean, payload?: unknown): ApiState {
  if (isRecord(payload) && payload.status === 'degraded') return 'degraded'
  return ok ? 'online' : 'offline'
}

export function readinessFromPayload(payload: unknown): ApiReadiness {
  if (!isRecord(payload)) return UNKNOWN_READINESS

  return {
    status: enumValue(payload.status, ['ok', 'degraded'] as const, 'unknown'),
    process: enumValue(payload.process, ['ok'] as const, 'unknown'),
    database: enumValue(payload.database, ['ok', 'unavailable'] as const, 'unknown'),
    schema: enumValue(payload.schema, ['ok', 'outdated', 'unavailable'] as const, 'unknown'),
    currentRevision: nullableString(payload.current_revision),
    expectedRevision: nullableString(payload.expected_revision),
  }
}
