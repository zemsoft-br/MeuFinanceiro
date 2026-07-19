import { useEffect, useState, type MouseEvent } from 'react'

import { isInternalNavigation, routeFromPath, type AppRoute } from './routes'

export function useAppRoute(): {
  route: AppRoute
  navigate: (path: string) => void
  handleLinkClick: (event: MouseEvent<HTMLAnchorElement>) => void
} {
  const [route, setRoute] = useState(() => routeFromPath(window.location.pathname))

  useEffect(() => {
    const handlePopState = () => setRoute(routeFromPath(window.location.pathname))
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  const navigate = (path: string) => {
    const nextRoute = routeFromPath(path)
    if (window.location.pathname !== nextRoute.path) {
      window.history.pushState({}, '', nextRoute.path)
    }
    setRoute(nextRoute)
    document.getElementById('main-content')?.focus()
  }

  const handleLinkClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return
    }

    const href = event.currentTarget.getAttribute('href')
    if (!href || !isInternalNavigation(href)) return

    event.preventDefault()
    navigate(href)
  }

  return { route, navigate, handleLinkClick }
}
