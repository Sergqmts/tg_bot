# MEMORY — VIBE Social Network Project

## Quick Overview
Full-stack social network (Flask + PostgreSQL + Tailwind CSS).  
Deployed on Railway: https://socnet.up.railway.app  
Repo: `github.com/Sergqmts/tg_bot`, branch `main`.

## How to Run
```bash
python app.py  # dev on :5000
# Production: uvicorn asgi_app:app --host 0.0.0.0 --port $PORT
```

## Key Architecture Decisions
- **Modular app**: `app.py` → `routes/*.py` (10 modules) + `models.py` + `extensions.py` + `helpers.py`
- **ASGI hybrid**: `asgi_app.py` wraps Flask via `WSGIMiddleware` + adds Starlette WebSocket route `/ws/call`
- **Flask-WTF CSRFProtect** for CSRF on all POST forms (except voice routes, bot API, and call API)
- **Cloudinary** for media persistence across deploys (fallback to local `/static/uploads/`)
- **No Socket.IO in production** — replaced by Starlette + WebSocket for call signaling. Notification polling via `GET /api/unread-count` every 10s.
- **Single uvicorn process** on Railway: `asgi_app.py` → Starlette mounts Flask + WebSocket
- **Media serving**: Cloudinary URLs used directly when configured; fallback to `/media/<filename>` → `send_from_directory`
- **Bots = Users with `is_bot=True`**: Bot platform modelled after Telegram. Token auth via URL path (`/bot<token>/sendMessage`). Webhooks for outgoing events.
- **Calls**: WebRTC peer-to-peer with WebSocket signaling (Starlette), TURN via Cloudflare, REST API in `routes/calls.py`

## Database
- SQLite locally (`instance/social.db`), PostgreSQL on Railway
- `Message.body` has `NOT NULL` in production (set explicit `body=''`)
- Auto-migrations in `app.py` `init_db()` and `@app.before_request run_migrations()`
- Full list of models in PROJECT.md (40+ models)

## Route Modules
| File | Prefix | Purpose |
|------|--------|---------|
| `routes/auth.py` | — | Login, register, Google OAuth |
| `routes/posts.py` | — | Feed, create post, like, comment, delete, repost, save, react, video/photo editor, search, tags, drafts |
| `routes/profiles.py` | — | Profile page, edit, follow/unfollow, block, privacy, photos, recommendations, explore, business analytics |
| `routes/stories.py` | — | Stories CRUD, reactions, comments, archive, hide |
| `routes/messages.py` | — | DM + group chats, voice/video messages, forward, chat settings, backgrounds |
| `routes/communities.py` | — | Communities CRUD, events, join requests, member management |
| `routes/music.py` | — | Deezer integration, playlists, favorites, history, recommendations |
| `routes/bots.py` | — | Bot management UI + Bot API (25 methods), webhooks |
| `routes/accounts.py` | — | Multi-account linking, business account creation, switching |
| `routes/calls.py` | — | VoIP call API (initiate, status, end, history, TURN credentials) |

## Branch History (recent)
- `main` — production branch, Railway auto-deploys
- `feature/bot-platform` → merged (bot platform, moderation, admin, staff)
- `feature/photo-editor` → merged (photo editor, nav redesign, drafts)
- `refactor/extract-models` → merged (models/routes refactor, Google OAuth)
- `feature/video-editor` → merged (video editor, VoIP calls)
- `feature/music-player` → merged (Deezer integration, playlists)
- `feature/shorts` → merged (shorts with audio, video editor)
- `feature/stories-improvements` → merged (story reactions, comments, archive)
- `feature/multi-account` → merged (account groups, business accounts)
- `feature/mobile-improvements` → pending merge

## Key Components

### VoIP Calls
- WebRTC p2p via Starlette WebSocket (`/ws/call`)
- `signaling.py`: connections dict, call rooms, SDP/ICE relay
- `static/call.js`: RTCPeerConnection, WS client, ringtone
- `templates/call_ui.html`: incoming popup, fullscreen call, PiP, screen share
- TURN: Cloudflare via HMAC-SHA256 credentials (`/api/turn/credentials`)
- Stale cleanup: ringing > 30s → auto-missed

### Photo Editor (`/photo_editor`)
- Full Canvas2D in `templates/photo_editor.html` (1555 lines)
- 11 tool panels, 25 filters, undo/redo (50 steps)
- Save to feed / stories / shorts / draft

### Video Editor (`/video_editor`)
- Cloudinary-based transformations (no server CPU)
- Trim, filters (7), speed (0.25x–2x), audio overlay
- ShortsAudio library for background music

### Bot Platform
- 25+ API methods, Telegram-style token auth
- Webhooks: async POST on new messages
- Bot management: `/bots`, `/bots/new`, `/bots/<id>/settings`
- Username must end with `bot`

### Content Moderation
- 150+ NSFW keywords (RU/EN)
- `moderate_post()` → warning DM → auto-ban at 5 violations
- `ModeratorBot` system bot, created on startup

### Admin Panel (`/admin`)
- Staff-only, `User.is_staff` flag
- Reports, user ban/unban, community ban/unban

## Bot API NewsBot
- Token: `657313327:peqDnhI7QJEPa3yHzwH_ycugww-0BgNgHbvCyBiTd_A`
- Community: `/community/news`
- Script: `api/announce.py` — `python announce.py <title> <body>`

## Key Environment Variables
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
PORT=8080
```

## Design
- Tailwind CSS via CDN (no build step)
- Custom CSS in `static/style.css` (2169 lines)
- Dark mode with `class="dark"` on `<html>`
- Glass-morphism cards
- Brand gradient: `from-brand-start (#FF3CAC) via-brand-middle (#784BA0) to-brand-end (#2B86C5)`

## Critical Templates
| File | Purpose |
|------|---------|
| `base.html` | Layout, nav, notification badge, audio player, theme toggle, bottom nav |
| `photo_editor.html` | Full photo editor (1555 lines, Canvas2D) |
| `call_ui.html` | VoIP call UI (incoming popup, call screen, PiP, controls) |
| `video_editor.html` | Cloudinary video editor with audio library |
| `post.html` | Single post view |
| `conversation.html` | DM chat with call buttons |
| `chat.html` | Group chat with call buttons |
| `admin.html` | Admin panel dashboard |
| `bot_docs.html` | Bot API documentation |
| `music_home.html` | Music player main page |

## Railway
- URL: `socnet.up.railway.app`
- Env: `d5f79170-1b9e-429b-bb25-d633a8b51c8c`
