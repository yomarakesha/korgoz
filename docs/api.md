# KörGöz API

REST API на FastAPI. Запуск: `uvicorn app.main:app` (по умолчанию http://127.0.0.1:8000).
Интерактивная документация со всеми схемами: `/docs` (Swagger UI).

> **Нужен вход** (Phase 9, подробно — [security.md](security.md)). Без сеанса все
> эндпоинты, кроме `GET /health` и `POST /auth/login`, отвечают **401**. Роль `user`
> может только читать (GET); POST/PATCH/DELETE, `/users` и `/audit` — только `admin`
> (иначе **403**). Сеанс — cookie `korgoz_session` (ставится при входе) или заголовок
> `Authorization: Bearer <access_token>`.

Общие правила:
- время — ISO 8601 с часовым поясом, хранится в UTC (`2026-01-01T09:00:00Z`);
- списки отдаются **новые сверху**, пагинация `limit` (1–1000, по умолчанию 100) и `offset`;
- ошибки — JSON `{"detail": "..."}`: 401 нужен вход, 403 нужна роль admin, 404 нет объекта,
  409 конфликт, 422 неверные данные, 429 много неудачных входов, 503 недоступна БД или Qdrant.

## Вход и пользователи

| Метод | Путь | Кто | Описание |
|---|---|---|---|
| POST | `/auth/login` | все | `{"username", "password"}` → `{"user", "access_token", "token_type", "expires_at"}` + cookie. 401 неверные данные, 429 слишком много попыток (`Retry-After`) |
| POST | `/auth/logout` | вошедший | завершить текущий сеанс, 204 |
| GET | `/auth/me` | вошедший | текущий пользователь |
| POST | `/auth/password` | вошедший | `{"current_password", "new_password"}` → 204; остальные сеансы завершаются. 400 неверный текущий пароль, 422 слабый новый |
| GET | `/users` | admin | список пользователей |
| POST | `/users` | admin | `{"username", "password", "role": "admin"\|"user"}` → 201; 409 логин занят |
| PATCH | `/users/{id}` | admin | `{"role"?, "is_active"?, "password"?}`; 409 — нельзя менять свою роль/статус |
| DELETE | `/users/{id}` | admin | 204; 409 — нельзя удалить себя |
| GET | `/audit` | admin | журнал, новые сверху. Фильтры: `user_id`, `action` (можно несколько), `since`, `until`, `limit`, `offset` |

Пользователь (`UserRead`): `id`, `username`, `role`, `is_active`, `last_login_at`,
`created_at`. Хеш пароля API не возвращает никогда.

```bash
curl -c cookies.txt -X POST localhost:8000/auth/login -H 'content-type: application/json' \
     -d '{"username": "admin", "password": "..."}'
curl -b cookies.txt localhost:8000/cameras
```

## Health

`GET /health` → `{"status", "database", "qdrant", "ai", "cameras"}`.
`status`: `ok`, `degraded` (HTTP 200: нет воркера или, в `recognition`, Qdrant) или
`error` (HTTP 503: нет PostgreSQL).

## Камеры

| Метод | Путь | Описание |
|---|---|---|
| GET | `/cameras` | Список камер |
| POST | `/cameras` | `{"name", "stream_url", "location_id?", "enabled?"}` → 201 |
| GET | `/cameras/{id}` | Камера (`stream_url` не возвращается, только `stream_url_masked`) |
| PATCH | `/cameras/{id}` | `{"name?", "location_id?", "enabled?"}` — меняются только переданные поля; `location_id: null` убирает локацию. `enabled` воркер подхватит после перезапуска |
| DELETE | `/cameras/{id}` | Удалить вместе с треками, сессиями и событиями |
| GET | `/cameras/{id}/snapshot` | Последний кадр с рамками (JPEG) |
| GET | `/cameras/{id}/stream` | Live view, MJPEG (`<img src=...>`) |

## Локации

| Метод | Путь | Описание |
|---|---|---|
| GET | `/locations` | Список (по имени) |
| POST | `/locations` | `{"name", "description?"}` → 201; 409 — имя занято |
| DELETE | `/locations/{id}` | → 204; камеры и прошлые события остаются, без локации |

## Треки

| Метод | Путь | Описание |
|---|---|---|
| GET | `/tracks` | Фильтры: `camera_id`, `active`, `since`, `until`, `limit`, `offset` |
| GET | `/tracks/{id}` | Трек: начало, последнее появление, конец, длительность |

`track_identifier` — номер трека в live view («Track #12»). Он локален для камеры и
начинается заново после перезапуска воркера. Уникален `id`.

## Люди (только `VISION_MODE=recognition` для регистрации)

| Метод | Путь | Описание |
|---|---|---|
| POST | `/persons` | multipart: `name`, `photo`, `external_id?`, `description?` → 201 |
| GET | `/persons` | Список (`embeddings` — сколько векторов лица в Qdrant) |
| GET | `/persons/{id}` | Человек |
| GET | `/persons/{id}/timeline` | История человека, см. ниже |
| DELETE | `/persons/{id}` | Удалить человека и все его векторы → 204 |

Ошибки регистрации:

| Код | Причина |
|---|---|
| 409 | режим `anonymous`; такой `external_id` уже есть |
| 413 | файл больше `FACE_UPLOAD_MAX_BYTES` |
| 422 | не картинка; слишком большое разрешение (> 40 Мп); нет лица; несколько лиц; лицо меньше `FACE_REGISTRATION_MIN_SIZE`; размытое; повёрнуто |
| 503 | Qdrant недоступен (человек не создаётся) или нет файлов моделей |

```bash
curl -b cookies.txt -F name="Alice" -F external_id=emp-1 -F photo=@alice.jpg http://127.0.0.1:8000/persons
```

## События

| Метод | Путь | Описание |
|---|---|---|
| GET | `/events` | Список событий с фильтрами |
| GET | `/events/{id}` | Одно событие |
| GET | `/events/count` | `{"count": N}` с теми же фильтрами, что у списка (например, «событий сегодня») |

Фильтры `GET /events` (все необязательные, комбинируются через И):

| Параметр | Пример | Смысл |
|---|---|---|
| `camera_id` | `1` | камера |
| `location_id` | `2` | локация (копируется из камеры в момент события) |
| `person_id` | `5` | событие с этим человеком |
| `track_id` | `17` | `tracks.id` |
| `event_type` | `event_type=PERSON_ENTERED&event_type=PERSON_LEFT` | один или несколько типов |
| `since` / `until` | `2026-01-01T09:00:00Z` | `since <= timestamp < until` (дата и время) |
| `limit` / `offset` | `50` / `100` | пагинация |

Пример ответа:

```json
{
  "id": 16,
  "event_type": "PERSON_RECOGNIZED",
  "timestamp": "2026-10-08T12:26:47.512Z",
  "camera_id": 1,
  "location_id": null,
  "person_id": 1,
  "track_id": 3,
  "confidence": 0.7941,
  "metadata": {"track_identifier": "3"}
}
```

### Типы событий

| Тип | Когда | Поля |
|---|---|---|
| `TRACK_STARTED`, `PERSON_ENTERED` | трек подтверждён (человек появился в кадре) | `track_id`, `confidence` — уверенность детектора |
| `TRACK_ENDED`, `PERSON_LEFT` | трек пропал дольше `TRACK_MAX_LOST_SECONDS` или воркер остановлен | `metadata.duration_seconds`; `person_id`, если человек был узнан |
| `PERSON_RECOGNIZED` | лицо совпало с зарегистрированным | `person_id`, `confidence` — сходство |
| `PERSON_UNKNOWN` | `UNKNOWN_AFTER_ATTEMPTS` качественных лиц трека ни с кем не совпали | `confidence` — лучшее отвергнутое сходство |
| `CAMERA_ONLINE`, `CAMERA_OFFLINE` | изменился статус камеры | `metadata.status` |
| `PERSON_DETECTED` | зарезервирован, пока не создаётся (вход описывает `PERSON_ENTERED`) | — |

Антидубли (`EVENT_COOLDOWN_SECONDS`): одно и то же событие (камера + тип + трек, а для
`PERSON_RECOGNIZED` — камера + человек) сохраняется не чаще раза в окно. Если трек
человека разорвался и тут же начался новый, повторного `PERSON_RECOGNIZED` не будет.
События камер не прореживаются.

## Timeline

`GET /persons/{id}/timeline?since=&until=&limit=&offset=` — где и когда был человек,
новые сверху:

```json
[
  {"event_id": 18, "event_type": "PERSON_LEFT", "timestamp": "...", "confidence": null,
   "camera": {"id": 1, "name": "entrance"}, "location": {"id": 1, "name": "Hall"}, "track_id": 3},
  {"event_id": 16, "event_type": "PERSON_RECOGNIZED", "...": "..."},
  {"event_id": 15, "event_type": "PERSON_ENTERED", "...": "..."}
]
```

В timeline попадают события с `person_id` этого человека **и** все события треков, на
которых он был узнан. Поэтому визит виден целиком: вход → узнан → выход, хотя в момент
входа человек ещё не был известен. 404 — человека нет; `[]` — его ещё не видели.

## Аналитика

Все метрики считаются SQL-запросами по сохранённым трекам, сессиям и событиям. Видео
повторно не анализируется.

Общие параметры:

| Параметр | По умолчанию | Смысл |
|---|---|---|
| `since`, `until` | последние 24 часа | период, `since <= t < until`, не длиннее 366 дней |
| `camera_id`, `location_id` | все | ограничить камерой или локацией |
| `tz` | `ANALYTICS_TIMEZONE` | IANA-пояс для разбивки по часам (`Asia/Tashkent`) |

| Путь | Ответ |
|---|---|
| `GET /analytics/occupancy?at=` | `{"at", "total", "cameras": [{"camera_id", "name", "count"}]}` — люди в кадре в момент `at` (по умолчанию сейчас) |
| `GET /analytics/people-count` | `{"period", "visits", "recognized_persons", "unknown_visits"}` |
| `GET /analytics/dwell-time` | `{"period", "sessions", "average_seconds", "median_seconds", "min_seconds", "max_seconds"}` — по сессиям, закончившимся в периоде |
| `GET /analytics/people-flow` | `{"period", "timezone", "peak_hours": [14, 9, 17], "buckets": [{"hour", "entered", "left"}]}` |
| `GET /analytics/repeat-visitors?min_visits=2` | `[{"person_id", "name", "visits", "first_seen", "last_seen"}]` |

Пример `people-flow` (пустые часы тоже есть, удобно для графика):

```json
{
  "timezone": "Asia/Tashkent",
  "peak_hours": [17],
  "buckets": [
    {"hour": "2026-10-08T16:00:00+05:00", "entered": 0, "left": 0},
    {"hour": "2026-10-08T17:00:00+05:00", "entered": 4, "left": 4}
  ]
}
```

Оговорки:
- визит = трек. Если человека надолго закрыли и трек разорвался, получится два визита;
- `recognized_persons` и `repeat-visitors` имеют смысл только в режиме `recognition`;
- открытый трек, который давно не обновлялся (упал воркер), в `occupancy` не считается.

## Настройки и дашборд

- `GET /settings` — текущие настройки **без секретов** (режим, пороги, часовой пояс,
  имя файла модели). Адреса БД, Qdrant, камер и ключи не возвращаются.
- `GET /ui/` — дашборд (если собран `frontend/dist`), `GET /` перенаправляет туда.
  Подробно — [dashboard.md](dashboard.md).
