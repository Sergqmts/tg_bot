# MEMORY — Social Network Project

## Quick Overview
Full-stack social network (Flask + PostgreSQL + Tailwind CSS). Deployed on Railway.
Repo: `github.com/Sergqmts/tg_bot`, branch `main` (current active: `feature/bot-platform`)

## How to Run
```bash
python app.py  # dev on :5000
# Production: gunicorn app:app --bind 0.0.0.0:$PORT
```

## Key Architecture Decisions
- **Single-file app**: `app.py` contains ALL routes, models, config (~4200 lines)
- **Flask-WTF CSRFProtect** for CSRF on all POST forms (except voice routes which are exempt)
- **Manual CSRF** for some routes (`/create_post`) via `session['csrf_token']` — Flask-WTF CSRF had issues with fresh sessions
- **Cloudinary** for media persistence across deploys (fallback to local `/static/uploads/`)
- **No real-time** — Socket.IO was removed due to gunicorn sync worker incompatibility. Notification badge uses JS polling (`GET /api/unread-count` every 10s)
- **No requirements.txt** — Railway auto-detects Python deps; add manually if needed
- **Media serving**: `/media/<filename>` → `send_from_directory(UPLOAD_FOLDER)`. Cloudinary URLs used directly when configured.
- **Bots = Users with `is_bot=True`**: Bot platform modelled after Telegram. Token auth via URL path (`/bot<token>/sendMessage`). Webhooks for outgoing events.

## Database
- SQLite locally (`instance/social.db`), PostgreSQL on Railway
- `Message.body` has `NOT NULL` in production (set explicit `body=''`)
- Models: User (+bot fields), Post, Media, Like, Comment, Message, MessageMedia, Chat, ChatMember, Community, CommunityMember, Notification, Story, Shorts, ShortsAudio, ShortsLike, ShortsComment

## Branch History (recent)
- `main` — production branch, Railway auto-deploys
- `feature/video-messages` — merged into main (video кружочки, notification fixes)
- `feature/bot-platform` — current: bot platform (User bot fields, create/manage bots, token auth)

## Recent Changes (feature/bot-platform)
- **Bot model**: Added `is_bot`, `bot_token`, `bot_commands`, `can_join_groups`, `privacy_mode`, `webhook_url`, `creator_id` fields to User model with auto-migration
- **Token generation**: `generate_bot_token()` — случайный токен в стиле Telegram
- **Bot management UI**: `/bots` (список), `/bots/new` (создание через BotForm), `/bots/<id>/settings` (настройки, сброс токена, webhook, команды)
- **BotForm**: Валидация — username должен заканчиваться на `bot`
- **Profile link**: Добавлен переход к ботам в профиле пользователя
- **Bot API**: Полноценный REST API как в Telegram
  - `POST /bot<token>/sendMessage` — текст в чат/диалог
  - `POST /bot<token>/sendPhoto` — фото
  - `POST /bot<token>/sendVideo` — видео
  - `POST /bot<token>/sendVoice` — голосовое
  - `POST /bot<token>/sendDocument` — документ
  - `POST /bot<token>/forwardMessage` — переслать
  - `POST /bot<token>/deleteMessage` — удалить своё сообщение
  - `POST /bot<token>/banChatMember` — заблокировать участника
  - `POST /bot<token>/unbanChatMember` — разблокировать
  - `POST /bot<token>/promoteChatMember` — повысить до админа
  - `GET /bot<token>/getChat` — инфо о чате
  - `GET /bot<token>/getChatMembers` — список участников
  - `GET /bot<token>/getMe` — инфо о боте
  - `POST /bot<token>/setWebhook` — установить webhook
  - `POST /bot<token>/deleteWebhook` — удалить webhook
  - `chat_id` поддерживает: число (ID чата или пользователя), `@username`
  - CSRF exempt (аутентификация через токен в URL)
- **Вебхуки**: автоматическая отправка событий на `webhook_url` бота при новых сообщениях
  - Срабатывает для сообщений в групповых чатах (где бот — участник) и DM (где получатель — бот)
  - Не срабатывает на сообщения самого бота (защита от циклов)
  - Асинхронные POST-запросы с Telegram-style JSON-payload
  - Формат: `{"update_id": ..., "message": {"message_id": ..., "from": {...}, "chat": {...}, "text": "..."}}`
- **Интеграция ботов с чатами**: боты отображаются в списке участников с иконкой 🤖
  - Добавление бота в чат при создании (create_chat)
  - Добавление бота через управление участниками (chat_add_member)
  - 🤖 в списке диалогов, в шапке чата, в explore/search
  - `create_chat` — боты доступны для выбора наравне с пользователями
- **Интеграция ботов с сообществами**: управление сообществами через Bot API
  - `getCommunity` — инфо о сообществе (по id или slug)
  - `getCommunityMembers` — список участников
  - `approveJoinRequest` — одобрить заявку
  - `denyJoinRequest` — отклонить заявку
  - `kickMember` — исключить участника
  - `promoteToAdmin` — повысить до админа
  - `deletePost` — удалить пост (свой или в сообществе где бот админ)
  - 🤖 в списке участников сообщества, заявках, постах

## Next Steps
- Web UI для добавления ботов в сообщества (кнопка в community_members)
- Privacy mode (бот видит только /команды и @упоминания)
- Long polling getUpdates

## Known Issues
1. **No requirements.txt** — if adding deps (e.g., eventlet), create `requirements.txt`
2. **Secret key** — must be set on Railway (`SECRET_KEY` env var), else sessions reset per restart
3. **Socket.IO** — not usable with gunicorn sync workers. If real-time needed, switch to eventlet workers: `gunicorn -k eventlet -w 1 app:app` and add eventlet to deps
4. **faster-whisper** — heavy CPU model on free Railway tier (voice transcription slow)
5. **Message.body NOT NULL** — production PostgreSQL has NOT NULL constraint, always pass `body=''`
6. **No file size limits** — large uploads can cause 502 timeout. Cloudinary has 30s timeout set.

## Key Environment Variables
```
DATABASE_URL=postgresql://...
SECRET_KEY=<random 30+ chars>
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
PORT=8080
```

## Design Languages
- Tailwind CSS via CDN (no build step)
- Custom CSS in `static/style.css` (2153 lines)
- Dark mode with `class="dark"` on `<html>`
- Glass-morphism cards: `class="glass rounded-2xl p-4 hover:shadow-md transition-all"`
- Brand gradient: `from-brand-start (#FF3CAC) via-brand-middle (#784BA0) to-brand-end (#2B86C5)`

## Critical Templates
| File | Purpose |
|------|---------|
| `base.html` | Layout, nav, notification badge, audio player JS, theme toggle |
| `index.html` | Feed with custom audio player, AJAX like |
| `post.html` | Post detail with comments |
| `conversation.html` | DM chat with voice/video recording |
| `chat.html` | Group chat with voice/video recording |
| `messages.html` | Chat list (DMs + groups) |
| `notifications.html` | Notification list |
| `profile.html` | User profile with tabs (posts, shorts) + link to bots |
| `community.html` | Community page with posts |
| `explore.html` | Search users/tags/posts |
| **`bots.html`** | List of user's bots |
| **`create_bot.html`** | Create bot form (BotFather-style) |
| **`bot_settings.html`** | Bot settings (token, webhook, commands) |

## Next Steps
- API blueprint: `/bot<token>/sendMessage`, `/bot<token>/getMe`, etc.
- Webhook delivery: POST events to `webhook_url` on new messages
- Bot integration with chats: add bot as member, display bot indicator
- Bot integration with communities: bot as admin/mod
