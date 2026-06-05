# Architecture — VIBE Social Network

---

## Основное приложение (монолит)

### Точки входа

```
asgi_app.py     — ASGI точка входа: Starlette + WSGIMiddleware(Flask)
  └── /ws/call  — WebSocket signaling для VoIP (Starlette, async)
  └── все остальное → Flask (WSGI)

app.py          — Flask-приложение: config, DB init, migrations, Socket.IO
signaling.py    — WebSocket handler: SDP/ICE relay, call rooms
extensions.py   — db, login_manager, socketio, csrf
models.py       — все SQLAlchemy модели (~880 строк)
helpers.py      — утилиты: upload, moderation, notifications (~314 строк)
middleware/
  abuse_protection.py  — rate limiting, abuse guards
  security_logging.py  — security event logging
```

### Архитектура роутов

`routes/__init__.py` → `register_all_routes(app)` — импортирует 11 модулей:

```
routes/
  auth.py        — /login, /register, /logout, /login/google, 2FA
  posts.py       — /, /create, /post/<id>, лайки, комменты, редакторы
  profiles.py    — /profile/<username>, подписки, блокировки, бизнес
  stories.py     — /stories, /create_story, /story/<id>
  messages.py    — /messages, /chat/<id>, голосовые, видео-кружочки
  communities.py — /communities, /community/<slug>, события, заявки
  music.py       — /music, Deezer, плейлисты, загрузка
  bots.py        — /bots, /bot<token>/<method>, Bot API (25+ методов)
  accounts.py    — /accounts, мультиаккаунты, бизнес
  calls.py       — /api/calls/*, VoIP REST API, TURN credentials
  editor.py      — /proxy/edit/*, /api/editor/*, JWT-прокси редактора
```

### VoIP поток

```
Браузер A                   Starlette /ws/call               Браузер B
    │ WSS connect (JWT)           │                               │
    │ ──────────────────────────► │                               │
    │ {type:"offer", sdp:...}     │  {type:"offer", to:B}         │
    │ ──────────────────────────► │ ──────────────────────────►   │
    │                             │  {type:"answer", sdp:...}     │
    │   {type:"answer", ...}      │ ◄──────────────────────────   │
    │ ◄────────────────────────── │                               │
    │        ICE candidates exchange (relay via WS)               │
    │ ◄──────────────────────────────────────────────────────►    │
    │              Direct WebRTC connection (TURN/STUN)           │
    │ ◄══════════════════════════════════════════════════════►    │
```

### Уведомления

```
Polling: GET /api/unread-count каждые 10 секунд (клиент)
Socket.IO: presence (online/offline статусы)
Типы уведомлений: like, comment, reply, follow, message, new_story
```

### Медиа

```
Production: Cloudinary (CDN, трансформации видео через e_* параметры)
Development: static/uploads/ (локальная папка, fallback)
helpers.py → upload_to_cloudinary(file) → URL или локальный path
```

---

## Система редактора (микросервис)

Отдельный FastAPI-сервис, общается с монолитом через HTTP + JWT.

## System Context

```
┌──────────────────────┐     JWT + HTTP      ┌──────────────────────┐
│                      │ ◄────────────────── │                      │
│   VIBE Social        │    /photo?token=     │   Editor Service     │
│   Network (Monolith) │ ──────────────────► │   editor.vibe.app    │
│                      │    HTML страницы     │                      │
│  socnet.up.railway   │                      │  editor.vibesocial   │
│                      │                      │  .app                │
└──────────┬───────────┘                      └──────────┬───────────┘
           │                                            │
           │ X-Service-Token                             │ Cloudinary API
           │ (межсервисная аутентификация)               │
           │                                            │
           ▼                                            ▼
┌──────────────────────┐                      ┌──────────────────────┐
│                      │                      │                      │
│   Main App API       │                      │   Cloudinary         │
│   /api/editor/*      │                      │   CDN + трансформации│
│                      │                      │                      │
└──────────────────────┘                      └──────────────────────┘
```

## Backend Architecture

```
FastAPI App
│
├── Middleware Pipeline
│   ├── CORSMiddleware
│   ├── JWTMiddleware
│   └── ExceptionHandler
│
├── Routes
│   ├── /health              ─► 200 {"status":"ok"}
│   ├── /photo, /video       ─► HTML страницы
│   ├── /api/photo-transform ─► Pillow (rotate/flip/crop)
│   ├── /api/upload-video    ─► Cloudinary upload
│   ├── /api/build-video-url ─► Cloudinary URL builder
│   ├── /api/publish         ─► Cloudinary + MainApp API
│   ├── /api/publish-video   ─► MainApp API
│   └── /api/draft/{id}      ─► MainApp API
│
└── Services
    ├── CloudinaryService    — загрузка, URL, удаление
    ├── MainAppClient        — HTTP клиент к монолиту
    ├── PhotoTransformService — Pillow операции
    └── JWTService           — encode/decode
```

### Middleware

**JWTMiddleware** (`backend/app/middleware/auth.py`):
- Пропускает без проверки: `/health`, `/static/*`, `/docs`
- Для HTML-страниц (`Accept: text/html`) — редирект при ошибке
- Для API — JSON 401
- Извлекает `user_id`, `username` в `request.state`

### Сервисы

| Сервис | Назначение | Зависимости |
|--------|-----------|-------------|
| `CloudinaryService` | Загрузка изображений/видео, построение URL с трансформациями | Cloudinary SDK |
| `MainAppClient` | HTTP-вызовы к монолиту (publish, draft) | `httpx` |
| `PhotoTransformService` | Серверная обработка изображений | Pillow |
| `JWTService` | Хэлперы для JWT | PyJWT |

### stateless-дизайн

Сервис не имеет БД. Все данные:
- **Черновики** — запрашиваются из основного приложения по HTTP
- **Медиа** — хранятся в Cloudinary
- **Сессии** — JWT (stateless)
- **Публикации** — создаются через API монолита

---

## Frontend Architecture

```
HTML (index.html)
│
├── CSS
│   ├── design-system.css    — CSS-переменные (цвета, скругления)
│   ├── theme.css            — цвета редактора
│   ├── main.css             — лейаут, компоненты
│   ├── tools.css            — стили панелей инструментов
│   └── mobile.css           — mobile-first media queries
│
    └── JavaScript
        ├── Shared
        │   ├── api-client.js    — ApiClient (fetch wrapper)
        │   ├── toast.js         — Toast-уведомления
        │   ├── loader.js        — Loader (спиннер)
        │   └── jwt.js           — JWT decode на клиенте
        │
        ├── Photo Editor
        │   ├── app.js           — Инициализация, lifecycle
        │   ├── canvas-engine.js — Canvas2D: слои, DPI, viewport
        │   ├── state-manager.js — Undo/Redo (50 шагов)
        │   ├── tool-manager.js  — Plugin-система
        │   ├── tools/
        │   │   ├── base-tool.js — Abstract class
        │   │   ├── crop.js      — Кадрирование + rotate/flip/straighten
        │   │   ├── adjust.js    — 11 параметров (яркость, контраст...)
        │   │   ├── filters.js   — 25 пресетов (LUT-based)
        │   │   ├── effects.js   — 15 эффектов (vintage, B&W, LOMO, glitter...)
        │   │   ├── portrait.js  — Сглаживание кожи, зубы, глаза, румянец...
        │   │   ├── draw.js      — Маркер, кисть, аэрограф, ластик
        │   │   ├── text.js      — 8 шрифтов, drag, shadow, align
        │   │   ├── stickers.js  — 32 эмодзи + загрузка изображений
        │   │   ├── frames.js    — 6 стилей рамок (полароид, плёнка...)
        │   │   ├── collage.js   — 6 шаблонов коллажа
        │   │   └── animation.js — 6 particle-систем (искры, сердца...)
        │   ├── filters/
        │   │   ├── presets.js       — Матрицы 25 фильтров
        │   │   └── lut-processor.js — Применение LUT к ImageData
        │   ├── mobile/
        │   │   ├── touch-adapter.js   — PointerEvents → unified API
        │   │   ├── gesture-handler.js — Pinch zoom, swipe, long-press
        │   │   ├── bottom-sheet.js    — Draggable bottom sheet
        │   │   ├── keyboard-helper.js — Virtual keyboard offset
        │   │   └── webview-bridge.js  — postMessage bridge (RN/Flutter)
        │   └── utils/
        │       ├── canvas-utils.js
        │       ├── file.js
        │       ├── color.js
        │       ├── math.js
        │       └── debounce.js
        │
        └── Video Editor
            ├── app.js              — Инициализация видеоредактора
            ├── cloudinary-player.js — Cloudinary URL construction
            ├── timeline.js          — Слайдеры start/end обрезки
            ├── uploader.js          — Загрузка в Cloudinary
            └── preview.js           — Переключение original/transformed
```

### CanvasEngine

Ядро фоторедактора. Отвечает за:

1. **Слои** — базовое изображение + overlay (текст, стикеры, draw)
2. **DPI** — учёт `devicePixelRatio` (макс. 2x)
3. **Viewport** — zoom/pan через transform matrix
4. **Rerender** — полная перерисовка при изменении

```javascript
engine = new CanvasEngine(canvasElement)
engine.setBaseImage(img)     // загрузить фото
engine.setZoom(1.5)          // приближение
engine.getCanvasPoint(x, y)  // экран → координаты canvas
engine.exportImage(0.92)     // data URL
```

### Tool Plugin System

Каждый инструмент — класс, наследуемый от `BaseTool`:

```javascript
class CropTool extends BaseTool {
  constructor() { super('Кадрирование', 'fa-crop', '<div>options</div>'); }
  activate(engine, stateManager, panel) { /* подписка на события */ }
  deactivate() { /* очистка */ }
  onPointerDown(e) { /* начало действия */ }
  onPointerMove(e) { /* процесс */ }
  onPointerUp(e) { /* завершение */ }
}
```

Регистрация:
```javascript
toolManager.register(new CropTool());
toolManager.register(new AdjustTool());
// ...
```

### StateManager (Undo/Redo)

- Хранит до 50 снимков canvas (offscreen canvas)
- При превышении лимита удаляет самые старые
- После undo, новый push — удаляет redo-историю

---

## Data Flow

### Фоторедактор: сохранение

```
1. Пользователь нажимает "Сохранить"
2. CanvasEngine.exportImage() → data URL (base64 JPEG)
3. ApiClient.post('/api/publish', { preview_data, caption, target, user_id })
4. Backend: CloudinaryService.upload_image(base64) → Cloudinary URL
5. Backend: MainAppClient.publish_photo(url, caption, target, user_id)
6. Main App: создаёт Post/Story/Shorts/Draft
7. Response: { status: "ok", post_id: 123 }
```

### Видеоредактор: сохранение

```
1. Пользователь загружает видео
2. ApiClient.upload('/api/upload-video', formData) → Cloudinary public_id
3. Пользователь настраивает трансформации (trim, filter, speed)
4. ApiClient.post('/api/build-video-url', { public_id, ... }) → Cloudinary URL
5. Пользователь нажимает "Опубликовать"
6. ApiClient.post('/api/publish-video', { cloudinary_url, ... })
7. Backend: MainAppClient.publish_video(url, ...)
8. Main App: создаёт Shorts
```

### Загрузка черновика

```
1. GET /photo?token=JWT&draft=42
2. Backend: отдаёт HTML с window.__INIT_DATA__.draft_id = 42
3. Frontend: PhotoEditorApp._loadDraft(42)
4. ApiClient.get('/api/draft/42')
5. Backend: MainAppClient.get_draft(42) → { media_data, caption }
6. Frontend: загружает изображение в CanvasEngine
```

---

## Mobile Adaptation

### Responsive Layout

| Breakpoint | Toolbar | Options Panel | Canvas |
|-----------|---------|---------------|--------|
| < 768px | Bottom (48-56px) | Bottom sheet (60vh, draggable) | Полный экран |
| 768-1023px | Left (64px) | Right panel | Оставшееся место |
| 1024px+ | Left (64px) | Right (280px) | Полный |

### Touch Events

```css
canvas { touch-action: none; }
```

`TouchAdapter` (`mobile/touch-adapter.js`) унифицирует mouse / touch / pen через `pointerdown/move/up` в единый интерфейс `{start, move, end}`.

### Gestures

`GestureHandler` (`mobile/gesture-handler.js`) обрабатывает:
- **Pinch zoom** — двумя пальцами, вызывает `engine.setZoom()`
- **Swipe** — порог 50px, определение направления (left/right/up/down)
- **Long press** — 500ms, с callback

### Bottom Sheet

`BottomSheet` (`mobile/bottom-sheet.js`) — мобильная замена правой панели:
- Открывается как `position: fixed` снизу
- Draggable handle для смахивания вниз
- Закрывается при клике на canvas
- `env(safe-area-inset-bottom)` для iPhone X+

### WebView Bridge

`WebViewBridge` (`mobile/webview-bridge.js`) — связь с React Native / Flutter через `postMessage`:

```javascript
// Инициализация (автоматически в app.js)
const bridge = new WebViewBridge();

// JS → Native (с ответом)
const result = await bridge.call('PUBLISH', { imageData, caption, target });

// JS → Native (без ответа)
bridge.send('HAPTIC', { style: 'light' });

// Native → JS
bridge.on('PICK_FROM_GALLERY', (payload) => {
  this._loadImage(payload.imageData);
});
```

Поддерживает:
- `window.ReactNativeWebView.postMessage()` (Android)
- `window.webkit.messageHandlers.editorBridge.postMessage()` (iOS)
- `window.parent.postMessage()` (iframe)
- Timeout 10s на `call()`, автоматическая обработка ответов по `_callId`

### Keyboard Helper

`KeyboardHelper` (`mobile/keyboard-helper.js`) — отслеживает `visualViewport.resize`:
- При открытии клавиатуры (diff > 100px) — поднимает canvas в область видимости
- При закрытии — восстанавливает исходную высоту

### Device Capabilities Detection

```javascript
// Встроено в app.js для мобильных устройств
const isMobile = window.innerWidth <= 768;
if (isMobile) {
  // TouchAdapter + GestureHandler + BottomSheet + KeyboardHelper
  // WebView bridge для PICK_FROM_GALLERY, PUBLISH_SUCCESS
}

---

## Key Decisions (ADRs)

### ADR-1: FastAPI вместо Flask
**Решение:** FastAPI async. **Причина:** I/O к Cloudinary и монолиту. **Следствие:** Лучшая утилизация CPU при ожидании I/O.

### ADR-2: Plugin-архитектура инструментов
**Решение:** Каждый инструмент — отдельный класс. **Причина:** 11 инструментов с разной логикой. **Следствие:** Изолированное тестирование, лёгкое добавление новых (Draw, Effects, Portrait, Frames, Collage, Animation реализованы по этому принципу).

### ADR-3: Слои вместо единого canvas
**Решение:** Offscreen canvas для каждого слоя. **Причина:** Текст, стикеры, draw накладываются поверх. **Следствие:** Undo для одного слоя, независимая перерисовка.

### ADR-4: Stateless (без БД)
**Решение:** Сервис не хранит данные. **Причина:** Все данные в монолите и Cloudinary. **Следствие:** Простой деплой, горизонтальное масштабирование.
