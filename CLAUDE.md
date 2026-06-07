
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
static/style.css    — ~2876 строк стилей (Tailwind + кастомные, dark electric theme)
static/manifest.json — PWA манифест (theme_color: #0A0A0A)
static/icon-192.png  — PWA иконка 192×192 (тёмный фон #0A0A0A, логотип #00C2FF)
static/icon-512.png  — PWA иконка 512×512
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
- Стафф-пользователи (`is_staff=True`) имеют права админа во всех сообществах системных ботов — логика в `User.is_admin()` в `models.py`. **Не давать им авто-admin при вступлении в приватные сообщества.**
- Медиа: Cloudinary (продакшн) или локальный `UPLOAD_FOLDER` (dev)
- `Message.body` требует пустую строку `''`, не NULL
- Socket.IO не работает с gunicorn sync workers — только Starlette WebSocket
- CSRF токены обязательны во всех POST-формах; **никогда не добавлять `@csrf.exempt` на state-changing endpoints** (follow/block/etc.)
- **ProxyFix**: `app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)` + `PREFERRED_URL_SCHEME='https'` — обязательно для корректной генерации `https://` URL за Railway-прокси. `x_host=1` НЕ включать — уязвимость host-header injection
- **Google OAuth callback URI**: в Google Cloud Console → Authorized redirect URIs должен быть `https://ВАШ-ДОМЕН/login/google/callback` (именно https, иначе ошибка "недопустимый запрос")
- **WebSocket auth**: `/ws/call` требует JWT-токен, получаемый через `GET /api/ws-token` (требует авторизации). Токен 5-минутный. Клиент обязан запросить токен перед auth-сообщением.
- **Editor service**: endpoint `/api/editor/publish` защищён `X-Service-Token` + server-side session token. Сессионный токен выдаётся через `POST /api/editor/session` (требует авторизации, 30 мин).
- **Open redirect**: все использования `redirect(request.args.get('next'))` должны проходить через `_is_safe_redirect()` из `routes/auth.py`.
- **Минимальная длина пароля**: 10 символов (форма + роут).

### Безопасность — что нельзя делать
- Хардкодить токены/секреты в коде (все в env vars, смотри `.env.example`)
- Доверять `user_id` из тела внешних запросов без валидации сессионным токеном
- Принимать webhook URL без проверки HTTPS и SSRF (`_is_ssrf_safe()` в `app.py`)
- Добавлять пользователей в групповой чат без проверки, что `current_user` с ними знаком (подписки/подписчики)

### Security headers
Устанавливаются автоматически в `@app.after_request set_security_headers` (app.py):
`X-Content-Type-Options`, `X-Frame-Options: DENY`, `X-XSS-Protection`, `Strict-Transport-Security` (только prod), `Content-Security-Policy`, `Referrer-Policy`

### Переменные окружения
`DATABASE_URL`, `SECRET_KEY`, `CLOUDINARY_*`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `METERED_APP_NAME`, `METERED_API_KEY`, `FREESOUND_API_KEY`, `EDITOR_SERVICE_URL`, `EDITOR_SERVICE_TOKEN`, `EDITOR_JWT_SECRET`, `ALLOWED_ORIGIN`, `NEWS_BOT_TOKEN`, `GITHUB_WEBHOOK_SECRET`

Полный список с примерами — в `.env.example`.

### Деплой
Railway (основной) + Vercel (API функции). Procfile: gunicorn.

---

## Дизайн-система — Dark Electric (с 2026-06-07)

**Принцип:** тёмный фон по умолчанию, один акцент без градиентов. Spec: `docs/superpowers/specs/2026-06-07-dark-electric-redesign.md`

### CSS-переменные (`:root` в `static/style.css`)

| Переменная | Значение | Использование |
|---|---|---|
| `--bg` | `#0A0A0A` | Основной фон |
| `--surface` | `#111111` | Карточки, посты, модалки |
| `--surface-2` | `#141414` | Вложенные элементы |
| `--border` | `#1A1A1A` | Границы и разделители |
| `--border-2` | `#222222` | Заметные границы |
| `--text` | `#FFFFFF` | Основной текст |
| `--text-2` | `#888888` | Вторичный текст |
| `--text-3` | `#444444` | Плейсхолдеры, timestamps |
| `--accent` | `#00C2FF` | Кнопки, иконки, лайки, активные состояния |
| `--accent-glow` | `rgba(0,194,255,0.15)` | Свечение вокруг акцентных элементов |
| `--accent-dark` | `#001B2E` | Фон плеера и акцентных блоков |
| `--danger` | `#FF4455` | Только удаление и ошибки (не лайки!) |
| `--success` | `#00E5A0` | Успех, онлайн-статус |

**Шрифт:** Space Grotesk (только). Inter удалён.

### Правила компонентов

- **Аватары:** `border-radius: 6px` — НЕ `50%` (круглые аватары убраны)
- **Карточки постов:** `border-radius: 10px`, `border: 1px solid var(--border)`, `box-shadow: none`
- **Кнопки primary:** `background: var(--accent)`, `color: #000`, `border-radius: 6px`
- **Кнопки secondary:** `background: var(--surface-2)`, `border: 1px solid var(--border-2)`, `border-radius: 6px`
- **Story rings:** `border-radius: 8px` (квадрат), `border: 1.5px solid var(--accent)`; `.seen` → `border-color: var(--border-2)`
- **Лайк активный:** `color: var(--accent)` — никогда не красный (`--danger` только для удаления)
- **Аудио-плеер:** `background: var(--accent-dark)`, play-кнопка с `box-shadow: 0 0 12px var(--accent-glow)`
- **Bottom nav:** `background: var(--bg)`, `border-top: 1px solid var(--border)`
- **Модалки:** `background: var(--surface)`, `border: 1px solid var(--border-2)`, `border-radius: 12px`, без `backdrop-filter`
- **Теги/лейблы:** `border-radius: 4px`
- **Inputs:** `border-radius: 8px`

### Что НЕЛЬЗЯ добавлять
- `backdrop-filter: blur(...)` — glassmorphism удалён
- Розово-фиолетовый градиент (`#FF3CAC → #784BA0 → #2B86C5`)
- Instagram-градиент для сторис (`#F09433 → #BC1888`)
- Светлые фоны (`#F8FAFC`, `#FFFFFF`) как дефолтные
- Переменные `--brand-start`, `--brand-middle`, `--brand-end` (удалены)

### Десктоп (≥1024px) / Планшет (768–1023px)
CSS-правила добавлены в конец `style.css`. Для активации нужно добавить классы в HTML-шаблоны:
- `.desktop-layout` — обёртка трёхколоночной сетки (240px / fluid / 300px)
- `.sidebar-nav`, `.sidebar-nav-item` — вертикальная навигация (вместо bottom nav)
- `.widgets-column` — правая колонка виджетов
- `.feed-column` — центральная колонка фида
На планшете: `.sidebar-nav-item span` скрывается (иконки без текста), `.widgets-column` скрывается.

---

## Бэклог доработок (реализовать после критичных)

### Push-уведомления (Web Push / VAPID)
- Добавить модель `PushSubscription(user_id, endpoint, p256dh, auth)` в `models.py`
- Установить `pywebpush`, сгенерировать VAPID-ключи (`VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` в env)
- Добавить роут `POST /api/push/subscribe` — сохраняет подписку
- Добавить роут `POST /api/push/unsubscribe`
- В `helpers.py` → `send_push_notification(user_id, title, body, url)` через pywebpush
- В `sw.js` добавить обработчики событий `push` и `notificationclick`
- Вызывать при: новом сообщении, лайке, подписчике, упоминании

### 2FA (TOTP)
- Установить `pyotp`, `qrcode`
- Добавить поля `User.totp_secret`, `User.totp_enabled` в `models.py`
- Роуты: `GET /settings/2fa` (показ QR), `POST /settings/2fa/enable`, `POST /settings/2fa/disable`
- Вставить проверку TOTP-кода в `login` после пароля (если `totp_enabled`)
- Шаблоны: `settings_2fa.html`, `login_2fa.html`

### Freesound API — поиск звуков для Shorts/Stories
- Переменная `FREESOUND_API_KEY` уже есть в `helpers.py` и `.env.example`
- Шаблон `upload_shorts_audio.html` уже есть
- Добавить в `routes/music.py`: `GET /api/freesound/search?q=` → проксирует Freesound `/apiv2/search/text/`
- Добавить `GET /api/freesound/preview/<sound_id>` — отдаёт preview URL
- Использовать в `upload_shorts_audio.html` для поиска и выбора трека

### Бот-платформа — недостающие методы
- `editMessage(chat_id, message_id, text)` — POST `/bot/<token>/editMessageText`
- `pinMessage(chat_id, message_id)` / `unpinMessage` — `Message.is_pinned` уже есть в модели
- `answerCallbackQuery` — нужна модель `CallbackQuery`, inline keyboards
- `sendPoll(chat_id, question, options[])` — новая модель `Poll`
- `getUpdates` — polling для ботов без webhook
- Задокументировать новые методы в `bot_docs.html`

### Алгоритм рекомендаций — оптимизация
- Текущий код в `routes/profiles.py` `recommendations()` делает N+1 запросы в Python-цикле
- Переписать через JOIN + подзапросы на уровне SQLAlchemy
- Добавить кеш (Flask-Caching или простой dict в памяти на 10 мин) — ключ `recommendations:{user_id}`
- Заменить перебор 50 юзеров на scored subquery с LIMIT

### Тесты — расширить покрытие
Нет тестов для: `messages`, `communities`, `music`, `bots API`, `profiles`, `accounts`, `onboarding`, `recommendations`.
Приоритет: messages (критичная функциональность), communities, bot API endpoints.

### Онбординг — улучшить
- Добавить шаг выбора языка интерфейса (поле `User.language`, сейчас не используется)
- Добавить туториал-оверлей на первый вход (показ основных фич)
- Добавить рекомендации пользователей для подписки на шаге 3

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

---

## Design Review — Незакрытые проблемы (2026-06-07)

Аудит показал: CSS-слой обновлён правильно, HTML-шаблоны **не обновлены**. Tailwind utility-классы в шаблонах перекрывают новые CSS-компоненты — поэтому визуально приложение почти не изменилось.

### КРИТИЧНЫЕ (HIGH)

**1. ~~Glassmorphism в inline-стиле~~ — ИСПРАВЛЕНО 2026-06-07**
Удалён `style="backdrop-filter: blur(12px)..."` из `templates/index.html:5`. `.glass` переопределён в `base.html <style>` как `background: var(--surface); border: 1px solid var(--border)` без blur.

**2. ~~Класс `.glass` без CSS-определения (59 мест)~~ — ИСПРАВЛЕНО 2026-06-07**
Добавлено корректное определение `.glass` в `base.html <style>` блок. Glassmorphism полностью убран.

**3. ~~Навигация в `base.html` — старые цвета~~ — ИСПРАВЛЕНО 2026-06-07**
Все `text-slate-*`, `hover:bg-slate-*`, `dark:*` классы в хедере, bottom nav и обоих dropdown-меню заменены на `text-[var(--accent)]`, `text-[var(--text-2)]`, `hover:bg-[var(--surface)]`, `border-[var(--border)]`.

**4. ~~Tailwind dark mode не активирован~~ — ИСПРАВЛЕНО 2026-06-07**
Логика темы в `base.html` изменена: dark активируется по умолчанию, если пользователь явно не выбрал `light` (`savedTheme !== 'light'`).

### ВАЖНЫЕ (MEDIUM)

**5. ~~Аватары — `rounded-full` перекрывает CSS~~ — ИСПРАВЛЕНО 2026-06-07**
Заменено `rounded-full` → `rounded-[6px]` в `base.html` (аватар в хедере, account switcher, moreMenu) и `accounts.html`. Градиентные заглушки-инициалы заменены на `bg-[var(--accent)] text-black`.

**6. ~~216 мест с gradient-классами (28 шаблонов)~~ — ИСПРАВЛЕНО 2026-06-07**
Все `bg-gradient-to-r from-brand-start ...`, `bg-gradient-to-tr ...`, `bg-clip-text text-transparent bg-gradient-to-r ...` заменены на `bg-[var(--accent)]` / `text-[var(--accent)]`. Все `text-white` на accent-фонах изменены на `text-black` (т.к. #00C2FF — светлый). Также заменены `text-brand-middle`, `hover:text-brand-middle`, `bg-brand-middle`, `focus:ring-brand-middle` и CSS `var(--brand-middle)` / `var(--accent-purple)` в 44 шаблонах.

**7. ~~Десктоп-раскладка~~ — ИСПРАВЛЕНО 2026-06-07**
В `base.html` добавлена структура: `.desktop-layout` > `.sidebar-nav` + `.feed-column` + `.widgets-column`. Сайдбар содержит все навигационные ссылки. Виджет-колонка содержит мини-карточку профиля. Чат-страницы исключены из grid-раскладки. В `style.css` добавлен `display: none` для `.sidebar-nav` и `.widgets-column` по умолчанию (показываются только через media queries ≥768px).

**8. ~~`forgot_password.html` — старый дизайн полностью~~ — ИСПРАВЛЕНО 2026-06-07**
Шаблон полностью переписан под dark electric: убраны glassmorphism, `rounded-2xl/3xl`, `slate-*` цвета, градиентная кнопка. Теперь использует `var(--surface)`, `var(--accent)`, `rounded-lg`, `rounded-[12px]`.

**9. ~~`accounts.html` — glassmorphism~~ — ИСПРАВЛЕНО 2026-06-07**
Убраны `.glass`, `rounded-2xl`, `bg-gradient-to-r from-brand-start`, `slate-*` цвета. Заменено на `bg-[var(--surface)]`, `border-[var(--border)]`, `rounded-[10px]`, `bg-[var(--accent)]`.

**10. ~~Логотип — gradient text вместо solid~~ — ИСПРАВЛЕНО 2026-06-07**
`bg-clip-text text-transparent bg-gradient-to-r from-brand-start to-brand-middle` → `text-[var(--accent)]` в `base.html`.

### Открытые задачи

Все задачи выполнены.
