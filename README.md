# VIBE Social Network

Полноценная социальная сеть на Python/Flask + PostgreSQL + Tailwind CSS.  
Развёрнута на Railway: https://socnet.up.railway.app

**Ветка**: `main` (production)

---

## Основные фичи

### Контент
- Посты с медиа (фото/видео/аудио), лайки, реакции (emoji), комментарии, репосты, сохранения
- **Shorts** — вертикальные видео с музыкой, лайки, комментарии, реакции
- **Stories** — 24h истории с фото/видео, реакции, комментарии, архив
- Черновики постов

### Коммуникации
- Личные и групповые чаты с голосовыми и видеосообщениями («кружочки»)
- **VoIP** — аудио/видеозвонки через WebRTC + WebSocket signaling + TURN

### Музыка
- **Deezer API** — поиск треков, популярное, альбомы, история прослушивания
- Плейлисты, избранное, рекомендации на основе истории
- Загрузка своих аудиофайлов

### Сообщества
- Открытые и закрытые сообщества с мероприятиями (RSVP) и архивами
- Системные боты с авто-создаваемыми сообществами (Новости, Технологии, Путешествия, …)

### Профили и аккаунты
- Профили, подписки, блокировка, приватность, верификация телефона по SMS
- **Мультиаккаунты** (личные + бизнес) с аналитикой
- **Google OAuth** вход

### Безопасность
- **2FA TOTP** (Google Authenticator / Authy)
- CSRF-защита на всех формах (Flask-WTF)
- Rate limiting на критичных endpoints
- Content Security Policy, HSTS, X-Frame-Options, X-Content-Type-Options
- NSFW-модерация (150+ ключевых слов, авто-бан)

### Инструменты
- **Фоторедактор** — 11 инструментов: кроп, подстройка, 25 фильтров, эффекты, текст, стикеры, рисование, портрет, рамки, коллаж, анимация
- **Видеоредактор для Shorts** — обрезка, фильтры, скорость, аудио (через Cloudinary)
- **Бот-платформа** — Telegram-style API, 25+ методов, вебхуки
- **Админ-панель** — жалобы, управление пользователями, модерация сообществ

---

## Быстрый старт

```bash
git clone https://github.com/Sergqmts/tg_bot.git
cd tg_bot
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # заполнить переменные
python app.py              # dev на :5000
```

Локально использует SQLite, в production — PostgreSQL.  
Откройте http://127.0.0.1:5000

---

## Переменные окружения

Полный список с описаниями — в [.env.example](.env.example).

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | PostgreSQL URI (`postgresql+psycopg://...`) |
| `SECRET_KEY` | Flask secret key (≥32 символа) |
| `CLOUDINARY_CLOUD_NAME` / `_API_KEY` / `_API_SECRET` | Хранилище медиа |
| `GOOGLE_CLIENT_ID` / `_CLIENT_SECRET` | Google OAuth |
| `METERED_APP_NAME` / `_API_KEY` | TURN-сервер для VoIP |
| `SMS_PROVIDER` / `SMSRU_API_ID` | SMS-верификация |
| `FREESOUND_API_KEY` | Аудио для Shorts |
| `EDITOR_SERVICE_URL` / `_TOKEN` / `EDITOR_JWT_SECRET` | Микросервис редактора |
| `ALLOWED_ORIGIN` | CORS origin для production |
| `NEWS_BOT_TOKEN` | GitHub → NewsBot вебхук |
| `GITHUB_WEBHOOK_SECRET` | Подпись GitHub-вебхуков |
| `MAIL_SENDER` / `MAIL_PASSWORD` | Email-уведомления |

---

## Деплой на Railway

1. https://railway.app → Login через GitHub
2. New Project → Deploy from GitHub repo → выбрать этот репозиторий
3. Add PostgreSQL (Add Service → Database → PostgreSQL)
4. Перейти в Variables → добавить все переменные из таблицы выше
5. Deploy автоматически запускается при push в `main`

Procfile: `web: gunicorn --worker-class eventlet -w 1 asgi_app:app`

---

## Документация

| Файл | Содержание |
|---|---|
| [PROJECT.md](PROJECT.md) | Полное описание архитектуры, моделей, фич |
| [ROADMAP.md](ROADMAP.md) | Что готово / в работе / планируется |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Системная архитектура + Editor Service |
| [docs/API.md](docs/API.md) | API Editor Service |
| [docs/BOT_API.md](docs/BOT_API.md) | Бот-платформа: полный справочник API |
| [docs/SECURITY.md](docs/SECURITY.md) | Безопасность: меры, настройки, известные ограничения |
| [docs/INTEGRATION.md](docs/INTEGRATION.md) | Интеграция с Editor Service |
| [docs/MIGRATION_GUIDE.md](docs/MIGRATION_GUIDE.md) | Миграция Editor Service → монолит |
| [EDITOR_SERVICE_SPEC.md](EDITOR_SERVICE_SPEC.md) | Спецификация Editor Service |

---

## Известные ограничения

1. Socket.IO не работает с gunicorn sync workers — real-time только через Starlette WebSocket
2. faster-whisper работает медленно на CPU (бесплатный Railway tier)
3. Нет ограничения размера файлов на уровне сервера — большие аплоады могут вызвать 502
4. `Message.body NOT NULL` в PostgreSQL — всегда передавать `body=''` при медиа-сообщениях
5. JWT key < 32 bytes вызывает `InsecureKeyLengthWarning` — использовать ключ ≥32 символа

---

## Стек

Python 3.12, Flask 3.x, Flask-Login, Flask-SQLAlchemy, Flask-WTF, Flask-SocketIO, PostgreSQL, Cloudinary, Starlette, Uvicorn, Gunicorn, Tailwind CSS, WebRTC, Deezer API, Google OAuth, pyotp (2FA), Authlib, Pillow, faster-whisper, Pytest
