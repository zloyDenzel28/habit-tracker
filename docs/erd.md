# ER-диаграмма

Источник — `backend/app/models/`. При любом расхождении с кодом верить коду, не этому файлу.

Ключевой инвариант виден прямо в диаграмме: у `habits` нет ни одного поля статуса
или времени выполнения — только шаблон расписания и метаданные. Весь статус
(`status`) и все временные метки выполнения (`notified_at`, `followup_sent_at`,
`started_at`, `finished_at`) лежат на `occurrences`.

Диаграмма — PlantUML, как и в [`architecture.md`](architecture.md). GitHub её в markdown
не рендерит; чем смотреть картинкой — в разделе «Про формат» там же.

Как читать: **точка перед полем означает `NOT NULL`**, поле без точки — nullable.
Через `=` показано значение по умолчанию, `«PK»` / `«FK»` / `«UK»` — ключи.
Связи в нотации «воронья лапка»: `||—o{` читается как «один ко многим, ноль допустим».

```plantuml
@startuml erd
hide circle
skinparam linetype ortho

entity "users" as users {
  * id : uuid <<PK>>
  --
  * telegram_id : bigint <<UK>>
  telegram_username : varchar(64)
  * first_name : varchar(128)
  * timezone : varchar(64) = 'UTC'
  * created_at : timestamptz = now()
}

entity "habits" as habits {
  * id : uuid <<PK>>
  --
  * user_id : uuid <<FK>>
  * title : varchar(200)
  description : text
  * duration_minutes : int = 5
  * schedule_days : smallint[]
  * schedule_time : time
  * is_archived : boolean = false
  streak_reset_on : date
  * created_at : timestamptz = now()
  * updated_at : timestamptz = now()
}

entity "occurrences" as occurrences {
  * id : uuid <<PK>>
  --
  * habit_id : uuid <<FK>>
  * user_id : uuid <<FK>>
  * local_date : date
  * scheduled_at : timestamptz
  * current_due_at : timestamptz
  * duration_minutes : int
  * status : occurrence_status = 'pending'
  * snooze_count : int = 0
  notified_at : timestamptz
  followup_sent_at : timestamptz
  started_at : timestamptz
  finished_at : timestamptz
}

entity "habit_pauses" as pauses {
  * id : uuid <<PK>>
  --
  * habit_id : uuid <<FK>>
  * starts_on : date
  * ends_on : date
  cancelled_at : timestamptz
  * created_at : timestamptz = now()
}

entity "sent_messages" as sent {
  * id : uuid <<PK>>
  --
  * occurrence_id : uuid <<FK>>
  * kind : sent_message_kind
  * message_id : bigint
  * text : text
  * sent_at : timestamptz
  closed_at : timestamptz
}

users       ||--o{ habits      : создаёт
users       ||--o{ occurrences : владеет
habits      ||--o{ occurrences : порождает выполнения
habits      ||--o{ pauses      : ставится на паузу
occurrences ||--o{ sent        : отправлено в чат

note right of habits
  Шаблон привычки. Статуса выполнения здесь нет
  и быть не должно (инвариант 1).

  schedule_time — ЛОКАЛЬНОЕ время без TZ
  (инвариант 3): хранить его в UTC значит
  уехать на час при переходе на летнее время.

  user_id → ondelete CASCADE.
end note

note bottom of occurrences
  Конкретное выполнение в конкретный день.
  ВСЯ история и весь статус живут только здесь.

  user_id — денормализация ради статистики,
  чтобы не join'ить habits на каждый запрос.
  duration_minutes — снимок на момент создания:
  правка привычки не должна задним числом
  двигать таймер уже запущенного занятия.
  local_date — дата по таймзоне владельца.

  habit_id и user_id → ondelete CASCADE.
end note

note bottom of pauses
  ends_on обязательна: бессрочная пауза даёт
  мёртвые привычки с формально живым стриком.
  cancelled_at — досрочное снятие.

  Создаётся только по явному действию
  пользователя (инвариант 8). Системных пауз нет.
end note

note right of sent
  Сообщение, отправленное в чат (§6.4).
  Без message_id действие из веба не может
  погасить кнопки в Telegram.

  text — СНИМОК отправленного, не ссылка на
  способ его собрать: занятие изменится,
  а сообщение уже нет. Та же причина, что и
  у duration_minutes на occurrences.

  Строк на занятие до двенадцати, а не две:
  снуз шлёт и уведомление, и пинг заново (§5).

  occurrence_id → ondelete CASCADE.
end note
@enduml
```

## Ограничения уровня таблицы

Не видны в списках полей выше, но существуют в БД.

**Уникальность и внешние ключи**

- `occurrences`: `UNIQUE(habit_id, scheduled_at)` — защита от дублей при повторном запуске генератора (инвариант 7). На нём же держится `ON CONFLICT DO NOTHING` в `services/generation.py`.
- `users`: `UNIQUE(telegram_id)` — он же `chat_id` личной переписки с ботом.
- Все FK — с `ondelete CASCADE`. Поэтому `python -m app.fixtures.seed`, пересоздавая пользователя, уносит вместе с ним все привычки и историю.

**Проверки (`CHECK`)**

| Таблица | Ограничение | Зачем |
|---|---|---|
| `habits` | `duration_minutes >= 5` | §3: убирает класс «привычек без длительности» |
| `habits` | `array_length(schedule_days, 1) BETWEEN 1 AND 7` | привычка без единого дня расписания не имеет смысла |
| `habits` | `schedule_days <@ ARRAY[1,…,7]` | дни недели 1–7, пн–вс |
| `occurrences` | `snooze_count BETWEEN 0 AND 5` | §4: максимум пять снузов |
| `occurrences` | `duration_minutes >= 5` | то же правило, что и на шаблоне — снимок не должен его нарушать |
| `habit_pauses` | `ends_on >= starts_on` | отрицательных интервалов не бывает |

**Индексы**

| Таблица | Индекс | Подо что |
|---|---|---|
| `occurrences` | `(status, current_due_at)` | запрос диспетчера уведомлений, §6.2 — раз в тик |
| `occurrences` | `(user_id, local_date)` | календарь-heatmap и расчёт стриков, §7 |
| `habits` | `user_id`, `is_archived` | список привычек пользователя, §9 |
| `habit_pauses` | `habit_id` | загрузка окон паузы генератором, §6.1 |
| `sent_messages` | `occurrence_id` | сообщения одного занятия — их гасит диспетчер при вытеснении |
| `sent_messages` | `(occurrence_id) WHERE closed_at IS NULL` | джоб закрытия сообщений, §6.4 — раз в тик. Частичный: незакрытых всегда единицы, а закрытых со временем накапливается по одной на занятие |

**Типы-перечисления**

`occurrence_status` — enum на стороне Postgres: `pending`, `notified`, `snoozed`, `in_progress`, `done`, `skipped`, `missed`, `paused`. Имена из §4, менять их нельзя. Переходы между ними — в [`architecture.md`](architecture.md) и §4 спеки.

`sent_message_kind` — `notification` (первое уведомление) и `followup` (догоняющий пинг). Оба вида описаны в §5.
