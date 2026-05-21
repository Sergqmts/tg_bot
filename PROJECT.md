# VIBE Social Network — полная документация

## Описание
Полноценная социальная сеть на Python/Flask с модульной архитектурой.  
Развёрнута на Railway: https://socnet.up.railway.app

## Архитектура

### ASGI + WSGI гибрид
- **`asgi_app.py`** — точка входа: Starlette с WebSocket-роутом `/ws/call` и Flask через `WSGIMiddleware`
- **`app.py`** — Flask-приложение: конфиг, инициализация БД, миграции, Socket.IO (presence)
- **`signaling.py`** — WebSocket handler для звонков (SDP/ICE relay, комнаты)
- **`extensions.py`** — глобальные объекты: `db`, `login_manager`, `socketio`, `csrf`
- **`models.py`** — все SQLAlchemy модели (880 строк)
- **`helpers.py`** — утилиты (загрузка Cloudinary, модерация, генерация токенов, уведомления)

### Маршруты (`routes/`)
Модульная система: `routes/__init__.py → register_all_routes(app)` импортирует 11 модулей:

| Файл | Маршруты |
|------|----------|
| `auth.py` | `/login`, `/register`, `/logout`, `/login/google`, `/login/google/callback` |
| `posts.py` | `/`, `/create`, `/post/<id>`, `/like`, `/comment`, `/delete`, `/repost`, `/save`, `/react`, `/video_editor`, `/photo_editor`, `/photo_transform`, `/search`, `/tags`, `/tag/<name>`, `/popular`, `/dashboard`, `/drafts`, `/forward` |
| `profiles.py` | `/profile/<username>`, `/edit_profile`, `/follow`, `/unfollow`, `/followers`, `/following`, `/block`, `/unblock`, `/photos`, `/recommendations`, `/explore`, `/business/analytics` |
| `stories.py` | `/stories`, `/create_story`, `/story/<id>`, `/story/<id>/react`, `/story/<id>/comment`, `/stories/archive`, `/stories/hide` |
| `messages.py` | `/messages`, `/messages/<username>`, `/chat/<id>`, `/voice`, `/video-message`, `/api/messages`, `/api/chats`, `/chat/<id>/edit`, `/chat/<id>/members`, `/forward_message` |
| `communities.py` | `/communities`, `/communities/create`, `/community/<slug>`, `/community/<slug>/post`, `/community/<slug>/events`, `/community/<slug>/requests` |
| `music.py` | `/music`, `/music/search`, `/music/track/<id>`, `/music/playlist`, `/music/favorites`, `/music/history`, `/music/recommendations`, `/music/upload` |
| `bots.py` | `/bots`, `/bots/new`, `/bots/<id>/settings`, `/bot<token>/<method>` (25 методов) |
| `accounts.py` | `/accounts`, `/accounts/create`, `/accounts/switch`, `/accounts/link` |
| `calls.py` | `/api/calls/initiate`, `/api/calls/<id>/status`, `/api/calls/<id>/end`, `/api/calls/history`, `/api/turn/credentials` |
| `editor.py` | `/proxy/edit/photo`, `/proxy/edit/video`, `/api/editor/publish`, `/api/editor/publish-video`, `/api/editor/draft/<id>` |

## 🗄️ База данных (SQLAlchemy + PostgreSQL/SQLite)

### Модели (полный список)

| Модель | Назначение | Ключевые поля |
|--------|-----------|---------------|
| **User** | Пользователь | username, email, google_id, password_hash, bio, avatar, avatar_cloudinary_url, location, website, birthday, interests, occupation, is_private, hide_followers, hide_following, approve_followers, phone, phone_verified, is_bot, bot_token, bot_commands, webhook_url, creator_id, is_banned, is_staff, is_business |
| **Post** | Пост | body, created_at, user_id, community_id, is_community_post, music_track_id |
| **Media** | Медиа поста | filename, cloudinary_url, media_type (image/video/audio/document), post_id |
| **Like** | Лайк поста | user_id, post_id |
| **Reaction** | Реакция (emoji) на пост | user_id, post_id, emoji |
| **Comment** | Комментарий | body, user_id, post_id, reply_to_id, media_url, media_type |
| **CommentReaction** | Реакция на комментарий | comment_id, user_id, emoji |
| **CommentMedia** | Legacy комментарий | body, media_url, media_type, user_id, post_id, reply_to_id |
| **Repost** | Репост | user_id, post_id |
| **SavedPost** | Сохранённый пост | user_id, post_id |
| **Tag** | Хештег | name |
| **PostTag** | Связь пост-тег | post_id, tag_id |
| **Draft** | Черновик | user_id, media_data, caption |
| **Story** | 24h история | user_id, media_url, media_type, expires_at, is_saved, is_archived |
| **StoryReaction** | Реакция на сторис | story_id, user_id, emoji |
| **StoryComment** | Комментарий к сторис | story_id, user_id, body |
| **Shorts** | Вертикальное видео | video_url, audio_id, caption, user_id, views |
| **ShortsLike** | Лайк shorts | user_id, shorts_id |
| **ShortsReaction** | Реакция shorts | user_id, shorts_id, emoji |
| **ShortsComment** | Комментарий shorts | body, user_id, shorts_id |
| **ShortsAudio** | Аудио для shorts | title, audio_url, duration, user_id |
| **Message** | Сообщение чата | body, sender_id, recipient_id, chat_id, post_id, transcription, forwarded_from_id |
| **MessageMedia** | Медиа сообщения | message_id, media_url, media_type |
| **MessageReaction** | Реакция на сообщение | message_id, user_id, emoji |
| **Chat** | Чат (личный/групповой) | name, type (direct/group), creator_id, avatar, background_type, background_value |
| **ChatMember** | Участник чата | chat_id, user_id, role (member/admin) |
| **Community** | Сообщество | name, slug, description, image, is_private, creator_id, is_banned |
| **CommunityMember** | Участник сообщества | user_id, community_id, role, status |
| **CommunityEvent** | Мероприятие | community_id, creator_id, title, description, event_date, location, is_archived |
| **EventAttendee** | Участник мероприятия | event_id, user_id, status |
| **Notification** | Уведомление | user_id, sender_id, type, post_id, comment_id, message_id, read |
| **Call** | Звонок | caller_id, callee_id, call_type (audio/video), status (ringing/ongoing/ended/declined/missed) |
| **MusicTrack** | Музыкальный трек | title, artist, album, duration, preview_url, cover_url, deezer_id, source, file_url |
| **Playlist** | Плейлист | name, description, cover_url, user_id, is_public |
| **PlaylistItem** | Трек в плейлисте | playlist_id, track_id, position |
| **FavoriteTrack** | Избранный трек | user_id, track_id |
| **ListeningHistory** | История прослушивания | user_id, track_id |
| **ModerationLog** | Лог модерации | user_id, community_id, post_id, reason |
| **Report** | Жалоба | reporter_id, target_user_id, target_post_id, reason, status |
| **ProfileVisit** | Посещение профиля | profile_id, visitor_id |
| **PostView** | Просмотр поста | post_id, viewer_id |
| **AccountGroup** | Группа аккаунтов | name, owner_id |
| **AccountGroupMember** | Аккаунт в группе | group_id, user_id, account_type, role, business_name |
| **FeatureAnnouncement** | Анонс фичи | title, body, icon, is_posted |

## 🚀 Быстрый старт

### Локальная разработка
```bash
git clone https://github.com/Sergqmts/tg_bot.git
cd tg_bot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Откройте http://127.0.0.1:5000

### Деплой на Railway
1. https://railway.app → Login через GitHub
2. New Project → Deploy from GitHub repo
3. Add PostgreSQL
4. Переменные: `DATABASE_URL`, `SECRET_KEY`, `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `CLOUDFLARE_TURN_KEY_ID`, `CLOUDFLARE_TURN_API_TOKEN`, `FREESOUND_API_KEY`
5. Auto-deploy

## 📁 Структура проекта
```
tg_bot/
├── app.py                  # Flask-приложение: конфиг, миграции, Socket.IO
├── asgi_app.py             # ASGI точка входа (Starlette + Flask)
├── signaling.py            # WebSocket signaling для звонков
├── extensions.py           # db, login_manager, socketio, csrf
├── models.py               # Все модели БД (880 строк)
├── helpers.py              # Утилиты (314 строк)
├── Procfile                # gunicorn app:app
├── requirements.txt        # Все зависимости
├── DESIGN_SPEC.json        # Дизайн-спецификация (цвета, типографика)
├── README.md / PROJECT.md / MEMORY.md / ROADMAP.md
├── routes/
│   ├── __init__.py         # register_all_routes()
│   ├── auth.py             # Аутентификация + Google OAuth
│   ├── posts.py            # Посты, лайки, комментарии, редакторы
│   ├── profiles.py         # Профили, подписки, блокировка
│   ├── stories.py          # Stories 24h
│   ├── messages.py         # Личные и групповые чаты
│   ├── communities.py      # Сообщества и мероприятия
│   ├── music.py            # Музыкальный плеер (Deezer)
│   ├── bots.py             # Bot API (Telegram-style)
│   ├── accounts.py         # Мультиаккаунты / бизнес-аккаунты
│   ├── calls.py            # VoIP звонки API
│   └── editor.py           # Editor Service Integration (прокси, API публикации)
├── static/
│   ├── style.css           # Все стили (2169 строк)
│   ├── call.js             # WebRTC клиент для звонков
│   └── uploads/            # Локальные медиа (fallback)
└── templates/              # 68 Jinja2 шаблонов
```

## 🧩 Ключевые фичи

### Бот-платформа (Telegram-style)
- Модель бота: `is_bot`, `bot_token`, `bot_commands`, `can_join_groups`, `privacy_mode`, `webhook_url`, `creator_id`
- Генерация токенов Telegram-style (`id:secret`)
- Bot API: 25+ методов (sendMessage, sendPhoto, sendVideo, sendVoice, sendDocument, forwardMessage, deleteMessage, banChatMember, unbanChatMember, promoteChatMember, getChat, getChatMembers, getMe, setWebhook, deleteWebhook, getCommunity, getCommunityMembers, approveJoinRequest, denyJoinRequest, kickMember, promoteToAdmin, deletePost, sendPost, joinCommunity, getUpdates)
- Вебхуки: асинхронный POST при новых сообщениях
- CSRF exempt для всех Bot API маршрутов

### Editor Service Integration
- Внешний микросервис редактора для фото и видео (`editor_service_VibeHub`)
- Прокси-роуты: `/proxy/edit/photo`, `/proxy/edit/video` — JWT-редирект на редактор
- API-эндпоинты для публикации: `/api/editor/publish`, `/api/editor/publish-video`
- API для черновиков: `/api/editor/draft/<id>`
- JWT-аутентификация: общий секрет `EDITOR_JWT_SECRET` / `JWT_SECRET`
- Service-to-service auth: `X-Service-Token` header
- Fallback на локальные редакторы при отсутствии `EDITOR_SERVICE_TOKEN`

### Фоторедактор (`/photo_editor`)
11 инструментов на Canvas2D:
1. **Crop** — свободный + 8 соотношений (1:1, 4:5, 9:16, 16:9, 3:2, 4:3, 2:3, 21:9), rotate, flip, straighten
2. **Adjust** — brightness, contrast, saturation, exposure, sharpness, shadows, highlights, temperature, tint, noise, vignette
3. **Filters** — 25 Instagram-style пресетов с живыми превью
4. **Effects** — vintage, B&W, LOMO, glitter, glow, grain, HDR, dramatic, soft
5. **Text** — шрифты, размер, цвет, bold/italic/underline, shadow, alignment
6. **Stickers** — 32 эмодзи + загрузка своих изображений
7. **Drawing** — marker, brush, spray, eraser с размером/цветом/прозрачностью
8. **Portrait** — skin smooth, teeth whiten, eye enhance, blemish remove, makeup, face slim
9. **Frames** — 6 стилей (thin, double, polaroid, neon, gold, VHS)
10. **Collage** — 6 шаблонов (до 6 фото)
11. **Animation** — sparkles, hearts, bubbles, stars, rainbow, glitch + GIF загрузка
- Сохранение: в ленту, stories, shorts или черновик
- Качество: 60/80/92/100%
- История: undo/redo (до 50 шагов)

### Видеоредактор для Shorts (`/video_editor`)
- Загрузка видео в Cloudinary с `resource_type='video'`
- Обрезка: ползунки start/end → Cloudinary `so`/`eo`
- Фильтры: 7 пресетов (grayscale, sepia, vintage, cinematic, vivid, cool, warm)
- Скорость: 0.25x–2x → `e_accelerate`
- Аудио: выбор из библиотеки `ShortsAudio`
- Трансформации на Cloudinary — нулевая нагрузка на сервер

### VoIP Звонки (WebRTC)
- **Сигнализация**: WebSocket (`/ws/call`) через Starlette
- **REST API**: `/api/calls/initiate`, `/api/calls/<id>/status`, `/api/calls/<id>/end`, `/api/calls/history`
- **TURN**: Google STUN + Cloudflare TURN для symmetric NAT
- **TURN auth**: HMAC-SHA256, 24h expiry (`/api/turn/credentials`)
- **Клиент**: `static/call.js` — RTCPeerConnection, WebSocket, Web Audio API рингтон
- **UI**: входящий popup, экран звонка, PiP, screen share, mute/camera/speaker
- **Call model**: caller_id, callee_id, call_type, status, timestamps
- Stale-звонки: auto-expire ringing > 30s

### Google OAuth
- `/login/google` и `/login/google/callback` в `routes/auth.py`
- `google_id` на User для привязки
- Авто-генерация username для новых пользователей
- Env vars: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`

### Музыкальный плеер
- Интеграция с Deezer API (поиск, популярное, альбомы)
- Плейлисты, избранное, история прослушивания
- Рекомендации на основе прослушанного
- Загрузка своих аудиофайлов
- Привязка трека к посту

### Модерация контента
- `ModerationLog` — журнал нарушений
- NSFW-детекция: 150+ ключевых слов (RU/EN)
- `moderate_post()` — отклоняет пост, отправляет DM предупреждение
- Авто-бан после 5 нарушений
- Хуки на `/create`, community posts, Bot API

### Админ-панель (`/admin`)
- `Report` модель: жалобы на пользователей и посты
- Staff-only доступ (`is_staff`)
- Разделы: System Bots, Reports, Users, Communities
- Кнопка жалобы (🚩) на каждом посте
- Авто-промоут `botadmin` и `Sergqmts` в staff

### Мультиаккаунты
- `AccountGroup` и `AccountGroupMember` модели
- Создание и переключение между личными/бизнес-аккаунтами
- Бизнес-аналитика (`/business/analytics`)

### Уведомления
- Polling: `GET /api/unread-count` каждые 10с
- Типы: like, comment, reply, follow, message, new_story
- Socket.IO presence (online/offline)

## 🧰 Технологии
- Python 3.12, Flask 3.x, Flask-Login, Flask-SQLAlchemy, Flask-WTF, Flask-SocketIO
- PostgreSQL (Railway) / SQLite (локально), psycopg 3
- Cloudinary (CDN медиа, трансформации видео)
- Starlette + Uvicorn (ASGI, WebSocket signaling)
- Gunicorn (production)
- Tailwind CSS (CDN), кастомный CSS
- faster-whisper (голос → текст)
- Authlib (Google OAuth)
- Deezer API (музыка)
- FreeSound API (аудио для shorts)
- Cloudflare TURN (звонки)
- WebRTC (RTCPeerConnection)
- Pillow (обработка изображений)
- Pytest (тесты)

## 🚀 Переменные окружения
```
DATABASE_URL=postgresql://...
SECRET_KEY=<random 30+ chars>
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
CLOUDFLARE_TURN_KEY_ID=...
CLOUDFLARE_TURN_API_TOKEN=...
FREESOUND_API_KEY=...
EDITOR_SERVICE_URL=https://editorservicevibehub-production.up.railway.app
EDITOR_SERVICE_TOKEN=service-token
EDITOR_JWT_SECRET=<общий JWT-секрет с редактором>
JWT_SECRET=<тот же секрет для редактора>
PORT=8080
```

## ⚠️ Известные проблемы
1. Socket.IO не работает с gunicorn sync workers — реальное время только через Starlette WebSocket
2. Whisper медленный на CPU (free Railway tier)
3. Нет лимита размера файлов — большие аплоады могут вызвать 502
4. `Message.body NOT NULL` в PostgreSQL — всегда передавать `body=''`
5. Нет requirements.txt generation — при новых зависимостях обновлять вручную
6. JWT key < 32 bytes вызывает `InsecureKeyLengthWarning` — рекомендуется ключ длиннее 32 символов
