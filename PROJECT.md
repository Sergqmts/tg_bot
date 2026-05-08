# Social Network на Flask

## Описание
Полноценная социальная сеть на Python с использованием Flask. Развёрнута на Railway.
Ссылка: https://tgbot-production-c350.up.railway.app

## 🚀 Быстрый старт

### Локальная разработка
```bash
git clone https://github.com/Sergqmts/tg_bot.git
cd tg_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # создать если нет: pip freeze > requirements.txt
python app.py
```
Откройте http://127.0.0.1:5000

### Деплой на Railway
1. [railway.app](https://railway.app) → Login через GitHub
2. New Project → Deploy from GitHub repo
3. Add PostgreSQL
4. Variables: `DATABASE_URL`, `SECRET_KEY` (мин. 30 символов), `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`
5. Auto-deploy

## 📁 Структура проекта
```
tg_bot/
├── app.py              # Всё приложение: routes, models, config (~4200 строк)
├── Procfile            # gunicorn app:app
├── README.md           # Краткое описание
├── PROJECT.md          # Полная документация
├── MEMORY.md           # Контекст для новой сессии
├── static/
│   ├── style.css       # Все стили (2150+ строк)
│   └── uploads/        # Локальные медиа (fallback без Cloudinary)
└── templates/
    ├── base.html           # Хедер, навигация, аудиоплеер, Socket.IO
    ├── index.html          # Лента постов
    ├── login.html          # Вход
    ├── register.html       # Регистрация
    ├── profile.html        # Профиль (посты, shorts, выход)
    ├── edit_profile.html   # Редактирование профиля
    ├── create.html         # Создание поста
    ├── post.html           # Просмотр поста + комментарии
    ├── explore.html        # Поиск людей/тегов/сообществ
    ├── messages.html       # Список диалогов и групп
    ├── conversation.html   # Личный чат (голосовые + видеосообщения)
    ├── chat.html           # Групповой чат (голосовые + видеосообщения)
    ├── notifications.html  # Уведомления
    ├── communities.html    # Список сообществ
    ├── community.html      # Страница сообщества
    ├── community_members.html # Участники сообщества
    ├── community_post.html # Создание поста в сообществе
    ├── create_community.html # Создание сообщества
    ├── shorts.html         # Shorts лента
    ├── create_shorts.html  # Создание shorts + FreeSound поиск
    └── ... (чаты, stories, video editor и др.)
```

## 🗄️ База данных (SQLAlchemy + PostgreSQL/SQLite)

### Модели
| Модель | Ключевые поля |
|--------|---------------|
| **User** | id, username, email, password_hash, bio, avatar, avatar_cloudinary_url, is_private, hide_followers, approve_followers, last_seen |
| **Post** | id, body, created_at, user_id, community_id, is_community_post |
| **Media** | id, filename, cloudinary_url, media_type (image/video/audio), post_id |
| **Comment** | id, body, created_at, user_id, post_id, reply_to_id |
| **Message** | id, body, created_at, read, sender_id, recipient_id, post_id, chat_id, transcription |
| **MessageMedia** | id, message_id, media_url, media_type (image/video/audio/voice/document/video_message) |
| **Chat** | id, name, type (direct/group), avatar, background |
| **Notification** | id, user_id, sender_id, type (like/comment/reply/follow/message/new_story), read |
| **Community** | id, name, slug, description, image, creator_id, is_private |
| **Shorts** | id, video_url, caption, views, user_id, audio_id |
| **Story** | id, media_url, media_type, expires_at, user_id |

## 🛣️ Основные маршруты

### Аутентификация
| URL | Методы | Описание |
|-----|--------|----------|
| `/register` | GET/POST | Регистрация |
| `/login` | GET/POST | Вход |
| `/logout` | GET | Выход |

### Посты
| URL | Методы | Описание |
|-----|--------|----------|
| `/` | GET | Лента |
| `/create` | GET | Форма создания |
| `/create_post` | POST | Создать пост (ручной CSRF) |
| `/post/<id>` | GET | Просмотр поста |
| `/post/<id>/like` | GET/POST | Лайк (AJAX+JSON) |
| `/post/<id>/comment` | POST | Комментарий |
| `/delete/<id>` | POST | Удалить пост |

### Сообщения
| URL | Методы | Описание |
|-----|--------|----------|
| `/messages` | GET | Список диалогов |
| `/messages/<username>` | GET/POST | Личный чат |
| `/messages/<username>/voice` | POST | Голосовое (CSRF exempt) |
| `/messages/<username>/video-message` | POST | Видеосообщение |
| `/chat/<id>` | GET/POST | Групповой чат |
| `/chat/<id>/voice` | POST | Голосовое в группу |
| `/chat/<id>/video-message` | POST | Видеосообщение в группу |

### Уведомления
| URL | Методы | Описание |
|-----|--------|----------|
| `/notifications` | GET | Список уведомлений |
| `/notifications/read/<id>` | POST | Отметить прочитанным |
| `/notifications/read_all` | POST | Все прочитаны |
| `/api/unread-count` | GET | JSON {count} (для polling) |

### Видеосообщения ("кружочки")
- Запись: MediaRecorder + front camera (`facingMode: user`), 60s max
- Хранение: Cloudinary (папка `video_messages`) или локально
- Отображение: `<video> 140×140, rounded-full, object-cover`
- Автовоспроизведение: IntersectionObserver (muted)
- Тап: fullscreen с аудио
- CSRF: включён (не exempt, в отличие от voice)

### Сообщества
| URL | Методы | Описание |
|-----|--------|----------|
| `/communities` | GET | Список |
| `/communities/create` | GET/POST | Создать |
| `/community/<slug>` | GET | Страница |
| `/community/<slug>/post` | GET/POST | Написать пост |
| `/community/<slug>/members` | GET | Участники |

## 🧩 Ключевые фичи
- **Аудиоплеер**: кастомный с градиентом, прогресс-баром, pulse-анимацией (Apple Music-style)
- **AJAX лайки**: без перезагрузки страницы, через fetch + JSON
- **CSRF**: все POST формы (кроме voice) требуют токен; `<meta name="csrf-token">` для AJAX
- **Cloudinary**: медиа посты, аватары, stories, голосовые, видео, shorts — всё в Cloudinary
- **Whisper**: транскрипция голосовых сообщений (faster-whisper, base model, CPU)
- **FreeSound API**: поиск аудио для shorts
- **Shorts**: вертикальные видео, лайки, комментарии, реакции
- **Stories**: 24h истории с фото/видео
- **Приватность**: закрытые профили, одобрение подписчиков, блокировка
- **Групповые чаты**: создание, управление участниками, админы

## 🧰 Технологии
- Flask 3.x, Flask-Login, Flask-SQLAlchemy, Flask-WTF, Flask-SocketIO
- PostgreSQL (Railway) / SQLite (локально)
- Cloudinary (CDN медиа)
- Gunicorn (production)
- Tailwind CSS (CDN)
- faster-whisper (голос → текст)
- Socket.IO (presence, отключен в production из-за sync workers)

## 🚀 Переменные окружения (Railway)
```
DATABASE_URL=postgresql://...
SECRET_KEY=<random 30+ chars>
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
PORT=8080
```

## ⚠️ Известные проблемы
1. Socket.IO не работает с gunicorn sync workers — для реального времени нужен eventlet
2. Нет requirements.txt — Railway автоопределяет, но при новых зависимостях создать вручную
3. `Message.body NOT NULL` в PostgreSQL — всегда передавать `body=''`
4. Whisper медленный на CPU (free Railway)
5. Нет лимита размера файлов — большие аплоады могут вызвать 502
