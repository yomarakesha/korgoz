# KörGöz — Intelligent Vision & Situational Analytics Platform

KörGöz — локальная (on-premise) платформа видеоаналитики. Она превращает видеопотоки
с камер в структурированные данные: **объекты → события → связи → аналитика**.

Распознавание лиц — лишь один из модулей. Основа системы — понимание того, *кто/что*
находится в кадре, *где*, *какой камерой* обнаружен, *когда* появился, *сколько* пробыл
в зоне и *как* перемещался.

- Local-first: после установки интернет не нужен, видео не уходит во внешние API.
- Без Docker: всё запускается в Python venv и через systemd.
- Privacy-by-design: видео по умолчанию не сохраняется, хранятся только события.

## Режимы работы

| Режим | `VISION_MODE` | Что делает |
|---|---|---|
| Anonymous Vision | `anonymous` | Без идентификации: track_id, подсчёт людей, occupancy, dwell time, потоки |
| Authorized Recognition | `recognition` | Узнаёт только заранее зарегистрированных людей; ниже `FACE_MATCH_THRESHOLD` → `UNKNOWN` |

## Статус разработки

| Phase | Содержание | Статус |
|---|---|---|
| 1 | Foundation: config, logging, DB, migrations, FastAPI, health | ✅ готово |
| 2 | Camera: OpenCV, RTSP, worker, reconnect | ✅ готово |
| 3 | Person / Face detection, live view | ✅ готово |
| 4 | Multi-object tracking | — |
| 5 | Recognition: embeddings, Qdrant, registration | — |
| 6 | Event Engine, sessions, timeline | — |
| 7 | Analytics | — |
| 8 | Dashboard (React + TS + Vite) | — |
| 9 | Security: auth, RBAC, audit | — |
| 10 | Optimization & benchmarks | — |

## Архитектура

```
Camera → Video Ingestion → Frame Buffer → Person Detection → Tracking
       → Face Detection → Quality Check → Embedding → Vector Search
       → Event Engine → Vision Ontology → PostgreSQL + Qdrant → FastAPI → Dashboard
```

Подробно: [docs/architecture.md](docs/architecture.md).

## Структура проекта

```
app/
├── main.py              FastAPI app factory + lifespan
├── config.py            Pydantic Settings (все настройки из env/.env)
├── api/                 HTTP-слой: routes/, dependencies.py
├── worker.py            процесс camera worker (python -m app.worker)
├── camera/              stream.py, buffer.py, worker.py, manager.py, status_store.py
├── detection/           Detector (abstraction), YOLOX person detector
├── recognition/         FaceDetector (abstraction), YuNet face detector
├── pipeline/            FrameProcessor, factory, annotate, live view (MJPEG)
├── core/                logging.py (с маскировкой credentials), health.py
├── database/            base.py, models.py, session.py, migrations/ (Alembic)
└── events/types.py      EventType enum
tests/
├── unit/                быстрые тесты, SQLite in-memory, без внешних сервисов
└── integration/         реальный PostgreSQL (пропускаются, если недоступен)
scripts/check_camera.py  проверка видеоисточника без БД
scripts/download_models.py   загрузка моделей с проверкой SHA-256
scripts/benchmark_detector.py  замер скорости детекции на этой машине
scripts/systemd/         unit-файлы systemd (korgoz-api, korgoz-worker)
docs/                    архитектура, развёртывание
```

## Быстрый старт (разработка)

Требования: Python 3.12, PostgreSQL 14+, (опционально в Phase 1) Qdrant.

```bash
# 1. Виртуальное окружение
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 2. База данных (один раз, нужен sudo)
sudo -u postgres psql -c "CREATE ROLE korgoz LOGIN PASSWORD 'придумай_пароль';"
sudo -u postgres psql -c "CREATE DATABASE korgoz OWNER korgoz;"

# 3. Конфигурация
cp .env.example .env
# отредактируй DATABASE_URL в .env

# 4. Миграции и модели
alembic upgrade head
python -m scripts.download_models --samples

# 5. Запуск API
uvicorn app.main:app --reload

# 6. Запуск camera worker (во втором терминале)
python -m app.worker
```

Проверка: http://127.0.0.1:8000/health и Swagger UI на http://127.0.0.1:8000/docs.

## Конфигурация

Все параметры задаются переменными окружения (см. [.env.example](.env.example)).
Основные:

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | — (обязательна) | `postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB` |
| `QDRANT_URL` | `http://localhost:6333` | адрес Qdrant |
| `QDRANT_COLLECTION` | `korgoz_faces` | коллекция для face embeddings |
| `VISION_MODE` | `anonymous` | `anonymous` / `recognition` |
| `CAMERA_ID`, `CAMERA_URL` | `1`, — | доп. камера из env (без записи в БД); `0` = вебка |
| `CAMERA_MAX_FPS` | `15` | верхний предел FPS на камеру (лишние кадры отбрасываются) |
| `CAMERA_LOOP_VIDEO` | `true` | зацикливать видеофайлы |
| `CAMERA_RECONNECT_*_DELAY_SECONDS` | `1` / `30` | пауза переподключения: растёт от 1 до 30 с |
| `CAMERA_READ_FAILURE_THRESHOLD` | `10` | неудачных чтений подряд до переподключения |
| `DETECTION_INTERVAL` | `3` | детекция на каждом N-м кадре |
| `PERSON_DETECTOR_MODEL_PATH` | `models/yolox_s.onnx` | `yolox_tiny.onnx` — быстрее |
| `PERSON_CONFIDENCE_THRESHOLD` | `0.5` | минимальная уверенность для «человека» |
| `ONNX_NUM_THREADS` | `0` | потоки ONNX Runtime (0 = авто) |
| `FACE_DETECTION_THRESHOLD` | `0.8` | порог YuNet (только в recognition) |
| `LIVE_VIEW_HOST` / `LIVE_VIEW_PORT` | `127.0.0.1` / `8001` | внутренний сервер кадров воркера |
| `FACE_MATCH_THRESHOLD` | `0.45` | порог cosine similarity; ниже → UNKNOWN |
| `EVENT_COOLDOWN_SECONDS` | `30` | антидублирование событий |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR / CRITICAL |

Значение `FACE_MATCH_THRESHOLD` — стартовое. Его нужно откалибровать под выбранную
модель на этапе Phase 5.

## API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/health` | Состояние компонентов |
| GET | `/cameras` | Список камер |
| POST | `/cameras` | Добавить камеру `{"name", "stream_url", "location_id?", "enabled?"}` |
| GET | `/cameras/{id}` | Камера |
| DELETE | `/cameras/{id}` | Удалить камеру (вместе с её треками и событиями) |
| GET | `/cameras/{id}/snapshot` | Последний кадр с рамками (JPEG) |
| GET | `/cameras/{id}/stream` | Live view: MJPEG с рамками, вставляется как `<img src=...>` |

`stream_url` никогда не возвращается: API отдаёт `stream_url_masked`
(`rtsp://***:***@host/...`) и `source_kind` (`usb` / `network` / `file`).
Swagger UI с примерами: `/docs`.

Пример ответа `/health`:

```json
{"status": "degraded", "database": "ok", "qdrant": "unavailable", "ai": "not_configured", "cameras": 0}
```

- `ok` — всё работает;
- `degraded` (HTTP 200) — API работает, но не запущен воркер/модели (`ai`) или, в режиме
  `recognition`, недоступен Qdrant;
- `error` (HTTP 503) — нет доступа к PostgreSQL.

## Камеры

Поддерживаемые источники (`stream_url` / `CAMERA_URL`):

| Тип | Пример |
|---|---|
| USB/вебка | `0` (= `/dev/video0`) |
| RTSP / IP-камера | `rtsp://user:password@192.168.1.10:554/stream1` |
| HTTP MJPEG | `http://192.168.1.10/video.mjpg` |
| Видеофайл | `data/videos/demo.mp4` (воспроизводится в реальном времени, по кругу) |

Путь RTSP зависит от производителя (Hikvision: `/Streaming/Channels/101`,
Dahua: `/cam/realmonitor?channel=1&subtype=0`). Сначала проверь источник:

```bash
python -m scripts.check_camera --source 0
python -m scripts.check_camera --source "rtsp://user:pass@192.168.1.10:554/stream1"
```

Скрипт печатает разрешение и FPS и сохраняет кадр в `data/snapshot.jpg`.

Добавить камеру в систему:

```bash
curl -X POST localhost:8000/cameras -H 'content-type: application/json' \
     -d '{"name": "Webcam", "stream_url": "0"}'
```

После этого перезапусти воркер: он читает список камер при старте.

Как работает воркер:
- каждая камера работает в своём потоке, сбой одной не влияет на другие;
- при обрыве воркер переподключается с паузой 1 → 2 → 4 … → 30 с;
- статус (`online` / `offline`) пишется в БД и виден в `/cameras` и `/health`;
- хранится только последний кадр: если обработка медленнее камеры, старые кадры
  отбрасываются, а не копятся;
- видео на диск не записывается.

## AI и live view

Модели: YOLOX-s (люди, Apache-2.0) и YuNet (лица, MIT), работают на CPU. Подробности,
лицензии и замеры скорости — в [docs/ai.md](docs/ai.md).

Посмотреть, что видит система: запусти API и воркер, затем открой в браузере
http://127.0.0.1:8000/cameras/1/stream. Там видео с зелёными рамками `Person 0.87`.

Без камеры можно взять тестовое видео:

```bash
curl -X POST localhost:8000/cameras -H 'content-type: application/json' \
     -d '{"name": "Demo", "stream_url": "data/samples/vtest.avi"}'
```

Кадры с рамками существуют только в памяти, на диск ничего не пишется.

## Тестирование

```bash
pytest                       # unit-тесты (integration пропускаются без БД)

# integration-тесты на реальной PostgreSQL (ПУСТАЯ отдельная БД — схема будет удалена)
sudo -u postgres psql -c "CREATE DATABASE korgoz_test OWNER korgoz;"
TEST_DATABASE_URL=postgresql+psycopg://korgoz:PASSWORD@localhost:5432/korgoz_test pytest -m integration

# качество кода
ruff check . && black --check . && mypy app tests
```

Маркеры: `integration` — нужны внешние сервисы; `ai` — реальные AI-модели
(по умолчанию исключены, запуск: `pytest -m ai`).

## Развёртывание

Docker не используется. Инструкции по установке PostgreSQL, Qdrant и настройке systemd:
[docs/deployment.md](docs/deployment.md).

## Troubleshooting

| Симптом | Причина / решение |
|---|---|
| `ValidationError: database_url Field required` | Нет `.env` или в нём не задан `DATABASE_URL` |
| `role "..." does not exist` | Не создана роль PostgreSQL (см. шаг 2) |
| `/health` → `"qdrant": "unavailable"` | Qdrant не запущен; в Phase 1 это допустимо |
| `/health` → HTTP 503 | PostgreSQL недоступен или неверный пароль в `DATABASE_URL` |
| `Cannot open video source 0` | Вебка занята другой программой или нет прав: `sudo usermod -aG video $USER` и перелогиниться |
| RTSP-камера постоянно `offline` | Проверь URL через `scripts.check_camera`, доступность порта 554, логин/пароль |
| Низкий FPS вебки (≈10) | Автоэкспозиция при слабом освещении удлиняет кадр; добавь света |
| Камера добавлена, но воркер её не видит | Воркер читает камеры при старте — перезапусти его |
| `/health` → `"ai": "unavailable"` | Воркер не запущен или модели не скачаны: `python -m scripts.download_models` |
| `Person detector model not found` | То же: скачай модели или проверь `PERSON_DETECTOR_MODEL_PATH` |
| `/cameras/1/stream` → 503 | Воркер не запущен (API берёт кадры у воркера) |
| `Live view disabled: cannot bind` | Порт 8001 занят — смени `LIVE_VIEW_PORT` (одинаково для API и воркера) |
| Низкий FPS обработки | См. «Настройка под слабое железо» в docs/ai.md |
| `alembic: command not found` | Не активирован venv: `source .venv/bin/activate` |
# korgoz
