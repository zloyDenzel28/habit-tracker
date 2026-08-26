/** Зеркало app/api/schemas.py. Меняется схема на бэке — меняется и здесь. */

export type OccurrenceStatus =
  | 'pending'
  | 'notified'
  | 'snoozed'
  | 'in_progress'
  | 'done'
  | 'skipped'
  | 'missed'
  | 'paused'

export interface User {
  id: string
  telegram_id: number
  telegram_username: string | null
  first_name: string
  timezone: string
  created_at: string
  /** Юзернейм бота из TELEGRAM_BOT_USERNAME, для ссылки t.me/<username>. */
  bot_username: string | null
}

/** Что «Настройки» узнают до сохранения таймзоны (§8): сколько сегодняшних
занятий исчезнет, потому что их новое плановое время уже прошло. */
export interface TimezonePreview {
  removed_today: number
}

export interface DevLogin {
  access_token: string
  token_type: string
  user: User
}

export interface Habit {
  id: string
  title: string
  description: string | null
  duration_minutes: number
  /** 1-7, пн-вс (§3). */
  schedule_days: number[]
  /** Локальное время без таймзоны, "HH:MM:SS" (инвариант 3). */
  schedule_time: string
  is_archived: boolean
  streak_reset_on: string | null
  created_at: string
  updated_at: string
  /** Дата окончания активной сегодня паузы (находка 13). Только в GET /habits. */
  paused_until: string | null
}

/** Тело POST /habits и PATCH /habits/{id} — при правке все поля опциональны. */
export interface HabitPayload {
  title: string
  description: string | null
  duration_minutes: number
  schedule_days: number[]
  schedule_time: string
}

/** Короткая карточка чужой привычки для предупреждения о пересечении (§9). */
export interface HabitOverlap {
  id: string
  title: string
  schedule_time: string
  duration_minutes: number
}

export interface HabitPause {
  id: string
  starts_on: string
  ends_on: string
  cancelled_at: string | null
}

export interface HabitStats {
  current_streak: number
  best_streak: number
  done: number
  skipped: number
  missed: number
  window_days: number
  /** null, а не 0, когда за окно ещё нечего считать. */
  completion_rate: number | null
}

export interface HeatmapDay {
  date: string
  status: OccurrenceStatus
}

export interface Occurrence {
  id: string
  habit_id: string
  habit_title: string
  local_date: string
  scheduled_at: string
  current_due_at: string
  duration_minutes: number
  status: OccurrenceStatus
  snooze_count: number
  notified_at: string | null
  followup_sent_at: string | null
  started_at: string | null
  finished_at: string | null
  // Какие кнопки показывать, решает бэк (инвариант 4) — фронт только читает.
  can_start: boolean
  can_snooze: boolean
  can_complete: boolean
  can_skip: boolean
}

export type OccurrenceAction = 'start' | 'snooze' | 'complete' | 'skip'
