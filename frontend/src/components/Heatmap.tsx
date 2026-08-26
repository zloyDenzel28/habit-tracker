import type { HeatmapDay, OccurrenceStatus } from '../api/types'
import { formatDate, STATUS_LABELS } from '../format'

const DAYS = 90
const LEGEND: OccurrenceStatus[] = ['done', 'skipped', 'missed', 'paused']

/** Heatmap за последние 90 дней (§9).

Ручка отдаёт только те дни, на которые есть occurrence: в дни, когда привычка
не запланирована, её просто нет. Поэтому сетка строится от календаря, а данные
раскладываются по ней — иначе пропуски в расписании съезжали бы по неделям.
*/
export default function Heatmap({ days, endDate }: { days: HeatmapDay[]; endDate: string }) {
  const byDate = new Map(days.map((day) => [day.date, day.status]))

  const end = new Date(`${endDate}T00:00:00Z`)
  const start = new Date(end)
  start.setUTCDate(start.getUTCDate() - (DAYS - 1))
  // Сетка всегда начинается с понедельника, чтобы строки соответствовали
  // дням недели. getUTCDay(): 0 — воскресенье, приводим к 0 — понедельник.
  start.setUTCDate(start.getUTCDate() - ((start.getUTCDay() + 6) % 7))

  const cells: Array<{ date: string; status: OccurrenceStatus | null }> = []
  for (const cursor = new Date(start); cursor <= end; cursor.setUTCDate(cursor.getUTCDate() + 1)) {
    const iso = cursor.toISOString().slice(0, 10)
    cells.push({ date: iso, status: byDate.get(iso) ?? null })
  }

  return (
    <div className="heatmap-block">
      <div className="heatmap">
        {cells.map((cell) => (
          <span
            key={cell.date}
            className={`hm ${cell.status === null ? 'hm-empty' : `status-${cell.status}`}`}
            title={`${formatDate(cell.date)}${cell.status === null ? '' : ` — ${STATUS_LABELS[cell.status]}`}`}
          />
        ))}
      </div>
      <div className="legend">
        {LEGEND.map((status) => (
          <span key={status}>
            <span className={`hm status-${status}`} /> {STATUS_LABELS[status]}
          </span>
        ))}
      </div>
    </div>
  )
}
