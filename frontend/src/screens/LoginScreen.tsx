import { useState } from 'react'

import { api, setToken } from '../api/client'
import type { User } from '../api/types'

/** §12.4: Telegram Login Widget требует домен, привязанный к боту через
/setdomain, и на localhost не отрисуется. Пока DEV_AUTH включён, вместо
виджета — кнопка входа в сид-пользователя. */
export default function LoginScreen({ onLogin }: { onLogin: (user: User) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function login() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.devLogin()
      setToken(result.access_token)
      onLogin(result.user)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось войти')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <h1>Трекер привычек</h1>
      <button type="button" onClick={login} disabled={busy}>
        {busy ? 'Входим…' : 'Войти как тестовый пользователь'}
      </button>
      {error !== null && <p className="error">{error}</p>}
      <p className="hint">
        Локальный вход без Telegram. Часовой пояс берётся из профиля
        пользователя, поменять его можно в настройках.
      </p>
    </div>
  )
}
