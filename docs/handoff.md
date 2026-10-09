# Передача проекта

Документ для разработчика, который продолжает KörGöz. Порядок чтения:

1. [spec.md](spec.md) — исходное ТЗ.
2. Этот файл — что сделано, как устроено, что дальше.
3. [README.md](../README.md) — как запустить (пошагово, с вебкой или видеофайлом).
4. [architecture.md](architecture.md), [ai.md](ai.md), [deployment.md](deployment.md),
   [security.md](security.md) — детали.

Состояние на момент передачи: **фазы 1–9 из 10 готовы**, всё протестировано и запушено.

---

## 1. Что работает сейчас

| Phase | Результат | Как проверить |
|---|---|---|
| 1 Foundation | Config (Pydantic), логи с маскировкой паролей, 7 моделей БД, Alembic, `/health` | `curl :8000/health` |
| 2 Camera | USB/RTSP/HTTP/файл, поток на камеру, переподключение 1→30 с, статус в БД, CRUD `/cameras` | `python -m scripts.check_camera --source 0` |
| 3 Detection | YOLOX (люди), YuNet (лица, только в recognition), live view MJPEG через API | `:8000/cameras/1/stream` |
| 4 Tracking | Свой ByteTrack + Kalman, треки в БД, `GET /tracks` | `:8000/tracks?active=true` |
| 5 Recognition | Quality check, SFace, Qdrant, `POST/GET/DELETE /persons`, подписи «Имя 0.78» в live view | README, шаг 4а |
| 6 Events | EventEngine (вход/выход/узнан/неизвестный/камера), сессии, `GET /events`, `GET /persons/{id}/timeline`, ontology | `:8000/events` |
| 7 Analytics | occupancy, people count, dwell time, people flow + peak hours (локальный пояс), повторные визиты | `:8000/analytics/people-flow` |
| 8 Dashboard | React + TS + Vite, 8 страниц (обзор, камеры, live view, люди, человек, события, аналитика, настройки), отдаётся API на `/ui/` | http://127.0.0.1:8000/ui/ |
| 9 Security | Вход (серверные сеансы, HttpOnly-cookie или Bearer), argon2id, роли admin/user, журнал аудита, защита от подбора, страницы «Пользователи» и «Журнал аудита» | `python -m scripts.create_user admin --role admin`, затем `/ui/` |

Замеры на Intel Core Ultra 5 125U, только CPU (подробно в [ai.md](ai.md)):
- YOLOX-s — ~76 мс на кадр;
- YOLOX-tiny — 21–40 мс;
- YuNet — 13 мс;
- SFace + поиск в Qdrant — ~9 мс на лицо (и только для новых треков);
- трекер — 0.6 мс на обновление;
- камера 10 FPS обрабатывается полностью при `DETECTION_INTERVAL=3`.

Проверки качества:
- `pytest` — 241 passed (243, если запущен Qdrant);
- `cd frontend && npm test` — 30 passed, `npm run typecheck` — чисто;
- `pytest -m ai` — 6 passed;
- `pytest -m integration` — 9 passed (PostgreSQL + Qdrant);
- ruff, black, `mypy --strict` — чисто.

---

## 2. Как устроено (главное)

### Два процесса

```
korgoz-api (uvicorn app.main:app)          korgoz-worker (python -m app.worker)
  REST API, регистрация лиц                  камеры → детекция → трекинг → распознавание
  проксирует live view  ── HTTP 127.0.0.1:8001 ──→  LiveViewServer (/status, MJPEG)
         │                                          │
         ├──────────── PostgreSQL ←──────────────────┤ (камеры, треки, сессии, события, люди)
         └──────────── Qdrant ←──────────────────────┘ (векторы лиц)
```

- Процессы общаются **только через БД, Qdrant** и внутренний HTTP воркера (`LIVE_VIEW_PORT`).
- Всё, кроме `/health` и `/auth/login`, требует входа. Роли проверяются в одном месте:
  `app/api/auth.py` (`authorize` на роутерах в `app/main.py`). Подробно — [security.md](security.md).
- API загружает модели лиц (YuNet + SFace) лениво, только при первом `POST /persons`.
  Состояние AI воркера он узнаёт через `GET :8001/status`.
- Воркер читает список камер **только при старте** (известное ограничение, см. §5).

### Pipeline воркера

```
CameraWorker (поток) → FrameBuffer (1 последний кадр) → FrameProcessor (поток)
                                                          │ detect каждый N-й кадр, track каждый кадр
                                                          ▼
                                                   FrameAnalysis
                                                          │ sinks (список AnalysisSink)
                                     ┌────────────────────┼─────────────────────┐
                          TrackStore      EventEngine     RecognitionSink      LiveViewHub
                            (треки,       (события,        (лица → люди,      (MJPEG, лениво)
                             сессии)       cooldown)        → EventEngine)
                                 └──────────┬──────┘
                                     DatabaseWriter (один поток, порядок записи сохраняется)
```

**Главная точка расширения — `AnalysisSink`** (`app/pipeline/types.py`). Это функция,
которая получает `FrameAnalysis` после каждого кадра. Event Engine и распознавание
подключаются как новые sinks в `WorkerRuntime.__init__` (`app/worker.py`). Pipeline
менять не нужно. Запись в БД из воркера — только через общий `DatabaseWriter`
(`app/database/writer.py`): так событие никогда не попадёт в БД раньше своего трека.

`FrameAnalysis` содержит:
- `frame` — кадр;
- `persons` — уверенные детекции;
- `faces` — лица, только в recognition;
- `tracks` — активные треки;
- `tracks_started` / `tracks_ended` — что началось или закончилось на этом кадре;
- `fresh` — была ли на этом кадре детекция.

### Абстракции (заменяемые реализации)

| Интерфейс | Реализация | Где создаётся |
|---|---|---|
| `Detector` | `YoloxPersonDetector` | `app/pipeline/factory.py` |
| `FaceDetector` | `YuNetFaceDetector` | `factory.py` (только в recognition) |
| `FaceEmbeddingProvider` | `SFaceProvider` | `factory.build_recognition_service()` |
| `VectorStore` | `QdrantVectorStore` | `factory.build_vector_store()` |
| `Tracker` | `ByteTracker` | `factory.build_tracker()` — один на камеру |
| `FrameSource` | `VideoStream` (OpenCV) | `CameraWorker` |

Конкретные модели упоминаются **только** в `factory.py`.

### Соглашения в коде

- Все настройки — в `app/config.py` (Pydantic Settings, env/.env). Секреты хранятся
  как `SecretStr`. Новую настройку добавляй и в `.env.example`.
- Внешние сбои (БД, камера, модель, sink) логируются и не роняют процесс. Каждый поток
  ловит исключения сам.
- В логах только `type(exc).__name__`, а не текст исключения: в тексте может оказаться
  URL с паролем. URL выводятся через `app.core.logging.redact()`.
- В БД статусы и типы событий хранятся как VARCHAR, а не PG ENUM. Новые значения
  добавляются без миграции.
- Тесты:
  - unit — SQLite in-memory и фейки (`tests/unit/*/fakes.py`), без железа;
  - маркер `ai` — реальные модели;
  - маркер `integration` — реальные PostgreSQL и Qdrant.
- Перед коммитом: `ruff check . && black --check . && mypy app tests scripts && pytest`.
- Язык: код, комментарии и коммиты на английском, документация на русском.

---

## 3. Отклонения от ТЗ и их причины

| ТЗ | Сделано | Почему |
|---|---|---|
| Модель `Session` | `TrackSession` (таблица `sessions`) | Конфликт имени с `sqlalchemy.orm.Session` |
| Поле `Event.metadata` | Атрибут `metadata_`, колонка `metadata` | `metadata` зарезервировано в SQLAlchemy |
| `Event.location_id` обязателен | Nullable | Камера может быть без локации |
| ByteTrack (библиотека) | Своя реализация, жадное сопоставление | Без лишних зависимостей, работает офлайн; при десятках людей разница незначима |
| InsightFace/ArcFace | YuNet + SFace из OpenCV Zoo | Модели InsightFace только для некоммерческого использования. SFace — Apache-2.0 |
| Recognition: YuNet на вырезке трека (план в handoff) | Лица из детекции на всём кадре, привязка к треку по центру лица | Детекция лиц по кадру уже есть; второй прогон YuNet не нужен |
| YOLO (Ultralytics) | YOLOX | Ultralytics под AGPL-3.0 |
| Модель `Device` в БД / ontology | Не создана | В ТЗ нет ни полей, ни сценариев; сейчас каждое устройство — камера |
| `PERSON_DETECTED` | Не создаётся | Дублировал бы `PERSON_ENTERED` на каждом кадре; тип оставлен в enum |
| JWT | Серверные сеансы: случайный токен в HttpOnly-cookie (или `Bearer`), в БД только SHA-256 | ТЗ допускает «безопасную session-based auth». Выход и блокировка действуют сразу, нет ключа подписи ([security.md](security.md)) |
| Cooldown для всех событий | Кроме событий камер | Статус камеры и так меняется только при реальном изменении; пропуск `CAMERA_OFFLINE` исказил бы текущее состояние |

---

## 4. Что дальше — план по фазам

### Phase 5 — Recognition ✅ (готово)

Сделано по плану; детали — [ai.md](ai.md) «Распознавание лиц» и
[architecture.md](architecture.md) «Recognition». Что важно знать для Phase 6:

- `RecognitionSink.identities(camera_id)` отдаёт `track_id → TrackIdentity`
  (`Match(person_id, score)` или `Unknown`). EventEngine может читать его или получать
  результаты через колбэк — добавь параметр `on_result` в `RecognitionSink`.
- Узнанный трек больше не пробуется, `Unknown` — повторяется раз в
  `RECOGNITION_INTERVAL_SECONDS`. Для `PERSON_UNKNOWN` разумно ждать несколько неудачных
  попыток, а не первую.
- Порог 0.40 откалиброван на студийных портретах. Проверь на реальной камере объекта.

### Phase 6 — Events, sessions, timeline, ontology ✅ (готово)

Детали — [api.md](api.md) (типы событий, фильтры, timeline) и
[architecture.md](architecture.md) «Events». Что важно знать для Phase 7:

- `sessions` заполняется при завершении трека (`duration_seconds`), включая треки,
  закрытые после аварии воркера (при следующем старте).
- События пишутся с `timestamp` из видео (время трека/кадра), а не временем записи.
- `PERSON_ENTERED`/`PERSON_LEFT` — по одному на трек. Если трек разрывается (человек
  закрыт другим дольше `TRACK_MAX_LOST_SECONDS`), это два визита. Для `people_count`
  это переоценка; при необходимости склеивать визиты по `person_id` или по времени.
- Cooldown хранится в памяти воркера и сбрасывается при перезапуске.

### Phase 7 — Analytics ✅ (готово)

`app/analytics/service.py` — только SQL по `tracks`, `sessions`, `events`. Описание
эндпоинтов и полей — [api.md](api.md) «Аналитика».

| Метрика | Как считается |
|---|---|
| occupancy | треки, видимые в момент T; открытый трек без обновления `last_seen_at` дольше `2·TRACK_FLUSH_INTERVAL + TRACK_MAX_LOST` не считается (упавший воркер) |
| people_count | треки, начатые в периоде; уникальные узнанные; `PERSON_UNKNOWN` |
| dwell_time | сессии, **закончившиеся** в периоде: среднее, медиана, мин, макс |
| people_flow + peak_hours | `PERSON_ENTERED` / `PERSON_LEFT` по часам в поясе `ANALYTICS_TIMEZONE` (или `?tz=`), пустые часы тоже отдаются |
| repeat_appearance | узнанные на ≥ `min_visits` разных треках |

- Часы считаются в SQL. PostgreSQL: `date_trunc('hour', timezone(tz, ts))`, учитывает
  переход на летнее время. SQLite (только тесты): сдвиг на текущий UTC-offset пояса.
- Медиана: PostgreSQL — `percentile_cont`, SQLite — в Python.
- Integration-тест `tests/integration/test_analytics_postgres.py` проверяет именно
  PostgreSQL-ветку, включая пояс со сдвигом +5:30.

### Phase 8 — Dashboard ✅ (готово)

Подробно — [dashboard.md](dashboard.md). Коротко:
- `frontend/`: React 19 + TypeScript (strict) + Vite, 8 страниц, тесты на vitest.
- API отдаёт сборку на `/ui/`. Один адрес: CORS не нужен (`CORS_ORIGINS` — для чужого домена).
- Новые эндпоинты для дашборда: `/locations`, `PATCH /cameras/{id}`, `/events/count`, `/settings`.
- Сборка (`frontend/dist`) не хранится в git: её делает `npm run build` (на Windows — `setup.bat`).

### Phase 9 — Security ✅ (готово)

Подробно — [security.md](security.md). Коротко:
- Таблицы `users`, `auth_sessions`, `audit_log` (миграция `5b354c3d999e`). Пароли — argon2id
  (`argon2-cffi`, MIT).
- `app/security/` — пароли, сеансы, ограничитель попыток входа, запись аудита.
  `app/api/auth.py` — зависимости `CurrentUser`, `AdminUser`, `authorize`, `AuditDep`.
- Новый роут на существующем роутере защищён автоматически: GET — любой вошедший,
  остальное — admin. Тест `test_auth_api.py` обходит все маршруты OpenAPI.
- Аудит пишется в той же транзакции, что и изменение: `record: AuditDep` в роуте,
  вызов до `db.commit()`. Не пиши в `details` пароли, `stream_url`, имена людей.
- Первый админ и сброс пароля — `scripts/create_user.py`. Камеру без входа (для
  `start.bat`) добавляет `scripts/add_camera.py`.
- Дашборд: страница входа, «Пользователи», «Журнал аудита», смена пароля в «Настройках»;
  для роли user кнопки изменения скрыты.

### Phase 10 — Optimization

- Есть `scripts/benchmark_detector.py`. Нужно добавить замеры сквозной задержки
  (время кадра → время события), CPU и RAM на камеру, и прогон с 2–4 камерами.

---

## 5. Известные ограничения и техдолг

| Проблема | Где | Идея решения |
|---|---|---|
| Новые и удалённые камеры подхватываются только после перезапуска воркера | `app/worker.py` | Каждые N с перечитывать `cameras` и вызывать `manager.add/remove` |
| После `kill -9` воркера статус камеры остаётся `online` | `camera/status_store.py` | Колонка `last_heartbeat_at`; API считает камеру offline, если heartbeat старше X с |
| Сопоставление в трекере жадное, без венгерского алгоритма | `tracking/tracker.py` | При плотной толпе заменить на `scipy.optimize.linear_sum_assignment` |
| Номер трека начинается с 1 после перезапуска воркера | by design | Глобальный id — `tracks.id` |
| Время детекции YOLOX-tiny скачет (21–40 мс) | ноутбучный CPU | Длинный бенчмарк от сети (Phase 10) |
| `StarletteDeprecationWarning` про `httpx2` в тестах | TestClient | Безвреден. Убрать, когда FastAPI обновит TestClient |
| Нет индексов `tracks(started_at)` и `sessions(ended_at)` для аналитики | `database/models.py` | Добавить миграцией, когда данных станет много (замерить `EXPLAIN ANALYZE`) |
| Разрыв трека (перекрытие дольше `TRACK_MAX_LOST_SECONDS`) = два визита в `people_count` | `analytics/service.py` | Склеивать визиты одного `person_id` или с паузой < N с |
| Подписи в live view рисуются `cv2.putText`: кириллица в имени выводится как `???` | `pipeline/annotate.py` | Рисовать текст через Pillow с TTF-шрифтом или показывать имя в дашборде (Phase 8) |
| Распознавание выполняется в потоке камеры (~9 мс на лицо) | `recognition/sink.py` | При многих людях одновременно вынести в отдельный поток с очередью |
| Счётчик неудачных входов хранится в памяти процесса API | `security/login_limiter.py` | Достаточно для одного процесса. При нескольких воркерах uvicorn — хранить в БД |
| Открытый MJPEG-поток не рвётся при выходе или блокировке пользователя | `routes/live_view.py` | Перепроверять сеанс раз в N с внутри `relay()` |
| Чтение (просмотр видео, списка людей) не пишется в аудит | `security/audit.py` | Если нужно по политике — писать `VIEW_*` хотя бы для `/persons` и live view |
| Внутренний сервер кадров воркера без авторизации | `pipeline/live_view.py` | Слушает только `127.0.0.1`. Не открывать наружу |
| Один вектор на человека (одно фото при регистрации) | `POST /persons` | Эндпоинт `POST /persons/{id}/photos` — несколько ракурсов повышают точность |
| Лицензия весов YOLOX (обучены на COCO) | `docs/ai.md` | Подтвердить у юриста перед коммерцией |

## 6. Окружение и подводные камни

- **Windows.** Есть `scripts\windows\*.bat` (подробности в README, раздел «Windows»).
  - Ставят portable PostgreSQL и Qdrant в `.local\`, запускают API и воркер.
  - На реальной Windows **ещё не проверялись**. Первым делом прогони
    `setup.bat` → `start.bat -Camera demo` → `test.bat -All`.
  - Под Windows вебка открывается через `CAP_DSHOW` (`app/camera/stream.py`, `usb_backend()`).
  - Версии PostgreSQL и Qdrant закреплены в `scripts/windows/common.ps1`.

- **Нет роли PostgreSQL** → `role "<user>" does not exist`. Создать её — README, шаг 1.
  Для тестов без sudo можно поднять временный кластер:
  `initdb` + `pg_ctl` из `/usr/lib/postgresql/<ver>/bin`, только TCP.
- **Нестабильная сеть.** GitHub был доступен только через VPN или прокси. Модели
  скачиваются один раз, `download_models.py` проверяет SHA-256. Если сети нет совсем,
  скопируй папку `models/` с другой машины.
- **Вебка** открывается через V4L2 как `/dev/video0` (источник `"0"`). Если пользователь
  не в группе `video`, доступ зависит от ACL сессии. Для systemd-сервиса нужна группа
  `video` (уже прописана в unit-файле).
- **Qdrant по умолчанию шлёт телеметрию.** Запускай с `QDRANT__TELEMETRY_DISABLED=true`
  (прописано в README и deployment.md).
- **FFmpeg печатает URL камер в stderr** в обход маскирующего логгера. Это заглушено в
  `app/camera/__init__.py` (`OPENCV_FFMPEG_LOGLEVEL=-8`). Не убирай эту строку.
- **Тестовые медиа** (`data/samples/vtest.avi`, `lena.jpg`, портреты для распознавания)
  лежат в `.gitignore`.
  Скачиваются командой `python -m scripts.download_models --samples`.
