const wait = (milliseconds) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds))

const waitForController = async () => {
  if (navigator.serviceWorker.controller) return

  await Promise.race([
    new Promise((resolve) =>
      navigator.serviceWorker.addEventListener('controllerchange', resolve, {
        once: true,
      }),
    ),
    wait(3000),
  ])
}

const loadFlutter = () => {
  const script = document.createElement('script')
  script.src = 'flutter_bootstrap.js'
  script.async = true
  document.body.append(script)
}

const start = async () => {
  try {
    if ('serviceWorker' in navigator) {
      const registration = await navigator.serviceWorker.register('sw.js', {
        scope: '/',
        updateViaCache: 'none',
      })

      if (navigator.serviceWorker.controller) {
        registration.update().catch((error) =>
          console.error('Falha ao atualizar o service worker.', error),
        )
      } else {
        await Promise.race([navigator.serviceWorker.ready, wait(10000)])
        await waitForController()
      }
    }
  } catch (error) {
    console.error('Falha ao preparar o service worker.', error)
  } finally {
    loadFlutter()
  }
}

start()
