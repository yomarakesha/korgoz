# Передача проекта

Документ для разработчика, который продолжает KörGöz. Порядок чтения:

1. [spec.md](spec.md) — исходное ТЗ.
2. Этот файл — что сделано, как устроено, что дальше.
3. [README.md](../README.md) — как запустить (пошагово, с вебкой или видеофайлом).
4. [architecture.md](architecture.md), [ai.md](ai.md), [deployment.md](deployment.md) — детали.

Состояние на момент передачи: **фазы 1–4 из 10 готовы**, всё протестировано и запушено.

---

## 1. Что работает сейчас

| Phase | Результат | Как проверить |
|---|---|---|
| 1 Foundation | Config (Pydantic), логи с маскировкой паролей, 7 моделей БД, Alembic, `/health` | `curl :8000/health` |
| 2 Camera | USB/RTSP/HTTP/файл, поток на камеру, переподключение 1→30 с, статус в БД, CRUD `/cameras` | `python -m scripts.check_camera --source 0` |
| 3 Detection | YOLOX (люди), YuNet (лица, только в recognition), live view MJPEG через API | `:8000/cameras/1/stream` |
| 4 Tracking | Свой ByteTrack + Kalman, треки в БД, `GET /tracks` | `:8000/tracks?active=true` |

Замеры на Intel Core Ultra 5 125U, только CPU (подробно в [ai.md](ai.md)):
- YOLOX-s — ~76 мс на кадр;
- YOLOX-tiny — 21–40 мс;
- YuNet — 13 мс;
- трекер — 0.6 мс на обновление;
- камера 10 FPS обрабатывается полностью при `DETECTION_INTERVAL=3`.

Проверки качества:
- `pytest` — 109 passed;
- `pytest -m ai` — 3 passed;
- `pytest -m integration` — 2 passed;
- ruff, black, `mypy --strict` — чисто.

---

## 2. Как устроено (главное)

### Два процесса

```
korgoz-api (uvicorn app.main:app)          korgoz-worker (python -m app.worker)
  REST API, читает БД                        камеры → детекция → трекинг
  проксирует live view  ── HTTP 127.0.0.1:8001 ──→  LiveViewServer (/status, MJPEG)
         │                                          │
         └──────────── PostgreSQL ←──────────────────┘ (статусы камер, треки)
```

- Процессы общаются **только через БД** и внутренний HTTP воркера (`LIVE_VIEW_PORT`).
- API ничего не знает о моделях. Состояние AI он узнаёт через `GET :8001/status`.
- Воркер читает список камер **только при старте** (известное ограничение, см. §5).

### Pipeline воркера

```
CameraWorker (поток) → FrameBuffer (1 последний кадр) → FrameProcessor (поток)
                                                          │ detect каждый N-й кадр, track каждый кадр
                                                          ▼
                                                   FrameAnalysis
                                                          │ sinks (список AnalysisSink)
                                     ┌────────────────────┼─────────────────────┐
                                TrackStore          LiveViewHub         [сюда: EventEngine,
                              (БД, свой поток)    (MJPEG, лениво)        RecognitionService]
```

**Главная точка расширения — `AnalysisSink`** (`app/pipeline/types.py`). Это функция,
которая получает `FrameAnalysis` после каждого кадра. Event Engine и распознавание
подключаются как новые sinks в `WorkerRuntime.__init__` (`app/worker.py`). Pipeline
менять не нужно.

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
  - маркер `integration` — реальный PostgreSQL.
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
| InsightFace/ArcFace | YuNet + (план) SFace из OpenCV Zoo | Модели InsightFace только для некоммерческого использования. SFace — Apache-2.0 |
| YOLO (Ultralytics) | YOLOX | Ultralytics под AGPL-3.0 |
| Модель `Device` в БД | Не создана | Нет в списке моделей §9 ТЗ; добавить вместе с ontology в Phase 6 |

---

## 4. Что дальше — план по фазам

### Phase 5 — Recognition (следующая)

Готово к старту: Qdrant v1.19.2 протестирован (установка — README, шаг 2), YuNet
подключён, режим `VISION_MODE=recognition` загружает детектор лиц.

1. **Модель эмбеддингов SFace** (OpenCV Zoo, Apache-2.0):
   - файл `face_recognition_sface_2021dec.onnx`, ~37 МБ;
   - URL: `https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx`.
   - Добавь его в `scripts/download_models.py` с SHA-256. Сумму сначала посчитай
     на скачанном файле: у автора не хватило скорости сети.
   - В OpenCV есть готовый класс `cv2.FaceRecognizerSF.create(path, "")`. Метод
     `alignCrop(image, face_row)` выравнивает лицо по 5 точкам YuNet, `feature()` даёт
     вектор 128-d. Размерность бери из выхода модели, не хардкодь.
   - Для cosine similarity OpenCV рекомендует порог **0.363**. Текущий дефолт
     `FACE_MATCH_THRESHOLD=0.45` строже. Откалибруй на реальных фото и обнови дефолт.
2. **`app/vector_store/`:**
   - `base.py` — `VectorStore` ABC с методами `create_collection`, `add_embedding`,
     `search`, `delete_embedding`, `health_check`;
   - `qdrant_store.py` — реализация на `qdrant-client`. Добавь его в `requirements.txt`.
     Метрика cosine. В payload храни только `person_id` и `model_name`.
   - Перенеси `check_qdrant` из `app/core/health.py` на `VectorStore.health_check()`.
3. **`app/recognition/`:**
   - `quality.py` — `FaceQualityChecker`: размер лица в пикселях, резкость (дисперсия
     Лапласиана), поворот головы по 5 точкам. Все пороги — в конфиг.
   - `embedding.py` — `FaceEmbeddingProvider` ABC плюс `SFaceProvider`.
   - `service.py` — `FaceRecognitionService.identify(image, face)` возвращает
     `Match(person_id, score)` или `Unknown`. Без forced matching: если ниже порога,
     то `UNKNOWN`.
4. **Регистрация `POST /persons`** (multipart: name, external_id, photo).
   - Ошибки 422: нет лица; несколько лиц; лицо меньше `FACE_MIN_SIZE`; низкое качество.
   - Порядок записи: сначала вектор в Qdrant, затем строки `Person` и `FaceEmbedding`
     (`vector_id` = UUID точки). Если БД упала, удали точку из Qdrant.
   - Фото **не сохранять** на диск.
   - Также нужны `GET /persons`, `GET /persons/{id}`, `DELETE /persons/{id}` (удаляет
     и векторы в Qdrant).
5. **Распознавание в воркере** — новый sink `RecognitionSink`:
   - распознавай **по трекам, а не по кадрам**: для нового трека пробуй, пока не
     узнал, но не чаще раза в N секунд на трек;
   - лицо ищи внутри рамки трека (YuNet на вырезке);
   - результат держи в словаре `track_id → (person_id | UNKNOWN, score)`;
   - в live view подпись «Имя 0.87» вместо `Track #N` (`app/pipeline/annotate.py`).
   - Проблема: API регистрирует новых людей, а воркер про них не знает. Решение
     простое — воркер на каждый запрос ходит в Qdrant, он и есть общий источник правды.
6. Тесты:
   - порог (ниже порога → UNKNOWN);
   - каждая ошибка регистрации;
   - Qdrant как integration-тест с маркером `integration`;
   - SFace как AI-тест на `data/samples/lena.jpg`: один и тот же человек → высокий score.

### Phase 6 — Events, sessions, timeline, ontology

- `app/events/engine.py` — `EventEngine` как `AnalysisSink` плюс `StatusListener`
  для камер. Источники событий:
  - `tracks_started` → `TRACK_STARTED` и `PERSON_ENTERED`;
  - `tracks_ended` → `TRACK_ENDED`, `PERSON_LEFT` и строка `TrackSession`
    (`duration_seconds`);
  - результаты RecognitionSink → `PERSON_RECOGNIZED` / `PERSON_UNKNOWN`;
  - статус камеры → `CAMERA_ONLINE` / `CAMERA_OFFLINE`. Подключить к
    `CameraManager(on_status=...)` рядом с `DatabaseStatusRecorder`.
- **Cooldown:** ключ `(camera_id, event_type, person_id or track_id)`, окно
  `EVENT_COOLDOWN_SECONDS`.
- Писать в БД через очередь и фоновый поток, по образцу `app/tracking/store.py`.
- `app/ontology/objects.py`, `relations.py` — доменные объекты и связи из §8 ТЗ поверх ORM.
- `TimelineService` и эндпоинты `GET /events` (фильтры из §25 ТЗ, newest first),
  `GET /events/{id}`, `GET /persons/{id}/timeline`.
- Написать `docs/api.md`.

### Phase 7 — Analytics

`app/analytics/service.py`. Только SQL по `events`, `tracks`, `sessions`, видео не трогаем.

| Метрика | Как считать |
|---|---|
| occupancy | активные треки сейчас или на момент времени |
| people_count | число треков за период |
| dwell_time | среднее и медиана `sessions.duration_seconds` |
| people_flow | `PERSON_ENTERED` / `PERSON_LEFT` по часам |
| peak_hours | `date_trunc('hour')` |
| repeat_appearance | `PERSON_RECOGNIZED`, сгруппированные по `person_id` |

Эндпоинты: `/analytics/occupancy`, `/analytics/people-flow`, `/analytics/dwell-time`.

Индексы под эти запросы уже есть: `events(camera_id, timestamp)`,
`events(person_id, timestamp)`, `sessions(started_at)`.

### Phase 8 — Dashboard

- `frontend/`: Vite + React + TypeScript, 8 страниц из §21 ТЗ.
- Live View — просто `<img src="/cameras/{id}/stream">`.
- В API понадобится CORS (`fastapi.middleware.cors`). Origin задавай настройкой.

### Phase 9 — Security

- Таблицы `users` и `audit_log` (Alembic-миграция). Пароли хешировать argon2 или bcrypt.
- JWT и роли admin/user через зависимости FastAPI.
- **Важно:** `<img>` не умеет отправлять заголовок `Authorization`. Для
  `/cameras/{id}/stream` нужна cookie-сессия или короткоживущий токен в query.
- Написать `docs/security.md`.

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
| Нет `docs/api.md`, `docs/security.md` | — | Phase 6 и 9 |
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
- **Тестовые медиа** (`data/samples/vtest.avi`, `lena.jpg`) лежат в `.gitignore`.
  Скачиваются командой `python -m scripts.download_models --samples`.
