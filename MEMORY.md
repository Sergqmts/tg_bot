# MEMORY — Social Network Project

## Quick Overview
Full-stack social network (Flask + PostgreSQL + Tailwind CSS). Deployed on Railway.
Repo: `github.com/Sergqmts/tg_bot`, branch `main` (current active: `feature/video-messages`)

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

## Database
- SQLite locally (`instance/social.db`), PostgreSQL on Railway
- `Message.body` has `NOT NULL` in production (set explicit `body=''`)
- Models: User, Post, Media, Like, Comment, Message, MessageMedia, Chat, ChatMember, Community, CommunityMember, Notification, Story, Shorts, ShortsAudio, ShortsLike, ShortsComment

## Branch History (recent)
- `main` — production branch, Railway auto-deploys
- `feature/video-messages` — current working branch (video кружочки, notification fixes)

## Recent Changes (feature/video-messages)
- **Video messages ("кружочки")**: New routes `send_video_message` (DM) and `send_chat_video_message` (group). MediaRecorder + front camera, 60s limit, circular display 140×140, autoplay on scroll (IntersectionObserver), tap for fullscreen with audio. CSRF not exempt (unlike voice).
- **Voice/video/shorts persistence**: All uploads now go to Cloudinary when configured.
- **Notifications**: Added `GET /api/unread-count` endpoint. Badge polls every 10s via `setInterval`.
- **Messages page fix**: Filtered out `chat.type != 'group'` from groups section. Removed deleted-user conversations.
- **Community post fix**: Removed AJAX fetch that swallowed validation errors.
- **Community attribution**: Posts in communities show community icon/name with author as subtitle.
- **Avatar fix**: All templates now use `get_avatar_url()` return value instead of hardcoded `url_for('uploaded_file', ...)`.
- **Logout button**: Added to own profile page.
- **Notifications CSRF fix**: Added missing `csrf_token` to mark-as-read forms.

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
| `profile.html` | User profile with tabs (posts, shorts) |
| `community.html` | Community page with posts |
| `explore.html` | Search users/tags/posts |
