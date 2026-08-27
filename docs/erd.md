# ER-диаграмма

Источник — `backend/app/models/`. При любом расхождении с кодом верить коду, не этому файлу.

Ключевой инвариант виден прямо в диаграмме: у `HABIT` нет ни одного поля статуса
или времени выполнения — только шаблон расписания и метаданные. Весь статус
(`status`) и все временные метки выполнения (`notified_at`, `followup_sent_at`,
`started_at`, `finished_at`) лежат на `OCCURRENCE`.

```mermaid
erDiagram
    USER ||--o{ HABIT : "создаёт"
    USER ||--o{ OCCURRENCE : "владеет (денормализация user_id)"
    HABIT ||--o{ OCCURRENCE : "порождает выполнения"
    HABIT ||--o{ HABIT_PAUSE : "ставится на паузу"

    USER {
        uuid id PK
        bigint telegram_id UK "not null, он же chat_id бота"
        string telegram_username "nullable, varchar(64)"
        string first_name "not null, varchar(128)"
        string timezone "not null, varchar(64), default 'UTC', IANA-имя"
        timestamptz created_at "not null, default now()"
    }

    HABIT {
        uuid id PK "шаблон привычки — статуса выполнения здесь нет"
        uuid user_id FK "not null, ondelete CASCADE"
        string title "not null, varchar(200)"
        text description "nullable"
        int duration_minutes "not null, default 5, check >= 5"
        smallint_array schedule_days "not null, дни 1-7 пн-вс, check длина 1..7 и значения из {1..7}"
        time schedule_time "not null, ЛОКАЛЬНОЕ время без TZ (инвариант 3)"
        boolean is_archived "not null, default false, мягкое удаление"
        date streak_reset_on "nullable, точка сброса серии после восстановления из архива"
        timestamptz created_at "not null, default now()"
        timestamptz updated_at "not null, default now(), onupdate now()"
    }

    OCCURRENCE {
        uuid id PK "конкретное выполнение в конкретный день — вся история здесь"
        uuid habit_id FK "not null, ondelete CASCADE"
        uuid user_id FK "not null, ondelete CASCADE, денормализация ради статистики"
        date local_date "not null, дата по таймзоне пользователя на момент создания"
        timestamptz scheduled_at "not null, исходное плановое время"
        timestamptz current_due_at "not null, плановое время с учётом снузов"
        int duration_minutes "not null, снимок Habit.duration_minutes на момент создания"
        occurrence_status status "not null, default 'pending' — СТАТУС ВЫПОЛНЕНИЯ ЖИВЁТ ТОЛЬКО ЗДЕСЬ"
        int snooze_count "not null, default 0, check 0..5"
        timestamptz notified_at "nullable, метка отправки уведомления"
        timestamptz followup_sent_at "nullable, метка догоняющего пинга (инвариант 7)"
        timestamptz started_at "nullable, метка начала выполнения"
        timestamptz finished_at "nullable, метка завершения выполнения"
    }

    HABIT_PAUSE {
        uuid id PK
        uuid habit_id FK "not null, ondelete CASCADE"
        date starts_on "not null"
        date ends_on "not null, check ends_on >= starts_on, обязательна — бессрочных пауз нет"
        timestamptz cancelled_at "nullable, метка досрочного снятия паузы"
        timestamptz created_at "not null, default now()"
    }
```

## Ограничения уровня таблицы (не видны в полях выше)

- `occurrences`: `UNIQUE(habit_id, scheduled_at)` — защита от дублей при повторном запуске генератора (инвариант 7).
- `occurrences`: индекс `(status, current_due_at)` — под диспетчер уведомлений, опрос раз в минуту.
- `occurrences`: индекс `(user_id, local_date)` — под календарь-heatmap и расчёт стриков.
- `habits`: индекс на `user_id` и на `is_archived`.
- `habit_pauses`: индекс на `habit_id`.
