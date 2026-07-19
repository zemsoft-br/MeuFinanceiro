export type RouteId = 'home' | 'components' | 'system'

export interface AppRoute {
  id: RouteId
  path: string
  label: string
  shortLabel: string
  description: string
}

export const APP_ROUTES: readonly AppRoute[] = [
  {
    id: 'home',
    path: '/',
    label: 'Início',
    shortLabel: 'Início',
    description: 'Visão geral da fundação do MeuFinanceiro',
  },
  {
    id: 'components',
    path: '/componentes',
    label: 'Componentes',
    shortLabel: 'UI',
    description: 'Referência inicial do design system',
  },
  {
    id: 'system',
    path: '/sistema',
    label: 'Sistema',
    shortLabel: 'Sistema',
    description: 'Saúde da API e instalação da PWA',
  },
] as const

const FALLBACK_ROUTE = APP_ROUTES[0]

export function normalizePath(pathname: string): string {
  const withoutQuery = pathname.split(/[?#]/, 1)[0] ?? '/'
  const normalized = `/${withoutQuery}`.replace(/\/{2,}/g, '/').replace(/\/$/, '')
  return normalized === '' ? '/' : normalized
}

export function routeFromPath(pathname: string): AppRoute {
  const normalized = normalizePath(pathname)
  return APP_ROUTES.find((route) => route.path === normalized) ?? FALLBACK_ROUTE
}

export function isInternalNavigation(href: string): boolean {
  return href.startsWith('/') && !href.startsWith('//') && !href.startsWith('/api/')
}
