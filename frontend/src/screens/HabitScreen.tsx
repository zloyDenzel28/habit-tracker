import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Habit, HabitPause, HabitStats, HeatmapDay, User } from '../api/types'
import HabitForm from '../components/HabitForm'
import Heatmap from '../components/Heatmap'
import { formatDate, formatDays, todayInTimezone, trimSeconds } from '../format'

/** Экран «Привычка» (§9): детали, серия, рекорд, heatmap, процент за 30 дней
и управление паузами. */
export default function HabitScreen({ habitId, user }: { habitId: string; user: User }) {
  const [habit, setHabit] = useState<Habit | null>(null)
  const [stats, setStats] = useState<HabitStats | null>(null)
  const [heatmap, setHeatmap] = useState<HeatmapDay[]>([])
  const [pauses, setPauses] = useState<HabitPause[]>([])
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [habitData, statsData, heatmapData, pausesData] = await Promise.all([
        api.getHabit(habitId),
        api.getStats(habitId),
        api.getHeatmap(habitId),
        api.listPauses(habitId),
      ])
      setHabit(habitData)
      setStats(statsData)
      setHeatmap(heatmapData)
      setPauses(pausesData)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить привычку')
    }
  }, [habitId])

  useEffect(() => {
    void reload()
  }, [reload])

  if (error !== null && habit === null) return <p className="error">{error}</p>
  if (habit === null || stats === null) return <p className="stub">Загрузка…</p>

  if (editing) {
    return (
      <HabitForm
        habit={habit}
        onSaved={() => {
          setEditing(false)
          void reload()
        }}
        onCancel={() => setEditing(false)}
      />
    )
  }

  return (
    <section>
      <a className="back" href="#/habits">
        ← Мои привычки
      </a>

      <div className="screen-head">
        <h1>{habit.title}</h1>
        <button type="button" onClick={() => setEditing(true)}>
          Изменить
        </button>
      </div>
      <p className="card-meta">
        {formatDays(habit.schedule_days)} в {trimSeconds(habit.schedule_time)} ·{' '}
        {habit.duration_minutes} мин
        {habit.is_archived && <> · в архиве</>}
      </p>
      {habit.description !== null && <p>{habit.description}</p>}

      {error !== null && <p className="error">{error}</p>}

      <h2>Статистика</h2>
      <div className="stats">
        <Metric value={String(stats.current_streak)} label="серия" />
        <Metric value={String(stats.best_streak)} label="рекорд" />
        <Metric
          // null означает «данных нет», и это не то же самое, что 0%.
          value={
            stats.completion_rate === null ? '—' : `${Math.round(stats.completion_rate * 100)}%`
          }
          label={`за ${stats.window_days} дней`}
        />
        <Metric value={String(stats.done)} label="выполнено" />
        <Metric value={String(stats.skipped)} label="пропущено" />
        <Metric value={String(stats.missed)} label="просрочено" />
      </div>

      <h2>Последние 90 дней</h2>
      <Heatmap days={heatmap} endDate={todayInTimezone(user.timezone)} />

      <h2>Заморозка</h2>
      <PauseSection
        habitId={habitId}
        pauses={pauses}
        timezone={user.timezone}
        onChanged={() => void reload()}
        onError={setError}
      />
    </section>
  )
}

function Metric({ value, label }: { value: string; label: string }) {
  return (
    <div className="metric">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  )
}

function PauseSection({
  habitId,
  pauses,
  timezone,
  onChanged,
  onError,
}: {
  habitId: string
  pauses: HabitPause[]
  timezone: string
  onChanged: () => void
  onError: (message: string) => void
}) {
  const [startsOn, setStartsOn] = useState(() => todayInTimezone(timezone))
  const [endsOn, setEndsOn] = useState('')
  const [resetsStreak, setResetsStreak] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    // Ручка предпросмотра требует обе даты. Пустое «до» означает паузу
    // на неделю по умолчанию (§3) — она заведомо короче 14 дней, и серию
    // не обнулит, так что спрашивать бэк не о чем.
    if (endsOn === '') {
      setResetsStreak(false)
      return
    }
    api
      .previewPause(habitId, startsOn, endsOn)
      .then((result) => setResetsStreak(result.resets_streak))
      .catch(() => setResetsStreak(false))
  }, [habitId, startsOn, endsOn])

  async function create(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    try {
      await api.createPause(habitId, startsOn, endsOn === '' ? null : endsOn)
      setEndsOn('')
      onChanged()
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Не удалось поставить паузу')
    } finally {
      setBusy(false)
    }
  }

  async function cancel(pauseId: string) {
    try {
      await api.cancelPause(habitId, pauseId)
      onChanged()
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Не удалось снять паузу')
    }
  }

  return (
    <>
      {pauses.length > 0 && (
        <ul className="pauses">
          {pauses.map((pause) => (
            <li key={pause.id}>
              {formatDate(pause.starts_on)} — {formatDate(pause.ends_on)}
              <button type="button" className="link" onClick={() => void cancel(pause.id)}>
                снять досрочно
              </button>
            </li>
          ))}
        </ul>
      )}

      <form className="pause-form" onSubmit={(event) => void create(event)}>
        <label>
          С
          <input
            type="date"
            value={startsOn}
            /* §3: пауза задним числом запрещена. Подсказка браузера, отказ
               всё равно приходит от бэка — проверка живёт в services (инвариант 4). */
            min={todayInTimezone(timezone)}
            onChange={(e) => setStartsOn(e.target.value)}
            required
          />
        </label>
        <label>
          По
          <input type="date" value={endsOn} onChange={(e) => setEndsOn(e.target.value)} />
        </label>
        <button type="submit" disabled={busy}>
          Поставить на паузу
        </button>
      </form>
      <p className="hint">Без даты окончания пауза ставится на неделю.</p>
      {resetsStreak && (
        <p className="warning">⚠️ Пауза дольше 14 дней обнулит текущую серию.</p>
      )}
    </>
  )
}
