# Развёртывание KörGöz (без Docker)

Целевая платформа: Ubuntu/Debian Linux. Все компоненты работают как обычные процессы ОС.

## 1. Python 3.12

```bash
sudo apt install python3.12 python3.12-venv
python3.12 --version
```

## 2. Пользователь и каталог

```bash
sudo useradd --system --create-home --home-dir /opt/korgoz korgoz
sudo -u korgoz git clone <repo> /opt/korgoz/app    # или скопировать файлы
cd /opt/korgoz/app
```

## 3. Виртуальное окружение и зависимости

```bash
sudo -u korgoz python3.12 -m venv .venv
sudo -u korgoz .venv/bin/pip install -r requirements.txt
```

## 4. PostgreSQL

```bash
sudo apt install postgresql
sudo systemctl enable --now postgresql

sudo -u postgres psql -c "CREATE ROLE korgoz LOGIN PASSWORD 'сильный_пароль';"
sudo -u postgres psql -c "CREATE DATABASE korgoz OWNER korgoz;"
```

Если пароль содержит спецсимволы (`@`, `:`, `/`, `%`), закодируй их в URL
(`@` → `%40` и т.д.).

## 5. Qdrant (нативный бинарник)

Qdrant распространяется как один исполняемый файл. Скачай релиз для своей архитектуры
со страницы https://github.com/qdrant/qdrant/releases (файл `qdrant-x86_64-unknown-linux-gnu.tar.gz`,
проверено на v1.19.2). SHA-256 архива сверь с полем `digest` в
`https://api.github.com/repos/qdrant/qdrant/releases/tags/<версия>`.

```bash
sudo mkdir -p /opt/qdrant/storage
sudo tar -xzf qdrant-x86_64-unknown-linux-gnu.tar.gz -C /opt/qdrant
sudo chown -R korgoz:korgoz /opt/qdrant
```

systemd unit `/etc/systemd/system/qdrant.service`:

```ini
[Unit]
Description=Qdrant vector database
After=network.target

[Service]
User=korgoz
WorkingDirectory=/opt/qdrant
Environment=QDRANT__STORAGE__STORAGE_PATH=/opt/qdrant/storage
Environment=QDRANT__SERVICE__HOST=127.0.0.1
# Qdrant sends anonymous usage telemetry by default; KörGöz is local-first.
Environment=QDRANT__TELEMETRY_DISABLED=true
ExecStart=/opt/qdrant/qdrant
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now qdrant
curl http://127.0.0.1:6333/healthz
```

`QDRANT__TELEMETRY_DISABLED=true` отключает анонимную телеметрию, которую Qdrant
по умолчанию отправляет разработчикам. `QDRANT__SERVICE__HOST=127.0.0.1` закрывает Qdrant от сети. Если Qdrant
нужен с другой машины, включи API key (`QDRANT__SERVICE__API_KEY`) и задай `QDRANT_API_KEY`.

## 6. Конфигурация

Для production секреты лучше хранить вне каталога проекта:

```bash
sudo mkdir -p /etc/korgoz
sudo cp .env.example /etc/korgoz/korgoz.env
sudo chown root:korgoz /etc/korgoz/korgoz.env
sudo chmod 640 /etc/korgoz/korgoz.env
sudo nano /etc/korgoz/korgoz.env     # DATABASE_URL, ENVIRONMENT=production, ...
```

## 7. AI-модели

```bash
cd /opt/korgoz/app
sudo -u korgoz .venv/bin/python -m scripts.download_models
```

Модели ложатся в `models/` (~56 МБ), SHA-256 проверяется. Если на сервере нет
интернета, скачай их на другой машине той же командой и скопируй каталог `models/`.

## 7a. Миграции

```bash
cd /opt/korgoz/app
sudo -u korgoz bash -c 'set -a; source /etc/korgoz/korgoz.env; set +a; .venv/bin/alembic upgrade head'
```

Первый администратор дашборда (пароль спросит дважды):

```bash
sudo -u korgoz bash -c 'set -a; source /etc/korgoz/korgoz.env; set +a; .venv/bin/python -m scripts.create_user admin --role admin'
```

Если API будет доступен из сети, поставь перед ним HTTPS-прокси и задай
`AUTH_COOKIE_SECURE=true` ([security.md](security.md)).

## 7b. Дашборд

Собирается один раз (и после каждого обновления кода) на машине с Node.js 22 LTS:

```bash
cd /opt/korgoz/app/frontend && npm ci && npm run build
```

Результат — статические файлы в `frontend/dist`. Их отдаёт сам API на `/ui/`, отдельный
веб-сервер не нужен. Node.js на сервере не обязателен: можно собрать на другой машине
и скопировать папку `frontend/dist`.

## 8. API как сервис systemd

```bash
sudo cp scripts/systemd/korgoz-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now korgoz-api
sudo systemctl status korgoz-api
journalctl -u korgoz-api -f          # логи
curl http://127.0.0.1:8000/health
```

## 9. Camera worker как сервис systemd

Воркер — отдельный процесс. Он подключается к камерам, держит переподключение и пишет
статус камер в БД. API читает статус оттуда.

```bash
sudo usermod -aG video korgoz        # доступ к USB-камерам (/dev/video*)
sudo cp scripts/systemd/korgoz-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now korgoz-worker
journalctl -u korgoz-worker -f       # каждые 10 с: fps, кадры, переподключения
```

Добавленные, удалённые и выключенные через API камеры воркер подхватывает сам
в течение `CAMERA_RELOAD_INTERVAL_SECONDS` (10 с), перезапуск не нужен.

Проверка источника до добавления в систему (без БД):

```bash
sudo -u korgoz .venv/bin/python -m scripts.check_camera --source "rtsp://user:pass@ip:554/stream1"
```

## Обновление

```bash
sudo systemctl stop korgoz-api korgoz-worker
sudo -u korgoz git pull
sudo -u korgoz .venv/bin/pip install -r requirements.txt
# модели (шаг 7) и миграции (шаг 7a)
sudo systemctl start korgoz-api korgoz-worker
```
