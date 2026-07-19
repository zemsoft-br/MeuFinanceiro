import { useCallback, useEffect, useState } from 'react'

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>
}

type InstallState = 'unsupported' | 'available' | 'installed' | 'dismissed'

function isStandalone(): boolean {
  return window.matchMedia('(display-mode: standalone)').matches
}

export function registerServiceWorker(): void {
  if (!('serviceWorker' in navigator)) return

  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => undefined)
  })
}

export function usePwaInstall(): {
  state: InstallState
  install: () => Promise<void>
} {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [state, setState] = useState<InstallState>(() =>
    isStandalone() ? 'installed' : 'unsupported',
  )

  useEffect(() => {
    const handlePrompt = (event: Event) => {
      event.preventDefault()
      setDeferredPrompt(event as BeforeInstallPromptEvent)
      setState('available')
    }
    const handleInstalled = () => {
      setDeferredPrompt(null)
      setState('installed')
    }

    window.addEventListener('beforeinstallprompt', handlePrompt)
    window.addEventListener('appinstalled', handleInstalled)
    return () => {
      window.removeEventListener('beforeinstallprompt', handlePrompt)
      window.removeEventListener('appinstalled', handleInstalled)
    }
  }, [])

  const install = useCallback(async () => {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    const choice = await deferredPrompt.userChoice
    setDeferredPrompt(null)
    setState(choice.outcome === 'accepted' ? 'installed' : 'dismissed')
  }, [deferredPrompt])

  return { state, install }
}
