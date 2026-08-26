import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Habit } from '../api/types'
import HabitForm from '../components/HabitForm'
import { formatDays, trimSeconds } from '../format'

/** Экран «Мои привычки» (§9): список, создание, редактирование, архивация.
Пауза живёт на экране привычки — там же, где серия, которую она может обнулить. */
export default function HabitsScreen() {
  const [habits, setHabits] = useState<Habit[] | null>(null)
  const [includeArchived, setIncludeArchived] = useState(false)
  const [editing, setEditing] = useState<Habit | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setHabits(await api.listHabits(includeArchived))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить привычки')
    }
  }, [includeArchived])

  useEffect(() => {
    void reload()
  }, [reload])

  async function toggleArchive(habit: Habit) {
    try {
      // Восстановление пересобирает будущие occurrences — это делает сервис,
      // фронту достаточно перечитать список.
      await (habit.is_archived ? api.restoreHabit(habit.id) : api.archiveHabit(habit.id))
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось изменить привычку')
    }
  }

  if (editing !== null) {
    return (
      <HabitForm
        habit={editing === 'new' ? undefined : editing}
        onSaved={() => {
          setEditing(null)
          void reload()
        }}
        onCancel={() => setEditing(null)}
      />
    )
  }

  return (
    <section>
      <div className="screen-head">
        <h1>Мои привычки</h1>
        <button type="button" onClick={() => setEditing('new')}>
          Новая привычка
        </button>
      </div>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={includeArchived}
          onChange={(e) => setIncludeArchived(e.target.checked)}
        />
        Показывать архивные
      </label>

      {error !== null && <p className="error">{error}</p>}
      {habits === null ? (
        <p className="stub">Загрузка…</p>
      ) : habits.length === 0 ? (
        <p className="stub">Привычек пока нет.</p>
      ) : (
        <ul className="cards">
          {habits.map((habit) => (
            <li key={habit.id} className={habit.is_archived ? 'card archived' : 'card'}>
              <div className="card-head">
                <span className="time">{trimSeconds(habit.schedule_time)}</span>
                <a className="title" href={`#/habits/${habit.id}`}>
                  {habit.title}
                </a>
                {habit.is_archived && <span className="badge">в архиве</span>}
              </div>
              <div className="card-meta">
                {formatDays(habit.schedule_days)} · {habit.duration_minutes} мин
                {habit.description !== null && <> · {habit.description}</>}
              </div>
              <div className="actions">
                <button type="button" onClick={() => setEditing(habit)}>
                  Изменить
                </button>
                <button type="button" onClick={() => void toggleArchive(habit)}>
                  {habit.is_archived ? 'Вернуть из архива' : 'В архив'}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
