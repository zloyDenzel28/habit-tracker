/** Форматирование для показа. Единственный источник локального времени —
User.timezone (инвариант 2), таймзона браузера здесь не участвует нигде,
кроме подсказки на экране настроек. */

import type { OccurrenceStatus } from './api/types'

const WEEKDAY_NAMES = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

export const STATUS_LABELS: Record<OccurrenceStatus, string> = {
  pending: 'ожидает',
  notified: 'напомнили',
  snoozed: 'отложено',
  in_progress: 'в процессе',
  done: 'выполнено',
  skipped: 'пропущено',
  missed: 'просрочено',
  paused: 'на паузе',
}

/** UTC-момент из API в часы:минуты по таймзоне пользователя. */
export function formatTime(iso: string, timezone: string): string {
  return new Date(iso).toLocaleTimeString('ru-RU', {
    timeZone: timezone,
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** "19:00:00" из Habit.schedule_time -> "19:00". Это уже локальное время
без таймзоны (инвариант 3), пересчитывать его нельзя. */
export function trimSeconds(scheduleTime: string): string {
  return scheduleTime.slice(0, 5)
}

/** Окно привычки для предупреждения о пересечении: "19:30–20:00" (§9). */
export function formatWindow(scheduleTime: string, durationMinutes: number): string {
  const [hours, minutes] = scheduleTime.split(':').map(Number)
  const end = hours * 60 + minutes + durationMinutes
  const endText = `${String(Math.floor(end / 60) % 24).padStart(2, '0')}:${String(end % 60).padStart(2, '0')}`
  return `${trimSeconds(scheduleTime)}–${endText}`
}

/** [1,2,3,4,5,6,7] -> "каждый день", [1,3,5] -> "пн, ср, пт". */
export function formatDays(days: number[]): string {
  if (days.length === 7) return 'каждый день'
  const sorted = [...days].sort((a, b) => a - b)
  if (sorted.length === 5 && sorted.every((d, i) => d === i + 1)) return 'по будням'
  return sorted.map((day) => WEEKDAY_NAMES[day - 1]).join(', ')
}

export function weekdayName(day: number): string {
  return WEEKDAY_NAMES[day - 1]
}

/** "2026-08-26" -> "26 августа". */
export function formatDate(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString('ru-RU', {
    timeZone: 'UTC',
    day: 'numeric',
    month: 'long',
  })
}

/** Дата в формате input[type=date] по таймзоне пользователя. */
export function todayInTimezone(timezone: string): string {
  // en-CA даёт ровно YYYY-MM-DD — то, что ждут и input, и бэк.
  return new Date().toLocaleDateString('en-CA', { timeZone: timezone })
}
