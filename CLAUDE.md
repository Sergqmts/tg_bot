
## Проект: VIBE — социальная сеть

**Стек:** Python 3.12, Flask 3.x, SQLAlchemy, Flask-SocketIO, Starlette (WebSocket), WebRTC, Cloudinary, Deezer API, Google OAuth, PostgreSQL (Railway).

### Структура
```
app.py              — главное Flask-приложение (~1000 строк), инициализация БД и системных ботов
models.py           — 35+ SQLAlchemy моделей (~880 строк)
helpers.py          — утилиты: загрузка файлов, модерация, уведомления
extensions.py       — db, login_manager, socketio, csrf
signaling.py        — WebSocket сигналинг для VoIP
asgi_app.py         — Starlette точка входа для WebSocket
routes/
  auth.py           — вход, регистрация, Google OAuth
  posts.py          — лента, посты, лайки, комментарии
  profiles.py       — профили, подписки, блокировки
  stories.py        — истории (24ч)
  messages.py       — личные и групповые чаты, кружочки
  communities.py    — сообщества, события, заявки
  music.py          — Deezer API, плейлисты
  bots.py           — бот-платформа (Telegram-стиль, 25+ методов)
  accounts.py       — мультиаккаунты, бизнес-аккаунты
  calls.py          — WebRTC VoIP REST API
  editor.py         — прокси к внешнему редактору фото/видео
templates/          — 73 Jinja2 шаблона
static/style.css    — 2169 строк стилей (Tailwind + кастомные)
```

### Ключевые модели
`User`, `Post`, `Media`, `Like`, `Comment`, `Story`, `Shorts`, `Message`, `Chat`, `ChatMember`, `Community`, `CommunityMember`, `CommunityEvent`, `Call`, `Notification`, `MusicTrack`, `Playlist`, `ModerationLog`, `Report`

### Системные боты (is_bot=True, is_staff=True)
Создаются автоматически при старте в `app.py`. Каждый является создателем и админом своего сообщества:
| Бот | Сообщество | Slug |
|---|---|---|
| NewsBot | Новости проекта | `news` |
| TechBot | Технологии и IT | `tech-and-it` |
| TravelBot | Все про отдых и путешествия | `travel-and-leisure` |
| CookingBot | Готовь как профи | `cooking-pro` |
| AutoBot | АвтоМир | `auto-world` |
| EventsBot | Афиша и куда сходить | `events-and-places` |
| EntertainBot | Игры, кино и сериалы | `games-and-cinema` |

### Важные правила и решения
- Сообщества идентифицируются по **slug**, числовые ID нигде не хардкожатся
- Стафф-пользователи (`is_staff=True`) имеют права админа во всех сообществах системных ботов — логика в `User.is_admin()` в `models.py`
- Медиа: Cloudinary (продакшн) или локальный `UPLOAD_FOLDER` (dev)
- `Message.body` требует пустую строку `''`, не NULL
- Socket.IO не работает с gunicorn sync workers — только Starlette WebSocket
- CSRF токены обязательны во всех POST-формах
- **ProxyFix**: `app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)` + `PREFERRED_URL_SCHEME='https'` — обязательно для корректной генерации `https://` URL за Railway-прокси. `x_host=1` НЕ включать — уязвимость host-header injection
- **Google OAuth callback URI**: в Google Cloud Console → Authorized redirect URIs должен быть `https://ВАШ-ДОМЕН/login/google/callback` (именно https, иначе ошибка "недопустимый запрос")

### Переменные окружения
`DATABASE_URL`, `SECRET_KEY`, `CLOUDINARY_*`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `CLOUDFLARE_TURN_*`, `FREESOUND_API_KEY`, `EDITOR_SERVICE_URL`, `EDITOR_SERVICE_TOKEN`, `EDITOR_JWT_SECRET`, `JWT_SECRET`

### Деплой
Railway (основной) + Vercel (API функции). Procfile: gunicorn.

---

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
