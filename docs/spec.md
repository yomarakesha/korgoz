# Исходное ТЗ KörGöz

Техническое задание, по которому строится проект. Ниже исходный текст, без изменений
по смыслу. Отклонения от него и их причины описаны в [handoff.md](handoff.md).

---

## 1. О проекте

KörGöz — локальная интеллектуальная платформа видеоаналитики.

Главная идея: KörGöz преобразует видеопотоки с камер в структурированные объекты, события,
связи, временные линии и аналитические данные.

Система должна не просто распознавать лица. Она должна понимать:
- кто/какой объект находится в кадре;
- где он находится;
- какая камера его обнаружила;
- когда он появился;
- сколько времени находился в зоне;
- как перемещался;
- какие события с ним связаны.

Распознавание лица является только одним из модулей системы.

## 2. Критические ограничения

**Docker запрещён.** Никогда не использовать Docker, Docker Compose, контейнеры,
Container Registry, Kubernetes. Не создавать Dockerfile, docker-compose.yml,
container configuration.

Все компоненты запускаются непосредственно на ОС: Python virtual environment, systemd
на Linux, обычные системные процессы, локально установленные PostgreSQL и Qdrant,
FastAPI, обычный frontend development server.

## 3. Основной принцип

Local-first, On-Premise, Modular, Privacy-by-Design, scalable, testable, maintainable.

Интернет не должен быть необходим для основной работы системы после установки
компонентов и моделей. Видеопотоки не должны отправляться во внешние облачные AI API.

## 4. Режимы работы

**MODE 1 — Anonymous Vision.** Система НЕ определяет личность. Работает с person_id,
track_id, camera_id, location_id, timestamp (например: Person #27, Track #104, Camera #3,
09:42:15). Используется для people counting, tracking, occupancy, dwell time, movement,
people flow, analytics.

**MODE 2 — Authorized Recognition.** Система может идентифицировать только заранее
зарегистрированных лиц.

Pipeline: Camera → Person Detection → Face Detection → Face Quality Check →
Face Embedding → Vector Search → Similarity Score → Registered Person / Unknown.

Если лицо не найдено в базе с достаточной уверенностью — UNKNOWN. Избегать forced
matching: нельзя назначать неизвестному лицу ближайшего человека из базы, если
similarity ниже настроенного threshold.

## 5. Архитектура

Camera → Video Ingestion → Frame Buffer → Person Detection → Multi Object Tracking →
Face Detection → Face Quality Check → Face Embedding → Vector Search → Event Engine →
Vision Ontology → PostgreSQL + Qdrant → FastAPI → Dashboard

## 6. Tech stack

- Backend: Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL
- Computer Vision: OpenCV, FFmpeg, ONNX Runtime, face recognition модель, person detector,
  ByteTrack или аналогичный tracker
- Vector DB: Qdrant
- Frontend: React, TypeScript, Vite
- Testing: pytest, pytest-asyncio
- Code quality: Ruff, Black, mypy
- Configuration: environment variables, .env для локальной разработки
- Deployment: Python venv, systemd

## 7. AI-модели

Можно использовать InsightFace/ArcFace или другую локальную модель, но: проверить
совместимость, проверить лицензию, не предполагать, что pretrained модель разрешена
для коммерческого использования. AI provider абстрактный: `FaceRecognitionProvider`
(InsightFaceProvider, ArcFaceProvider, CustomProvider) заменяется без переписывания системы.

## 8. Vision Ontology

Отдельный слой ontology. Сущности: Person, Camera, Location, Event, Session, Track, Device.

Связи: Person → generated → Event; Event → detected_by → Camera;
Event → occurred_at → Location; Track → belongs_to → Camera;
Person → associated_with → Track; Session → contains → Events.

## 9. Database model (SQLAlchemy)

- **Person:** id, external_id, name, description, status, created_at, updated_at
- **FaceEmbedding:** id, person_id, vector_id, model_name, created_at
  (embedding не хранить в PostgreSQL, если он в Qdrant)
- **Camera:** id, name, location_id, stream_url, enabled, status, created_at, updated_at
  (не логировать stream_url с credentials)
- **Location:** id, name, description
- **Track:** id, camera_id, track_identifier, started_at, ended_at, last_seen_at
- **Event:** id, event_type, person_id nullable, track_id nullable, camera_id, location_id,
  timestamp, confidence nullable, metadata JSON, created_at
- **Session:** id, track_id, camera_id, started_at, ended_at, duration_seconds

## 10. Event types

PERSON_DETECTED, PERSON_ENTERED, PERSON_LEFT, PERSON_RECOGNIZED, PERSON_UNKNOWN,
TRACK_STARTED, TRACK_ENDED, CAMERA_ONLINE, CAMERA_OFFLINE. Архитектура должна позволять
добавлять новые типы.

## 11. Camera module

`app/camera/`: CameraManager, CameraWorker, VideoStream, FrameBuffer. Поддержка USB, RTSP,
IP camera. CameraWorker: подключается, получает кадры, контролирует FPS, frame skipping,
восстанавливает соединение, фиксирует camera offline, не блокирует остальные камеры.

## 12. Person detection

Абстракция `Detector` (`PersonDetector`), API `detect(frame)` →
`DetectionResult(bbox, confidence, class_id)`. Не привязывать проект к одной модели.

## 13. Tracking

`Tracker` (ByteTrack или аналог). Каждый объект имеет track_id, стабильный между кадрами.
Не выполнять распознавание лица на каждом кадре.

## 14. Face recognition

FaceDetector, FaceQualityChecker, FaceEmbeddingProvider, FaceRecognitionService.
Pipeline: Face Detection → Quality Check → Embedding → Vector Search → Threshold →
Match / Unknown. Параметры конфигурируемые (`FACE_MATCH_THRESHOLD`), не зашивать в код.

## 15. Qdrant

`app/vector_store/`: интерфейс VectorStore с методами create_collection(), add_embedding(),
search(), delete_embedding(), health_check(). Cosine similarity, если подходит модели.
Размерность вектора не хардкодить — брать из конфигурации модели.

## 16. Event engine

`app/events/`: EventEngine получает результаты CV pipeline и создаёт события
(Face recognized → PERSON_RECOGNIZED; Track disappeared → TRACK_ENDED; Camera disconnected →
CAMERA_OFFLINE). Не создавать тысячи одинаковых событий: deduplication / cooldown
(configurable).

## 17. Timeline

TimelineService: история Person → Events → Camera → Location → Timestamp.

## 18. Analytics

`app/analytics/`: people_count, occupancy, dwell_time, people_flow, peak_hours,
repeat_appearance. Работают на Event/Track/Session данных, видео повторно не анализировать.

## 19. FastAPI endpoints (минимум)

GET /health; GET, POST /cameras; GET, DELETE /cameras/{id}; GET, POST /persons;
GET, DELETE /persons/{id}; GET /events; GET /events/{id}; GET /persons/{id}/timeline;
GET /analytics/occupancy; GET /analytics/people-flow; GET /analytics/dwell-time; GET /tracks.

## 20. Person registration

Указать имя, external_id, загрузить фото, проверить наличие лица и качество, создать
embedding, сохранить в Qdrant, metadata в PostgreSQL. Ошибки: нет лица; несколько лиц;
лицо слишком маленькое; качество недостаточное.

## 21–26. Dashboard (React + TypeScript + Vite)

Страницы: Dashboard, Cameras, Live View, Persons, Person Details, Events, Analytics, Settings.

- **Главная:** количество камер, online/offline, people currently detected, events today,
  occupancy, recent events.
- **Live View:** для каждой камеры Name, Location, Status, Live Stream с bounding boxes
  (Anonymous: Track #42; Recognition: Person Name + Confidence).
- **Person:** Name, External ID, Registration date, Timeline (Time, Camera, Location,
  Event, Confidence).
- **Events:** фильтры Date, Time, Camera, Location, Person, Event type; newest first.
- **Analytics:** People count, Occupancy, Peak hours, Average dwell time, People flow,
  с графиками.

## 27. Security

Authentication, password hashing, JWT или безопасная session-based auth, RBAC
(admin/user), audit log. Никогда: пароли в plaintext, логирование credentials, RTSP
password в API response, секреты в коде.

## 28. Privacy

Не сохранять видеопоток постоянно по умолчанию; хранить структурированные события.
Возможность: Anonymous Mode, Recognition Mode, удаление человека, его embeddings и
связанных событий по политике хранения.

## 29. Configuration

`app/config.py` на Pydantic Settings: DATABASE_URL, QDRANT_URL, QDRANT_COLLECTION,
CAMERA_ID, CAMERA_URL, DETECTION_INTERVAL, FACE_MATCH_THRESHOLD, EVENT_COOLDOWN_SECONDS,
LOG_LEVEL. Никаких секретов в коде; `.env.example` в git, `.env` — нет.

## 30. Logging

Уровни DEBUG/INFO/WARNING/ERROR/CRITICAL; timestamp, module, level, message. Не логировать
пароли, API keys, RTSP credentials, raw face embeddings.

## 31–32. Error handling и health checks

Корректная обработка ошибок Camera, PostgreSQL, Qdrant, AI model, FastAPI, Filesystem.
Отключение одной камеры не роняет систему. `GET /health` с проверками database, qdrant,
AI model, camera workers.

## 33. Testing

Минимум: configuration, database, Qdrant, API, event engine, recognition threshold,
timeline, analytics tests. Разделить unit / integration / AI integration tests.

## 35. Development phases

1. Foundation  2. Camera  3. Detection  4. Tracking  5. Recognition  6. Events
7. Analytics  8. Dashboard  9. Security  10. Optimization (FPS, latency, CPU/RAM/GPU
profiling, DB optimization)

## 36–38. Производительность, 360°, мульти-камера

- MVP с одной камерой near real-time; recognition не на каждом кадре, а для новых или
  изменившихся треков; configurable detection interval.
- Измерять FPS, latency, CPU, RAM, GPU, recognition latency. Не утверждать FPS без benchmark.
- 360° не реализовывать, но архитектура готова: Fisheye → Dewarping → Virtual regions →
  Detection → Tracking → Recognition.
- Камеры добавляются без изменения AI pipeline, работают независимо.

## 39–41. Deployment, документация, git

systemd: korgoz-api.service, korgoz-worker.service; docs/deployment.md. README и
docs/architecture.md, api.md, deployment.md, ai.md, security.md. `.gitignore`: .env, .venv,
__pycache__, *.pyc, logs, models, data, node_modules, dist. Не коммитить credentials,
дампы БД, фото лиц, embeddings, приватные URL камер.

## 42–46. Правила работы

Небольшие модули с одной ответственностью, type hints, без дублирования, без хардкода
конфигурации и credentials, AI за абстракциями, тесты на критические сервисы.
Работать поэтапно; после этапа отчёт: STATUS, FILES CREATED/MODIFIED, TESTS, HOW TO RUN,
NEXT PHASE. При ошибке: прочитать traceback, найти причину, минимально исправить,
перезапустить тест. При нехватке информации — явно назвать допущение.

## 47. Критерии готовности MVP

Backend без Docker; PostgreSQL; Qdrant; FastAPI; Camera Manager подключает камеру;
обнаружение людей; трекинг; регистрация человека; embedding в Qdrant; vector search;
REGISTERED / UNKNOWN; events; timeline; Anonymous Mode; Recognition Mode; базовая
аналитика; Dashboard; authentication; tests; README; deployment documentation;
нет Docker-зависимостей.
