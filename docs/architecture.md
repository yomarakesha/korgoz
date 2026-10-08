# Архитектура KörGöz

## Поток данных

```
Camera → Video Ingestion → Frame Buffer
       → Person Detection → Multi-Object Tracking
       → Face Detection → Face Quality Check → Face Embedding → Vector Search   (только recognition mode)
       → Event Engine → Vision Ontology → PostgreSQL + Qdrant
       → FastAPI → Dashboard
```

Ключевая идея: тяжёлый CV-конвейер превращает кадры в **события**. Аналитика и UI
работают только с событиями, треками и сессиями в БД и не анализируют видео повторно.

## Слои (Phase 1)

| Модуль | Ответственность |
|---|---|
| `app/config.py` | Единственный источник настроек. Pydantic проверяет типы и диапазоны при старте |
| `app/core/logging.py` | Формат логов и `RedactingFilter`, маскирующий `user:password@` в любом URL |
| `app/core/health.py` | Проверки компонентов; никогда не бросают исключение |
| `app/database/` | ORM-модели, engine (создаётся лениво), Alembic-миграции |
| `app/events/types.py` | `EventType` |
| `app/api/` | HTTP-слой. Роуты получают зависимости через `Depends`, что упрощает тесты |

## Camera module (Phase 2)

```
            ┌────────────── процесс korgoz-worker ──────────────┐
camera 1 ── │ VideoStream → CameraWorker(thread) → FrameBuffer ──┼─→ [Phase 3: pipeline]
camera 2 ── │ VideoStream → CameraWorker(thread) → FrameBuffer ──┼─→
            │          CameraManager          status → PostgreSQL│
            └───────────────────────────────────────────────────┘
                                                      ↑
                                     korgoz-api читает cameras.status
```

- `FrameSource` (Protocol) — минимальный интерфейс источника: `open/read/release`.
  `VideoStream` реализует его на OpenCV. Тесты подставляют фейки. 360°-источник
  (dewarping) в будущем реализует тот же интерфейс.
- `CameraWorker` — поток на камеру: подключение, чтение, ограничение FPS по расписанию,
  переподключение с растущей паузой, статусы. Любое исключение остаётся внутри потока.
- `FrameBuffer` хранит только последний кадр. Pipeline всегда обрабатывает свежий кадр,
  а задержка не накапливается.
- API и воркер — разные процессы. Они общаются через БД (`cameras.status`).
- Нативные логи FFmpeg отключены (`OPENCV_FFMPEG_LOGLEVEL=-8`): FFmpeg печатает URL
  в stderr в обход маскирующего логгера.

Ограничения MVP:
- новые камеры подхватываются только при перезапуске воркера;
- если воркер убит через `kill -9`, статус в БД остаётся `online` (heartbeat — в планах).

## Vision pipeline (Phase 3)

```
CameraWorker → FrameBuffer → FrameProcessor (поток на камеру)
                                 │ каждый N-й кадр: Detector.detect()  (+ FaceDetector в recognition)
                                 ▼
                           FrameAnalysis(frame, persons, faces, fresh)
                                 │ sinks:
                                 ├─→ LiveViewHub → LiveViewServer :8001 ─→ API /cameras/{id}/stream
                                 └─→ [Phase 4: Tracker → Phase 6: Event Engine]
```

- `FrameProcessor` берёт свежий кадр из буфера и запускает детекцию на каждом
  `DETECTION_INTERVAL`-м кадре. Результат отдаётся всем «приёмникам» (sinks).
  Ошибка детектора или приёмника логируется, поток продолжает работать.
- Один экземпляр модели общий для всех камер. Сессия ONNX Runtime потокобезопасна,
  YuNet защищён lock.
- **Live view:** воркер держит HTTP-сервер на `127.0.0.1:8001`, API проксирует его.
  Наружу открыт один порт (API), поэтому аутентификация в Phase 9 закроет и видео.
  Рамки рисуются и кодируются в JPEG лениво, только когда кто-то смотрит.
  Каждый кадр кодируется один раз, сколько бы ни было зрителей.
- Статус AI: воркер отдаёт `/status`, а `/health` в API его опрашивает.

## Tracking (Phase 4)

```
FrameProcessor ── кадр с детекцией ──→ ByteTracker.update(detections)
               └─ кадр без детекции ─→ ByteTracker.predict()      (Kalman двигает рамки)
                                              │
                         TrackingResult(active, started, ended)
                                              ▼
                      FrameAnalysis.tracks ──→ TrackStore (поток + очередь) ──→ таблица tracks
                                           └─→ LiveViewHub ("Track #12")
```

- `ByteTracker` — своя реализация ByteTrack на numpy, без внешних зависимостей.
  Сопоставление жадное по IoU (упрощение вместо венгерского алгоритма).
- Детектор при включённом трекинге отдаёт и неуверенные рамки (от `TRACK_LOW_THRESHOLD`).
  Они только продлевают уже существующие треки, например при частичном перекрытии.
  В `persons` и на экран попадают только рамки выше `PERSON_CONFIDENCE_THRESHOLD`.
- Номер трека выдаётся только после подтверждения (второе совпадение). Одиночные
  ложные срабатывания номер не получают, поэтому номера идут подряд.
- Номер в `tracks.track_identifier` локальный для камеры и после перезапуска воркера
  начинается заново. Уникален `tracks.id`.
- `TrackStore` пишет в БД из отдельного потока. Медленная или упавшая БД не тормозит видео.
  - `last_seen_at` сбрасывается в БД раз в `TRACK_FLUSH_INTERVAL_SECONDS`.
  - При остановке воркера все треки закрываются.
  - Треки, оставшиеся открытыми после аварии, закрываются при следующем старте
    (`ended_at = last_seen_at`).
- Трек — это непрерывное присутствие в кадре одной камеры. Межкамерная связка
  (один человек на разных камерах) появится через recognition (Phase 5) и ontology (Phase 6).

## Recognition (Phase 5)

```
FrameAnalysis (tracks + faces, fresh) ──→ RecognitionSink ── assign_faces: лицо → трек
                                               │
                         FaceRecognitionService.identify(image, face)
                           quality → SFace → VectorStore.search → порог
                                               │
                    track_id → Match(person_id, score) / Unknown
                                               └─→ LiveViewHub (подпись «Имя 0.78»)

API: POST /persons → registration_embedding(photo) → Qdrant (вектор) + PG (Person, FaceEmbedding)
```

- Воркер и API не общаются напрямую: общий источник правды — Qdrant (векторы) и
  PostgreSQL (имена). Новые люди видны воркеру сразу.
- В Qdrant хранятся только вектор и payload `person_id`, `model_name`. Имена, фото
  и кадры туда не попадают. Фото регистрации не пишется на диск.
- Имена для подписей воркер читает из БД (`PersonNames`, кэш в памяти).
- Ошибки Qdrant оборачиваются в `VectorStoreError` (в тексте только тип исключения).
  В воркере сбой Qdrant не ломает видео: трек просто останется без подписи и будет
  повторён позже.

## Events (Phase 6)

```
FrameAnalysis ─→ TrackStore ── tracks, sessions ──┐
             ─→ EventEngine ── EventRecord ───────┤  DatabaseWriter (1 поток, очередь)
RecognitionSink.on_result ─→ EventEngine          ├─→ PostgreSQL
CameraManager.on_status ─→ DatabaseStatusRecorder │
                        └→ EventEngine.on_camera_status
```

- `EventEngine` (`app/events/engine.py`) решает, *что* произошло, и применяет cooldown.
  Хранением занимается `EventStore` (`app/events/store.py`). В тестах вместо него — список.
- `EventStore` в потоке записи превращает номер трека из live view в `tracks.id` (самая
  новая строка с этим номером на камере) и копирует `location_id` камеры.
- Порядок sinks важен: `TrackStore` → `EventEngine` → `RecognitionSink`. Строка трека
  ставится в очередь раньше его событий, `TRACK_STARTED` — раньше `PERSON_RECOGNIZED`.
- `TimelineService` (`app/events/timeline.py`) строит историю человека через
  `Ontology` (`app/ontology/relations.py`).

## Модель данных (Vision Ontology, хранимая часть)

```
Location 1──* Camera 1──* Track 1──* TrackSession
                 │           │
                 └──* Event *┘
Person 1──* FaceEmbedding        (вектор лежит в Qdrant, в PG только vector_id)
Person 1──* Event
```

Связи онтологии:

- Person → generated → Event (`events.person_id`)
- Event → detected_by → Camera (`events.camera_id`)
- Event → occurred_at → Location (`events.location_id`)
- Track → belongs_to → Camera (`tracks.camera_id`)
- Person → associated_with → Track (через события `PERSON_RECOGNIZED` с `track_id`)
- Session → contains → Events (события того же `track_id` в интервале сессии)

Слой `app/ontology/`: `objects.py` — неизменяемые снимки сущностей (без открытой сессии БД),
`relations.py` — связи из списка выше как SQL-запросы (`Ontology.events_of_person`,
`tracks_of_person`, `events_in_session`, …).

## Проектные решения

- **`event_type` и статусы — VARCHAR, а не PostgreSQL ENUM.** Новый тип события
  добавляется в Python enum без миграции схемы.
- **`Event.metadata` → атрибут `metadata_`.** Имя `metadata` зарезервировано в SQLAlchemy.
  В БД колонка называется `metadata` (JSONB).
- **`Session` → `TrackSession`.** Чтобы не путать с `sqlalchemy.orm.Session`. Таблица — `sessions`.
- **Удаление (privacy):**
  - `Person` удалён → `face_embeddings` удаляются каскадно, `events.person_id` → NULL
    (анонимная статистика сохраняется).
  - `Camera` удалена → её треки, сессии и события удаляются.
  - Векторы в Qdrant удаляет `DELETE /persons/{id}` — **до** удаления из БД. Если
    Qdrant недоступен, ответ 503, человек остаётся, удаление можно повторить.
- **`Event.location_id` nullable.** Камера может быть ещё не привязана к локации.
- **`Track.track_identifier` не уникален.** Трекеры (ByteTrack) нумеруют заново после
  перезапуска. Уникален только `tracks.id`.
- **Синхронный SQLAlchemy.** FastAPI выполняет sync-эндпоинты в threadpool. Это проще
  отлаживать, чем async-драйвер, а CV-воркеры всё равно работают в отдельных потоках/процессах.
- **Секреты.** `DATABASE_URL`, `CAMERA_URL`, `QDRANT_API_KEY` хранятся как `SecretStr`.
  У `Camera.__repr__` нет `stream_url`.

## Расширяемость

- **Мульти-камера.** Каждая камера получит свой `CameraWorker` (Phase 2). Ошибка одной
  камеры изолирована.
- **AI-провайдеры.** Детектор, трекер и face recognition будут скрыты за абстрактными
  интерфейсами (Phase 3–5).
- **360° камеры.** Задел: шаг dewarping → virtual regions встраивается между Frame Buffer
  и Detection, не меняя остальной конвейер.
