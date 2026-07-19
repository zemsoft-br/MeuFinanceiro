export type ApiState = 'checking' | 'online' | 'offline'

export function apiStateFromResponse(ok: boolean): ApiState {
  return ok ? 'online' : 'offline'
}
