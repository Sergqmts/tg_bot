# MEMORY — Social Network Project

## Quick Overview
Full-stack social network (Flask + PostgreSQL + Tailwind CSS). Deployed on Railway.
Repo: `github.com/Sergqmts/tg_bot`, branch `main`.

## How to Run
```bash
python app.py  # dev on :5000
# Production: gunicorn app:app --bind 0.0.0.0:$PORT
```

## Key Architecture Decisions
- **Single-file app**: `app.py` contains ALL routes, models, config (~5300 lines)
- **Flask-WTF CSRFProtect** for CSRF on all POST forms (except voice routes which are exempt)
- **Cloudinary** for media persistence across deploys (fallback to local `/static/uploads/`)
- **No real-time** — Socket.IO was removed due to gunicorn sync worker incompatibility. Notification badge uses JS polling (`GET /api/unread-count` every 10s)
- **Media serving**: `/media/<filename>` → `send_from_directory(UPLOAD_FOLDER)`. Cloudinary URLs used directly when configured.
- **Bots = Users with `is_bot=True`**: Bot platform modelled after Telegram. Token auth via URL path (`/bot<token>/sendMessage`). Webhooks for outgoing events.

## Database
- SQLite locally (`instance/social.db`), PostgreSQL on Railway
- `Message.body` has `NOT NULL` in production (set explicit `body=''`)
- Models: User (+bot fields), Post, Media, Like, Comment, Message, MessageMedia, Chat, ChatMember, Community, CommunityMember, Notification, Story, Shorts, ShortsAudio, ShortsLike, ShortsComment, Draft, ModerationLog, Report, Reaction, Tag, PostTag

## Branch History (recent)
- `main` — production branch, Railway auto-deploys
- `feature/bot-platform` — merged into main (bot platform, content moderation, admin panel, staff system)
- `feature/photo-editor` — merged into main (comprehensive photo editor, navigation redesign, drafts)

## Features

### Bot Platform (Telegram-style)
- **Bot model**: `is_bot`, `bot_token`, `bot_commands`, `can_join_groups`, `privacy_mode`, `webhook_url`, `creator_id` fields on User
- **Token generation**: `generate_bot_token()` — Telegram-style (`id:secret`)
- **Bot management UI**: `/bots`, `/bots/new`, `/bots/<id>/settings`
- **BotForm**: username must end with `bot`
- **Bot API (25 methods)**: sendMessage, sendPhoto, sendVideo, sendVoice, sendDocument, forwardMessage, deleteMessage, banChatMember, unbanChatMember, promoteChatMember, getChat, getChatMembers, getMe, setWebhook, deleteWebhook, getCommunity, getCommunityMembers, approveJoinRequest, denyJoinRequest, kickMember, promoteToAdmin, deletePost, sendPost, joinCommunity, getUpdates
- **Webhooks**: async POST to `bot.webhook_url` on new messages (skips bot's own messages)
- CSRF exempt for all bot API routes
- Bot indicator 🤖 in all relevant templates

### Content Moderation
- `ModerationLog` model for tracking violations
- `ModeratorBot` — system bot created on startup (`creator_id=None`)
- NSFW detection: 150+ keywords (RU/EN) via `check_nsfw_text()`
- `moderate_post()` — rejects post, sends DM warning, auto-bans after 5 violations
- Hooks into `/create`, community post, and Bot API `sendPost`

### Admin Panel (`/admin`)
- `Report` model for user complaints (target_user, target_post, reason, status)
- Staff-only access (`staff_required` decorator, `User.is_staff`)
- Sections: System Bots, Reports, Users (ban/unban/make staff), Communities (ban/unban)
- Report button (🚩) on every post
- Auto-promotes `botadmin` and `Sergqmts` to staff on startup

### Photo Editor (`/photo_editor`)
Full-featured in-browser photo editor with 11 tool panels:
1. **Crop** — free + 8 aspect ratio presets (1:1, 4:5, 9:16, 16:9, 3:2, 4:3, 2:3, 21:9), rotate, flip, straighten
2. **Adjust** — brightness, contrast, saturation, exposure, sharpness, shadows, highlights, temperature, tint, noise, vignette
3. **Filters** — 25 Instagram-style presets with live canvas thumbnails
4. **Effects** — vintage, B&W, LOMO, glitter, glow, grain, HDR, dramatic, soft
5. **Text** — fonts, size, color, bold/italic/underline, shadow, alignment, layer list
6. **Stickers** — 32 emoji + custom image upload
7. **Drawing** — marker, brush, spray, eraser with size/color/opacity
8. **Portrait** — skin smooth, teeth whiten, eye enhance, blemish remove, makeup, face slim
9. **Frames** — 6 decorative styles (thin, double, polaroid, neon, gold, VHS)
10. **Collage** — 6 layout templates (up to 6 photos)
11. **Animation** — sparkles, hearts, bubbles, stars, rainbow, glitch + GIF upload
- **Save to**: feed, stories, shorts, or draft
- **Quality**: 60/80/92/100%
- **History**: undo/redo (up to 50 steps)
- **Draft model** (`Draft`) with `/drafts` route for listing/resuming

### Navigation
- Bottom nav: Главная | Шортсы | Сообщения | Сообщества | ⋯ (ещё)
- "Ещё" popup: профиль, создать пост, фоторедактор, поиск, уведомления, черновики, админка (staff)

### Other
- **Feed sorting**: `Post.created_at.desc()` (newest first)
- **Draft system**: `/drafts`, `/drafts/<id>/delete`, create with `?draft=1`
- **Staff bypass**: staff can view private profiles and communities without joining
- **Favicon**: SVG route at `/favicon.ico`
- **init_db() fix**: `pool_pre_ping: True` + `with db.engine.connect()` context manager for Railway PostgreSQL

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
| `base.html` | Layout, nav, notification badge, audio player JS, theme toggle, bottom nav with "more" menu |
| `photo_editor.html` | Full photo editor (1555 lines, Canvas2D) |
| `create_story.html` | Story creation with camera + link to photo editor |
| `drafts.html` | Draft list with edit/delete |
| `admin.html` | Admin panel dashboard |
| `bot_docs.html` | Bot API documentation |
| `bot_settings.html` | Bot settings |

## Railway
- Project: `8f4bd177-1f4e-4afa-a55a-1ac415f7ee7b`
- Service: `a7eb91a7-a672-484f-a6ad-7f8149a850dd`
- Env: `d5f79170-1b9e-429b-bb25-d633a8b51c8c`
- URL: `socnet.up.railway.app`
- Deploy: GraphQL `githubRepoDeploy` mutation with projectId, repo, branch, environmentId
- Token: `2dffee3b-d944-4281-8d4f-84cc6eb686f2`
