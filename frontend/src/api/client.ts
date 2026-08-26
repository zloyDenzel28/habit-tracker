/** Тонкая обёртка над fetch: токен, разбор ошибок, типизированные ручки.

Никакой бизнес-логики здесь нет и быть не должно (инвариант 4) — решения
про допустимость действий принимает бэк, фронт только вызывает и показывает.
*/

import type {
  DevLogin,
  Habit,
  HabitOverlap,
  HabitPause,
  HabitPayload,
  HabitStats,
  HeatmapDay,
  Occurrence,
  OccurrenceAction,
  User,
} from './types'

const TOKEN_KEY = 'habit-tracker-token'

/** Событие, по которому App возвращает пользователя на экран входа. */
export const AUTH_EXPIRED = 'habit-tracker:auth-expired'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token === null) localStorage.removeItem(TOKEN_KEY)
  else localStorage.setItem(TOKEN_KEY, token)
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token !== null) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  // Префикс /api снимает прокси Vite (см. vite.config.ts).
  const response = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!response.ok) {
    // Единый формат ошибок бэка — {"detail": "..."}, текст на русском
    // и предназначен для показа человеку как есть.
    let detail = `Ошибка ${response.status}`
    try {
      const payload = (await response.json()) as { detail?: unknown }
      if (typeof payload.detail === 'string') detail = payload.detail
      // 422 от Pydantic отдаёт detail списком — до пользователя такое
      // доводить незачем, показываем обобщённо.
      else if (Array.isArray(payload.detail)) detail = 'Неверные данные формы'
    } catch {
      /* тело не JSON — остаётся код */
    }
    if (response.status === 401) {
      // Дев-токен без TTL протухнуть не может, но пересозданный сидом
      // пользователь получает новый id, и старый токен в localStorage
      // становится чужим. Тогда единственный выход — заново войти.
      setToken(null)
      window.dispatchEvent(new Event(AUTH_EXPIRED))
    }
    throw new ApiError(response.status, detail)
  }

  return (await response.json()) as T
}

export const api = {
  devLogin: () => request<DevLogin>('POST', '/auth/dev-login'),

  getMe: () => request<User>('GET', '/users/me'),
  setTimezone: (timezone: string) => request<User>('PATCH', '/users/me', { timezone }),

  listHabits: (includeArchived = false) =>
    request<Habit[]>('GET', `/habits?include_archived=${includeArchived}`),
  getHabit: (id: string) => request<Habit>('GET', `/habits/${id}`),
  createHabit: (payload: HabitPayload) => request<Habit>('POST', '/habits', payload),
  updateHabit: (id: string, payload: Partial<HabitPayload>) =>
    request<Habit>('PATCH', `/habits/${id}`, payload),
  archiveHabit: (id: string) => request<Habit>('POST', `/habits/${id}/archive`),
  restoreHabit: (id: string) => request<Habit>('POST', `/habits/${id}/restore`),
  checkOverlap: (payload: {
    schedule_days: number[]
    schedule_time: string
    duration_minutes: number
    exclude_habit_id?: string
  }) => request<HabitOverlap[]>('POST', '/habits/check-overlap', payload),

  listPauses: (habitId: string) => request<HabitPause[]>('GET', `/habits/${habitId}/pauses`),
  createPause: (habitId: string, starts_on: string, ends_on: string | null) =>
    request<HabitPause>('POST', `/habits/${habitId}/pauses`, { starts_on, ends_on }),
  cancelPause: (habitId: string, pauseId: string) =>
    request<HabitPause>('POST', `/habits/${habitId}/pauses/${pauseId}/cancel`),
  previewPause: (habitId: string, starts_on: string, ends_on: string) =>
    request<{ resets_streak: boolean }>(
      'GET',
      `/habits/${habitId}/pause-preview?starts_on=${starts_on}&ends_on=${ends_on}`,
    ),

  getStats: (habitId: string) => request<HabitStats>('GET', `/habits/${habitId}/stats`),
  getHeatmap: (habitId: string) => request<HeatmapDay[]>('GET', `/habits/${habitId}/heatmap`),

  listOccurrences: () => request<Occurrence[]>('GET', '/occurrences'),
  actOnOccurrence: (id: string, action: OccurrenceAction) =>
    request<Occurrence>('POST', `/occurrences/${id}/${action}`),
}
