# KörGöz — Intelligent Vision & Situational Analytics Platform

KörGöz — локальная (on-premise) платформа видеоаналитики. Она превращает видеопотоки
с камер в структурированные данные: **объекты → события → связи → аналитика**.

Распознавание лиц — лишь один из модулей. Основа системы — понимание того, *кто/что*
находится в кадре, *где*, *какой камерой* обнаружен, *когда* появился, *сколько* пробыл
в зоне и *как* перемещался.

- Local-first: после установки интернет не нужен, видео не уходит во внешние API.
- Без Docker: всё запускается в Python venv и через systemd.
- Privacy-by-design: видео по умолчанию не сохраняется, хранятся только события.

> **Продолжаешь проект?** Начни с [docs/handoff.md](docs/handoff.md): там состояние,
> устройство кода, план оставшихся фаз и известные проблемы. Исходное ТЗ —
> [docs/spec.md](docs/spec.md).

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
| 4 | Multi-object tracking (ByteTrack) | ✅ готово |
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
├── tracking/            Tracker (abstraction), ByteTrack + Kalman, TrackStore (DB)
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
docs/                    handoff (передача проекта), spec (ТЗ), архитектура, AI, развёртывание
```

## Как запустить (пошагово)

Проверено на Ubuntu 26.04, Python 3.12, PostgreSQL 18. Docker не нужен.

Всё работает на CPU, видеокарта не нужна. Интернет нужен только для установки:
pip-пакеты, модели (~56 МБ) и Qdrant (~33 МБ).

### Шаг 1. Установка (один раз)

```bash
git clone https://github.com/yomarakesha/korgoz.git ~/projects/korgoz   # если ещё не склонирован
cd ~/projects/korgoz

# Python-окружение
python3.12 -m venv .venv
source .venv/bin/activate          # делать в КАЖДОМ новом терминале
pip install -r requirements-dev.txt

# База данных PostgreSQL (нужен sudo)
sudo -u postgres psql -c "CREATE ROLE korgoz LOGIN PASSWORD 'korgoz_dev_pw';"
sudo -u postgres psql -c "CREATE DATABASE korgoz OWNER korgoz;"

# Конфигурация
cp .env.example .env
```

Открой `.env` и впиши пароль, который задал выше:

```
DATABASE_URL=postgresql+psycopg://korgoz:korgoz_dev_pw@localhost:5432/korgoz
```

Если в пароле есть символы `@ : / %`, их нужно закодировать (`@` → `%40`).
Проще всего использовать пароль из букв и цифр.

```bash
# Таблицы в БД
alembic upgrade head

# AI-модели и тестовое видео (SHA-256 проверяется)
python -m scripts.download_models --samples
```

Если загрузка падает (`Failed to connect ... port 443`), значит нет доступа к GitHub.
Включи VPN или прокси и повтори.

### Шаг 2. Qdrant (нужен только для распознавания лиц, Phase 5)

Для режима `anonymous` (детекция и трекинг) этот шаг можно пропустить.

```bash
mkdir -p ~/qdrant/storage && cd ~/qdrant
curl -L -O https://github.com/qdrant/qdrant/releases/download/v1.19.2/qdrant-x86_64-unknown-linux-gnu.tar.gz
tar -xzf qdrant-x86_64-unknown-linux-gnu.tar.gz
cd ~/projects/korgoz
```

### Шаг 3. Запуск

Понадобятся 2 терминала, третий — если нужен Qdrant. В каждом сначала выполни
`cd ~/projects/korgoz && source .venv/bin/activate`.

**Терминал 1 — API:**

```bash
uvicorn app.main:app --reload
```

**Терминал 2 — camera worker** (камеры, детекция, трекинг):

```bash
python -m app.worker
```

**Терминал 3 — Qdrant** (по желанию):

```bash
cd ~/qdrant && QDRANT__STORAGE__STORAGE_PATH=./storage QDRANT__SERVICE__HOST=127.0.0.1 QDRANT__TELEMETRY_DISABLED=true ./qdrant
```

Если воркер пишет `No cameras configured`, это нормально: камера ещё не добавлена.
Добавь её (шаг 4) и запусти воркер снова.

### Шаг 4. Добавить камеру

Камеры добавляются через API, пока работает терминал 1. **После добавления
перезапусти воркер** (Ctrl+C в терминале 2, затем снова `python -m app.worker`):
список камер он читает только при старте.

**Вариант А — вебка ноутбука:**

```bash
python -m scripts.check_camera --source 0      # проверка: печатает разрешение и FPS
curl -X POST localhost:8000/cameras -H 'content-type: application/json' \
     -d '{"name": "Webcam", "stream_url": "0"}'
```

`0` означает `/dev/video0`. Если вебка не открывается, закрой программы, которые
её используют (Zoom, браузер с видеозвонком).

**Вариант Б — тестовое видео с пешеходами** (без камеры, удобно для проверки):

```bash
curl -X POST localhost:8000/cameras -H 'content-type: application/json' \
     -d '{"name": "Demo", "stream_url": "data/samples/vtest.avi"}'
```

Видео проигрывается в реальном времени и по кругу. Можно указать путь к любому
своему `.mp4` или `.avi`.

**Вариант В — IP/RTSP-камера:**

```bash
python -m scripts.check_camera --source "rtsp://user:password@192.168.1.10:554/stream1"
curl -X POST localhost:8000/cameras -H 'content-type: application/json' \
     -d '{"name": "Entrance", "stream_url": "rtsp://user:password@192.168.1.10:554/stream1"}'
```

Путь RTSP зависит от производителя (Hikvision: `/Streaming/Channels/101`,
Dahua: `/cam/realmonitor?channel=1&subtype=0`). Пароль камеры API никогда не
показывает и в логи не пишет.

Можно добавить несколько камер сразу, например вебку и видео. Каждая работает
независимо и получает свой `id`: 1, 2, …

### Шаг 5. Что смотреть

| Что | Где |
|---|---|
| **Live view с рамками `Track #N`** | http://127.0.0.1:8000/cameras/1/stream (`1` — id камеры) |
| Один кадр (JPEG) | http://127.0.0.1:8000/cameras/1/snapshot |
| Swagger UI: все эндпоинты, можно вызывать из браузера | http://127.0.0.1:8000/docs |
| Состояние системы | http://127.0.0.1:8000/health |
| Список камер и их статус | http://127.0.0.1:8000/cameras |
| Кто сейчас в кадре (активные треки) | http://127.0.0.1:8000/tracks?active=true |
| История треков с длительностью | http://127.0.0.1:8000/tracks?camera_id=1 |

Что должно получиться:
- `/health` показывает `"database": "ok"`, `"ai": "ok"`, `"cameras": 1`.
  `"qdrant": "unavailable"` в режиме `anonymous` допустимо.
- В live view вокруг людей зелёные рамки `Track #N`, а сверху счётчик `persons: N`.
  Если пройти перед вебкой, выйти из кадра и вернуться через 3+ секунды, появится
  новый номер трека.
- Терминал воркера каждые 10 с печатает
  `capture_fps=… processing_fps=… detection=…ms tracks=…`.

Остановка: Ctrl+C в каждом терминале. Воркер при этом закроет треки и пометит
камеры `offline`.

### Быстрая проверка без БД и API

```bash
python -m scripts.check_camera --source 0              # камера работает? FPS?
python -m scripts.benchmark_detector                    # скорость детекции на этом CPU
python -m scripts.benchmark_detector --model models/yolox_tiny.onnx --faces
```

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
| `TRACKING_ENABLED` | `true` | трекинг людей (ByteTrack) |
| `TRACK_MAX_LOST_SECONDS` | `3` | сколько человек может быть скрыт и сохранить номер трека |
| `TRACK_LOW_THRESHOLD` / `TRACK_NEW_THRESHOLD` | `0.1` / `0.6` | неуверенные рамки продлевают треки; новый трек — только от уверенной |
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
| GET | `/tracks` | Треки, новые сверху. Фильтры: `camera_id`, `active`, `since`, `until`, `limit`, `offset` |
| GET | `/tracks/{id}` | Трек: начало, последнее появление, конец, длительность |

`stream_url` никогда не возвращается: API отдаёт `stream_url_masked`
(`rtsp://***:***@host/...`) и `source_kind` (`usb` / `network` / `file`).
Swagger UI с примерами: `/docs`.

Пример ответа `/health`:

```json
{"status": "ok", "database": "ok", "qdrant": "unavailable", "ai": "ok", "cameras": 1}
```

- `ok` — всё нужное для текущего режима работает (в `anonymous` Qdrant не обязателен);
- `degraded` (HTTP 200) — API работает, но не запущен воркер/модели (`ai`) или, в режиме
  `recognition`, недоступен Qdrant;
- `error` (HTTP 503) — нет доступа к PostgreSQL.

## Камеры (подробно)

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

Live view: http://127.0.0.1:8000/cameras/{id}/stream (подробно — в «Как запустить», шаг 5).

Кадры с рамками существуют только в памяти, на диск ничего не пишется.

## Тестирование

Тесты не нужны ни камера, ни запущенные сервисы. Unit-тесты используют SQLite в памяти
и фейковые источники видео.

```bash
source .venv/bin/activate

pytest                    # unit-тесты (~110 шт., ~10 с)
pytest -m ai              # реальные модели: YOLOX находит пешеходов, YuNet — лицо
                          # (нужен python -m scripts.download_models --samples)
pytest tests/unit/tracking -v   # только один модуль, подробно
```

Integration-тесты на настоящем PostgreSQL. Нужна **пустая отдельная** БД: схема
создаётся и в конце удаляется.

```bash
sudo -u postgres psql -c "CREATE DATABASE korgoz_test OWNER korgoz;"
TEST_DATABASE_URL=postgresql+psycopg://korgoz:korgoz_dev_pw@localhost:5432/korgoz_test pytest -m integration
```

Без `TEST_DATABASE_URL` integration-тесты просто пропускаются (`SKIPPED`).

Качество кода (все три должны пройти без ошибок):

```bash
ruff check . && black --check . && mypy app tests scripts
```

| Маркер | Что нужно | Запуск |
|---|---|---|
| (без маркера) | ничего | `pytest` |
| `ai` | скачанные модели | `pytest -m ai` |
| `integration` | PostgreSQL + `TEST_DATABASE_URL` | `pytest -m integration` |

## Развёртывание

Docker не используется. Инструкции по установке PostgreSQL, Qdrant и настройке systemd:
[docs/deployment.md](docs/deployment.md).

## Troubleshooting

| Симптом | Причина / решение |
|---|---|
| `ValidationError: database_url Field required` | Нет `.env` или в нём не задан `DATABASE_URL` |
| `role "..." does not exist` | Не создана роль PostgreSQL (см. шаг 1) |
| `password authentication failed` | Пароль в `DATABASE_URL` (`.env`) не совпадает с паролем роли |
| `/health` → `"qdrant": "unavailable"` | Qdrant не запущен. В режиме `anonymous` это допустимо |
| `/health` → HTTP 503 | PostgreSQL недоступен или неверный пароль в `DATABASE_URL` |
| `Cannot open video source 0` | Вебка занята другой программой или нет прав: `sudo usermod -aG video $USER` и перелогиниться |
| RTSP-камера постоянно `offline` | Проверь URL через `scripts.check_camera`, доступность порта 554, логин/пароль |
| Низкий FPS вебки (≈10) | Автоэкспозиция при слабом освещении удлиняет кадр; добавь света |
| Камера добавлена, но воркер её не видит | Воркер читает камеры при старте — перезапусти его |
| `/health` → `"ai": "unavailable"` | Воркер не запущен или модели не скачаны: `python -m scripts.download_models` |
| `Person detector model not found` | То же: скачай модели или проверь `PERSON_DETECTOR_MODEL_PATH` |
| `/cameras/1/stream` → 503 | Воркер не запущен (API берёт кадры у воркера) |
| `/cameras/1/stream` → 404 `Camera not found` | Нет камеры с таким id: смотри `GET /cameras` |
| `/cameras/1/stream` → 404 `No frames` | Камера добавлена после старта воркера — перезапусти воркер |
| `Live view disabled: cannot bind` | Порт 8001 занят — смени `LIVE_VIEW_PORT` (одинаково для API и воркера) |
| Низкий FPS обработки | См. «Настройка под слабое железо» в docs/ai.md |
| `alembic: command not found` | Не активирован venv: `source .venv/bin/activate` |
