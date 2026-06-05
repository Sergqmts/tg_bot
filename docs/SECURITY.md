# Security — VIBE Social Network

Обзор мер безопасности, конфигурации и известных ограничений.

---

## Заголовки безопасности

Устанавливаются автоматически в `app.py` через `@app.after_request set_security_headers`:

| Заголовок | Значение |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (только prod) |
| `Content-Security-Policy` | Ограниченный список источников (см. ниже) |

### Content-Security-Policy

```
default-src 'self';
script-src 'self' cdn.tailwindcss.com cdnjs.cloudflare.com;
style-src 'self' 'unsafe-inline' cdn.tailwindcss.com cdnjs.cloudflare.com fonts.googleapis.com;
font-src 'self' cdnjs.cloudflare.com fonts.gstatic.com data:;
img-src 'self' data: blob: res.cloudinary.com *.cloudinary.com;
media-src 'self' blob: res.cloudinary.com *.cloudinary.com;
connect-src 'self' ws: wss: api.deezer.com api.freesound.org;
frame-src 'none';
object-src 'none';
```

> `unsafe-inline` разрешён только для `style-src` — необходим для Tailwind. Все inline-скрипты запрещены.

---

## CSRF-защита

Реализована через Flask-WTF (`flask_wtf.csrf.CSRFProtect`).

- Все POST/PUT/DELETE формы обязаны передавать CSRF-токен
- Стандартная вставка в шаблоны: `{{ csrf_token() }}` или `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`
- Исключения (`@csrf.exempt`) применяются **только** к Bot API endpoints (`/bot<token>/<method>`) — намеренно, т.к. это machine-to-machine вызовы с token-аутентификацией
- **Никогда не добавлять `@csrf.exempt` на state-changing endpoints** (follow, block, like, delete, …)

---

## Аутентификация

### Пароли
- Хеширование: `werkzeug.security.generate_password_hash` (PBKDF2-HMAC-SHA256)
- Минимальная длина пароля: **10 символов** (проверяется в форме и роуте)

### 2FA TOTP
- Библиотека: `pyotp` (RFC 6238)
- Секрет (`totp_secret`) генерируется при включении, хранится в базе
- При входе: если `totp_enabled=True` → после пароля нужен код из приложения-аутентификатора
- Защита от брут-форса: 5 попыток за 1 минуту (rate limit), session expiry 5 минут
- Google OAuth обходит 2FA — пользователи, вошедшие через Google, не попадают на экран TOTP

### Google OAuth
- Библиотека: `Authlib`
- `google_id` на модели User для привязки аккаунта
- **Authorized redirect URI в Google Cloud Console**: `https://ВАШ-ДОМЕН/login/google/callback` (обязательно `https://`)
- `ProxyFix(x_proto=1)` + `PREFERRED_URL_SCHEME='https'` в `app.py` — гарантируют генерацию `https://` URL за Railway-прокси

### SMS-верификация
- OTP генерируется `secrets.randbelow(900000) + 100000` (6 цифр, криптографически случайный)
- Провайдеры: `log` (dev, только вывод в лог), `smsru` (prod)
- Срок действия OTP: 10 минут
- Поля: `User.phone`, `User.phone_verified`, `User.otp_code`, `User.otp_expiry`

---

## Rate Limiting

Реализован в `middleware/abuse_protection.py`.

| Декоратор | Лимит | Применение |
|---|---|---|
| `@user_rate_limit(100, 60)` | 100 req/мин per user | API endpoints |
| `@api_rate_limit` | 100 req/мин per user | Алиас для API |
| `@ai_rate_limit` | Снижен лимит | AI-intensive операции |
| 2FA verify | 5 попыток/мин | Защита от брут-форса TOTP |

---

## Защита от инъекций и редиректов

### SQL-инъекции
SQLAlchemy ORM используется везде — параметризованные запросы. Сырые SQL-запросы (`db.session.execute(text(...))`) используют именованные параметры.

### Open Redirect
Все `redirect(request.args.get('next'))` проходят через `_is_safe_redirect()` из `routes/auth.py`. Функция разрешает только относительные URL на тот же домен.

### SSRF (Server-Side Request Forgery)
Webhook URL у ботов проверяется `_is_ssrf_safe()` в `app.py`:
- Разрешены только `https://` URL
- Заблокированы приватные IP-диапазоны (127.x, 10.x, 192.168.x, 169.254.x, ::1)
- DNS-резолюция не выполняется при регистрации — проверка только по формату

---

## Proxy и заголовки

```python
# app.py
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)
app.config['PREFERRED_URL_SCHEME'] = 'https'
```

- `x_proto=1` — доверяем только `X-Forwarded-Proto` (Railway проксирует этот заголовок)
- `x_host=1` **НЕ включать** — открывает host-header injection: атакующий подменяет домен в генерируемых URL (письма, OAuth redirect)

---

## WebSocket-аутентификация

`/ws/call` (signaling для VoIP) требует JWT-токен:

1. Клиент запрашивает токен: `GET /api/ws-token` (только для авторизованных пользователей)
2. Токен действует **5 минут**
3. Клиент отправляет `{"type": "auth", "token": "..."}` как первое сообщение
4. При ошибке → соединение закрывается с кодом 4001

---

## Editor Service

Межсервисная аутентификация через `X-Service-Token` (общий секрет в env vars).

- `/api/editor/publish`, `/api/editor/publish-video`, `/api/editor/draft/<id>` — проверяют `X-Service-Token`
- Сессионный токен выдаётся через `POST /api/editor/session` (требует авторизации, действует 30 мин)
- JWT-секрет (`EDITOR_JWT_SECRET`) должен быть ≥32 символов (иначе `InsecureKeyLengthWarning`)

---

## Модерация контента

- 150+ NSFW-ключевых слов (RU + EN) в `helpers.py → moderate_post()`
- При обнаружении: пост отклоняется + DM-предупреждение пользователю
- После **5 нарушений**: авто-бан аккаунта (`User.is_banned = True`)
- Хуки на: `/create`, community posts, Bot API sendMessage/sendPost

---

## Чувствительные данные — что нельзя

- Хардкодить токены/секреты в коде (всё в env vars — см. `.env.example`)
- Доверять `user_id` из тела внешних запросов без валидации сессионным токеном
- Принимать webhook URL без проверки HTTPS и SSRF
- Добавлять пользователей в групповой чат без проверки связи (подписки/подписчики)
- Включать `x_host=1` в ProxyFix

---

## Известные ограничения

1. Google OAuth обходит 2FA — это осознанное решение (два отдельных метода входа)
2. CSP содержит `unsafe-inline` для `style-src` — требование Tailwind CSS
3. SSRF-защита проверяет формат URL, но не DNS-резолюцию в момент выполнения вебхука
4. Socket.IO не работает с gunicorn sync workers — real-time данные только через Starlette WebSocket (ASGI)
5. Нет ограничения размера загружаемых файлов на уровне Flask — большие файлы могут вызвать 502 на Railway
