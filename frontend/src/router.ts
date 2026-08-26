/** Мини-роутер на location.hash.

Пять экранов не окупают отдельной библиотеки, а хэш выбран вместо History API
намеренно: dev-сервер Vite отдаёт index.html только по корню, и на F5 по
адресу вроде /habits/<id> пришлось бы настраивать фолбэк. Хэш сервер не видит
вовсе, поэтому перезагрузка и «назад» в браузере работают сами.
*/

import { useEffect, useState } from 'react'

export type Route =
  | { name: 'today' }
  | { name: 'habits' }
  | { name: 'habit'; id: string }
  | { name: 'settings' }

const DEFAULT: Route = { name: 'today' }

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  switch (parts[0]) {
    case undefined:
    case 'today':
      return DEFAULT
    case 'habits':
      return parts[1] === undefined ? { name: 'habits' } : { name: 'habit', id: parts[1] }
    case 'settings':
      return { name: 'settings' }
    default:
      return DEFAULT
  }
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return route
}

export function navigate(path: string): void {
  window.location.hash = path.startsWith('#') ? path : `#${path}`
}
