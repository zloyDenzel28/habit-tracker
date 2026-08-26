import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import type { Occurrence, OccurrenceAction, User } from '../api/types'
import { formatTime, STATUS_LABELS } from '../format'

const ACTION_LABELS: Record<OccurrenceAction, string> = {
  start: '▶️ Начал',
  snooze: '⏰ +5 мин',
  complete: '✅ Выполнил',
  skip: '❌ Пропустил',
}

/** Экран «Сегодня» (§9). День берётся не из браузера: ручка без параметра
отдаёт занятия на сегодня по User.timezone (инвариант 2). */
export default function TodayScreen({ user }: { user: User }) {
  const [items, setItems] = useState<Occurrence[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setItems(await api.listOccurrences())
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось загрузить список')
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  if (error !== null && items === null) return <p className="error">{error}</p>
  if (items === null) return <p className="stub">Загрузка…</p>

  return (
    <section>
      <h1>Сегодня</h1>
      <TelegramHint />
      {error !== null && <p className="error">{error}</p>}
      {items.length === 0 ? (
        <p className="stub">На сегодня занятий нет.</p>
      ) : (
        <ul className="cards">
          {items.map((item) => (
            <OccurrenceCard
              key={item.id}
              occurrence={item}
              user={user}
              onUpdated={(updated) =>
                setItems((prev) =>
                  prev === null ? prev : prev.map((o) => (o.id === updated.id ? updated : o)),
                )
              }
              onFailed={(message) => {
                setError(message)
                // Отказ обычно значит, что статус уже сменился в другом месте:
                // кнопкой в Telegram или джобом закрытия дня. Перечитываем,
                // чтобы на экране не осталось кнопок, которых уже нет.
                void reload()
              }}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

const HINT_KEY = 'habit-tracker:telegram-hint-dismissed'

/** Одноразовая подсказка про подписку на бота.

Проверить, начал ли человек диалог, нельзя: Telegram про это не сообщает,
отказ виден только при попытке отправки и уходит в логи воркера. Поэтому
подсказка показывается всем и закрывается вручную — иначе тот, кто уже
нажал «Старт», видел бы её вечно. */
function TelegramHint() {
  const [dismissed, setDismissed] = useState(() => {
    // В приватном окне доступ к localStorage может бросить исключение.
    try {
      return localStorage.getItem(HINT_KEY) !== null
    } catch {
      return false
    }
  })

  if (dismissed) return null

  function dismiss() {
    try {
      localStorage.setItem(HINT_KEY, '1')
    } catch {
      /* не сохранилось — подсказка просто вернётся после перезагрузки */
    }
    setDismissed(true)
  }

  return (
    <p className="notice">
      Напоминания приходят в Telegram, но бот не может написать первым, пока вы
      сами не отправите ему «Старт». Как это сделать — в{' '}
      <a href="#/settings">настройках</a>.
      <button type="button" className="link" onClick={dismiss}>
        понятно
      </button>
    </p>
  )
}

function OccurrenceCard({
  occurrence,
  user,
  onUpdated,
  onFailed,
}: {
  occurrence: Occurrence
  user: User
  onUpdated: (updated: Occurrence) => void
  onFailed: (message: string) => void
}) {
  const [busy, setBusy] = useState(false)

  // Какие действия доступны, посчитал бэк из тех же наборов статусов, что
  // и кнопки в Telegram (§9) — фронт эти правила не дублирует.
  const actions: OccurrenceAction[] = []
  if (occurrence.can_start) actions.push('start')
  if (occurrence.can_snooze) actions.push('snooze')
  if (occurrence.can_complete) actions.push('complete')
  if (occurrence.can_skip) actions.push('skip')

  async function act(action: OccurrenceAction) {
    setBusy(true)
    try {
      onUpdated(await api.actOnOccurrence(occurrence.id, action))
    } catch (err) {
      onFailed(err instanceof Error ? err.message : 'Действие не прошло')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="card">
      <div className="card-head">
        <span className="time">{formatTime(occurrence.current_due_at, user.timezone)}</span>
        <a className="title" href={`#/habits/${occurrence.habit_id}`}>
          {occurrence.habit_title}
        </a>
        <span className={`badge status-${occurrence.status}`}>
          {STATUS_LABELS[occurrence.status]}
        </span>
      </div>
      <div className="card-meta">
        {occurrence.duration_minutes} мин
        {occurrence.snooze_count > 0 && <> · отложено {occurrence.snooze_count} раз</>}
      </div>
      {actions.length > 0 && (
        <div className="actions">
          {actions.map((action) => (
            <button key={action} type="button" disabled={busy} onClick={() => void act(action)}>
              {ACTION_LABELS[action]}
            </button>
          ))}
        </div>
      )}
    </li>
  )
}
