import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Habit, HabitOverlap } from '../api/types'
import { formatWindow, trimSeconds, weekdayName } from '../format'

const ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]

/** Форма создания и правки привычки (§9).

Проверки минимальной длительности, непустого названия и диапазона дней живут
в services/habits.py (инвариант 4). Здесь только атрибуты required/min, чтобы
браузер подсказал заранее; отказ всё равно приходит от бэка и показывается
его текстом.
*/
export default function HabitForm({
  habit,
  onSaved,
  onCancel,
}: {
  habit?: Habit
  onSaved: (habit: Habit) => void
  onCancel: () => void
}) {
  const [title, setTitle] = useState(habit?.title ?? '')
  const [description, setDescription] = useState(habit?.description ?? '')
  const [duration, setDuration] = useState(habit?.duration_minutes ?? 5)
  const [days, setDays] = useState<number[]>(habit?.schedule_days ?? ALL_DAYS)
  const [time, setTime] = useState(trimSeconds(habit?.schedule_time ?? '09:00:00'))
  const [overlaps, setOverlaps] = useState<HabitOverlap[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const habitId = habit?.id

  useEffect(() => {
    if (days.length === 0 || time === '') {
      setOverlaps([])
      return
    }
    // Ручка вызывается на каждое изменение полей, поэтому задержка: без неё
    // набор времени в поле даёт запрос на каждое нажатие.
    const timer = window.setTimeout(() => {
      api
        .checkOverlap({
          schedule_days: days,
          schedule_time: time,
          duration_minutes: duration,
          exclude_habit_id: habitId,
        })
        .then(setOverlaps)
        // Пересечение только предупреждает и не блокирует сохранение (§9),
        // поэтому упавшая проверка не должна мешать заполнять форму.
        .catch(() => setOverlaps([]))
    }, 400)
    return () => window.clearTimeout(timer)
  }, [days, time, duration, habitId])

  function toggleDay(day: number) {
    setDays((prev) =>
      prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day].sort((a, b) => a - b),
    )
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const payload = {
      title,
      description: description.trim() === '' ? null : description,
      duration_minutes: duration,
      schedule_days: days,
      schedule_time: time,
    }
    try {
      onSaved(habit ? await api.updateHabit(habit.id, payload) : await api.createHabit(payload))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="habit-form" onSubmit={(event) => void submit(event)}>
      <h2>{habit ? 'Изменить привычку' : 'Новая привычка'}</h2>

      <label>
        Название
        <input value={title} onChange={(e) => setTitle(e.target.value)} required />
      </label>

      <label>
        Описание
        <textarea
          value={description}
          rows={2}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>

      <div className="row">
        <label>
          Время
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} required />
        </label>
        <label>
          Длительность, мин
          <input
            type="number"
            min={5}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            required
          />
        </label>
      </div>

      <fieldset className="days">
        <legend>Дни недели</legend>
        {ALL_DAYS.map((day) => (
          <label key={day} className={days.includes(day) ? 'day on' : 'day'}>
            <input type="checkbox" checked={days.includes(day)} onChange={() => toggleDay(day)} />
            {weekdayName(day)}
          </label>
        ))}
      </fieldset>

      {overlaps.map((other) => (
        <p key={other.id} className="warning">
          ⚠️ Пересекается с «{other.title}» ({formatWindow(other.schedule_time, other.duration_minutes)})
        </p>
      ))}

      {error !== null && <p className="error">{error}</p>}

      <div className="actions">
        <button type="submit" disabled={busy}>
          {busy ? 'Сохраняем…' : 'Сохранить'}
        </button>
        <button type="button" className="link" onClick={onCancel}>
          Отмена
        </button>
      </div>
    </form>
  )
}
