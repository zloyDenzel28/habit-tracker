import { useCallback, useEffect, useState } from 'react'

import { api, AUTH_EXPIRED, getToken, setToken } from './api/client'
import type { User } from './api/types'
import { navigate, useRoute } from './router'
import HabitScreen from './screens/HabitScreen'
import HabitsScreen from './screens/HabitsScreen'
import LoginScreen from './screens/LoginScreen'
import SettingsScreen from './screens/SettingsScreen'
import TodayScreen from './screens/TodayScreen'

const NAV: Array<{ path: string; label: string; match: string }> = [
  { path: '/today', label: 'Сегодня', match: 'today' },
  { path: '/habits', label: 'Мои привычки', match: 'habits' },
  { path: '/settings', label: 'Настройки', match: 'settings' },
]

export default function App() {
  const route = useRoute()
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    // Токен переживает перезагрузку, но проверить его можно только запросом:
    // сид мог пересоздать пользователя, и тогда токен указывает в никуда.
    if (getToken() === null) {
      setReady(true)
      return
    }
    api
      .getMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setReady(true))
  }, [])

  useEffect(() => {
    const onExpired = () => setUser(null)
    window.addEventListener(AUTH_EXPIRED, onExpired)
    return () => window.removeEventListener(AUTH_EXPIRED, onExpired)
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    navigate('/today')
  }, [])

  if (!ready) return <p className="stub">Загрузка…</p>
  if (user === null) return <LoginScreen onLogin={setUser} />

  return (
    <div className="app">
      <header className="topbar">
        <nav>
          {NAV.map((item) => (
            <a
              key={item.path}
              href={`#${item.path}`}
              className={route.name === item.match ? 'active' : undefined}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <span className="who">
          {user.first_name}
          <button type="button" className="link" onClick={logout}>
            выйти
          </button>
        </span>
      </header>

      <TimezoneNotice user={user} />

      <main>
        {route.name === 'today' && <TodayScreen user={user} />}
        {route.name === 'habits' && <HabitsScreen />}
        {route.name === 'habit' && <HabitScreen habitId={route.id} user={user} />}
        {route.name === 'settings' && <SettingsScreen user={user} onChange={setUser} />}
      </main>
    </div>
  )
}

/** Расхождение таймзоны браузера и User.timezone. Само по себе оно ничего
не ломает — расписание считается по User.timezone (инвариант 2) — но объясняет,
почему занятие стоит на непривычное время. Молча подменять настройку нельзя:
человек мог уехать на неделю и не хотеть сдвигать привычки. */
function TimezoneNotice({ user }: { user: User }) {
  const browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone
  if (browserTz === user.timezone) return null
  return (
    <p className="notice">
      Часовой пояс в профиле — <b>{user.timezone}</b>, а браузер показывает{' '}
      <b>{browserTz}</b>. Расписание считается по профилю.{' '}
      <a href="#/settings">Изменить</a>
    </p>
  )
}
