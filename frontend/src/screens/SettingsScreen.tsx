import { useEffect, useState } from 'react'

import { api } from '../api/client'
import type { User } from '../api/types'

/** «1 занятие исчезнет» / «2 занятия исчезнут» / «5 занятий исчезнут».
Слово и глагол вместе: по отдельности они разъезжаются на единице. */
function removedPhrase(count: number): string {
  // 11-14 ведут себя как «много» вопреки последней цифре: 11, 111, 1011.
  const teen = count % 100 >= 11 && count % 100 <= 14
  const last = count % 10
  const one = !teen && last === 1
  const few = !teen && last >= 2 && last <= 4
  const word = one ? 'занятие' : few ? 'занятия' : 'занятий'
  return `${count} ${word} ${one ? 'исчезнет' : 'исчезнут'}`
}

/** Список IANA-зон из браузера. supportedValuesOf есть не везде, поэтому
на случай его отсутствия остаётся хотя бы текущая зона и зона браузера —
поле всё равно редактируется вручную, а неизвестное имя отсеет бэк. */
function timezoneOptions(current: string): string[] {
  const supported = Intl.supportedValuesOf?.('timeZone') ?? []
  const fallback = [current, Intl.DateTimeFormat().resolvedOptions().timeZone]
  return [...new Set(supported.length > 0 ? supported : fallback)]
}

/** Экран «Настройки» (§9): таймзона и канал уведомлений. */
export default function SettingsScreen({
  user,
  onChange,
}: {
  user: User
  onChange: (user: User) => void
}) {
  const [timezone, setTimezone] = useState(user.timezone)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [removedToday, setRemovedToday] = useState(0)

  // §8: занятия, чьё новое плановое время уже прошло, при сохранении
  // удаляются — день исчезает из «Сегодня», из heatmap и из знаменателя
  // процента за 30 дней. Спросить об этом надо до нажатия, а не после.
  useEffect(() => {
    if (timezone === user.timezone) {
      setRemovedToday(0)
      return
    }
    // Поле редактируется вручную, поэтому задержка: без неё каждая
    // напечатанная буква даёт запрос, и почти каждый — на битое имя зоны.
    const timer = window.setTimeout(() => {
      api
        .previewTimezone(timezone)
        .then((preview) => setRemovedToday(preview.removed_today))
        // Предупреждение не блокирует сохранение, а недописанное имя зоны
        // законно даёт 400 — молчим и ждём следующего ввода.
        .catch(() => setRemovedToday(0))
    }, 400)
    return () => window.clearTimeout(timer)
  }, [timezone, user.timezone])

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      // §8: смена таймзоны пересобирает будущие occurrences. Это делает
      // сервисный слой, фронт только отправляет новое имя зоны.
      onChange(await api.setTimezone(timezone))
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h1>Настройки</h1>

      <form className="settings" onSubmit={(event) => void save(event)}>
        <label>
          Часовой пояс
          <input list="timezones" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
          <datalist id="timezones">
            {timezoneOptions(user.timezone).map((zone) => (
              <option key={zone} value={zone} />
            ))}
          </datalist>
        </label>
        <p className="hint">
          По нему считаются день привычки и время напоминания. Уже назначенные
          на будущее занятия пересчитаются.
        </p>
        {removedToday > 0 && (
          <p className="warning">
            ⚠️ {removedPhrase(removedToday)} из «Сегодня» и из статистики:
            по новому времени сегодняшний срок уже прошёл. Отменить это
            будет нельзя.
          </p>
        )}
        <button type="submit" disabled={busy || timezone === user.timezone}>
          {busy ? 'Сохраняем…' : 'Сохранить'}
        </button>
        {saved && <p className="hint">Сохранено.</p>}
        {error !== null && <p className="error">{error}</p>}
      </form>

      <h2>Уведомления</h2>
      <label className="channel">
        Канал
        <select value="telegram" disabled>
          <option value="telegram">Telegram</option>
        </select>
      </label>
      <p className="hint">Других каналов в MVP нет — поле оставлено на будущее.</p>

      <p>
        Telegram не разрешает боту написать первым, пока вы сами не начали
        диалог. Поэтому один раз это нужно сделать вручную:
      </p>
      <ol className="steps">
        <li>
          Откройте в Telegram своего бота — того, чей токен лежит
          в <code>TELEGRAM_BOT_TOKEN</code>.
        </li>
        <li>
          Нажмите «Старт» или отправьте <code>/start</code>.
        </li>
      </ol>
      <p className="hint">
        Без этого напоминания не придут, и в интерфейсе это никак не видно:
        отказ Telegram попадает только в логи воркера. Если уведомлений нет —
        проверку стоит начинать отсюда.
      </p>

      <h2>Профиль</h2>
      <ul className="profile">
        <li>Имя: {user.first_name}</li>
        <li>Telegram: {user.telegram_username ?? '—'}</li>
      </ul>
    </section>
  )
}
